"""Backtest Euroleague: πόσο καλά προβλέπει το δικό μας μοντέλο (ratings επίθεσης/άμυνας, betbot/models/basketball.py) τα αποτελέσματα;
Δεδομένα: επίσημο API Euroleague (σεζόν E2018–E2025). Walk-forward: για κάθε αγώνα το μοντέλο εκπαιδεύεται ΜΟΝΟ με αγώνες πριν από αυτόν
(ανανέωση ανά 14 ημέρες). Ελέγχουμε νίκη (log-loss, Brier, βαθμονόμηση), διαφορά πόντων και σύνολο. Δεν υπάρχουν ιστορικές αποδόσεις Euroleague
(το Pinnacle δεν τη δίνει), άρα ΔΕΝ συγκρίνεται με την αγορά — μόνο με απλές βάσεις (γηπεδούχος, μέσος όρος).
Χρήση: python tools/euroleague_backtest.py > docs/euroleague_backtest.txt
"""
import math
import sys
from collections import defaultdict
from datetime import timedelta

import numpy as np
from scipy.stats import norm

sys.path.insert(0, ".")
from betbot.collectors.euroleague import _parse, URL  # noqa: E402
from betbot.models.basketball import BasketballModel  # noqa: E402
from betbot.util import http_get, parse_iso  # noqa: E402

CFG = {"history_days": 400, "half_life_days": 90}


def load(years):
    out = []
    for y in years:
        try:
            d, _ = http_get(URL.format(comp="E", year=y), timeout=40, retries=2)
            ms = _parse({"id": "EL"}, "E", y, d)
            out += ms
            print(f"# E{y}: {len(ms)} αγώνες", file=sys.stderr)
        except Exception as e:
            print(f"# E{y}: ΑΠΟΤΥΧΙΑ {str(e)[:80]}", file=sys.stderr)
    out = [dict(m.__dict__) for m in out]
    return sorted([m for m in out if m["status"] == "finished" and m["home_score"]], key=lambda m: m["kickoff"])


def main():
    ms = load(range(2018, 2026))
    print(f"Backtest Euroleague: {len(ms)} τελειωμένοι αγώνες ({ms[0]['kickoff'][:10]} – {ms[-1]['kickoff'][:10]})\n")
    rows = []
    last_fit, model = None, None
    for i, m in enumerate(ms):
        t = parse_iso(m["kickoff"])
        if t.year < 2019 or (t.year == 2019 and t.month < 11):
            continue                                  # πρώτη χρονιά = μόνο εκπαίδευση
        if model is None or (t - last_fit).days >= 14:
            try:
                model = BasketballModel(CFG, {}).fit(ms[:i], t)
                last_fit = t
            except Exception:
                continue
        if not (model.known(m["home"], 8) and model.known(m["away"], 8)):
            continue
        p = model.predict(m["home"], m["away"])
        ph = float(1 - norm.cdf(0, p.margin, p.sd_margin))
        rows.append((t, ph, int(m["home_score"] > m["away_score"]), p.margin, m["home_score"] - m["away_score"], p.total, m["home_score"] + m["away_score"], p.sd_margin, p.sd_total))
    n = len(rows)
    base = sum(r[2] for r in rows) / n
    br = sum((r[1] - r[2]) ** 2 for r in rows) / n
    brb = sum((base - r[2]) ** 2 for r in rows) / n
    ll = -sum(math.log(min(max(r[1] if r[2] else 1 - r[1], 1e-6), 1)) for r in rows) / n
    llb = -sum(math.log(base if r[2] else 1 - base) for r in rows) / n
    acc = sum((r[1] > 0.5) == bool(r[2]) for r in rows) / n
    print(f"{n} προβλέψεις (walk-forward) · γηπεδούχος κερδίζει {base * 100:.1f}% · σωστός νικητής μοντέλου {acc * 100:.1f}%")
    print(f"Brier {br:.4f} (σταθερή πιθανότητα γηπεδούχου: {brb:.4f}) · log-loss {ll:.4f} (σταθερή: {llb:.4f})")
    print(f"Μέσο σφάλμα διαφοράς: {np.mean([abs(r[3] - r[4]) for r in rows]):.2f} πόντοι · σφάλμα συνόλου: {np.mean([abs(r[5] - r[6]) for r in rows]):.2f} πόντοι")
    print(f"Τυπική απόκλιση που υποθέτει το μοντέλο: διαφορά {np.mean([r[7] for r in rows]):.1f}, σύνολο {np.mean([r[8] for r in rows]):.1f}\n")
    print("Βαθμονόμηση νίκης γηπεδούχου:")
    B = defaultdict(lambda: [0, 0.0, 0])
    for _, p, y, *_ in rows:
        k = min(int(p * 10), 9)
        B[k][0] += 1; B[k][1] += p; B[k][2] += y
    for k in sorted(B):
        c, sp, sy = B[k]
        if c >= 30:
            print(f"  {k * 10:3d}–{k * 10 + 10:3d}%: n={c:4d} μοντέλο {sp / c * 100:5.1f}% πραγματικό {sy / c * 100:5.1f}% διαφορά {(sy - sp) / c * 100:+5.1f}")
    print("\nΦαβορί μοντέλου (νικητής με p ≥ όριο):")
    for t in (0.60, 0.65, 0.70, 0.75, 0.80):
        v = [(max(p, 1 - p), (y if p >= 0.5 else 1 - y)) for _, p, y, *_ in rows if max(p, 1 - p) >= t]
        if len(v) >= 30:
            print(f"  ≥{t:.2f}: n={len(v):4d} μοντέλο {sum(a for a, _ in v) / len(v) * 100:5.1f}% πραγματικό {sum(b for _, b in v) / len(v) * 100:5.1f}%")
    print("\nΣυστολή πιθανότητας προς 50% (p' = 0.5 + (p−0.5)·s): Brier και log-loss — ποιο s είναι το καλύτερο;")
    for sh in (0.80, 0.85, 0.90, 0.95, 1.00, 1.05):
        pp = [(min(max(0.5 + (r[1] - 0.5) * sh, 1e-4), 1 - 1e-4), r[2]) for r in rows]
        print(f"  s={sh:.2f}: Brier {sum((a - b) ** 2 for a, b in pp) / n:.4f}  log-loss {-sum(math.log(a if b else 1 - a) for a, b in pp) / n:.4f}")
    print("\nΣύνολο πόντων: κάλυψη των διαστημάτων του μοντέλου (κανονική κατανομή):")
    for z in (0.5, 1.0, 1.5):
        cov = np.mean([abs(r[6] - r[5]) <= z * r[8] for r in rows])
        print(f"  ±{z}σ: μοντέλο {(2 * norm.cdf(z) - 1) * 100:.0f}% πραγματικό {cov * 100:.0f}%")
    print("\nΑνά σεζόν (σωστός νικητής / Brier):")
    S = defaultdict(list)
    for t, p, y, *_ in rows:
        S[t.year if t.month >= 8 else t.year - 1].append((p, y))
    for s, v in sorted(S.items()):
        print(f"  {s}-{s + 1}: n={len(v)} νικητής {sum((p > .5) == bool(y) for p, y in v) / len(v) * 100:.1f}% Brier {sum((p - y) ** 2 for p, y in v) / len(v):.4f}")


if __name__ == "__main__":
    main()
