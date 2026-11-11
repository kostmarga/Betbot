"""Agent – τραυματισμοί και στατιστικά παικτών Premier League από το επίσημο Fantasy Premier League API (δωρεάν, χωρίς κλειδί).

`bootstrap-static` δίνει για ΚΑΘΕ παίκτη: κατάσταση (a διαθέσιμος, d αμφίβολος, i τραυματίας, s αποκλεισμένος, u μη διαθέσιμος),
ειδησεογραφία («Thigh injury - Unknown return date»), πιθανότητα συμμετοχής, βαθμούς, γκολ, ασίστ, λεπτά. Είναι δημόσιο API (χωρίς
τεκμηρίωση ή εγγύηση σταθερότητας). ΜΟΝΟ Premier League. Αν δεν απαντήσει, το bot συνεχίζει χωρίς αυτά.
Γράφουμε μόνο παίκτες που μετράνε (στις 5 κορυφαίες της ομάδας σε βαθμούς ή ≥600 λεπτά) στον πίνακα `lineups`
(status missing | doubtful, source fpl) με ετικέτα «βασικός · γκολ/ασίστ» όταν είναι από τους πρώτους της ομάδας.
"""
from __future__ import annotations

from datetime import timedelta

from ..db import LineupRow
from ..util import http_get, iso, name_similarity, norm_team
from .base import Collector, Context

URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
ALIASES = {"man city": "manchester city", "man utd": "manchester united", "spurs": "tottenham hotspur", "tottenham": "tottenham hotspur",
           "nott'm forest": "nottingham forest", "wolves": "wolverhampton wanderers", "newcastle": "newcastle united",
           "brighton": "brighton hove albion", "leeds": "leeds united", "west ham": "west ham united", "bournemouth": "afc bournemouth"}


def _n(name):
    s = norm_team(name)
    return ALIASES.get(s, s)


class FplCollector(Collector):
    name = "fpl"

    def run(self, ctx: Context) -> str:
        cc = ctx.cfg["collectors"].get("fpl", {})
        hours = float(cc.get("hours_ahead", 36))
        ms = [m for m in ctx.db.matches(status="scheduled", since=iso(ctx.now - timedelta(hours=1)), until=iso(ctx.now + timedelta(hours=hours)))
              if m["league"] == "EPL"]
        if not ms:
            return "κανένας αγώνας Premier League"
        data, _ = http_get(URL, timeout=25, retries=2)
        teams = {t["id"]: t["name"] for t in data["teams"]}
        els = data["elements"]
        by_team = {}
        for e in els:
            by_team.setdefault(e["team"], []).append(e)
        # κορυφαίοι της ομάδας σε βαθμούς
        top = {tid: {e["id"] for e in sorted(lst, key=lambda x: -x["total_points"])[:5]} for tid, lst in by_team.items()}
        n_m = n_rows = 0
        for m in ms:
            rows = []
            for side in ("home", "away"):
                team = m[side]
                best, sc = None, 0.0
                for tid, nm in teams.items():
                    s = name_similarity(_n(team), _n(nm))
                    if s > sc:
                        best, sc = tid, s
                if best is None or sc < 0.7:
                    continue
                for e in by_team[best]:
                    st = e["status"]
                    if st not in ("i", "d", "s"):
                        continue
                    key = e["id"] in top[best]
                    if not (key or e["minutes"] >= 600):
                        continue
                    ch = e.get("chance_of_playing_next_round")
                    news = (e.get("news") or "").strip()
                    tag = f"βασικός · {e['goals_scored']} γκολ {e['assists']} ασίστ" if key else ""
                    if st == "d" and ch is not None:
                        tag = (tag + " · " if tag else "") + f"{ch}% πιθανότητα να παίξει"
                    status = "doubtful" if st == "d" else "missing"
                    nm = e["web_name"]
                    rows.append(LineupRow(m["match_id"], team, nm, status, None, (tag + "|" + news) if tag else news, 1, "fpl"))
            if rows:
                n_m += 1
                n_rows += ctx.db.upsert_lineups(rows)
        return f"{n_m}/{len(ms)} αγώνες Premier League με τραυματίες, {n_rows} παίκτες"
