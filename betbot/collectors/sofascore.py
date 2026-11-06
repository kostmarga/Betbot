"""Agent 6 – Sofascore (δωρεάν, χωρίς κλειδί, ανεπίσημο API).

Από εδώ παίρνουμε ό,τι ΔΕΝ δίνουν οι άλλες δωρεάν πηγές:
  • πλάγια άουτ (throwIns), κόρνερ, κάρτες, φάουλ, σουτ ανά ομάδα και αγώνα
  • στατιστικά παικτών (σουτ, σουτ στην εστία, φάουλ, κάρτες, λεπτά)
  • ενδεκάδες (επίσημες ~1 ώρα πριν) και απουσίες (τραυματίες / τιμωρημένοι / αμφίβολοι)
  • διαιτητή
  • αποδόσεις ΜΕ την αρχική τους τιμή → βλέπουμε τι πέφτει και τι ανεβαίνει

Endpoints (βάση https://www.sofascore.com/api/v1):
  /sport/football/scheduled-events/{YYYY-MM-DD}
  /event/{id}                 → διαιτητής
  /event/{id}/statistics      → statistics[period=ALL].groups[].statisticsItems[] (χρησιμοποιούμε το `key`)
  /event/{id}/lineups         → confirmed, home/away.players[], missingPlayers[]
  /event/{id}/incidents       → κάρτες ανά παίκτη
  /event/{id}/odds/1/all      → markets[].choices[] με initialFractionalValue / fractionalValue

ΣΗΜΑΝΤΙΚΟ:
  - Είναι ανεπίσημο API. Μπορεί να αλλάξει μορφή ή να μπλοκάρει (HTTP 403).
    Ο collector ΔΕΝ προσπαθεί να παρακάμψει μπλοκαρίσματα. Αν μπλοκαριστεί, σταματά ήσυχα,
    το γράφει στο dashboard, και τα κόρνερ/κάρτες/σουτ καλύπτονται από το ESPN (espn_stats).
    Τα πλάγια ΔΕΝ έχουν εναλλακτική πηγή.
  - Κάνουμε 1 κλήση κάθε ~1.7 δευτερόλεπτα για να μην επιβαρύνουμε το site.
"""
from __future__ import annotations

import random
import time
from datetime import timedelta

import requests

from ..db import LineupRow, OddsRow, PlayerStat, TeamStat
from ..util import iso, log, parse_iso
from .base import Collector, Context, attach_to_fixture

BASE = "https://www.sofascore.com/api/v1"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.sofascore.com/",
}

TEAM_KEYS = {             # key στο Sofascore -> στήλη στο team_stats
    "cornerKicks": "corners",
    "yellowCards": "yellow",
    "redCards": "red",
    "fouls": "fouls",
    "totalShotsOnGoal": "shots",     # (στο Sofascore αυτό είναι ΣΥΝΟΛΟ σουτ)
    "shotsOnGoal": "sot",            # σουτ στην εστία
    "throwIns": "throw_ins",
    "ballPossession": "possession",
}
MISSING_REASON = {0: "άγνωστο", 1: "τραυματισμός", 2: "τιμωρία", 3: "άλλο", 11: "τραυματισμός", 12: "ασθένεια",
                  21: "τιμωρία (κάρτες)", 22: "τιμωρία (κόκκινη)"}
POS = {"G": "G", "D": "D", "M": "M", "F": "F"}


class Blocked(Exception):
    pass


def frac_to_dec(s):
    """'11/10' -> 2.10 · '1/2' -> 1.50 · δέχεται και δεκαδικό."""
    if s in (None, ""):
        return None
    s = str(s)
    try:
        if "/" in s:
            a, b = s.split("/")
            return round(1 + float(a) / float(b), 3)
        v = float(s)
        return v if v > 1 else None
    except (ValueError, ZeroDivisionError):
        return None


