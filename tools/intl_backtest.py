"""Έμμεσο backtest για διεθνείς αγώνες (17/11/2026) με τα ανοιχτά αποτελέσματα martj42/international_results (49.940 αγώνες).
ΠΡΟΣΟΧΗ: ΔΕΝ υπάρχουν δωρεάν ιστορικά με αποδόσεις για εθνικές ομάδες, άρα ΔΕΝ ελέγχουμε την αγορά. Ελέγχουμε πόσο προβλέψιμοι είναι οι αγώνες με ένα
απλό Elo (μόνο παρελθοντικά δεδομένα, χωρίς διαρροή): αν τα φαβορί με «πιθανότητα X» κερδίζουν όσο λέει το Elo, οι αγορές (που είναι τουλάχιστον τόσο καλές) είναι
εύλογο να είναι εξίσου βαθμονομημένες. Χρήση: python tools/intl_backtest.py results.csv > docs/intl_backtest.txt"""
import csv
import math
import sys
from collections import defaultdict

COMPETITIVE = ("UEFA Nations League", "FIFA World Cup qualification", "UEFA Euro qualification", "UEFA Euro", "FIFA World Cup", "Copa América",
               "African Cup of Nations", "African Cup of Nations qualification", "AFC Asian Cup", "CONCACAF Nations League", "Gold Cup")


def k_of(t):
    if t == "Friendly":
        return 20
    if t in ("FIFA World Cup", "UEFA Euro", "Copa América"):
        return 60
    return 40


def main(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    elo = defaultdict(lambda: 1500.0)
    out = []                       # (date, tournament, E_fav, fav_result)  fav_result: 1 νίκη φαβορί, 0.5 ισοπαλία, 0 ήττα
    for r in rows:
        try:
            h, a, hs, as_ = r["home_team"], r["away_team"], int(r["home_score"]), int(r["away_score"])
        except (ValueError, TypeError):
            continue
        ha = 0.0 if r["neutral"] == "TRUE" else 100.0
        dr = elo[h] + ha - elo[a]
        e = 1 / (1 + 10 ** (-dr / 400))                        # αναμενόμενο σκορ γηπεδούχου (νίκη=1, ισοπαλία=.5)
        res = 1.0 if hs > as_ else 0.5 if hs == as_ else 0.0
        if r["date"] >= "2010-01-01":
            if e >= 0.5:
                out.append((r["date"], r["tournament"], e, res))
            else:
                out.append((r["date"], r["tournament"], 1 - e, 1 - res))
        gd = abs(hs - as_)
        m = 1 if gd <= 1 else 1.5 if gd == 2 else (11 + gd) / 8
        k = k_of(r["tournament"]) * m
        d = k * (res - e)
        elo[h] += d
        elo[a] -= d
    print(f"{len(rows)} αγώνες· αξιολόγηση από το 2010: {len(out)} αγώνες (το Elo χρησιμοποιεί μόνο ό,τι προηγείται κάθε αγώνα)\n")

    def table(title, data):
        print(title)
        print("  Elo-αναμενόμενο φαβορί | n | νίκη φαβορί | ισοπαλία | ήττα φαβορί")
        B = defaultdict(lambda: [0, 0, 0, 0])
        for _, _, e, res in data:
            k = "0.50-0.60" if e < .6 else "0.60-0.70" if e < .7 else "0.70-0.80" if e < .8 else "0.80-0.90" if e < .9 else "0.90+"
            b = B[k]
            b[0] += 1
            b[1] += res == 1.0
            b[2] += res == 0.5
            b[3] += res == 0.0
        for k in sorted(B):
            n, w, d, l = B[k]
            print(f"  {k}                    {n:5d}   {w / n:.1%}      {d / n:.1%}     {l / n:.1%}")
        print()

    comp = [x for x in out if x[1] in COMPETITIVE]
    table("ΟΛΟΙ οι αγώνες 2010+:", out)
    table("ΜΟΝΟ επίσημοι/ανταγωνιστικοί αγώνες (Nations League, προκριματικά, τελικές φάσεις) 2010+:", comp)
    nl = [x for x in out if x[1] == "UEFA Nations League"]
    table("ΜΟΝΟ UEFA Nations League:", nl)
    fr = [x for x in out if x[1] == "Friendly"]
    table("ΜΟΝΟ φιλικοί (για σύγκριση):", fr)
    # σταθερότητα: δύο μισά των ανταγωνιστικών
    mid = comp[len(comp) // 2][0]
    for nm, d in (("παλιά", [x for x in comp if x[0] < mid]), ("πρόσφατα", [x for x in comp if x[0] >= mid])):
        sel = [x for x in d if 0.65 <= x[2] < 0.80]
        if sel:
            w = sum(1 for x in sel if x[3] == 1.0) / len(sel)
            print(f"  ανταγωνιστικοί {nm} (έως/από {mid}): φαβορί με Elo 65–80%: n={len(sel)} κερδίζουν {w:.1%} (αν «πιθανότητα νίκης» ≈ Elo-αναμενόμενο − ισοπαλίες/2)")
    # Brier 1X2 απλό: P(νίκη)=E−d/2 με d=μέσος ρυθμός ισοπαλιών ανά κάδο -> ελέγχουμε ότι η ισοπαλία είναι πιο συχνή όταν ισοζυγίζονται
    print("\nΣΥΜΠΕΡΑΣΜΑ: βλ. σχόλιο στο README (δεν υπάρχουν αποδόσεις για να ελεγχθεί η αγορά).")


if __name__ == "__main__":
    main(sys.argv[1])
