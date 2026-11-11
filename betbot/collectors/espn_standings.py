"""Agent – βαθμολογία διοργανώσεων από το ESPN (δωρεάν, χωρίς κλειδί).

Για κάθε διοργάνωση ποδοσφαίρου ή NBA με αγώνες στις επόμενες `hours_ahead` ώρες γράφει θέση, αγώνες, βαθμούς, νίκες/ισοπαλίες/ήττες και τέρματα.
Χρησιμεύει για το «γιατί» κάθε επιλογής (π.χ. ο 3ος εναντίον του 17ου). Ομάδες σε φάσεις ομίλων (UEFA) εμφανίζονται με τη θέση στον όμιλό τους.
"""
from __future__ import annotations

from datetime import timedelta

from ..util import http_get, iso
from .base import Collector, Context

URL = "https://site.api.espn.com/apis/v2/sports/{sport}/{league}/standings"
SPORT = {"football": "soccer", "basketball": "basketball"}


def _stat(stats, name):
    for s in stats or []:
        if s.get("name") == name:
            v = s.get("value")
            return float(v) if v is not None else None
    return None


class EspnStandingsCollector(Collector):
    name = "espn_standings"

    def run(self, ctx: Context) -> str:
        cc = ctx.cfg["collectors"].get("espn_standings", {})
        hours = float(cc.get("hours_ahead", 36))
        leagues = {lg["id"]: lg for lg in ctx.leagues() if lg.get("espn") and lg["sport"] in SPORT}
        ms = ctx.db.matches(status="scheduled", since=iso(ctx.now - timedelta(hours=1)), until=iso(ctx.now + timedelta(hours=hours)))
        need = sorted({m["league"] for m in ms if m["league"] in leagues})
        n_lg = n_rows = 0
        upd = iso(ctx.now)
        for lid in need:
            try:
                data, _ = http_get(URL.format(sport=SPORT[leagues[lid]["sport"]], league=leagues[lid]["espn"]), timeout=15, retries=2)
            except Exception:
                continue
            rows = []
            bball = leagues[lid]["sport"] == "basketball"
            for ch in data.get("children") or [data]:
                conf = (ch.get("name") or "").replace("Conference", "").strip()
                for e in (ch.get("standings") or {}).get("entries") or []:
                    team = (e.get("team") or {}).get("displayName")
                    st = e.get("stats")
                    gi = lambda n: (lambda v: int(v) if v is not None else None)(_stat(st, n))
                    if bball:
                        rk = _stat(st, "playoffSeed")
                        if not team or rk is None:
                            continue
                        w, l = gi("wins"), gi("losses")
                        disp = {x.get("name"): x.get("displayValue") for x in (st or [])}
                        extra = {"Eastern": "Ανατολή", "Western": "Δύση"}.get(conf, conf)
                        extra = f"{extra} · {w}-{l} · τελ.10: {disp.get('Last Ten Games')} · σερί {disp.get('streak')} · {_stat(st, 'avgPointsFor'):.0f}-{_stat(st, 'avgPointsAgainst'):.0f} πόντοι"
                        rows.append({"league": lid, "team": team, "rank": int(rk), "played": (w or 0) + (l or 0), "points": None, "wins": w, "draws": 0,
                                     "losses": l, "gf": gi("pointsFor"), "ga": gi("pointsAgainst"), "updated": upd, "extra": extra})
                        continue
                    rk = _stat(st, "rank")
                    if not team or rk is None:
                        continue
                    rows.append({"league": lid, "team": team, "rank": int(rk), "played": gi("gamesPlayed"), "points": _stat(st, "points"),
                                 "wins": gi("wins"), "draws": gi("ties"), "losses": gi("losses"), "gf": gi("pointsFor"), "ga": gi("pointsAgainst"), "updated": upd})
            if rows:
                n_lg += 1
                n_rows += ctx.db.upsert_standings(rows)
        return f"{n_lg}/{len(need)} διοργανώσεις, {n_rows} ομάδες"
