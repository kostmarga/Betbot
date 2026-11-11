"""Agent – τραυματισμοί NBA από το ESPN (δωρεάν, χωρίς κλειδί).

Το endpoint `/basketball/nba/injuries` δίνει ανά ομάδα τους παίκτες με κατάσταση (Out, Day-To-Day, Questionable…) και σχόλιο.
Γράφουμε για κάθε αγώνα NBA των επόμενων `hours_ahead` ωρών τα απόντα/αμφίβολα στον πίνακα `lineups` (status: missing | doubtful, source: espn).
ΠΡΟΣΟΧΗ: δεν ξέρουμε πόσο σημαντικός είναι ο κάθε παίκτης (λείπει βαρύτητα) και δεν υπάρχει backtest τραυματισμών· πρόκειται για
πληροφορία στο «γιατί», όχι για κανόνα αποκλεισμού.
"""
from __future__ import annotations

from datetime import timedelta

from ..db import LineupRow
from ..util import http_get, iso
from .base import Collector, Context

URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"


def _status(s: str) -> str | None:
    t = (s or "").strip().lower()
    if t == "out" or "out" in t.split():
        return "missing"
    if t in ("day-to-day", "questionable", "doubtful", "probable") or "day" in t or "question" in t or "doubt" in t:
        return "doubtful"
    return None


class EspnInjuriesCollector(Collector):
    name = "espn_injuries"

    def run(self, ctx: Context) -> str:
        cc = ctx.cfg["collectors"].get("espn_injuries", {})
        hours = float(cc.get("hours_ahead", 36))
        ms = [m for m in ctx.db.matches(status="scheduled", since=iso(ctx.now - timedelta(hours=1)), until=iso(ctx.now + timedelta(hours=hours)))
              if m["league"] == "NBA"]
        if not ms:
            return "κανένας αγώνας NBA"
        data, _ = http_get(URL, timeout=15, retries=2)
        by_team = {}
        for t in data.get("injuries") or []:
            name = t.get("displayName")
            rows = []
            for i in t.get("injuries") or []:
                st = _status(i.get("status"))
                nm = (i.get("athlete") or {}).get("displayName")
                if st and nm:
                    rows.append((nm, st, str(i.get("shortComment") or "")[:160]))
            by_team[name] = rows
        n_m = n_rows = 0
        for m in ms:
            rows = []
            for team in (m["home"], m["away"]):
                for nm, st, com in by_team.get(team, []):
                    rows.append(LineupRow(m["match_id"], team, nm, st, None, com, 1, "espn"))
            if rows:
                n_m += 1
                n_rows += ctx.db.upsert_lineups(rows)
        return f"{n_m}/{len(ms)} αγώνες με τραυματίες, {n_rows} παίκτες"
