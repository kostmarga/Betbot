"""Agent – αποδόσεις Stoiximan για κόρνερ και κάρτες από το OddsPapi (δωρεάν key, ΟΡΙΟ 250 ΚΛΗΣΕΙΣ ΤΟΝ ΜΗΝΑ· ανανεώνεται την 1η).

Πηγή: https://api.oddspapi.io/v4 · κλειδί από env ODDSPAPI_KEY (GitHub secret, ΠΟΤΕ στον κώδικα).
Κλήσεις που μετράνε: /markets, /odds-by-tournaments (κ.ά.)· ΔΩΡΕΑΝ και χωρίς όριο: /account (δείχνει request_limit / request_count).

Οικονομία κλήσεων (ΚΡΙΣΙΜΟ — λίγες κλήσεις):
  • Πριν από κάθε κλήση ρωτάμε το /account (δωρεάν). Αν μένουν λιγότερες από `reserve`, δεν κάνουμε τίποτα.
  • /markets (κατάλογος αγορών) μία φορά τον μήνα, αποθηκεύεται στη βάση.
  • Ανά μέρα το πολύ 2 «γύροι» (πρωί/απόγευμα). Σε κάθε γύρο: 1 κλήση /odds-by-tournaments ανά 3 λίγκες, για ΕΝΑ πρακτορείο (Stoiximan).
  • Οι τιμές γράφονται στη βάση· οι υπόλοιπες εκτελέσεις της ημέρας διαβάζουν από εκεί χωρίς νέες κλήσεις.
Αγορές: totals-corners και totals-bookings (πλήρης αγώνας) -> market CORNERS / CARDS, επιλογή OVER/UNDER, γραμμή = handicap.
Σημείωση για τις κάρτες: τα πρακτορεία μετρούν «bookings» (π.χ. κίτρινη 1, κόκκινη 2)· η κρίση του bot χρησιμοποιεί την ίδια λογική.
Τα κόρνερ/κάρτες εμφανίζονται στα πρακτορεία ~1–3 μέρες πριν τον αγώνα· για πιο μακρινούς αγώνες δεν υπάρχουν τιμές ακόμα.
"""
from __future__ import annotations

import json
import os
import time
from datetime import timedelta

from ..db import OddsRow
from ..util import http_get, iso, match_fixture, parse_iso
from .base import Collector, Context

BASE = "https://api.oddspapi.io/v4"
MARKET_TYPES = {"totals-corners": "CORNERS", "totals-bookings": "CARDS"}
MAP_VERSION = 3
# ποια αγορές θέλουμε από κάθε πρακτορείο: Stoiximan = οι τιμές που παίζεις· Pinnacle = πρακτορείο αναφοράς για τις πιθανότητες (devig)
BOOKS = {"stoiximan": {"CORNERS", "CARDS", "1X2", "OU", "BTTS", "ML", "TOTAL", "SPREAD"}, "pinnacle": {"1X2", "OU", "BTTS", "ML", "TOTAL", "SPREAD"}}
SPORT_ID = {"football": 10, "basketball": 11, "nfl": 14}      # sportId του OddsPapi
# Μπάσκετ/NFL: οι κύριες αγορές έχουν περίοδο «result» και όνομα «… (incl. overtime)» (επιβεβαιώθηκε με τεστ 17/11/2026)
US_TOTAL_NAME = {11: "Over Under (incl. overtime)", 14: "Total (incl. overtime)"}
US_TOTAL_RANGE = {11: (150, 300), 14: (25, 80)}           # λογικά όρια γραμμών totals
US_SPREAD_MAX = {11: 30.0, 14: 25.0}                        # μέγιστο |χάντικαπ|


