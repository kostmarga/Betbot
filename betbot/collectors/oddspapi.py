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


def build_market_map(markets: list) -> dict:
    """{marketId: {"m": CORNERS|CARDS, "line": float, "over": outcomeId, "under": outcomeId}} από τον κατάλογο αγορών."""
    out = {}
    for m in markets or []:
        mt = MARKET_TYPES.get(m.get("marketType"))
        if not mt or m.get("playerProp") or m.get("period") not in ("fulltime", "full time", "ft"):
            continue
        h = m.get("handicap")
        ocs = {str(o.get("outcomeName") or "").strip().lower(): str(o.get("outcomeId")) for o in (m.get("outcomes") or [])}
        if h is None or "over" not in ocs or "under" not in ocs:
            continue
        out[str(m.get("marketId"))] = {"m": mt, "line": float(h), "over": ocs["over"], "under": ocs["under"]}
    return out


def parse_fixture_odds(fx: dict, bookmaker: str, mmap: dict) -> list[tuple]:
    """[(market, selection, line, price)] για έναν αγώνα (μόνο ενεργές τιμές > 1)."""
    bo = ((fx.get("bookmakerOdds") or {}).get(bookmaker) or {}).get("markets") or {}
    rows = []
    for mid, m in bo.items():
        d = mmap.get(str(mid))
        if not d or m.get("marketActive") is False:
            continue
        for sel, oid in (("OVER", d["over"]), ("UNDER", d["under"])):
            o = ((m.get("outcomes") or {}).get(oid) or {}).get("players", {}).get("0") or {}
            p = o.get("price")
            if p and float(p) > 1.0 and o.get("active") is not False:
                rows.append((d["m"], sel, d["line"], round(float(p), 3)))
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
                if d.get("month") == ctx.now.strftime("%Y-%m") and d.get("map"):
                    return d["map"]
            except Exception:
                pass
        mk = self._get(key, "/markets")
        mm = build_market_map(mk if isinstance(mk, list) else [])
        if mm:
            ctx.db.set_ext_id("oddspapi:markets", "map", json.dumps({"month": ctx.now.strftime("%Y-%m"), "map": mm}))
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
        slot = f"{ctx.now:%Y-%m-%d}:{part}"
        done_slot = ctx.db.cached(f"oddspapi:{slot}")
        leagues = {lg["id"]: lg for lg in ctx.leagues() if lg.get("oddspapi") and lg["sport"] == "football"}
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
        groups = [top[i:i + 3] for i in range(0, len(top), 3)]
        fetched, calls, n_fx, n_rows, no_mkts = iso(ctx.now), 0, 0, 0, 0
        for g in groups:
            if calls >= max_calls:
                break
            tids = ",".join(str(leagues[l]["oddspapi"]) for l in g)
            try:
                data = self._get(key, "/odds-by-tournaments", tournamentIds=tids, bookmaker=book, verbosity=3)
            except Exception as e:
                return f"σφάλμα κλήσης: {e}"
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
                rows = parse_fixture_odds(fx, book, mmap)
                if not rows:
                    no_mkts += 1
                    continue
                n_fx += 1
                n_rows += ctx.db.upsert_odds([OddsRow(hit["m"]["match_id"], mk, sel, ln, pr, 1, book, fetched) for mk, sel, ln, pr in rows])
        ctx.db.mark_cached(f"oddspapi:{slot}", iso(ctx.now))
        return (f"{n_fx} αγώνες με κόρνερ/κάρτες ({book}), {n_rows} γραμμές · {no_mkts} χωρίς ακόμα αγορές · "
                f"κλήσεις {calls} · όριο: μένουν {left - calls - (0 if mmap else 0)}/{limit} τον μήνα")
