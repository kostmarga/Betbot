"""Backtest BTTS (και οι δύο σκοράρουν) με ιστορικά δεδομένα football-data.co.uk (τιμές κλεισίματος Pinnacle).
ΔΕΝ υπάρχουν ιστορικές τιμές BTTS, οπότε ελέγχουμε την αγορά ΕΜΜΕΣΑ: από 1Χ2 + Over/Under 2.5 του Pinnacle (devig) βρίσκουμε
τα αναμενόμενα γκολ κάθε ομάδας (Poisson) και υπολογίζουμε P(BTTS). Ερώτημα: βγαίνουν στην πράξη όσο λέει το μοντέλο;
Χρήση: python tools/btts_backtest.py > docs/btts_backtest.txt
"""
import csv
import io
import math
import sys
from collections import defaultdict

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

sys.path.insert(0, ".")
from betbot.util import http_get  # noqa: E402

DIVS = ["E0", "E1", "E2", "E3", "SC0", "D1", "D2", "I1", "I2", "SP1", "SP2", "F1", "F2", "N1", "B1", "P1", "T1", "G1"]
SEASONS = ["2223", "2324", "2425", "2526"]
G = 11


def f(r, *cols):
    for c in cols:
        try:
            v = float(r.get(c) or "")
            if v > 1.0:
                return v
        except ValueError:
            pass
    return None


def probs(lh, la):
    ph, pa = poisson.pmf(np.arange(G), lh), poisson.pmf(np.arange(G), la)
    m = np.outer(ph, pa)
    i, j = np.indices(m.shape)
    return m[i > j].sum(), m[i == j].sum(), m[i < j].sum(), m[i + j > 2].sum(), m[(i > 0) & (j > 0)].sum()


def fit(p1, px, p2, po):
    def loss(x):
        lh, la = math.exp(x[0]), math.exp(x[1])
        a, b, c, d, _ = probs(lh, la)
        return (a - p1) ** 2 + (b - px) ** 2 + (c - p2) ** 2 + (d - po) ** 2
    r = minimize(loss, [0.2, 0.0], method="Nelder-Mead", options={"xatol": 1e-3, "fatol": 1e-8})
    return math.exp(r.x[0]), math.exp(r.x[1])


def main():
    rows = []
    for s in SEASONS:
        for d in DIVS:
            try:
                t, _ = http_get(f"https://www.football-data.co.uk/mmz4281/{s}/{d}.csv", expect="text", retries=2, timeout=40)
            except Exception:
                continue
            for r in csv.DictReader(io.StringIO(t.lstrip("﻿"))):
                h, a = f(r, "PSCH", "PSH"), f(r, "PSCA", "PSA")
                x = f(r, "PSCD", "PSD")
                o, u = f(r, "PC>2.5", "P>2.5"), f(r, "PC<2.5", "P<2.5")
                try:
                    gh, ga = int(r["FTHG"]), int(r["FTAG"])
                except (KeyError, ValueError):
                    continue
                if None in (h, x, a, o, u):
                    continue
                s1 = 1 / h + 1 / x + 1 / a
                so = 1 / o + 1 / u
                lh, la = fit((1 / h) / s1, (1 / x) / s1, (1 / a) / s1, (1 / o) / so)
                p = probs(lh, la)[4]
                rows.append((d, s, p, int(gh > 0 and ga > 0), lh + la))
    n = len(rows)
    print(f"Backtest BTTS: {n} αγώνες ({SEASONS[0]}–{SEASONS[-1]}, {len(DIVS)} λίγκες), P(BTTS) από Pinnacle 1Χ2 + Over/Under 2.5 (Poisson, ανεξάρτητα γκολ)\n")
    base = sum(r[3] for r in rows) / n
    br = sum((r[2] - r[3]) ** 2 for r in rows) / n
    brb = sum((base - r[3]) ** 2 for r in rows) / n
    ll = -sum(math.log(r[2] if r[3] else 1 - r[2]) for r in rows) / n
    print(f"Ποσοστό BTTS όλων των αγώνων: {base * 100:.1f}% · Brier μοντέλου {br:.4f} (σταθερό ποσοστό: {brb:.4f}) · log-loss {ll:.4f}\n")
    print("Βαθμονόμηση (μοντέλο vs πραγματικό):")
    B = defaultdict(lambda: [0, 0.0, 0])
    for _, _, p, y, _ in rows:
        k = min(int(p * 20), 19)
        B[k][0] += 1; B[k][1] += p; B[k][2] += y
    for k in sorted(B):
        c, sp, sy = B[k]
        if c >= 30:
            print(f"  {k * 5:3d}–{k * 5 + 5:3d}%: n={c:5d}  μοντέλο {sp / c * 100:5.1f}%  πραγματικό {sy / c * 100:5.1f}%  διαφορά {(sy - sp) / c * 100:+5.1f}")
    print("\nΣκέλη που θα επέλεγε η κατηγορία (YES όταν p≥ όριο, NO όταν 1−p≥ όριο):")
    for t in (0.55, 0.58, 0.60, 0.62, 0.65):
        y = [(p, o) for _, _, p, o, _ in rows if p >= t]
        no = [(1 - p, 1 - o) for _, _, p, o, _ in rows if 1 - p >= t]
        for name, v in (("YES", y), ("NO ", no)):
            if len(v) >= 30:
                print(f"  {name} ≥{t:.2f}: n={len(v):5d}  μοντέλο {sum(a for a, _ in v) / len(v) * 100:5.1f}%  πραγματικό {sum(b for _, b in v) / len(v) * 100:5.1f}%")
    print("\nΑνά λίγκα (πραγματικό ποσοστό BTTS − μέση πιθανότητα μοντέλου):")
    L = defaultdict(lambda: [0, 0.0, 0])
    for d, _, p, y, _ in rows:
        L[d][0] += 1; L[d][1] += p; L[d][2] += y
    for d, (c, sp, sy) in sorted(L.items(), key=lambda x: -x[1][0]):
        print(f"  {d:4s} n={c:5d} μοντέλο {sp / c * 100:5.1f}% πραγματικό {sy / c * 100:5.1f}% διαφορά {(sy - sp) / c * 100:+4.1f}")


if __name__ == "__main__":
    main()
