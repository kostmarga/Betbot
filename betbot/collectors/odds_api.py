"""Agent 4 – The Odds API (δωρεάν κλειδί, 500 credits/μήνα).

Καλύπτει: Champions/Europa/Conference, NBA, Euroleague (+ λίγκες αν το fdco δεν τις έχει).
Κόστος κλήσης = αριθμός markets × αριθμός regions (π.χ. h2h,totals × eu = 2 credits).

Οικονομία credits:
  1. /events είναι ΔΩΡΕΑΝ → πρώτα ελέγχουμε αν η διοργάνωση έχει αγώνες στις επόμενες ώρες.
  2. Μόνο τότε καλούμε /odds.
  3. Σεβόμαστε ημερήσιο πλαφόν = credits που απομένουν / μέρες που απομένουν στον μήνα.
Το κλειδί διαβάζεται από τη μεταβλητή περιβάλλοντος ODDS_API_KEY.
"""
from __future__ import annotations

import calendar
import os
from collections import defaultdict
from datetime import timedelta

from ..db import OddsRow
from ..util import http_get, iso, parse_iso, log
from .base import Collector, Context, attach_to_fixture

BASE = "https://api.the-odds-api.com/v4/sports"


class OddsApiCollector(Collector):
    name = "odds_api"

    def run(self, ctx: Context) -> str:
        key = os.environ.get("ODDS_API_KEY", "").strip()
        if not key:
            return "παράλειψη: δεν υπάρχει ODDS_API_KEY"
        cc = ctx.cfg["collectors"]["odds_api"]
        markets_by_sport = {"football": ["h2h", "totals"], "basketball": ["h2h", "totals", "spreads"]}
        fdco_on = ctx.cfg["collectors"]["fdco_odds"]["enabled"]
        horizon = ctx.now + timedelta(hours=ctx.cfg["slip"]["hours_ahead"])

        remaining = None
        spent, rows, notes = 0, [], []
        for lg in ctx.leagues(odds_api=True):
            if cc.get("skip_if_fdco_covers") and fdco_on and lg.get("fdco"):
                continue
            # 1) δωρεάν: υπάρχουν αγώνες;
            try:
                events, resp = http_get(f"{BASE}/{lg['odds_api']}/events", params={"apiKey": key})
            except Exception as e:
                notes.append(f"{lg['id']}: {e}")
                continue
            remaining = int(resp.headers.get("x-requests-remaining", remaining or 500))
            soon = [e for e in events if parse_iso(e["commence_time"]) <= horizon
                    and parse_iso(e["commence_time"]) >= ctx.now]
            if not soon:
                continue
            mk = [m for m in markets_by_sport[lg["sport"]] if m in cc["markets"] or m == "spreads"]
            cost = len(mk) * len(cc["regions"].split(","))
            if not self._budget_ok(ctx, remaining, cost, spent):
                notes.append(f"{lg['id']}: παράλειψη για εξοικονόμηση credits (απομένουν {remaining})")
                continue
            # 2) αποδόσεις
            data, resp = http_get(f"{BASE}/{lg['odds_api']}/odds", params={
                "apiKey": key, "regions": cc["regions"], "markets": ",".join(mk),
                "oddsFormat": "decimal", "commenceTimeFrom": iso(ctx.now), "commenceTimeTo": iso(horizon)})
            remaining = int(resp.headers.get("x-requests-remaining", remaining))
            spent += int(resp.headers.get("x-requests-last", cost))
            rows += self._parse(ctx, lg, data)
        ctx.db.upsert_odds(rows)
        msg = f"{len(rows)} αποδόσεις, ξοδεύτηκαν {spent} credits"
        if remaining is not None:
            msg += f", απομένουν {remaining}"
        return msg + (" | " + "; ".join(notes) if notes else "")

    def _budget_ok(self, ctx, remaining, cost, spent_today):
        """Ημερήσιο πλαφόν = (credits που απομένουν − απόθεμα) / μέρες που απομένουν × 1.5
        (το ×1.5 επιτρέπει μέρες με πολλά ματς, π.χ. Τρίτη/Τετάρτη Champions League)."""
        today = ctx.now
        days_in_month = calendar.monthrange(today.year, today.month)[1]
        days_left = days_in_month - today.day + 1
        reserve = 500 - ctx.cfg["collectors"]["odds_api"]["monthly_budget"]
        usable = max(0, remaining - reserve)
        daily_cap = max(cost, usable / days_left * 1.5)
        return cost <= usable and spent_today + cost <= daily_cap

    def _parse(self, ctx, lg, events) -> list[OddsRow]:
        fetched = iso(ctx.now)
        out = []
        for ev in events:
            mid = attach_to_fixture(ctx, lg, ev["home_team"], ev["away_team"], ev["commence_time"],
                                    "oddsapi", ev["id"])
            agg = defaultdict(list)   # (market, sel, line) -> [prices]
            for bk in ev.get("bookmakers", []):
                for m in bk.get("markets", []):
                    for o in m.get("outcomes", []):
                        key = self._map(lg["sport"], m["key"], o, ev)
                        if key:
                            agg[key].append(float(o["price"]))
            for (market, sel, line), prices in agg.items():
                if len(prices) >= 2 or market in ("1X2", "ML"):
                    out.append(OddsRow(mid, market, sel, line, round(sum(prices) / len(prices), 3),
                                       len(prices), "oddsapi", fetched))
        return out

    @staticmethod
    def _map(sport, mkey, o, ev):
        name, point = o.get("name"), o.get("point")
        if mkey == "h2h":
            if sport == "football":
                sel = "1" if name == ev["home_team"] else "2" if name == ev["away_team"] else "X"
                return ("1X2", sel, None)
            sel = "HOME" if name == ev["home_team"] else "AWAY"
            return ("ML", sel, None)
        if mkey == "totals" and point is not None:
            return ("OU" if sport == "football" else "TOTAL", name.upper(), float(point))
        if mkey == "spreads" and point is not None:
            # γράφουμε τη γραμμή πάντα από την πλευρά της γηπεδούχου
            if name == ev["home_team"]:
                return ("SPREAD", "HOME", float(point))
            return ("SPREAD", "AWAY", -float(point))
        return None
