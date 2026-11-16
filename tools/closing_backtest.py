"""Backtest με τα δικά ΜΑΣ αποθηκευμένα δεδομένα (τιμές Pinnacle/Stoiximan που κρατάμε από 17/11/2026): BTTS και πόντοι παικτών NBA.
Δεν υπάρχουν δωρεάν ιστορικές τιμές αυτών των αγορών, οπότε το τεστ γίνεται καθώς μαζεύονται δεδομένα (ξανατρέξε το σε 1–2 μήνες).
Ελέγχει: (1) βαθμονόμηση της πιθανότητας Pinnacle (devig) και (2) ROI στην τιμή Pinnacle / Stoiximan.
Χρήση: python tools/closing_backtest.py <betbot.sqlite> > docs/closing_backtest.txt
"""
import math
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, ".")
from betbot.props import devig2, norm_name  # noqa: E402


def calib(rows, label):
    n = len(rows)
    if n < 20:
        print(f"{label}: μόνο {n} αγώνες/γραμμές — πολύ λίγα, ξαναδοκίμασε αργότερα\n")
        return
    base = sum(y for _, y, _ in rows) / n
    br = sum((p - y) ** 2 for p, y, _ in rows) / n
    print(f"{label}: n={n} · ποσοστό {base * 100:.1f}% · Brier {br:.4f} (σταθερή βάση {sum((base - y) ** 2 for _, y, _ in rows) / n:.4f})")
    B = defaultdict(lambda: [0, 0.0, 0, 0.0])
    for p, y, o in rows:
        k = min(int(p * 10), 9)
        B[k][0] += 1; B[k][1] += p; B[k][2] += y; B[k][3] += (o * y - 1) if o else 0
    for k in sorted(B):
        c, sp, sy, pr = B[k]
        if c >= 10:
            print(f"   {k * 10:3d}–{k * 10 + 10:3d}%: n={c:4d} μοντέλο {sp / c * 100:5.1f}% πραγματικό {sy / c * 100:5.1f}%  ROI στην τιμή {pr / c * 100:+6.1f}%")
    print()


def main(db):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    fin = {r["match_id"]: r for r in c.execute("select * from matches where status='finished' and home_score is not null")}
    # --- BTTS
    byk = defaultdict(dict)
    for r in c.execute("select * from odds where market='BTTS' and source='pinnacle'"):
        byk[r["match_id"]][r["selection"]] = r["price"]
    rows = []
    for mid, v in byk.items():
        m = fin.get(mid)
        if m and "YES" in v and "NO" in v:
            p = devig2(v["YES"], v["NO"])
            yes = m["home_score"] > 0 and m["away_score"] > 0
            rows += [(p, int(yes), v["YES"]), (1 - p, int(not yes), v["NO"])]
    calib(rows, "BTTS (Pinnacle, και οι δύο πλευρές)")
    # --- Πόντοι NBA
    box = defaultdict(dict)
    for r in c.execute("select * from nba_box"):
        box[r["match_id"]][norm_name(r["player"])] = r
    pr = defaultdict(dict)
    for r in c.execute("select * from props where stat='PTS'"):
        pr[(r["match_id"], r["player"], r["line"])][r["source"]] = r
    rp = []
    for (mid, pl, ln), d in pr.items():
        b = box.get(mid, {}).get(norm_name(pl))
        if not b or not b["minutes"] or b["points"] == ln or "pinnacle" not in d or not d["pinnacle"]["active"]:
            continue
        p0 = d["pinnacle"]
        po = devig2(p0["over_price"], p0["under_price"])
        over = b["points"] > ln
        rp += [(po, int(over), p0["over_price"]), (1 - po, int(not over), p0["under_price"])]
    calib(rp, "Πόντοι NBA (Pinnacle, κύρια γραμμή παίκτη)")


if __name__ == "__main__":
    main(sys.argv[1])
