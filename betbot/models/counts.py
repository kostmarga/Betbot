"""Μοντέλο για «μετρήσιμα» στατιστικά αγώνα: κόρνερ, κάρτες, πλάγια (και φάουλ, σουτ).

Για κάθε ομάδα υπολογίζουμε (με χρονική στάθμιση και συρρίκνωση προς τον μέσο όρο):
  • «υπέρ»  : πόσα κάνει η ίδια σε σχέση με τον μέσο όρο της λίγκας (εντός/εκτός)
  • «κατά»  : πόσα κάνουν οι αντίπαλοί της σε σχέση με τον μέσο όρο

  αναμενόμενα γηπεδούχου = μ.ο. λίγκας (εντός) × υπέρ_Γ × κατά_Φ
  αναμενόμενα φιλοξενούμενου = μ.ο. λίγκας (εκτός) × υπέρ_Φ × κατά_Γ

Για τις κάρτες πολλαπλασιάζουμε και με τον «συντελεστή διαιτητή»
(πόσες κάρτες βγάζει σε σχέση με τον μέσο όρο, συρρικνωμένο όταν έχει λίγα ματς).

Η κατανομή είναι αρνητική διωνυμική (Poisson με επιπλέον διασπορά), με τη διασπορά
να εκτιμάται από τα ίδια τα δεδομένα. Από εκεί βγαίνουν οι πιθανότητες για κάθε γραμμή
(Over/Under) και για το «ποια ομάδα θα κάνει περισσότερα».
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np
from scipy.stats import nbinom, poisson

from ..util import norm_team, parse_iso

METRICS = {   # μετρική -> (στήλη στο team_stats, συνηθισμένες γραμμές)
    "corners": ("corners", [7.5, 8.5, 9.5, 10.5, 11.5, 12.5]),
    "cards": ("yellow", [2.5, 3.5, 4.5, 5.5, 6.5]),
    "throw_ins": ("throw_ins", [32.5, 35.5, 38.5, 40.5, 42.5, 44.5, 47.5]),
}
LABEL = {"corners": "κόρνερ", "cards": "κάρτες", "throw_ins": "πλάγια"}


class CountModel:
    def __init__(self, metric: str, cfg: dict, aliases: dict):
        self.metric = metric
        self.col, self.lines = METRICS[metric]
        self.cfg = cfg
        self.aliases = aliases
        self.att, self.dfn = {}, {}
        self.raw = defaultdict(list)        # ομάδα -> [(ημ/νία, υπέρ, κατά, εντός)]
        self.venue_mean = {}                # (λίγκα, εντός) -> μ.ο.
        self.global_mean = {1: 1.0, 0: 1.0}
        self.ref = {}                       # διαιτητής -> (συντελεστής, ματς, μ.ο.)
        self.phi = 1.2
        self.n_rows = 0

    def key(self, n):
        return norm_team(n, self.aliases)

    def fit(self, rows: list[dict], now) -> "CountModel":
        hl = self.cfg["half_life_days"]
        # ζευγάρια (γηπεδούχος, φιλοξενούμενος) ανά αγώνα
        by_ev = defaultdict(dict)
        for r in rows:
            if r.get(self.col) is None:
                continue
            by_ev[r["event_key"]][r["is_home"]] = r
        games = []
        for ev, sides in by_ev.items():
            if 1 in sides and 0 in sides:
                h, a = sides[1], sides[0]
                age = (now - parse_iso(h["kickoff"])).total_seconds() / 86400
                if 0 <= age <= self.cfg["history_days"]:
                    games.append((h, a, 0.5 ** (age / hl)))
        self.n_rows = len(games)
        if len(games) < 20:
            raise ValueError(f"λίγα δεδομένα για {LABEL[self.metric]} ({len(games)} αγώνες)")

        # μέσοι όροι λίγκας ανά έδρα
        acc = defaultdict(lambda: [0.0, 0.0])
        for h, a, w in games:
            for r, home in ((h, 1), (a, 0)):
                acc[(r["league"], home)][0] += w * r[self.col]
                acc[(r["league"], home)][1] += w
        for k, (s, n) in acc.items():
            if n >= 8:
                self.venue_mean[k] = s / n
        for home in (1, 0):
            s = sum(acc[k][0] for k in acc if k[1] == home)
            n = sum(acc[k][1] for k in acc if k[1] == home)
            self.global_mean[home] = s / n if n else 1.0

        def vm(league, home):
            return self.venue_mean.get((league, home), self.global_mean[home]) or 1e-6

        # δυνάμεις ομάδων (συρρίκνωση με k «ψεύτικα» ματς στον μέσο όρο)
        k = self.cfg.get("shrink_games", 4)
        sa, sd, sw = defaultdict(float), defaultdict(float), defaultdict(float)
        for h, a, w in games:
            hk, ak = self.key(h["team"]), self.key(a["team"])
            sa[hk] += w * h[self.col] / vm(h["league"], 1)
            sd[hk] += w * a[self.col] / vm(a["league"], 0)
            sa[ak] += w * a[self.col] / vm(a["league"], 0)
            sd[ak] += w * h[self.col] / vm(h["league"], 1)
            sw[hk] += w
            sw[ak] += w
            self.raw[hk].append((h["kickoff"], h[self.col], a[self.col], 1))
            self.raw[ak].append((a["kickoff"], a[self.col], h[self.col], 0))
        for t in sw:
            self.att[t] = (sa[t] + k) / (sw[t] + k)
            self.dfn[t] = (sd[t] + k) / (sw[t] + k)

        # διαιτητές (μόνο για κάρτες)
        if self.metric == "cards":
            ref = defaultdict(lambda: [0.0, 0.0, 0])
            for h, a, w in games:
                nm = h.get("referee")
                if not nm:
                    continue
                exp = vm(h["league"], 1) + vm(a["league"], 0)
                ref[nm][0] += (h[self.col] + a[self.col]) / exp
                ref[nm][1] += h[self.col] + a[self.col]
                ref[nm][2] += 1
            kr = self.cfg.get("referee_shrink_games", 6)
            for nm, (ratio_sum, tot, n) in ref.items():
                self.ref[nm] = ((ratio_sum + kr) / (n + kr), n, tot / n)

        # διασπορά: πόσο «απλώνουν» τα σύνολα σε σχέση με Poisson
        res, mus = [], []
        for h, a, w in games:
            mu = self._exp(h["team"], a["team"], h["league"], h.get("referee"))
            mus.append(sum(mu))
            res.append((h[self.col] + a[self.col] - sum(mu)) ** 2)
        self.phi = float(np.clip(np.mean(res) / max(np.mean(mus), 1e-6), 1.0, 3.0))
        return self

    def _exp(self, home, away, league, referee=None):
        hk, ak = self.key(home), self.key(away)
        mh = self.venue_mean.get((league, 1), self.global_mean[1])
        ma = self.venue_mean.get((league, 0), self.global_mean[0])
        eh = mh * self.att.get(hk, 1.0) * self.dfn.get(ak, 1.0)
        ea = ma * self.att.get(ak, 1.0) * self.dfn.get(hk, 1.0)
        if self.metric == "cards" and referee and referee in self.ref:
            f = self.ref[referee][0]
            eh, ea = eh * f, ea * f
        return eh, ea

    def known(self, team, min_games):
        return len(self.raw.get(self.key(team), [])) >= min_games

    # ---------------- κατανομές ----------------
    def _pmf(self, mu, n=None):
        n = n or int(mu * 3 + 25)
        x = np.arange(n)
        if self.phi <= 1.01:
            return poisson.pmf(x, mu)
        r = mu / (self.phi - 1)
        return nbinom.pmf(x, r, r / (r + mu))

    def predict(self, home, away, league, referee=None) -> dict:
        eh, ea = self._exp(home, away, league, referee)
        ph, pa = self._pmf(eh), self._pmf(ea)
        tot = np.convolve(ph, pa)
        cdf = np.cumsum(tot)
        out = {"exp_home": eh, "exp_away": ea, "exp_total": eh + ea, "lines": {}}
        base = round((eh + ea) * 2) / 2
        lines = sorted(set(self.lines) | {base - 1.5, base - 0.5, base + 0.5, base + 1.5})
        for L in lines:
            if L <= 0 or L % 1 == 0:
                continue
            over = float(1 - cdf[int(np.floor(L))]) if int(np.floor(L)) < len(cdf) else 0.0
            out["lines"][L] = over
        # ποιος θα κάνει περισσότερα
        joint = np.outer(ph, pa)
        out["more_home"] = float(np.tril(joint, -1).sum())
        out["more_away"] = float(np.triu(joint, 1).sum())
        out["equal"] = float(np.trace(joint))
        return out

    # ---------------- για το «γιατί» ----------------
    def team_avgs(self, team, n=10):
        rows = sorted(self.raw.get(self.key(team), []))[-n:]
        if not rows:
            return None
        return {"n": len(rows), "for": np.mean([r[1] for r in rows]), "against": np.mean([r[2] for r in rows]),
                "totals": [r[1] + r[2] for r in rows]}

    def referee_info(self, referee):
        if referee and referee in self.ref:
            f, n, avg = self.ref[referee]
            return {"name": referee, "factor": f, "games": n, "avg": avg}
        return None
