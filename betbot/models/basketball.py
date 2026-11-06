"""Μοντέλο μπάσκετ: ratings επίθεσης/άμυνας ανά ομάδα (σταθμισμένα ελάχιστα τετράγωνα με ridge).

  πόντοι γηπεδούχου = μ + home + επίθεση_Γ − άμυνα_Φ
  πόντοι φιλοξενούμενου = μ + επίθεση_Φ − άμυνα_Γ

Από αυτά: αναμενόμενη διαφορά και αναμενόμενο σύνολο πόντων. Η αβεβαιότητα
(τυπική απόκλιση) εκτιμάται από τα σφάλματα του ίδιου του μοντέλου στο ιστορικό,
και οι πιθανότητες βγαίνουν από κανονική κατανομή.
Ξεχωριστό μοντέλο ανά διοργάνωση (NBA ≠ Euroleague ≠ ΕΚΟ Basket League).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import norm

from ..util import norm_team, parse_iso


@dataclass
class BasketPrediction:
    exp_home: float
    exp_away: float
    sd_margin: float
    sd_total: float

    @property
    def margin(self):
        return self.exp_home - self.exp_away

    @property
    def total(self):
        return self.exp_home + self.exp_away


class BasketballModel:
    def __init__(self, cfg: dict, aliases: dict):
        self.cfg, self.aliases = cfg, aliases
        self.teams, self.games = {}, None
        self.coef = None
        self.sd_margin = self.sd_total = None
        self.history: list[dict] = []

    def key(self, n):
        return norm_team(n, self.aliases)

    def fit(self, matches, now):
        rows = []
        for m in matches:
            if m["status"] != "finished" or m["home_score"] is None:
                continue
            age = (now - parse_iso(m["kickoff"])).total_seconds() / 86400
            if age < 0 or age > self.cfg["history_days"]:
                continue
            rows.append((self.key(m["home"]), self.key(m["away"]), m["home_score"], m["away_score"],
                         0.5 ** (age / self.cfg["half_life_days"])))
            self.history.append(m)
        if len(rows) < 30:
            raise ValueError(f"Πολύ λίγα ματς μπάσκετ για εκπαίδευση ({len(rows)})")
        names = sorted({r[0] for r in rows} | {r[1] for r in rows})
        self.teams = {n: i for i, n in enumerate(names)}
        T = len(names)
        P = 2 + 2 * T                       # μ, home, off[T], def[T]
        X, y, w = [], [], []
        for h, a, hs, as_, wt in rows:
            i, j = self.teams[h], self.teams[a]
            r1 = np.zeros(P); r1[0] = 1; r1[1] = 1; r1[2 + i] = 1; r1[2 + T + j] = -1
            r2 = np.zeros(P); r2[0] = 1; r2[2 + j] = 1; r2[2 + T + i] = -1
            X += [r1, r2]; y += [hs, as_]; w += [wt, wt]
        X, y, w = np.array(X), np.array(y, float), np.array(w)
        lam = 3.0
        R = np.diag([0, 0] + [lam] * (2 * T))
        sw = np.sqrt(w)[:, None]
        A = np.vstack([X * sw, np.sqrt(R)])
        b = np.concatenate([y * sw[:, 0], np.zeros(P)])
        self.coef = np.linalg.lstsq(A, b, rcond=None)[0]
        pred = X @ self.coef
        ph, pa = pred[0::2], pred[1::2]
        yh, ya = y[0::2], y[1::2]
        ww = w[0::2]
        em = (yh - ya) - (ph - pa)
        et = (yh + ya) - (ph + pa)
        self.sd_margin = max(8.0, float(np.sqrt(np.average(em ** 2, weights=ww))))
        self.sd_total = max(10.0, float(np.sqrt(np.average(et ** 2, weights=ww))))
        self.games = np.bincount([self.teams[r[0]] for r in rows] + [self.teams[r[1]] for r in rows],
                                 minlength=T)
        return self

    def known(self, name, min_games):
        i = self.teams.get(self.key(name))
        return i is not None and self.games[i] >= min_games

    def predict(self, home, away) -> BasketPrediction:
        T = len(self.teams)
        c = self.coef
        i, j = self.teams[self.key(home)], self.teams[self.key(away)]
        eh = c[0] + c[1] + c[2 + i] - c[2 + T + j]
        ea = c[0] + c[2 + j] - c[2 + T + i]
        return BasketPrediction(float(eh), float(ea), self.sd_margin, self.sd_total)

    @staticmethod
    def market_probs(p: BasketPrediction, lines: dict) -> dict:
        """lines: {'TOTAL': [221.5, ...], 'SPREAD': [-4.5, ...]} από τις διαθέσιμες αποδόσεις."""
        out = {}
        ph = float(1 - norm.cdf(0, p.margin, p.sd_margin))
        out[("ML", "HOME", None)] = ph
        out[("ML", "AWAY", None)] = 1 - ph
        for L in lines.get("TOTAL", []):
            ov = float(1 - norm.cdf(L, p.total, p.sd_total))
            out[("TOTAL", "OVER", L)] = ov
            out[("TOTAL", "UNDER", L)] = 1 - ov
        for L in lines.get("SPREAD", []):
            # γηπεδούχος με handicap L καλύπτει αν διαφορά + L > 0
            hc = float(1 - norm.cdf(-L, p.margin, p.sd_margin))
            out[("SPREAD", "HOME", L)] = hc
            out[("SPREAD", "AWAY", L)] = 1 - hc
        return out

    def form(self, team, n=6):
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
                        "venue": "Ε" if home else "Χ", "gf": gf, "ga": ga, "r": "Ν" if gf > ga else "Η"})
            if len(res) == n:
                break
        return res

    def h2h(self, home, away, limit=6):
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