def build_market_map(markets: list) -> dict:
    """{marketId: {"m": αγορά, "line": float|None, "outs": {outcomeId: επιλογή}}} από τον κατάλογο αγορών του OddsPapi.
    Κόρνερ/κάρτες (totals-corners / totals-bookings, πλήρης αγώνας) και ποδόσφαιρο (sportId 10): Full Time Result (1X2), Over Under Full Time (μόνο γραμμές
    x.5), Both Teams To Score."""
    out = {}
    for m in markets or []:
        if m.get("playerProp"):
            continue
        sid, name = m.get("sportId"), (m.get("marketName") or "").strip()
        if sid in (11, 14) and m.get("period") == "result":          # NBA/NFL: νικητής, χάντικαπ, totals ΜΕ παράταση
            oraw = {str(o.get("outcomeName") or "").strip().lower(): str(o.get("outcomeId")) for o in (m.get("outcomes") or [])}
            h = m.get("handicap")
            if name == "Winner (incl. overtime)" and m.get("marketType") == "moneyline" and {"1", "2"} <= set(oraw):
                out[str(m.get("marketId"))] = {"m": "ML", "line": None, "outs": {oraw["1"]: "HOME", oraw["2"]: "AWAY"}}
            elif name == US_TOTAL_NAME[sid] and m.get("marketType") == "totals" and h is not None and {"over", "under"} <= set(oraw) \
                    and abs(float(h) % 1 - 0.5) < 1e-9 and US_TOTAL_RANGE[sid][0] <= float(h) <= US_TOTAL_RANGE[sid][1]:
                out[str(m.get("marketId"))] = {"m": "TOTAL", "line": float(h), "outs": {oraw["over"]: "OVER", oraw["under"]: "UNDER"}}
            elif name == "Handicap (incl. overtime)" and m.get("marketType") == "spreads" and h is not None and {"1", "2"} <= set(oraw) \
                    and abs(float(h) % 1 - 0.5) < 1e-9 and abs(float(h)) <= US_SPREAD_MAX[sid]:
                out[str(m.get("marketId"))] = {"m": "SPREAD", "line": float(h), "outs": {oraw["1"]: "HOME", oraw["2"]: "AWAY"}}
            continue
        if m.get("period") not in ("fulltime", "full time", "ft"):
            continue
        outs_raw = {str(o.get("outcomeName") or "").strip().lower(): str(o.get("outcomeId")) for o in (m.get("outcomes") or [])}
        h = m.get("handicap")
        mt = MARKET_TYPES.get(m.get("marketType"))
        if mt:
            if h is None or "over" not in outs_raw or "under" not in outs_raw:
                continue
            out[str(m.get("marketId"))] = {"m": mt, "line": float(h), "outs": {outs_raw["over"]: "OVER", outs_raw["under"]: "UNDER"}}
        elif m.get("sportId") == 10 and name == "Full Time Result" and {"1", "x", "2"} <= set(outs_raw):
            out[str(m.get("marketId"))] = {"m": "1X2", "line": None, "outs": {outs_raw["1"]: "1", outs_raw["x"]: "X", outs_raw["2"]: "2"}}
        elif m.get("sportId") == 10 and name == "Over Under Full Time" and h is not None and abs(float(h) % 1 - 0.5) < 1e-9 and {"over", "under"} <= set(outs_raw):
            out[str(m.get("marketId"))] = {"m": "OU", "line": float(h), "outs": {outs_raw["over"]: "OVER", outs_raw["under"]: "UNDER"}}
        elif m.get("sportId") == 10 and name == "Both Teams To Score" and {"yes", "no"} <= set(outs_raw):
            out[str(m.get("marketId"))] = {"m": "BTTS", "line": None, "outs": {outs_raw["yes"]: "YES", outs_raw["no"]: "NO"}}
    return out


def _near_main(rows):
    """Μπάσκετ/NFL: κρατάμε μόνο γραμμές totals/χάντικαπ όπου και οι δύο τιμές είναι 1.45–2.8 (κοντά στην κύρια γραμμή)· οι υπόλοιπες είναι θόρυβος."""
    by = {}
    for mk, sel, ln, pr in rows:
        if mk in ("TOTAL", "SPREAD"):
            by.setdefault((mk, ln), []).append(pr)
    bad = {k for k, v in by.items() if not all(1.45 <= p <= 2.8 for p in v)}
    return [r for r in rows if (r[0], r[2]) not in bad]


def spreads_consistent(rows) -> bool:
    """Έλεγχος ασφαλείας: στην «κύρια» γραμμή χάντικαπ (οι τιμές HOME/AWAY κοντύτερα), το φαβορί του νικητή πρέπει να έχει ΑΡΝΗΤΙΚΟ χάντικαπ.
    Αν δεν επαληθεύεται (π.χ. ανάποδο πρόσημο ή λείπει ο νικητής), τα χάντικαπ δεν χρησιμοποιούνται."""
    ml = {sel: pr for mk, sel, ln, pr in rows if mk == "ML"}
    if len(ml) < 2:
        return False
    sp = {}
    for mk, sel, ln, pr in rows:
        if mk == "SPREAD":
            sp.setdefault(ln, {})[sel] = pr
    full = {ln: v for ln, v in sp.items() if len(v) == 2}
    if not full:
        return True
    main = min(full, key=lambda ln: abs(full[ln]["HOME"] - full[ln]["AWAY"]))
    if abs(main) < 1.0:
        return True
    return (main < 0) == (ml["HOME"] < ml["AWAY"])


