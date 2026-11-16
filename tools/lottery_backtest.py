"""Backtest δελτίων 10+/30+/100+, Safe, Over και Προτεινόμενο στο ΠΟΔΟΣΦΑΙΡΟ με ιστορικά δεδομένα football-data.co.uk.
Για κάθε μέρα αγώνων: υποψήφιες επιλογές = 1Χ2 και Over 2.5 (όχι Under, όπως στο config) με πιθανότητα από το devig του Pinnacle (κλείσιμο) και
απόδοση = ΜΕΣΟΣ ΟΡΟΣ πρακτορείων (κλείσιμο) — πιο κοντά σε αυτό που δίνει ένα κανονικό πρακτορείο από ό,τι το Pinnacle. Τα δελτία χτίζονται με
τον ΙΔΙΟ αλγόριθμο και τα ΙΔΙΑ όρια του config.yaml (selector.build_slip). Μετράμε: πόσο συχνά πέρασαν, πόσο λέει το μοντέλο ότι θα περνούσαν, και ROI.
Περιορισμοί: δεν εφαρμόζονται τραυματισμοί/rotation/φόρμα (δεν υπάρχουν ιστορικά)· οι αποδόσεις δεν είναι του Stoiximan/ΟΠΑΠ· ένα δελτίο ανά μέρα και κατηγορία.
Χρήση: python tools/lottery_backtest.py > docs/lottery_backtest.txt
"""
import csv
import io
import math
import random
import sys
from collections import defaultdict
from datetime import datetime

import numpy as np
import yaml

sys.path.insert(0, ".")
from betbot.selector import build_slip  # noqa: E402
from betbot.util import http_get  # noqa: E402

DIVS = ["E0", "E1", "E2", "E3", "SC0", "D1", "D2", "I1", "I2", "SP1", "SP2", "F1", "F2", "N1", "B1", "P1", "T1", "G1"]
SEASONS = ["2223", "2324", "2425", "2526"]


def f(r, *cols):
    for c in cols:
        try:
            v = float(r.get(c) or "")
            if v > 1.0:
                return v
        except ValueError:
            pass
    return None


def load():
    days = defaultdict(list)
    for s in SEASONS:
        for d in DIVS:
            try:
                t, _ = http_get(f"https://www.football-data.co.uk/mmz4281/{s}/{d}.csv", expect="text", retries=2, timeout=40)
            except Exception:
                continue
            for i, r in enumerate(csv.DictReader(io.StringIO(t.lstrip("﻿")))):
                ds = (r.get("Date") or "").strip()
                try:
                    dt = datetime.strptime(ds, "%d/%m/%Y" if len(ds) == 10 else "%d/%m/%y")
                    gh, ga = int(r["FTHG"]), int(r["FTAG"])
                except (ValueError, KeyError):
                    continue
                ph, px, pa = f(r, "PSCH", "PSH"), f(r, "PSCD", "PSD"), f(r, "PSCA", "PSA")
                po, pu = f(r, "PC>2.5", "P>2.5"), f(r, "PC<2.5", "P<2.5")
                ah, ax, aa = f(r, "AvgCH", "AvgH", "B365H"), f(r, "AvgCD", "AvgD", "B365D"), f(r, "AvgCA", "AvgA", "B365A")
                ao = f(r, "AvgC>2.5", "Avg>2.5", "B365>2.5")
                if None in (ph, px, pa, ah, ax, aa):
                    continue
                s1 = 1 / ph + 1 / px + 1 / pa
                cs = [("1X2", "1", (1 / ph) / s1, ah, gh > ga), ("1X2", "X", (1 / px) / s1, ax, gh == ga), ("1X2", "2", (1 / pa) / s1, aa, gh < ga)]
                if None not in (po, pu, ao):
                    cs.append(("OU", "OVER", (1 / po) / (1 / po + 1 / pu), ao, gh + ga > 2.5))
                for mk, sel, p, odds, win in cs:
                    days[dt.strftime("%Y-%m-%d")].append({
                        "match_id": f"{s}{d}{i}", "league": d, "league_name": d, "sport": "football", "kickoff": dt.strftime("%Y-%m-%dT15:00:00Z"),
                        "market": mk, "selection": sel, "line": 2.5 if mk == "OU" else None, "family": "result" if mk == "1X2" else "goals",
                        "label": f"{mk} {sel}", "odds": odds, "p": p, "p_market": p, "p_model": p, "edge": p * odds - 1, "win": win, "blocked": set()})
    return days


