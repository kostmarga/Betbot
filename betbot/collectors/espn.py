"""Agent 1 – ESPN public API (δωρεάν, χωρίς κλειδί).

Φέρνει αποτελέσματα + πρόγραμμα για ποδόσφαιρο (λίγκες & κύπελλα Ευρώπης) και NBA.
Endpoint: https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard?dates=YYYYMM (ανά μήνα· το εύρος YYYYMMDD-YYYYMMDD δίνει πλέον 400)

Πρώτη εκτέλεση: γεμίζει ιστορικό (history_days) σε κομμάτια των 30 ημερών.
Επόμενες: μόνο τις τελευταίες 4 μέρες (για αποτελέσματα) + τις επόμενες 3 (πρόγραμμα).
"""
from __future__ import annotations

from datetime import timedelta

from ..db import Match
from ..util import http_get, log, iso, parse_iso
from .base import Collector, Context

BASE = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"
SPORT = {"football": "soccer", "basketball": "basketball"}


def _parse(league: dict, data: dict) -> list[Match]:
    out = []
    for ev in data.get("events", []):
        try:
            comp = ev["competitions"][0]
            teams = {c["homeAway"]: c for c in comp["competitors"]}
            st = ev.get("status", comp.get("status", {})).get("type", {})
            name = st.get("name", "")
            if st.get("completed"):
                status = "finished"
            elif "POSTPONED" in name or "CANCELED" in name or "ABANDONED" in name:
                status = "postponed"
            elif st.get("state") == "pre":
                status = "scheduled"
            else:
                status = "live"
            def score(c):
                try:
                    return int(float(c.get("score"))) if status == "finished" else None
                except (TypeError, ValueError):
                    return None
            out.append(Match(
                match_id=f"espn:{ev['id']}", sport=league["sport"], league=league["id"],
                kickoff=iso(parse_iso(ev["date"])),
                home=teams["home"]["team"]["displayName"], away=teams["away"]["team"]["displayName"],
                home_score=score(teams["home"]), away_score=score(teams["away"]),
                status=status, source="espn"))
        except (KeyError, IndexError) as e:
            log.debug("ESPN: παράλειψη event %s (%s)", ev.get("id"), e)
    return out


class EspnCollector(Collector):
    name = "espn"

    def fetch_range(self, league, start, end):
        url = BASE.format(sport=SPORT[league["sport"]], league=league["espn"])
        # Η μορφή ΑΑΑΑΜΜΗΗ-ΑΑΑΑΜΜΗΗ δίνει 400 από το 06/11/2026 -> ζητάμε ανά μήνα (ΑΑΑΑΜΜ).
        out, seen = [], set()
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            data, _ = http_get(url, params={"dates": f"{y}{m:02d}", "limit": 1000})
            for mt in _parse(league, data):
                if mt.match_id not in seen:
                    seen.add(mt.match_id)
                    out.append(mt)
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return out

    def run(self, ctx: Context) -> str:
        total, notes = 0, []
        for lg in ctx.leagues(espn=True):
            hist_days = ctx.cfg["models"][lg["sport"]]["history_days"]
            have = len(ctx.db.matches(league=lg["id"], status="finished"))
            if have < 30:   # πρώτη φορά -> backfill
                start = ctx.now - timedelta(days=hist_days)
            else:
                start = ctx.now - timedelta(days=4)
            end = ctx.now + timedelta(days=3)
            n = 0
            cur = start
            try:
                while cur < end:
                    chunk_end = min(cur + timedelta(days=30), end)
                    n += ctx.db.upsert_matches(self.fetch_range(lg, cur, chunk_end))
                    cur = chunk_end + timedelta(days=1)
            except Exception as e:  # μία λίγκα που αποτυγχάνει δεν ρίχνει τις άλλες
                notes.append(f"{lg['id']}: {e}")
            total += n
        msg = f"{total} αγώνες"
        return msg + (" | σφάλματα: " + "; ".join(notes) if notes else "")