def parse_fixture_odds(fx: dict, bookmaker: str, mmap: dict, allowed=None) -> list[tuple]:
    """[(market, selection, line, price)] για έναν αγώνα. Μόνο ΠΛΗΡΕΙΣ αγορές (όλες οι επιλογές ενεργές με τιμή > 1)· αλλιώς δεν
    μπορεί να γίνει σωστό devig. `allowed`: σύνολο αγορών που θέλουμε."""
    bo = ((fx.get("bookmakerOdds") or {}).get(bookmaker) or {}).get("markets") or {}
    rows = []
    for mid, m in bo.items():
        d = mmap.get(str(mid))
        if not d or (allowed and d["m"] not in allowed) or m.get("marketActive") is False:
            continue
        got = []
        for oid, sel in d["outs"].items():
            o = ((m.get("outcomes") or {}).get(oid) or {}).get("players", {}).get("0") or {}
            p = o.get("price")
            if p and float(p) > 1.0 and o.get("active") is not False:
                got.append((d["m"], sel, d["line"], round(float(p), 3)))
        if len(got) == len(d["outs"]):
            rows += got
    rows = _near_main(rows)
    if any(r[0] == "SPREAD" for r in rows) and not spreads_consistent(rows):
        rows = [r for r in rows if r[0] != "SPREAD"]
    return rows


