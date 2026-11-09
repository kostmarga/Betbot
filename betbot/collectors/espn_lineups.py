"""Agent – ενδεκάδες (και διαιτητής όπου υπάρχει) από το ESPN, δωρεάν.

Το «summary» του ESPN περιέχει `rosters` με τους βασικούς (`starter: true`) και τα αναπληρωματικά περίπου 1 ώρα πριν την έναρξη.
Γράφουμε μόνο ματς που ξεκινούν σε `window_hours` ώρες (ή ξεκίνησαν πριν λίγο). Κατάσταση παίκτη: `starter` | `bench`.
Το ιστορικό ενδεκάδων μένει στη βάση, ώστε το bot να βλέπει πόσες αλλαγές έκανε μια ομάδα σε σχέση με το προηγούμενο ματς (rotation).
Αν το ESPN δεν έχει ακόμα ενδεκάδα για έναν αγώνα, δεν γράφουμε τίποτα (δεν υποθέτουμε).
"""
from __future__ import annotations

from datetime import timedelta

from ..db import LineupRow
from ..util import http_get, iso
from .base import Collector, Context

URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/summary"


class EspnLineupsCollector(Collector):
    name = "espn_lineups"

    def run(self, ctx: Context) -> str:
        cc = ctx.cfg["collectors"].get("espn_lineups", {})
        hours = float(cc.get("window_hours", 3))
        cap = int(cc.get("max_calls_per_run", 40))
        leagues = {lg["id"]: lg for lg in ctx.leagues() if lg.get("espn") and lg["sport"] == "football"}
        ms = ctx.db.matches(status="scheduled", since=iso(ctx.now - timedelta(minutes=30)), until=iso(ctx.now + timedelta(hours=hours)))
        fetched = iso(ctx.now)
        calls = n_match = n_rows = n_ref = 0
        for m in sorted(ms, key=lambda x: x["kickoff"]):
            lg = leagues.get(m["league"])
            if not lg or not m["match_id"].startswith("espn:") or calls >= cap:
                continue
            calls += 1
            try:
                data, _ = http_get(URL.format(league=lg["espn"]), params={"event": m["match_id"][5:]}, timeout=15, retries=2)
            except Exception:
                continue
            rows = []
            for r in data.get("rosters") or []:
                side = r.get("homeAway")
                team = m["home"] if side == "home" else m["away"] if side == "away" else None
                players = r.get("roster") or []
                if not team or not any(p.get("starter") for p in players):
                    continue
                for p in players:
                    name = (p.get("athlete") or {}).get("displayName")
                    if not name:
                        continue
                    pos = ((p.get("position") or {}).get("abbreviation")) or None
                    rows.append(LineupRow(m["match_id"], team, name, "starter" if p.get("starter") else "bench", pos, None, 1, "espn"))
            if rows:
                n_match += 1
                n_rows += ctx.db.upsert_lineups(rows)
            offs = ((data.get("gameInfo") or {}).get("officials")) or []
            if offs:
                ref = next((o.get("displayName") or o.get("fullName") for o in offs if (o.get("position") or {}).get("name", "").lower() in ("referee", "")), None)
                if ref:
                    ctx.db.set_referee(m["match_id"], ref, "espn")
                    n_ref += 1
        return f"{n_match}/{calls} αγώνες με ενδεκάδα, {n_rows} παίκτες, {n_ref} διαιτητές"
