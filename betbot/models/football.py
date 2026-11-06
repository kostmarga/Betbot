"""Μοντέλο ποδοσφαίρου: Poisson με δύναμη επίθεσης/άμυνας ανά ομάδα (στυλ Dixon-Coles).

  λ_γηπεδούχου = exp(μ + home + επίθεση_Γ − άμυνα_Φ)
  λ_φιλοξενούμενου = exp(μ + επίθεση_Φ − άμυνα_Γ)

- Ένα κοινό μοντέλο για όλες τις διοργανώσεις: τα ματς Champions/Europa/Conference
  «γεφυρώνουν» τις λίγκες, έτσι μια ομάδα της Super League συγκρίνεται σωστά με μια της Premier.
- Χρονική στάθμιση: ματς πριν από half_life ημέρες μετράει τα μισά.
- Ridge (L2) ώστε ομάδες με λίγα ματς να μη βγάζουν ακραίες τιμές.
- Διόρθωση Dixon-Coles (rho) για τα χαμηλά σκορ 0-0, 1-0, 0-1, 1-1.
- H2H: μικρό blend (έως h2h_weight_max) με τα γκολ των προηγούμενων αναμετρήσεών τους.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

from ..util import norm_team, parse_iso

MAX_GOALS = 10


@dataclass
class FootballPrediction:
    lam_home: float
    lam_away: float
    matrix: np.ndarray          # πιθανότητα σκορ [γκολ γηπ., γκολ φιλοξ.]
    h2h_weight: float


class FootballModel:
    def __init__(self, cfg: dict, aliases: dict):
        self.cfg = cfg
        self.aliases = aliases
        self.teams: dict[str, int] = {}
        self.games_w: np.ndarray | None = None
        self.params = None
        self.history: list[dict] = []

    def key(self, name: str) -> str:
        return norm_team(name, self.aliases)

    # ---------------- εκπαίδευση ----------------
    def fit(self, matches: list[dict], now) -> "FootballModel":
        hl = self.cfg["half_life_days"]
        rows = []
        for m in matches:
            if m["status"] != "finished" or m["home_score"] is None:
                continue
            age = (now - parse_iso(m["kickoff"])).total_seconds() / 86400
            if age < 0 or age > self.cfg["history_days"]:
                continue
            rows.append((self.key(m["home"]), self.key(m["away"]), m["home_score"], m["away_score"],
                         0.5 ** (age / hl)))
            self.history.append(m)
        if len(rows) < 30:
            raise ValueError(f"Πολύ λίγα ματς ποδοσφαίρου για εκπαίδευση ({len(rows)})")

        names = sorted({r[0] for r in rows} | {r[1] for r in rows})
        self.teams = {n: i for i, n in enumerate(names)}
        T = len(names)
        hi = np.array([self.teams[r[0]] for r in rows])
        ai = np.array([self.teams[r[1]] for r in rows])
        yh = np.array([r[2] for r in rows], float)
        ya = np.array([r[3] for r in rows], float)
        w = np.array([r[4] for r in rows])
        self.games_w = np.bincount(hi, minlength=T) + np.bincount(ai, minlength=T)
        tau = 1.0  # δύναμη ridge

        def nll(theta):
            mu, h = theta[0], theta[1]
            att, de = theta[2:2 + T], theta[2 + T:]
            lh = mu + h + att[hi] - de[ai]
            la = mu + att[ai] - de[hi]
            eh, ea = np.exp(lh), np.exp(la)
            f = -np.sum(w * (yh * lh - eh + ya * la - ea)) + 0.5 * tau * (att @ att + de @ de)
            rh, ra = w * (yh - eh), w * (ya - ea)   # παράγωγοι log-lik ως προς lh, la
            g = np.zeros_like(theta)
            g[0] = -(rh.sum() + ra.sum())
            g[1] = -rh.sum()
            ga = -(np.bincount(hi, rh, T) + np.bincount(ai, ra, T)) + tau * att
            gd = (np.bincount(ai, rh, T) + np.bincount(hi, ra, T)) + tau * de
            g[2:2 + T], g[2 + T:] = ga, gd
            return f, g

        x0 = np.zeros(2 + 2 * T)
        x0[0] = math.log(max(0.5, (yh.mean() + ya.mean()) / 2))
        res = minimize(nll, x0, jac=True, method="L-BFGS-B", options={"maxiter": 500})
        self.params = res.x
        return self

    # ---------------- πρόβλεψη ----------------
    def known(self, name: str, min_games: int) -> bool:
        i = self.teams.get(self.key(name))
        return i is not None and self.games_w[i] >= min_games

    def predict(self, home: str, away: str) -> FootballPrediction:
        T = len(self.teams)
        mu, h = self.params[0], self.params[1]
        att, de = self.params[2:2 + T], self.params[2 + T:]
        i, j = self.teams[self.key(home)], self.teams[self.key(away)]
        lh = math.exp(mu + h + att[i] - de[j])
        la = math.exp(mu + att[j] - de[i])

        # H2H blend
        h2h = self.h2h(home, away, limit=6)
        n = len(h2h)
        wgt = min(self.cfg["h2h_weight_max"], n / (n + 10)) if n else 0.0
        if n:
            gh = np.mean([m["gf"] for m in h2h])   # γκολ της (σημερινής) γηπεδούχου στα H2H
            ga = np.mean([m["ga"] for m in h2h])
            lh = (1 - wgt) * lh + wgt * max(gh, 0.2)
            la = (1 - wgt) * la + wgt * max(ga, 0.2)

        mat = np.outer(poisson.pmf(range(MAX_GOALS + 1), lh), poisson.pmf(range(MAX_GOALS + 1), la))
        rho = self.cfg["dc_rho"]
        mat[0, 0] *= max(0.0, 1 - lh * la * rho)
        mat[0, 1] *= 1 + lh * rho
        mat[1, 0] *= 1 + la * rho
        mat[1, 1] *= max(0.0, 1 - rho)
        mat /= mat.sum()
        return FootballPrediction(lh, la, mat, wgt)

    # ---------------- αγορές ----------------
    @staticmethod
    def market_probs(p: FootballPrediction) -> dict:
        m = p.matrix
        g = np.add.outer(np.arange(MAX_GOALS + 1), np.arange(MAX_GOALS + 1))
        out = {
            ("1X2", "1", None): float(np.tril(m, -1).sum()),
            ("1X2", "X", None): float(np.trace(m)),
            ("1X2", "2", None): float(np.triu(m, 1).sum()),
            ("BTTS", "YES", None): float(m[1:, 1:].sum()),
            ("BTTS", "NO", None): float(1 - m[1:, 1:].sum()),
        }
        out[("DC", "1X", None)] = out[("1X2", "1", None)] + out[("1X2", "X", None)]
        out[("DC", "X2", None)] = out[("1X2", "X", None)] + out[("1X2", "2", None)]
        out[("DC", "12", None)] = out[("1X2", "1", None)] + out[("1X2", "2", None)]
        for line in (0.5, 1.5, 2.5, 3.5, 4.5):
            over = float(m[g > line].sum())
            out[("OU", "OVER", line)] = over
            out[("OU", "UNDER", line)] = 1 - over
        return out

    # ---------------- στατιστικά για την αναφορά ----------------
    def form(self, team: str, n=6) -> list[dict]:
        k = self.key(team)
        res = []
        for m in reversed(self.history):
            hk, ak = self.key(m["home"]), self.key(m["away"])
            if k not in (hk, ak):
                continue
            home = hk == k
            gf = m["home_score"] if home else m["away_score"]
            ga = m["away_score"] if home else m["home_score"]
            res.append({"date": m["kickoff"][:10], "opp": m["away"] if home else m["home"],
                        "venue": "Ε" if home else "Χ", "gf": gf, "ga": ga,
                        "r": "Ν" if gf > ga else "Ι" if gf == ga else "Η"})
            if len(res) == n:
                break
        return res

    def h2h(self, home: str, away: str, limit=6) -> list[dict]:
        kh, ka = self.key(home), self.key(away)
        res = []
        for m in reversed(self.history):
            mh, ma = self.key(m["home"]), self.key(m["away"])
            if {mh, ma} != {kh, ka}:
                continue
            same = mh == kh
            res.append({"date": m["kickoff"][:10], "home": m["home"], "away": m["away"],
                        "score": f"{m['home_score']}-{m['away_score']}",
                        "gf": m["home_score"] if same else m["away_score"],
                        "ga": m["away_score"] if same else m["home_score"]})
            if len(res) == limit:
                break
        return res
