"""Agent 2 – Euroleague official API (δημόσιο, χωρίς κλειδί).

Endpoint: https://api-live.euroleague.net/v2/competitions/E/seasons/E{έτος}/games
Η σεζόν 2026-27 έχει κωδικό E2026. Φέρνουμε τρέχουσα + προηγούμενη σεζόν.

Το API αλλάζει πού και πού μορφή· γι' αυτό ο parser δοκιμάζει πολλά ονόματα πεδίων.
Αν σταματήσει να φέρνει αγώνες, δες README §6 (Euroleague).
"""
from __future__ import annotations

from ..db import Match
from ..util import http_get, iso, parse_iso
from .base import Collector, Context

URL = "https://api-live.euroleague.net/v2/competitions/{comp}/seasons/{comp}{year}/games"


def _first(d, *paths):
    for p in paths:
        cur = d
        try:
            for k in p.split("."):
                cur = cur[k]
            if cur not in (None, ""):
                return cur
        except (KeyError, TypeError):
            continue
    return None


def _parse(league, comp, year, payload) -> list[Match]:
    items = payload.get("data", payload) if isinstance(payload, dict) else payload
    out = []
    for g in items or []:
        home = _first(g, "local.club.name", "local.club.abbreviatedName", "homeTeam.name", "local.name")
        away = _first(g, "road.club.name", "road.club.abbreviatedName", "awayTeam.name", "road.name")
        date = _first(g, "utcDate", "date", "startDate")
        if not (home and away and date):
            continue
        played = bool(_first(g, "played", "isPlayed")) or _first(g, "status") in ("result", "finished", "FINISHED")
        hs = _first(g, "local.score", "homeScore")
        as_ = _first(g, "road.score", "awayScore")
        code = _first(g, "gameCode", "code", "id")
        out.append(Match(
            match_id=f"euroleague:{comp}{year}-{code}", sport="basketball", league=league["id"],
            kickoff=iso(parse_iso(str(date)[:19])), home=home, away=away,
            home_score=int(hs) if played and hs is not None else None,
            away_score=int(as_) if played and as_ is not None else None,
            status="finished" if played else "scheduled", source="euroleague"))
    return out


class EuroleagueCollector(Collector):
    name = "euroleague"

    def run(self, ctx: Context) -> str:
        total = 0
        # σεζόν ξεκινά Οκτώβριο: Οκτ 2026 -> 2026, Μάρτιος 2027 -> 2026
        season = ctx.now.year if ctx.now.month >= 8 else ctx.now.year - 1
        for lg in ctx.leagues(euroleague=True):
            comp = lg["euroleague"]
            for year in (season - 1, season):
                data, _ = http_get(URL.format(comp=comp, year=year))
                total += ctx.db.upsert_matches(_parse(lg, comp, year, data))
        return f"{total} αγώνες"
