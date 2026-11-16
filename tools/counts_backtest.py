"""Backtest κόρνερ και καρτών (walk-forward) με ιστορικά δεδομένα football-data.co.uk (σεζόν 2021-22 … 2025-26, 18 λίγκες).
Μοντέλο: ΑΚΡΙΒΩΣ το betbot/models/counts.py με τις ρυθμίσεις του config.yaml. Για κάθε παράθυρο 28 ημερών το μοντέλο εκπαιδεύεται ΜΟΝΟ με αγώνες πριν από αυτό.
Τρία τεστ: (1) κόρνερ, (2) «κάρτες» όπως τις εκπαιδεύαμε ως τώρα (μόνο κίτρινες), (3) «κάρτες» όπως τις μετράνε τα πρακτορεία και η κρίση του bot
(πόντοι κράτησης: κίτρινη 1 + κόκκινη 2). Δεν υπάρχουν ιστορικές αποδόσεις κόρνερ/καρτών, άρα ελέγχουμε ΠΙΘΑΝΟΤΗΤΕΣ (βαθμονόμηση, Brier vs σταθερή βάση), όχι ROI.
Χρήση: python tools/counts_backtest.py > docs/counts_backtest.txt
"""
import csv
import io
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
import yaml

sys.path.insert(0, ".")
from betbot.models.counts import CountModel  # noqa: E402
from betbot.util import http_get, parse_iso  # noqa: E402

DIVS = ["E0", "E1", "E2", "E3", "SC0", "D1", "D2", "I1", "I2", "SP1", "SP2", "F1", "F2", "N1", "B1", "P1", "T1", "G1"]
SEASONS = ["2122", "2223", "2324", "2425", "2526"]
LINES = {"corners": [7.5, 8.5, 9.5, 10.5, 11.5], "yellow": [2.5, 3.5, 4.5, 5.5], "bookings": [3.5, 4.5, 5.5, 6.5, 7.5]}


