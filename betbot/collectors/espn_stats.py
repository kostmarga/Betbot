"""Agent 7 – ESPN match summary (δωρεάν, χωρίς κλειδί) – ΕΦΕΔΡΙΚΗ πηγή στατιστικών.

Για τελειωμένους αγώνες ποδοσφαίρου που δεν έχουν ήδη στατιστικά από το Sofascore,
κατεβάζει: κόρνερ, κάρτες, φάουλ, σουτ, σουτ στην εστία, κατοχή, διαιτητή, και
στατιστικά παικτών.  ΔΕΝ δίνει πλάγια.

Endpoint: https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/summary?event={id}
  boxscore.teams[].statistics[]  -> {name, displayValue}
  rosters[].roster[]             -> {starter, athlete.displayName, stats[] {name, value}}
  gameInfo.officials[]           -> διαιτητές

Τα ονόματα των πεδίων ESPN δεν είναι επίσημα τεκμηριωμένα· ο parser δοκιμάζει
εναλλακτικά ονόματα. Αν μια μέρα βγάζει μηδενικά, δες README §9 (ESPN stats).
"""
from __future__ import annotations

from ..db import PlayerStat, TeamStat
from ..util import http_get, iso
from .base import Collector, Context

URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/summary"

TEAM_ALT = {
    "corners": ["wonCorners", "cornerKicks", "corners"],
    "yellow": ["yellowCards"],
    "red": ["redCards"],
    "fouls": ["foulsCommitted", "fouls"],
    "shots": ["totalShots", "shots"],
    "sot": ["shotsOnTarget", "shotsOnGoal"],
    "possession": ["possessionPct", "possession"],
}
PLAYER_ALT = {
    "shots": ["totalShots", "shots"],
    "sot": ["shotsOnTarget"],
    "fouls": ["foulsCommitted", "fouls"],
    "yellow": ["yellowCards"],
    "goals": ["totalGoals", "goals"],
}


def _pick(d: dict, names):
    for n in names:
        if n in d and d[n] not in (None, ""):
            try:
                return float(str(d[n]).replace("%", ""))
            except ValueError:
                continue
    return None


class EspnStatsCollector(Collector):
    name = "espn_stats"

    def run(self, ctx: Context) -> str:
        cc = ctx.cfg["collectors"]["espn_stats"]
        done = skipped = 0
        leagues = {lg["id"]: lg for lg in ctx.leagues(sport="football") if lg.get("espn")}
        from datetime import timedelta
        since = iso(ctx.now - timedelta(days=cc["lookback_days"]))
        for m in ctx.db.matches(sport="football", status="finished", since=since):
            if not m["match_id"].startswith("espn:") or m["league"] not in leagues:
                continue
            if ctx.db.team_stats_for_match(m["match_id"]):      # ήδη έχουμε (π.χ. από Sofascore)
                continue
            key = f"espn:{m['match_id'][5:]}"
            if ctx.db.cached(key):
                continue
            if done >= cc["max_calls_per_run"]:
                skipped += 1
                continue
            try:
                self._one(ctx, leagues[m["league"]], m, key)
                done += 1
            except Exception as e:
                ctx.db.mark_cached(key, iso(ctx.now), ok=False)
                skipped += 1
        return f"{done} αγώνες με στατιστικά" + (f", {skipped} για επόμενη εκτέλεση/αποτυχίες" if skipped else "")

    def _one(self, ctx, lg, m, key):
        data, _ = http_get(URL.format(league=lg["espn"]), params={"event": m["match_id"][5:]})
        box = (data.get("boxscore") or {}).get("teams", [])
        officials = (data.get("gameInfo") or {}).get("officials") or []
        referee = None
        if officials:
            o = officials[0]
            referee = o.get("displayName") or o.get("fullName")
        by_side = {}
        for t in box:
            side = t.get("homeAway")
            if side not in ("home", "away"):
                continue
            stats = {s.get("name"): s.get("displayValue", s.get("value")) for s in t.get("statistics", [])}
            by_side[side] = {col: _pick(stats, alts) for col, alts in TEAM_ALT.items()}
        if not by_side:
            raise ValueError("χωρίς boxscore")
        rows = []
        for side, team, opp, goals in (("home", m["home"], m["away"], m["home_score"]),
                                       ("away", m["away"], m["home"], m["away_score"])):
            v = by_side.get(side, {})
            rows.append(TeamStat(key, m["match_id"], m["league"], m["kickoff"], team, opp, int(side == "home"),
                                 goals, _i(v.get("corners")), _i(v.get("yellow")), _i(v.get("red")),
                                 _i(v.get("fouls")), _i(v.get("shots")), _i(v.get("sot")), None,
                                 v.get("possession"), referee, "espn"))
        ctx.db.upsert_team_stats(rows)

        prow = []
        for r in data.get("rosters", []) or []:
            side = r.get("homeAway")
            team = m["home"] if side == "home" else m["away"]
            for p in r.get("roster", []) or []:
                nm = (p.get("athlete") or {}).get("displayName")
                if not nm:
                    continue
                st = {s.get("name"): s.get("value") for s in p.get("stats", []) or []}
                vals = {col: _pick(st, alts) for col, alts in PLAYER_ALT.items()}
                starter = bool(p.get("starter"))
                subbed_in = bool(p.get("subbedIn"))
                if not starter and not subbed_in:
                    continue
                minutes = 85 if starter else 25          # το ESPN δεν δίνει λεπτά -> εκτίμηση
                prow.append(PlayerStat(key, m["kickoff"], m["league"], team, nm, int(starter), minutes,
                                       _i(vals["shots"]), _i(vals["sot"]), _i(vals["fouls"]),
                                       _i(vals["yellow"]), _i(vals["goals"]), "espn"))
        ctx.db.upsert_player_stats(prow)
        ctx.db.mark_cached(key, iso(ctx.now), ok=True)


def _i(v):
    return None if v is None else int(round(v))