def boot(profits, n=2000, seed=1):
    rnd = random.Random(seed)
    m = [np.mean([rnd.choice(profits) for _ in profits]) for _ in range(n)]
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def main():
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    L, sel = cfg["lists"], cfg["selection"]
    days = load()
    print(f"Backtest δελτίων ποδοσφαίρου: {len(days)} μέρες αγώνων ({SEASONS[0]}–{SEASONS[-1]}), πιθανότητες Pinnacle (κλείσιμο), αποδόσεις μέσος όρος πρακτορείων\n")
    cats = {
        "recommended": (L["recommended"], dict(max_leg_odds=L["recommended"]["max_leg_odds"])),
        "safe": (L["safe"], {}), "x10": (L["x10"], {}), "x30": (L["x30"], {}), "x100": (L["x100"], {}),
    }
    for name, (c, extra) in cats.items():
        res = []
        for day, cs in sorted(days.items()):
            pool = [x for x in cs if x["edge"] >= sel["min_edge"] and x["p"] >= c.get("min_leg_prob", 0) and sel["min_odds"] <= x["odds"] <= sel["max_odds_any"]
                    and x["odds"] <= extra.get("max_leg_odds", 99)]
            if len({x["match_id"] for x in pool}) < c["min_legs"]:
                continue
            sl = build_slip(pool, c["min_total"], c["max_total"], c["min_legs"], c["max_legs"], cfg, max_basket=99)
            if not sl:
                continue
            win = all(l["win"] for l in sl["legs"])
            res.append((sl["p_win"], sl["total_odds"], win, len(sl["legs"])))
        if not res:
            print(f"{name}: κανένα δελτίο\n")
            continue
        n = len(res)
        pw = np.mean([r[0] for r in res]); hit = np.mean([r[2] for r in res])
        profits = [(r[1] if r[2] else 0) - 1 for r in res]
        lo, hi = boot(profits)
        lo_w, hi_w = (hit - 1.96 * math.sqrt(hit * (1 - hit) / n), hit + 1.96 * math.sqrt(hit * (1 - hit) / n))
        print(f"{name:12s} δελτία: {n:4d} · μέσες αποδόσεις {np.mean([r[1] for r in res]):6.1f} · σκέλη {np.mean([r[3] for r in res]):.1f} · "
              f"πιθανότητα μοντέλου {pw * 100:5.1f}% · πέρασαν {hit * 100:5.1f}% [{lo_w * 100:.1f}–{hi_w * 100:.1f}] · ROI {np.mean(profits) * 100:+6.1f}% [{lo * 100:+.0f}…{hi * 100:+.0f}]")
        # βαθμονόμηση ανά κάδο πιθανότητας δελτίου
        B = defaultdict(lambda: [0, 0.0, 0])
        for p, o, w, k in res:
            b = 0 if p < 0.05 else 1 if p < 0.15 else 2 if p < 0.30 else 3 if p < 0.50 else 4
            B[b][0] += 1; B[b][1] += p; B[b][2] += w
        names = ["<5%", "5–15%", "15–30%", "30–50%", "≥50%"]
        for b in sorted(B):
            c_, sp, sw = B[b]
            if c_ >= 15:
                print(f"      p δελτίου {names[b]:7s}: n={c_:4d} μοντέλο {sp / c_ * 100:5.1f}% πραγματικό {sw / c_ * 100:5.1f}%")
        print()


if __name__ == "__main__":
    main()
