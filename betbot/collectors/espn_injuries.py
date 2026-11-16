"""Agent – τραυματισμοί NBA και NFL από το ESPN (δωρεάν, χωρίς κλειδί).

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

# league id -> (injuries URL, summary URL, κατηγορίες «κορυφαίων» παικτών, ώρες μπροστά)
BASE = "https://site.api.espn.com/apis/site/v2/sports/{}"
LEAGUES = {
    "NBA": (BASE.format("basketball/nba/injuries"), BASE.format("basketball/nba/summary"),
            {"pointsPerGame": "σκόρερ", "assistsPerGame": "πασέρ", "reboundsPerGame": "ριμπάουντερ"}, 36),
    # NFL (16/11/2026): ο κορυφαίος σε πάσες = ο quarterback της ομάδας· εκτός από αυτόν, κορυφαίοι σε τρέξιμο/λήψεις
    "NFL": (BASE.format("football/nfl/injuries"), BASE.format("football/nfl/summary"),
            {"passingYards": "quarterback", "rushingYards": "σε τρέξιμο", "receivingYards": "δέκτης"}, 96),
}


def _status(s: str) -> str | None:
    t = (s or "").strip().lower()
    if t == "out" or "out" in t.split() or "injured reserve" in t or t in ("ir", "suspended"):
        return "missing"
    if t in ("day-to-day", "questionable", "doubtful", "probable") or "day" in t or "question" in t or "doubt" in t:
        return "doubtful"
    return None


class EspnInjuriesCollector(Collector):
    name = "espn_injuries"

    def run(self, ctx: Context) -> str:
        cc = ctx.cfg["collectors"].get("espn_injuries", {})
        out = []
        for lid, (url, summary, lead, default_hours) in LEAGUES.items():
            hours = float(cc.get(f"{lid.lower()}_hours_ahead", cc.get("hours_ahead", 36) if lid == "NBA" else default_hours))
            ms = [m for m in ctx.db.matches(status="scheduled", since=iso(ctx.now - timedelta(hours=1)), until=iso(ctx.now + timedelta(hours=hours)))
                  if m["league"] == lid]
            if not ms:
                out.append(f"{lid}: κανένας αγώνας")
                continue
            try:
                out.append(f"{lid}: " + self._league(ctx, ms, url, summary, lead))
            except Exception as e:      # μία λίγκα που αποτυγχάνει δεν ρίχνει την άλλη
                out.append(f"{lid}: σφάλμα {e}")
        return " | ".join(out)

    def _league(self, ctx, ms, url, summary, lead) -> str:
        data, _ = http_get(url, timeout=15, retries=2)
        by_team = {}
        for t in data.get("injuries") or []:
            name = t.get("displayName")
            rows = []
            for i in t.get("injuries") or []:
                st = _status(i.get("status"))
                nm = (i.get("athlete") or {}).get("displayName")
                if st and nm:
                    ir = " (IR)" if "reserve" in str(i.get("status")).lower() else ""
                    rows.append((nm, st, (str(i.get("shortComment") or "")[:160] + ir) if ir and "IR" not in str(i.get("shortComment")) else str(i.get("shortComment") or "")[:160]))
            by_team[name] = rows
        n_m = n_rows = 0
        for m in ms:
            rows = []
            # «κορυφαίοι» παίκτες κάθε ομάδας από το summary του αγώνα: ώστε να φαίνεται αν λείπει βασικός
            key = {}
            try:
                j, _ = http_get(summary, params={"event": m["match_id"][5:]}, timeout=15, retries=2)
                for tl in j.get("leaders") or []:
                    tname = (tl.get("team") or {}).get("displayName")
                    for cat in tl.get("leaders") or []:
                        for x in (cat.get("leaders") or [])[:1]:
                            nm = (x.get("athlete") or {}).get("displayName")
                            if nm and cat.get("name") in lead:
                                key.setdefault((tname, nm), []).append(f"κορυφαίος {lead[cat['name']]} {x.get('displayValue')}")
            except Exception:
                pass
            for team in (m["home"], m["away"]):
                for nm, st, com in by_team.get(team, []):
                    tag = ", ".join(key.get((team, nm), []))
                    rows.append(LineupRow(m["match_id"], team, nm, st, None, (tag + "|" + com) if tag else com, 1, "espn", iso(ctx.now)))
            if rows:
                n_m += 1
                n_rows += ctx.db.upsert_lineups(rows)
        return f"{n_m}/{len(ms)} αγώνες με τραυματίες, {n_rows} παίκτες"
