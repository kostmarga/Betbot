"""Agent – παλιό ιστορικό αγώνων NBA/NFL (ESPN, δωρεάν) για τα «Μεταξύ τους» (H2H) και τη φόρμα στο «γιατί» (20/11/2026).
Ο χρήστης ζήτησε σύγκριση ΤΕΛΕΥΤΑΙΩΝ 10 (όχι 2): με ιστορικό μόνο ~13 μηνών δύο ομάδες NBA έχουν 2–3 συναντήσεις. Εδώ φέρνουμε προηγούμενες σεζόν
με το πρόγραμμα κάθε ομάδας (`teams/{id}/schedule?season=YYYY`)· σταδιακά (max κλήσεις ανά εκτέλεση)· κάθε (ομάδα, σεζόν) κατεβαίνει ΜΙΑ φορά (fetch_cache).
Δεν επηρεάζει τα μοντέλα (εκπαιδεύονται μόνο με το παράθυρο history_days)· χρησιμεύει στο archive των μοντέλων (φόρμα/H2H).
"""
from __future__ import annotations

from ..db import Match
from ..util import http_get, iso, parse_iso
from .base import Collector, Context

TEAMS = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{lg}/teams"
SCHED = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{lg}/teams/{tid}/schedule"
SPORTS = {"NBA": ("basketball", "nba", "basketball"), "NFL": ("football", "nfl", "nfl")}      # id λίγκας -> (sport path, ESPN league, sport του bot)


def parse_schedule(league_id: str, sport: str, data: dict) -> list[Match]:
    out = []
    for ev in data.get("events") or []:
        try:
            comp = ev["competitions"][0]
            if not comp["status"]["type"].get("completed"):
                continue
            t = {c["homeAway"]: c for c in comp["competitors"]}

            def sc(c):
                v = c.get("score")
                return int(float(v.get("value") if isinstance(v, dict) else v))
            out.append(Match(match_id=f"espn:{ev['id']}", sport=sport, league=league_id, kickoff=iso(parse_iso(ev["date"][:16] + ":00Z")),
                             home=t["home"]["team"]["displayName"], away=t["away"]["team"]["displayName"],
                             home_score=sc(t["home"]), away_score=sc(t["away"]), status="finished", source="espn_hist"))
        except (KeyError, TypeError, ValueError):
            continue
    return out


class HistoryBackfillCollector(Collector):
    name = "history_backfill"

    def run(self, ctx: Context) -> str:
        cc = ctx.cfg["collectors"].get("history_backfill", {})
        if not cc.get("enabled", False):
            return "ανενεργό"
        budget = int(cc.get("max_calls_per_run", 40))
        calls = added = 0
        for lid, (path, espn_lg, sport) in SPORTS.items():
            seasons = cc.get(f"{lid.lower()}_seasons") or []
            if not seasons or not any(lg["id"] == lid for lg in ctx.leagues()):
                continue
            # ομάδες (μία κλήση ανά λίγκα ανά εκτέλεση μόνο αν μένει δουλειά)
            todo = [(s,) for s in seasons]
            teams_key = f"hist:{lid}:teams"
            if all(ctx.db.cached(f"hist:{lid}:done:{s}") for s in seasons):
                continue
            try:
                d, _ = http_get(TEAMS.format(sport=path, lg=espn_lg), retries=2)
                tids = [t["team"]["id"] for t in d["sports"][0]["leagues"][0]["teams"]]
            except Exception:
                continue
            for season in seasons:
                pending = [tid for tid in tids if not ctx.db.cached(f"hist:{lid}:{tid}:{season}")]
                for tid in pending:
                    if calls >= budget:
                        break
                    calls += 1
                    try:
                        data, _ = http_get(SCHED.format(sport=path, lg=espn_lg, tid=tid), params={"season": season, "seasontype": 2}, retries=1)
                        added += ctx.db.upsert_matches(parse_schedule(lid, sport, data))
                        ctx.db.mark_cached(f"hist:{lid}:{tid}:{season}", iso(ctx.now), ok=True)
                    except Exception:
                        ctx.db.mark_cached(f"hist:{lid}:{tid}:{season}", iso(ctx.now), ok=False)
                if all(ctx.db.cached(f"hist:{lid}:{tid}:{season}") for tid in tids):
                    ctx.db.mark_cached(f"hist:{lid}:done:{season}", iso(ctx.now), ok=True)
        left = sum(1 for lid in SPORTS for s in (cc.get(f"{lid.lower()}_seasons") or []) if not ctx.db.cached(f"hist:{lid}:done:{s}"))
        return f"{calls} κλήσεις, {added} αγώνες ιστορικού" + (f" · μένουν {left} σεζόν (λίγκα×σεζόν)" if left else " · ολοκληρώθηκε")
