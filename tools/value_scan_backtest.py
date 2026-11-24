"""Backtest «αναζήτηση αξίας» + CLV με τα δικά μας αποθηκευμένα snapshots (Pinnacle & Stoiximan, από 16–17/11/2026).

Ιδέα: η δίκαιη πιθανότητα βγαίνει από το Pinnacle (devig). Αν η τιμή του Stoiximan για την ίδια επιλογή είναι ΨΗΛΟΤΕΡΗ από τη δίκαιη
(edge = τιμή_stx × p_pinnacle − 1 ≥ όριο), τότε σε βάθος χρόνου αυτό το μονό στοίχημα έχει θετικό αναμενόμενο κέρδος.
Για κάθε επιλογή παίρνουμε το ΠΡΩΤΟ snapshot πριν τον αγώνα που ξεπερνά το όριο και μετράμε:
  • ROI (πραγματικό κέρδος με 1 μονάδα, στην τιμή Stoiximan εκείνη τη στιγμή)
  • CLV = τιμή_stx × p_κλεισίματος_Pinnacle − 1  (έλεγχος πλεονεκτήματος χωρίς να χρειάζονται εκατοντάδες αγώνες)
Χρήση: python tools/value_scan_backtest.py <betbot.sqlite> > docs/value_scan_backtest.txt"""
import math
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, ".")
from betbot.selector import GROUPS, settle_leg  # noqa: E402
from betbot.util import parse_iso  # noqa: E402

NL = None
MAX_AGE_H = 3.0          # η τιμή Stoiximan πρέπει να είναι το πολύ τόσες ώρες παλιά σε σχέση με το snapshot Pinnacle


def devig_group(rows):
    """rows: {selection: price} για πλήρη αγορά -> {selection: p} ή None."""
    return None


def main(db):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    matches = {r["match_id"]: dict(r) for r in c.execute("select * from matches where status='finished' and home_score is not null")}
    hist = defaultdict(lambda: defaultdict(list))     # match -> (source, market, line, sel) -> [(t, price)]
    for r in c.execute("select * from odds_history where source in ('pinnacle','stoiximan') order by fetched_at"):
        if r["match_id"] in matches:
            hist[r["match_id"]][(r["source"], r["market"], r["line"], r["selection"])].append((parse_iso(r["fetched_at"]), r["price"]))
    bets = []      # (edge, p_fair, price, result, clv, hours_before, market)
    for mid, H in hist.items():
        m = matches[mid]
        ko = parse_iso(m["kickoff"])
        pin = defaultdict(lambda: defaultdict(dict))       # (market,line) -> t -> {sel: price}
        for (src, mk, ln, sel), pts in H.items():
            if src == "pinnacle":
                for t, p in pts:
                    if t <= ko:
                        pin[(mk, ln)][t][sel] = p
        for (mk, ln), snaps in pin.items():
            need = GROUPS.get(mk)
            if not need:
                continue
            full = {t: v for t, v in snaps.items() if all(s in v for s in need)}
            if not full:
                continue
            tc = max(full)
            pc = {s: (1 / full[tc][s]) / sum(1 / full[tc][x] for x in need) for s in need}      # δίκαιη πιθανότητα στο κλείσιμο
            seen = set()
            for t in sorted(full):
                v = full[t]
                tot = sum(1 / v[x] for x in need)
                for s in need:
                    if s in seen:
                        continue
                    st = [(tt, p) for tt, p in H.get(("stoiximan", mk, ln, s), []) if tt <= t and (t - tt).total_seconds() <= MAX_AGE_H * 3600]
                    if not st:
                        continue
                    price = st[-1][1]
                    pf = (1 / v[s]) / tot
                    edge = price * pf - 1
                    if edge >= 0.0:
                        seen.add(s)
                        res = settle_leg({"market": mk, "selection": s, "line": ln}, m, None)
                        if res in ("won", "lost"):
                            bets.append((edge, pf, price, res == "won", price * pc[s] - 1, (ko - t).total_seconds() / 3600, mk))
    print(f"Αγώνες με snapshots Pinnacle+Stoiximan: {len(hist)} · επιλογές με edge ≥ 0 στο πρώτο snapshot: {len(bets)}\n")
    for th in (0.0, 0.02, 0.03, 0.05, 0.08):
        b = [x for x in bets if x[0] >= th]
        if len(b) < 5:
            print(f"edge ≥ {th:.0%}: μόνο {len(b)} επιλογές")
            continue
        n = len(b)
        roi = sum((x[2] - 1) if x[3] else -1 for x in b) / n
        exp = sum(x[1] for x in b) / n
        hit = sum(1 for x in b if x[3]) / n
        clv = sum(x[4] for x in b) / n
        pos = sum(1 for x in b if x[4] > 0) / n
        sd = math.sqrt(sum(((x[2] - 1) if x[3] else -1) ** 2 for x in b) / n - roi ** 2) / math.sqrt(n)
        print(f"edge ≥ {th:>3.0%}: n={n:4d} · επιτυχία {hit:.1%} (αναμ. {exp:.1%}) · ROI {roi:+.1%} ± {sd:.1%} · CLV {clv:+.1%} · θετικό CLV {pos:.0%}")
    print("\nΑνά αγορά (edge ≥ 2%):")
    by = defaultdict(list)
    for x in bets:
        if x[0] >= 0.02:
            by[x[6]].append(x)
    for mk, b in sorted(by.items(), key=lambda kv: -len(kv[1])):
        n = len(b)
        print(f"  {mk:<8} n={n:3d} ROI {sum((x[2] - 1) if x[3] else -1 for x in b) / n:+.1%} CLV {sum(x[4] for x in b) / n:+.1%}")
    print("\nΑνά ώρες πριν τον αγώνα (edge ≥ 2%):")
    for lo, hi in ((0, 3), (3, 12), (12, 48), (48, 999)):
        b = [x for x in bets if x[0] >= 0.02 and lo <= x[5] < hi]
        if len(b) >= 5:
            n = len(b)
            print(f"  {lo:>3}–{hi:<3}ω n={n:3d} ROI {sum((x[2] - 1) if x[3] else -1 for x in b) / n:+.1%} CLV {sum(x[4] for x in b) / n:+.1%}")


if __name__ == "__main__":
    main(sys.argv[1])