class SofascoreCollector(Collector):
    name = "sofascore"

    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update(HEADERS)
        self.calls = 0
        self.delay = 1.7

    # ---------------- HTTP ----------------
    def get(self, path):
        time.sleep(self.delay + random.uniform(-0.4, 0.4))
        self.calls += 1
        for attempt in range(3):
            try:
                r = self.s.get(BASE + path, timeout=20)
            except requests.RequestException as e:
                if attempt == 2:
                    raise RuntimeError(f"δίκτυο: {e}")
                time.sleep(5)
                continue
            if r.status_code == 403:
                raise Blocked("Το Sofascore απάντησε 403 (μπλοκάρισμα).")
            if r.status_code == 404:
                return None                    # π.χ. αγώνας χωρίς στατιστικά/αποδόσεις
            if r.status_code == 429:
                time.sleep(30 * (attempt + 1))
                continue
            if r.status_code >= 500:
                time.sleep(5)
                continue
            try:
                return r.json()
            except ValueError:
                return None
        return None

    # ---------------- κύρια ροή ----------------
    def run(self, ctx: Context) -> str:
        cc = ctx.cfg["collectors"]["sofascore"]
        by_ut, by_name = {}, {}
        for lg in ctx.leagues(sport="football"):
            if lg.get("sofascore"):
                by_ut[int(lg["sofascore"])] = lg
            by_name[lg["name"].lower()] = lg

        first_run = len(ctx.db.team_stats()) < 50
        back = cc["backfill_days"] if first_run else cc["daily_lookback_days"]
        days = [ctx.now.date() - timedelta(days=d) for d in range(back, 0, -1)]
        days += [ctx.now.date(), ctx.now.date() + timedelta(days=1)]

        n_stats = n_up = 0
        try:
            for day in days:
                data = self.get(f"/sport/football/scheduled-events/{day:%Y-%m-%d}") or {}
                for ev in data.get("events", []):
                    lg = self._league_of(ev, by_ut, by_name)
                    if not lg:
                        continue
                    st = (ev.get("status") or {}).get("type")
                    if st == "finished":
                        n_stats += self._finished(ctx, lg, ev, with_incidents=not first_run)
                    elif st == "notstarted":
                        ko = ev.get("startTimestamp")
                        if ko and 0 <= ko - ctx.now.timestamp() <= ctx.cfg["slip"]["hours_ahead"] * 3600:
                            n_up += self._upcoming(ctx, lg, ev)
                if self.calls >= cc["max_calls_per_run"]:
                    return f"σταμάτησε στο όριο {self.calls} κλήσεων · {n_stats} αγώνες με στατιστικά, {n_up} επερχόμενοι"
        except Blocked as e:
            return f"ΜΠΛΟΚΑΡΙΣΤΗΚΕ μετά από {self.calls} κλήσεις ({e}). Τα κόρνερ/κάρτες έρχονται από ESPN· πλάγια σήμερα δεν υπάρχουν."
        return f"{n_stats} αγώνες με στατιστικά, {n_up} επερχόμενοι (ενδεκάδες/απουσίες/αποδόσεις), {self.calls} κλήσεις"

    @staticmethod
    def _league_of(ev, by_ut, by_name):
        t = ev.get("tournament") or {}
        ut = (t.get("uniqueTournament") or {})
        if ut.get("id") in by_ut:
            return by_ut[ut["id"]]
        return by_name.get(str(ut.get("name", "")).lower())

    # ---------------- τελειωμένοι αγώνες ----------------
    def _finished(self, ctx, lg, ev, with_incidents=True) -> int:
        eid = ev["id"]
        key = f"sofascore:{eid}"
        if ctx.db.cached(key):
            return 0
        home, away = ev["homeTeam"]["name"], ev["awayTeam"]["name"]
        ko = iso(parse_iso_ts(ev["startTimestamp"]))
        mid = attach_to_fixture(ctx, lg, home, away, ko, "sofascore", str(eid), create_if_missing=False)
        hs = (ev.get("homeScore") or {}).get("current")
        as_ = (ev.get("awayScore") or {}).get("current")

        stats = self.get(f"/event/{eid}/statistics") or {}
        vals = {"home": {}, "away": {}}
        for block in stats.get("statistics", []):
            if block.get("period") != "ALL":
                continue
            for g in block.get("groups", []):
                for it in g.get("statisticsItems", []):
                    col = TEAM_KEYS.get(it.get("key"))
                    if col:
                        vals["home"][col] = _num(it.get("homeValue", it.get("home")))
                        vals["away"][col] = _num(it.get("awayValue", it.get("away")))
        detail = self.get(f"/event/{eid}") or {}
        referee = ((detail.get("event") or {}).get("referee") or {}).get("name")

        rows = []
        for side, team, opp, goals in (("home", home, away, hs), ("away", away, home, as_)):
            v = vals[side]
            rows.append(TeamStat(key, mid, lg["id"], ko, team, opp, int(side == "home"), goals,
                                 v.get("corners"), v.get("yellow"), v.get("red"), v.get("fouls"),
                                 v.get("shots"), v.get("sot"), v.get("throw_ins"), v.get("possession"),
                                 referee, "sofascore"))
        ctx.db.upsert_team_stats(rows)

        # παίκτες
        lu = self.get(f"/event/{eid}/lineups") or {}
        cards = {}
        if with_incidents:
            inc = self.get(f"/event/{eid}/incidents") or {}
            for i in inc.get("incidents", []):
                if i.get("incidentType") == "card" and i.get("player"):
                    nm = i["player"].get("name")
                    if i.get("incidentClass") in ("yellow", "yellowRed"):
                        cards[nm] = cards.get(nm, 0) + 1
        prow = []
        for side, team in (("home", home), ("away", away)):
            for p in (lu.get(side) or {}).get("players", []):
                st = p.get("statistics") or {}
                nm = (p.get("player") or {}).get("name")
                if not nm or not st:
                    continue
                on = int(st.get("onTargetScoringAttempt", 0) or 0)
                shots = on + int(st.get("shotOffTarget", 0) or 0) + int(st.get("blockedScoringAttempt", 0) or 0) \
                    + int(st.get("hitWoodwork", 0) or 0)
                prow.append(PlayerStat(key, ko, lg["id"], team, nm, int(not p.get("substitute", False)),
                                       int(st.get("minutesPlayed", 0) or 0), shots, on,
                                       int(st.get("fouls", 0) or 0), cards.get(nm, 0) if with_incidents else None,
                                       int(st.get("goals", 0) or 0), "sofascore"))
        ctx.db.upsert_player_stats(prow)
        ctx.db.mark_cached(key, iso(ctx.now), ok=bool(vals["home"]))
        return 1

    # ---------------- επερχόμενοι αγώνες ----------------
    def _upcoming(self, ctx, lg, ev) -> int:
        eid = ev["id"]
        home, away = ev["homeTeam"]["name"], ev["awayTeam"]["name"]
        ko = iso(parse_iso_ts(ev["startTimestamp"]))
        mid = attach_to_fixture(ctx, lg, home, away, ko, "sofascore", str(eid))
        ctx.db.set_ext_id(mid, "sofascore", eid)
        now = iso(ctx.now)

        detail = self.get(f"/event/{eid}") or {}
        ref = ((detail.get("event") or {}).get("referee") or {}).get("name")
        if ref:
            ctx.db.set_referee(mid, ref, "sofascore")

        lu = self.get(f"/event/{eid}/lineups") or {}
        rows = []
        confirmed = int(bool(lu.get("confirmed")))
        for side, team in (("home", home), ("away", away)):
            block = lu.get(side) or {}
            for p in block.get("players", []):
                nm = (p.get("player") or {}).get("name")
                if nm:
                    rows.append(LineupRow(mid, team, nm, "sub" if p.get("substitute") else "starter",
                                          POS.get((p.get("position") or (p.get("player") or {}).get("position") or "")[:1]),
                                          None, confirmed, "sofascore", now))
            for p in block.get("missingPlayers", []):
                nm = (p.get("player") or {}).get("name")
                if nm:
                    st = "doubtful" if p.get("type") == "doubtful" else "missing"
                    rows.append(LineupRow(mid, team, nm, st, POS.get(((p.get("player") or {}).get("position") or "")[:1]),
                                          p.get("description") or MISSING_REASON.get(p.get("reason"), ""),
                                          0, "sofascore", now))
        if rows:
            ctx.db.upsert_lineups(rows)

        odds = self.get(f"/event/{eid}/odds/1/all") or {}
        orows = []
        for m in odds.get("markets", []):
            if m.get("isLive"):
                continue
            for market, sel, line, cur, opn in self._map_market(m):
                orows.append(OddsRow(mid, market, sel, line, cur, 1, "sofascore", now, open_price=opn))
        ctx.db.upsert_odds(orows)
        return 1

    @staticmethod
    def _map_market(m):
        name = str(m.get("marketName", "")).lower()
        group = m.get("choiceGroup")
        try:
            line = float(group) if group not in (None, "") else None
        except ValueError:
            line = None
        for ch in m.get("choices", []):
            cur = frac_to_dec(ch.get("fractionalValue"))
            opn = frac_to_dec(ch.get("initialFractionalValue")) or cur
            if not cur:
                continue
            c = str(ch.get("name", "")).strip().lower()
            if name == "full time" and c in ("1", "x", "2"):
                yield ("1X2", c.upper(), None, cur, opn)
            elif name == "double chance" and c.replace(" ", "") in ("1x", "x2", "12"):
                yield ("DC", c.replace(" ", "").upper(), None, cur, opn)
            elif name == "both teams to score" and c in ("yes", "no"):
                yield ("BTTS", c.upper(), None, cur, opn)
            elif name == "match goals" and line is not None and c in ("over", "under"):
                yield ("OU", c.upper(), line, cur, opn)
            elif "corner" in name and line is not None and c in ("over", "under"):
                yield ("CORNERS", c.upper(), line, cur, opn)
            elif ("card" in name or "booking" in name) and line is not None and c in ("over", "under"):
                yield ("CARDS", c.upper(), line, cur, opn)
            elif "throw" in name and line is not None and c in ("over", "under"):
                yield ("THROWINS", c.upper(), line, cur, opn)


def parse_iso_ts(ts):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(int(ts), tz=timezone.utc)


def _num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).replace("%", "").strip()
    try:
        return float(s) if "." in s else int(s)
    except ValueError:
        return None
