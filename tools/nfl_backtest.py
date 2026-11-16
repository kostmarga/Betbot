"""Backtest NFL με τα ανοιχτά δεδομένα nflverse (https://github.com/nflverse/nfldata, games.csv: αποτελέσματα + γραμμές αγοράς).
Ερώτημα: είναι η αγορά NFL καλά βαθμονομημένη (όπως στο NBA/ποδόσφαιρο) και ποιο ROI έχουν τα φαβορί/spread/totals;
Χρήση: python tools/nfl_backtest.py games.csv > docs/nfl_backtest.txt
"""
import csv
import math
import sys
from collections import defaultdict


def dec(ml):
    ml = float(ml)
    return 1 + (ml / 100 if ml > 0 else 100 / -ml)


def main(path):
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8")) if r["home_score"] not in ("", None) and r["home_moneyline"] not in ("", None)]
    print(f"{len(rows)} αγώνες NFL με γραμμή αγοράς και αποτέλεσμα ({rows[0]['season']}–{rows[-1]['season']})\n")
    # --- 1) Moneyline: βαθμονόμηση φαβορί
    B = defaultdict(lambda: [0, 0.0, 0, 0.0])      # κλάδος -> n, Σp, νίκες, κέρδος (1 μονάδα)
    games = []
    for r in rows:
        oh, oa = dec(r["home_moneyline"]), dec(r["away_moneyline"])
        ph, pa = 1 / oh, 1 / oa
        s = ph + pa
        ph, pa = ph / s, pa / s
        h, a = int(r["home_score"]), int(r["away_score"])
        if h == a:
            continue
        for side, p, o, win in (("home", ph, oh, h > a), ("away", pa, oa, a > h)):
            if p < 0.5:
                continue
            k = "0.50-0.60" if p < .6 else "0.60-0.70" if p < .7 else "0.70-0.80" if p < .8 else "0.80+"
            b = B[k]
            b[0] += 1; b[1] += p; b[2] += win; b[3] += (o - 1) if win else -1
            games.append((r["season"], int(r["week"]) if r["week"].isdigit() else 0, r["gameday"], p, o, win))
    print("Φαβορί (moneyline, χωρίς προμήθεια): κλίμακα, n, προβλεπόμενη, πραγματική, ROI")
    for k in sorted(B):
        n, sp, w, pl = B[k]
        print(f"  {k}  {n:5d}  {sp / n:.3f}  {w / n:.3f}  ROI {pl / n:+.1%}")
    # --- 2) Spread / total
    sc = [0, 0, 0.0]; tc = [0, 0, 0.0]
    for r in rows:
        if r["spread_line"] in ("", None) or r["total_line"] in ("", None):
            continue
        h, a = int(r["home_score"]), int(r["away_score"])
        sp = float(r["spread_line"])           # θετικό = φαβορί η γηπεδούχος (nflverse: spread_line = προβλεπόμενη διαφορά γηπεδούχου)
        d = (h - a) - sp
        if d != 0:
            sc[0] += 1; sc[1] += d > 0; sc[2] += (100 / 110) if d > 0 else -1
        t = h + a - float(r["total_line"])
        if t != 0:
            tc[0] += 1; tc[1] += t > 0; tc[2] += (100 / 110) if t > 0 else -1
    print(f"\nSpread (γηπεδούχος, -110): n={sc[0]} κάλυψε {sc[1] / sc[0]:.1%} ROI {sc[2] / sc[0]:+.1%}")
    print(f"Totals (Over, -110):      n={tc[0]} Over {tc[1] / tc[0]:.1%} ROI {tc[2] / tc[0]:+.1%}")
    # --- 3) Προσομοίωση: ανά εβδομάδα 1 δελτίο 2 σκελών από τα πιο πιθανά φαβορί, απόδοση στο [1.85, 2.30]
    byw = defaultdict(list)
    for g in games:
        byw[(g[0], g[1])].append(g)
    res = {"n": 0, "w": 0, "pl": 0.0}
    for k, gs in byw.items():
        gs = sorted(gs, key=lambda g: -g[3])
        best = None
        for i in range(len(gs)):
            for j in range(i + 1, len(gs)):
                o = gs[i][4] * gs[j][4]
                if 1.85 <= o <= 2.30 and gs[i][3] >= .62 and gs[j][3] >= .62:
                    sc_ = gs[i][3] * gs[j][3]
                    if best is None or sc_ > best[0]:
                        best = (sc_, gs[i], gs[j], o)
        if best:
            ok = best[1][5] and best[2][5]
            res["n"] += 1; res["w"] += ok; res["pl"] += (best[3] - 1) if ok else -1
    if res["n"]:
        print(f"\nΠροσομοίωση: 1 δελτίο 2 σκελών/εβδομάδα (p≥62% ανά σκέλος, απόδοση 1.85–2.30): {res['n']} δελτία, "
              f"επιτυχία {res['w'] / res['n']:.1%}, ROI {res['pl'] / res['n']:+.1%}")
    # --- 4) Σε δύο μισά (σταθερότητα)
    seas = sorted({g[0] for g in games})
    mid = seas[len(seas) // 2]
    for nm, f in (("παλιά", lambda s: s < mid), ("πρόσφατα", lambda s: s >= mid)):
        x = [g for g in games if f(g[0]) and g[3] >= .65]
        if x:
            print(f"Φαβορί p≥65% ({nm}, σεζόν {'<' if nm == 'παλιά' else '≥'}{mid}): n={len(x)} ROI {sum((g[4] - 1) if g[5] else -1 for g in x) / len(x):+.1%}")


if __name__ == "__main__":
    main(sys.argv[1])
