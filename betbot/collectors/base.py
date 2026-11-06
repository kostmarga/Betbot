"""Κοινή βάση για όλους τους collectors ("agents" άντλησης).

Κάθε collector:
  - έχει ένα `name`
  - υλοποιεί `run(ctx)` και επιστρέφει ένα σύντομο μήνυμα για το log
  - αν αποτύχει, πετάει exception: ο orchestrator το καταγράφει και
    συνεχίζει με τους υπόλοιπους (ένα πεσμένο site δεν σταματάει το δελτίο).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from ..db import DB, Match
from ..util import match_fixture, parse_iso, iso


@dataclass
class Context:
    db: DB
    cfg: dict
    now: object                     # datetime UTC
    aliases: dict = field(default_factory=dict)

    def leagues(self, **flt):
        out = []
        for lg in self.cfg["leagues"]:
            if all(lg.get(k) == v if v is not True else lg.get(k) for k, v in flt.items()):
                out.append(lg)
        return out


class Collector:
    name = "base"

    def run(self, ctx: Context) -> str:  # pragma: no cover
        raise NotImplementedError


def attach_to_fixture(ctx: Context, league: dict, home: str, away: str, kickoff_iso: str,
                      source: str, ext_id: str, create_if_missing=True) -> str | None:
    """Βρίσκει τον αγώνα στη βάση (από άλλη πηγή) ώστε οι αποδόσεις να «κολλήσουν» στο σωστό match_id.
    Αν δεν υπάρχει και create_if_missing, δημιουργεί scheduled αγώνα με αυτά τα στοιχεία."""
    ko = parse_iso(kickoff_iso)
    cands = ctx.db.matches(league=league["id"], since=iso(ko - timedelta(hours=18)),
                           until=iso(ko + timedelta(hours=18)))
    m, _score = match_fixture(home, away, cands, ctx.aliases)
    if m:
        return m["match_id"]
    if not create_if_missing:
        return None
    mid = f"{source}:{ext_id}"
    ctx.db.upsert_matches([Match(mid, league["sport"], league["id"], iso(ko), home, away,
                                 None, None, "scheduled", source)])
    return mid
