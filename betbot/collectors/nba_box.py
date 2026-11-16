"""Agent – boxscore NBA από το ESPN (δωρεάν): πόντοι/λεπτά ανά παίκτη για τελειωμένους αγώνες.
Χρησιμοποιείται για την κρίση των δελτίων «Πόντοι NBA» (βλ. betbot/props.py).
Endpoint: https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={id}
  boxscore.players[].statistics[0] -> {labels:[MIN,PTS,...], athletes:[{athlete:{displayName}, stats:[...], didNotPlay}]}
"""
from __future__ import annotations

from datetime import timedelta

from ..util import http_get, iso
from .base import Collector, Context
from .oddspapi import norm_player

URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"


def parse_box(data: dict, match: dict) -> list[dict]:
    rows = []
    for t in (data.get("boxscore") or {}).get("players") or []:
        team = ((t.get("team") or {}).get("displayName")) or ""
        for grp in t.get("statistics") or []:
            labels = [str(x).upper() for x in grp.get("labels") or []]
            if "PTS" not in labels:
                continue
            ip, im = labels.index("PTS"), (labels.index("MIN") if "MIN" in labels else None)
            for a in grp.get("athletes") or []:
                nm = (a.get("athlete") or {}).get("displayName")
                st = a.get("stats") or []
                if not nm:
                    continue
                if a.get("didNotPlay") or len(st) <= ip:
                    rows.append({"match_id": match["match_id"], "team": team, "player": norm_player(nm), "minutes": 0.0, "points": 0})
                    continue
                try:
                    pts = int(float(st[ip]))
                    mn = float(str(st[im]).split(":")[0]) if im is not None and len(st) > im and str(st[im]).replace(":", "").isdigit() else None
                except (ValueError, TypeError):
                    continue
                rows.append({"match_id": match["match_id"], "team": team, "player": norm_player(nm), "minutes": mn, "points": pts})
    return rows


class NbaBoxCollector(Collector):
    name = "nba_box"

    def run(self, ctx: Context) -> str:
        cc = ctx.cfg["collectors"].get("nba_box", {})
        if not cc.get("enabled", True):
            return "ανενεργό"
        since = iso(ctx.now - timedelta(days=int(cc.get("lookback_days", 5))))
        done = fail = 0
        for m in ctx.db.matches(sport="basketball", status="finished", since=since):
            if m["league"] != "NBA" or not m["match_id"].startswith("espn:") or ctx.db.box_for(m["match_id"]):
                continue
            if done + fail >= int(cc.get("max_calls_per_run", 20)):
                break
            try:
                data, _ = http_get(URL, params={"event": m["match_id"][5:]})
                rows = parse_box(data, m)
                if rows:
                    ctx.db.upsert_box(rows)
                    done += 1
                else:
                    fail += 1
            except Exception:
                fail += 1
        return f"{done} boxscore NBA" + (f", {fail} για επόμενη εκτέλεση" if fail else "")