def fnum(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def load():
    rows = []
    for s in SEASONS:
        for d in DIVS:
            try:
                t, _ = http_get(f"https://www.football-data.co.uk/mmz4281/{s}/{d}.csv", expect="text", retries=2, timeout=40)
            except Exception:
                continue
            for i, r in enumerate(csv.DictReader(io.StringIO(t.lstrip("﻿")))):
                try:
                    dt = datetime.strptime(r["Date"].strip(), "%d/%m/%Y" if len(r["Date"].strip()) == 10 else "%d/%m/%y")
                except (KeyError, ValueError):
                    continue
                hc, ac, hy, ay = fnum(r.get("HC")), fnum(r.get("AC")), fnum(r.get("HY")), fnum(r.get("AY"))
                hr, ar = fnum(r.get("HR")) or 0, fnum(r.get("AR")) or 0
                if None in (hc, ac, hy, ay) or not r.get("HomeTeam"):
                    continue
                ko = dt.replace(hour=15, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                ev = f"{s}{d}{i}"
                ref = (r.get("Referee") or "").strip() or None
                for team, home, c, y, red in ((r["HomeTeam"], 1, hc, hy, hr), (r["AwayTeam"], 0, ac, ay, ar)):
                    rows.append({"event_key": ev, "kickoff": ko, "league": d, "team": team, "is_home": home, "corners": c, "yellow": y,
                                 "bookings": y + 2 * red, "referee": ref})
    return rows


def ll(p):
    return -math.log(min(max(p, 1e-6), 1 - 1e-6))


def evaluate(metric, col, rows, cfg, start, end, ref_on=True):
    by_ev = defaultdict(dict)
    for r in rows:
        by_ev[r["event_key"]][r["is_home"]] = r
    events = sorted([(parse_iso(s[1]["kickoff"]), s) for s in by_ev.values() if 1 in s and 0 in s], key=lambda x: x[0])
    res = []                                         # (L, p, y, base, league, referee_known)
    w0 = start
    while w0 < end:
        w1 = w0 + timedelta(days=28)
        test = [e for e in events if w0 <= e[0] < w1]
        if test:
            train = [r for r in rows if parse_iso(r["kickoff"]) < w0]
            m = CountModel(metric if metric == "corners" else "cards", cfg["models"]["counts"], {})
            m.col, m.lines = col, LINES[col]
            m.fit(train, w0)
            tot_tr = defaultdict(float)
            for r in train:
                tot_tr[r["event_key"]] += r[col]
            tots = list(tot_tr.values())
            for ko, s in test:
                h, a = s[1], s[0]
                if not (m.known(h["team"], 8) and m.known(a["team"], 8)):
                    continue
                refn = h["referee"] if ref_on else None
                pred = m.predict(h["team"], a["team"], h["league"], refn)
                total = h[col] + a[col]
                for L, p in pred["lines"].items():
                    b = float(np.mean([t > L for t in tots]))
                    res.append((L, p, int(total > L), b, h["league"], bool(refn and refn in m.ref and m.ref[refn][1] >= 8)))
        w0 = w1
    return res


def report(name, res):
    n = len(res)
    print(f"\n=== {name}: {n} προβλέψεις (αγώνας × γραμμή) ===")
    br = np.mean([(p - y) ** 2 for _, p, y, *_ in res]); brb = np.mean([(b - y) ** 2 for _, _, y, b, *_ in res])
    l1 = np.mean([ll(p if y else 1 - p) for _, p, y, *_ in res]); l0 = np.mean([ll(b if y else 1 - b) for _, _, y, b, *_ in res])
    print(f"Brier {br:.4f} (σταθερή βάση: {brb:.4f}) · log-loss {l1:.4f} (βάση {l0:.4f})")
    print("Βαθμονόμηση Over (όλες οι γραμμές):")
    B = defaultdict(lambda: [0, 0.0, 0])
    for _, p, y, *_ in res:
        k = min(int(p * 10), 9)
        B[k][0] += 1; B[k][1] += p; B[k][2] += y
    for k in sorted(B):
        c, sp, sy = B[k]
        if c >= 100:
            print(f"  {k * 10:3d}–{k * 10 + 10:3d}%: n={c:6d} μοντέλο {sp / c * 100:5.1f}% πραγματικό {sy / c * 100:5.1f}% διαφορά {(sy - sp) / c * 100:+5.1f}")
    print("Ανά γραμμή (μέση πιθανότητα Over μοντέλου vs πραγματικό):")
    for L in sorted({r[0] for r in res}):
        v = [r for r in res if r[0] == L]
        if len(v) >= 200:
            print(f"  {L:5.1f}: n={len(v):6d} μοντέλο {np.mean([r[1] for r in v]) * 100:5.1f}% πραγματικό {np.mean([r[2] for r in v]) * 100:5.1f}%")
    print("Σκέλη που θα επέλεγε η κατηγορία (Over ή Under με p ≥ όριο):")
    for t in (0.60, 0.65, 0.70, 0.75):
        for side in ("Over", "Under"):
            v = [(p if side == "Over" else 1 - p, y if side == "Over" else 1 - y) for _, p, y, *_ in res if (p if side == "Over" else 1 - p) >= t]
            if len(v) >= 100:
                print(f"  {side:5s} ≥{t:.2f}: n={len(v):6d} μοντέλο {np.mean([a for a, _ in v]) * 100:5.1f}% πραγματικό {np.mean([b for _, b in v]) * 100:5.1f}%")
    ks = [r for r in res if r[5]]
    if ks:
        print(f"Με διαιτητή γνωστό (≥8 αγώνες): n={len(ks)} Brier {np.mean([(p - y) ** 2 for _, p, y, *_ in ks]):.4f} (όλοι: {br:.4f})")


def main():
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    rows = load()
    n_ev = len({r["event_key"] for r in rows})
    print(f"Backtest κόρνερ/καρτών: {n_ev} αγώνες ({SEASONS[0]}–{SEASONS[-1]}, {len(DIVS)} λίγκες)· δοκιμή από 08/2024")
    start, end = datetime(2024, 8, 1, tzinfo=timezone.utc), datetime(2026, 7, 1, tzinfo=timezone.utc)
    report("Κόρνερ", evaluate("corners", "corners", rows, cfg, start, end))
    report("Κάρτες = μόνο κίτρινες (όπως εκπαιδεύαμε ως τώρα)", evaluate("cards", "yellow", rows, cfg, start, end))
    report("Κάρτες = πόντοι κράτησης (κίτρινη 1 + κόκκινη 2, όπως τα πρακτορεία)", evaluate("cards", "bookings", rows, cfg, start, end))
    report("Κάρτες (πόντοι κράτησης) ΧΩΡΙΣ διαιτητή", evaluate("cards", "bookings", rows, cfg, start, end, ref_on=False))


if __name__ == "__main__":
    main()
