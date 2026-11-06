"""Μοντέλο παικτών: σουτ, σουτ στην εστία, φάουλ, κάρτα, γκολ.

Για κάθε παίκτη: ρυθμός ανά 90' στα τελευταία N ματς (με μικρή συρρίκνωση) ×
αναμενόμενα λεπτά → Poisson → πιθανότητα για 1+, 2+ κ.λπ.

Κανόνας (από τα λάθη της 1ης μέρας): επιλογές παικτών βγαίνουν ΜΟΝΟ για
  • παίκτες στην επίσημη ενδεκάδα, ή
  • «πιθανούς βασικούς» (βασικοί σε ≥4 από τα 5 τελευταία) – σημειώνονται με ⚠️
Αν ο παίκτης είναι στις απουσίες, δεν εμφανίζεται.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np
from scipy.stats import poisson

from ..util import norm_team

PROPS = {   # αγορά -> (στήλη, όρια για εμφάνιση)
    "SOT": ("sot", [1, 2]),
    "SHOTS": ("shots", [1, 2, 3]),
    "FOULS": ("fouls", [1, 2]),
    "CARD": ("yellow", [1]),
    "GOAL": ("goals", [1]),
}
PROP_LABEL = {"SOT": "σουτ στην εστία", "SHOTS": "σουτ", "FOULS": "φάουλ", "CARD": "κάρτα", "GOAL": "σκόρερ"}


class PlayerModel:
    def __init__(self, cfg, aliases):
        self.cfg, self.aliases = cfg, aliases
        self.hist = defaultdict(list)    # (ομάδα, παίκτης) -> λίστα αγώνων

    def fit(self, rows, now):
        for r in rows:
            if r.get("minutes"):
                self.hist[(norm_team(r["team"], self.aliases), r["player"])].append(r)
        for k in self.hist:
            self.hist[k].sort(key=lambda r: r["kickoff"])
        return self

    def probable_starter(self, team, player):
        h = self.hist.get((norm_team(team, self.aliases), player), [])[-5:]
        return len(h) >= 4 and sum(1 for r in h if r.get("starter")) >= 4

    def predict(self, team, player, n=None):
        n = n or self.cfg["player_last_n"]
        h = self.hist.get((norm_team(team, self.aliases), player), [])[-n:]
        if len(h) < self.cfg["player_min_games"]:
            return None
        starts = [r for r in h if r.get("starter")]
        exp_min = np.mean([r["minutes"] for r in starts[-5:]]) if starts else 70
        mins = sum(r["minutes"] for r in h)
        out = {"games": len(h), "exp_min": float(exp_min), "props": {}}
        for prop, (col, ks) in PROPS.items():
            vals = [r.get(col) for r in h]
            if any(v is None for v in vals):
                continue
            total = sum(vals)
            rate90 = (total + 0.2) / (mins / 90 + 1)        # μικρή συρρίκνωση
            lam = rate90 * exp_min / 90
            hit = {k: sum(1 for v in vals if v >= k) for k in ks}
            out["props"][prop] = {"lam": lam, "per90": rate90,
                                  "p": {k: float(1 - poisson.cdf(k - 1, lam)) for k in ks},
                                  "hit": hit, "n": len(vals)}
        return out