class OddsPapiCollector(Collector):
    name = "oddspapi"

    # ---- χαμηλού επιπέδου ----
    def _get(self, key, path, **params):
        time.sleep(1.1)                       # όριο ρυθμού: 1 κλήση/δευτ.
        data, _ = http_get(BASE + path, params={**params, "apiKey": key}, timeout=60, retries=2)
        return data

    def _quota(self, key):
        """(limit, count) από το /account (δωρεάν)· None αν δεν διαβάζεται."""
        try:
            a = self._get(key, "/account")
            for s in (a.get("subscriptions") or []):
                if s.get("is_active", True) and s.get("request_limit") is not None:
                    return int(s["request_limit"]), int(s.get("request_count") or 0)
        except Exception:
            pass
        return None

    def _markets(self, ctx, key):
        raw = ctx.db.ext_id("oddspapi:markets", "map")
        if raw:
            try:
                d = json.loads(raw)
                if d.get("month") == ctx.now.strftime("%Y-%m") and d.get("map") and d.get("v") == MAP_VERSION:
                    return d["map"]
            except Exception:
                pass
        mk = self._get(key, "/markets")
        mm = build_market_map(mk if isinstance(mk, list) else [])
        if mm:
            ctx.db.set_ext_id("oddspapi:markets", "map", json.dumps({"month": ctx.now.strftime("%Y-%m"), "v": MAP_VERSION, "map": mm}))
        return mm

    # ---- κύριο ----
    def run(self, ctx: Context) -> str:
        keys = [k for k in (os.environ.get("ODDSPAPI_KEY", ""), os.environ.get("ODDSPAPI_KEY_2", "") or os.environ.get("ODDSPAPI_KEY_2_TEMPMAIL", "")) if k]
        if not keys:
            return "παραλείφθηκε: δεν υπάρχει ODDSPAPI_KEY"
        cc = ctx.cfg["collectors"].get("oddspapi", {})
        book = cc.get("bookmaker", "stoiximan")
        hours = float(cc.get("hours_ahead", 36))
        max_calls = int(cc.get("max_calls_per_run", 3))
        reserve = int(cc.get("reserve", 25))
        max_leagues = int(cc.get("max_leagues", 6))
        # γύροι ημέρας: πρωί (<10 UTC), μεσημέρι (10–15), απόγευμα (≥15)· ένας γύρος ανά slot (νέοι αγώνες/τιμές εμφανίζονται μέσα στην ημέρα)
        part = "am" if ctx.now.hour < 10 else "mid" if ctx.now.hour < 15 else "pm"
        slot = f"{ctx.now:%Y-%m-%d}:{part}:v{MAP_VERSION}"      # η έκδοση στο κλειδί ξαναρχίζει τον γύρο όταν αλλάζουν οι αγορές που ζητάμε
        done_slot = ctx.db.cached(f"oddspapi:{slot}")
        leagues = {lg["id"]: lg for lg in ctx.leagues() if lg.get("oddspapi") and lg["sport"] in SPORT_ID}
        ms = ctx.db.matches(status="scheduled", since=iso(ctx.now - timedelta(hours=1)), until=iso(ctx.now + timedelta(hours=hours)))
        by_lg = {}
        for m in ms:
            if m["league"] in leagues:
                by_lg.setdefault(m["league"], []).append(m)
        if not by_lg:
            ctx.db.mark_cached(f"oddspapi:{slot}", iso(ctx.now))
            return "κανένας αγώνας σε λίγκα με OddsPapi"
        # Επιλογή key: το πρώτο που έχει ακόμα κλήσεις· ο λογαριασμός 2 μπαίνει αυτόματα όταν το 1 φτάσει στο όριο
        key, limit, used, left, info = None, 0, 0, 0, []
        for i, k in enumerate(keys, 1):
            q = self._quota(k)
            if q is None:
                info.append({"n": i, "limit": 0, "used": 0, "left": 0, "ok": False})      # δεν διαβάστηκε: λάθος key ή πρόβλημα δικτύου -> σφάλμα στη σελίδα
                continue
            lim, us = q
            info.append({"n": i, "limit": lim, "used": us, "left": lim - us})
            if key is None and lim - us > reserve:
                key, limit, used, left = k, lim, us, lim - us
        ctx.db.set_ext_id("oddspapi:quota", "info", json.dumps({"at": iso(ctx.now), "accounts": info, "warn_below": int(cc.get("warn_below", 40))}))
        if done_slot:
            return f"ήδη έγινε ο γύρος {slot} · υπόλοιπα: " + ", ".join(f"λογαριασμός {a['n']}: {a['left']}" + ("" if a.get("ok", True) else " (ΔΕΝ διαβάζεται)") for a in info)
        if not info or not any(a.get("ok", True) for a in info):
            return "ΣΦΑΛΜΑ: δεν διαβάστηκε το όριο κλήσεων (/account)· έλεγξε το ODDSPAPI_KEY· καμία κλήση"
        days_left = max(1, (31 - ctx.now.day))
        if key is None:
            return "όριο κλήσεων: " + ", ".join(f"λογαριασμός {a['n']}: μένουν {a['left']}" for a in info) + f" (αποθεματικό {reserve})· καμία κλήση"
        tot_left = sum(a["left"] for a in info)
        if tot_left / days_left < 2 and not slot.endswith("am"):
            return f"εξοικονόμηση κλήσεων: {left} για {days_left} μέρες· παράλειψη γύρου {part}"
        mmap = self._markets(ctx, key)
        if not mmap:
            return "χωρίς κατάλογο αγορών· καμία κλήση τιμών"
        top = sorted(by_lg, key=lambda l: -len(by_lg[l]))[:max_leagues]
        groups = []                       # ≤3 διοργανώσεις ανά κλήση και ΜΟΝΟ του ίδιου αθλήματος
        for sp in SPORT_ID:
            tl = [l for l in top if leagues[l]["sport"] == sp]
            groups += [tl[i:i + 3] for i in range(0, len(tl), 3)]
        fetched, calls, n_fx, n_rows, no_mkts = iso(ctx.now), 0, 0, 0, 0
        per_book = {}
        for book in [bk for bk in (cc.get("bookmakers") or [cc.get("bookmaker", "stoiximan"), "pinnacle"]) if bk in BOOKS]:
            for g in groups:
                if calls >= max_calls:
                    break
                tids = ",".join(str(leagues[l]["oddspapi"]) for l in g)
                try:
                    data = self._get(key, "/odds-by-tournaments", tournamentIds=tids, bookmaker=book, verbosity=3)
                except Exception as e:
                    return f"ΣΦΑΛΜΑ κλήσης ({book}): {e}"
                calls += 1
                for fx in data if isinstance(data, list) else []:
                    cands = [m for l in g for m in by_lg.get(l, [])]
                    tm = [{"home": m["home"], "away": m["away"], "m": m} for m in cands]
                    hit, sc = match_fixture(fx.get("participant1Name") or "", fx.get("participant2Name") or "", tm, ctx.aliases)
                    if not hit:
                        continue
                    try:
                        dt = abs((parse_iso(fx["startTime"]) - parse_iso(hit["m"]["kickoff"])).total_seconds())
                    except Exception:
                        dt = 0
                    if dt > 4 * 3600:
                        continue
                    rows = parse_fixture_odds(fx, book, mmap, BOOKS[book])
                    if not rows:
                        no_mkts += 1
                        continue
                    n_fx += 1
                    per_book[book] = per_book.get(book, 0) + 1
                    n_rows += ctx.db.upsert_odds([OddsRow(hit["m"]["match_id"], mk, sel, ln, pr, 1, book, fetched) for mk, sel, ln, pr in rows])
        ctx.db.mark_cached(f"oddspapi:{slot}", iso(ctx.now))
        return (f"{n_fx} αγώνες-πρακτορεία {per_book}, {n_rows} γραμμές · {no_mkts} χωρίς ακόμα αγορές · "
                f"κλήσεις {calls} · όριο: μένουν {left - calls}/{limit} (λογαριασμός που χρησιμοποιήθηκε)")
