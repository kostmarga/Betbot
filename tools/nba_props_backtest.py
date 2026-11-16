"""Backtest πόντων παικτών NBA: ελέγχουμε την ΚΑΤΑΝΟΜΗ που υποθέτει το betbot/props.py (κανονική, σ = max(3.5, 0.30·γραμμή)).
Δεδομένα: boxscore ESPN για όλους τους τελειωμένους αγώνες NBA που έχουμε στη βάση (αυτή η σεζόν + η προηγούμενη).
Δεν υπάρχουν ιστορικές γραμμές props, άρα ως «κύρια γραμμή» παίρνουμε τον κυλιόμενο μέσο όρο των 10 τελευταίων αγώνων του παίκτη (ΧΕΙΡΟΤΕΡΗ από της αγοράς·
άρα το πραγματικό σ γύρω από τη γραμμή της αγοράς θα είναι ΜΙΚΡΟΤΕΡΟ — το αποτέλεσμα είναι ΑΝΩ ΟΡΙΟ για το σ).
Χρήση: python tools/nba_props_backtest.py <betbot.sqlite> > docs/nba_props_backtest.txt
"""
import math
import os
import pickle
import sqlite3
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from statistics import NormalDist

sys.path.insert(0, ".")
from betbot.collectors.nba_box import parse_box  # noqa: E402
from betbot.util import http_get  # noqa: E402

SM = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
CACHE = "/tmp/nba_box_cache.pkl"
ND = NormalDist()


def fetch(m):
    try:
        d, _ = http_get(SM, params={"event": m["match_id"][5:]}, timeout=25, retries=2)
        return m, parse_box(d, m)
    except Exception:
        return m, None


def fit_median(games):
    """Ίδιο τεστ, αλλά με «γραμμή» τον κυλιόμενο ΔΙΑΜΕΣΟ των 10 τελευταίων αγώνων και αναζήτηση του καλύτερου σ = max(min_sd, k·γραμμή)."""
    import statistics
    hist = defaultdict(list)
    obs = []
    for _, rows in games:
        for r in rows:
            h = hist[r["player"]]
            if r["minutes"] and r["minutes"] >= 10 and len(h) >= 8:
                last = [p for mn, p in h[-10:] if mn >= 10]
                if len(last) >= 7 and statistics.median(last) >= 8:
                    obs.append((math.floor(statistics.median(last)) + 0.5, r["points"]))
            if r["minutes"] is not None:
                h.append((r["minutes"], r["points"]))
    print(f"\nΕπανάληψη με γραμμή = κυλιόμενος διάμεσος ({len(obs)} παρατηρήσεις): μέσος log-loss για Over/Under σε L0±2..6, κανονική κατανομή")
    res = []
    for k in (0.30, 0.35, 0.40, 0.45, 0.50):
        for mn in (3.5, 4.5, 5.5, 6.5, 7.5):
            tot = n = 0
            for l0, p in obs:
                sd = max(mn, k * l0)
                for d in (-6, -4, -3, -2, 2, 3, 4, 6):
                    po = min(max(1 - ND.cdf((l0 - d - l0) / sd), 1e-4), 1 - 1e-4)
                    tot += -math.log(po if p > l0 - d else 1 - po); n += 1
            res.append((tot / n, k, mn))
    for v, k, mn in sorted(res)[:6]:
        print(f"  k={k:.2f} min_sd={mn:.1f}: {v:.4f}")
    cur = next(v for v, k, mn in res if k == 0.30 and mn == 3.5)
    print(f"  (τωρινή υπόθεση k=0.30, min_sd=3.5: {cur:.4f})")
    print("  ΣΗΜΕΙΩΣΗ: ο κυλιόμενος διάμεσος είναι χειρότερη εκτίμηση από τη γραμμή της αγοράς, άρα το πραγματικό σ γύρω από την αγορά είναι μικρότερο· το αποτέλεσμα είναι ΑΝΩ ΟΡΙΟ.")


def main(db):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    ms = [dict(r) for r in c.execute("select match_id,kickoff from matches where league='NBA' and status='finished' and match_id like 'espn:%' order by kickoff")]
    cache = pickle.load(open(CACHE, "rb")) if os.path.exists(CACHE) else {}
    todo = [m for m in ms if m["match_id"] not in cache]
    with ThreadPoolExecutor(8) as ex:
        for m, rows in ex.map(fetch, todo):
            if rows:
                cache[m["match_id"]] = rows
    pickle.dump(cache, open(CACHE, "wb"))
    games = [(m["kickoff"], cache[m["match_id"]]) for m in ms if m["match_id"] in cache]
    print(f"Backtest πόντων παικτών NBA: {len(games)} αγώνες με boxscore από {len(ms)}\n")
    hist = defaultdict(list)                      # παίκτης -> [(λεπτά, πόντοι)]
    obs = []                                      # (μ, ελάχ λεπτά, πόντοι)
    for _, rows in games:
        for r in rows:
            h = hist[r["player"]]
            if r["minutes"] and r["minutes"] >= 10 and len(h) >= 8:
                last = [p for mn, p in h[-10:] if mn >= 10]
                if len(last) >= 7:
                    mu = sum(last) / len(last)
                    if mu >= 8:
                        obs.append((mu, r["minutes"], r["points"]))
            if r["minutes"] is not None:
                h.append((r["minutes"], r["points"]))
    print(f"{len(obs)} παρατηρήσεις (παίκτης-αγώνας, μέσος όρος ≥ 8 πόντοι, ≥ 7 αγώνες ιστορικό, έπαιξε ≥ 10 λεπτά)\n")

    def sd_model(mu, k=0.30):
        return max(3.5, k * mu)

    # 1) Τι σ ταιριάζει καλύτερα; (μέγιστη πιθανοφάνεια, ανά k)
    print("Σ ως ποσοστό του μέσου όρου (k): μέσος log-likelihood της κανονικής")
    for k in (0.22, 0.26, 0.30, 0.34, 0.38, 0.42):
        ll = sum(-0.5 * math.log(2 * math.pi * sd_model(mu, k) ** 2) - (p - mu) ** 2 / (2 * sd_model(mu, k) ** 2) for mu, _, p in obs) / len(obs)
        print(f"  k={k:.2f}: {ll:.4f}")
    emp = math.sqrt(sum(((p - mu) / max(mu, 1)) ** 2 for mu, _, p in obs) / len(obs))
    print(f"  πραγματική τυπική απόκλιση / μέσο όρο: {emp:.3f}\n")

    # 2) Βαθμονόμηση: P(Over L) για γραμμές κάτω/πάνω από τον μέσο όρο (L = μ − d)
    print("Over/Under σε γραμμές μακριά από τον μέσο όρο (L = μέσος όρος − d, στρογγυλεμένο σε .5)· μοντέλο = σ=max(3.5,0.30μ), κανονική")
    for d in (-6, -4, -3, -2, 0, 2, 3, 4, 6):
        n = hit = 0
        pm = 0.0
        for mu, _, p in obs:
            L = math.floor(mu - d) + 0.5
            pr = 1 - ND.cdf((L - mu) / sd_model(mu))
            n += 1; hit += p > L; pm += pr
        print(f"  L=μ{-d:+d}: n={n}  μοντέλο Over {pm / n * 100:5.1f}%  πραγματικό {hit / n * 100:5.1f}%  διαφορά {(hit - pm) / n * 100:+5.1f}")
    print()
    # 3) Οι επιλογές που θα έκανε η κατηγορία (p ≥ 0.62 μετά τη συστολή 10%)
    print("Σκέλη με p μοντέλου ≥ 0.62 (μετά συστολή 10% προς 50%):")
    for side in ("OVER", "UNDER"):
        n = hit = 0
        ps = 0.0
        for mu, _, p in obs:
            for d in (-5, -4, -3, -2, 2, 3, 4, 5):
                L = math.floor(mu - d) + 0.5
                po = 1 - ND.cdf((L - mu) / sd_model(mu))
                pr = po if side == "OVER" else 1 - po
                pr = 0.5 + (pr - 0.5) * 0.9
                if pr >= 0.62:
                    n += 1; ps += pr
                    hit += (p > L) if side == "OVER" else (p < L)
        print(f"  {side}: n={n}  μέση πιθανότητα μοντέλου {ps / max(n, 1) * 100:.1f}%  πραγματικό {hit / max(n, 1) * 100:.1f}%")
    print("\nΑνά ζώνη μέσου όρου πόντων (Over L=μ−3.5):")
    for lo, hi in ((8, 12), (12, 16), (16, 20), (20, 25), (25, 40)):
        s = [(mu, p) for mu, _, p in obs if lo <= mu < hi]
        if len(s) < 100:
            continue
        hit = sum(p > math.floor(mu - 3.5) + 0.5 for mu, p in s) / len(s)
        pm = sum(1 - ND.cdf((math.floor(mu - 3.5) + 0.5 - mu) / sd_model(mu)) for mu, _ in s) / len(s)
        print(f"  μ {lo}–{hi}: n={len(s)}  μοντέλο {pm * 100:.1f}%  πραγματικό {hit * 100:.1f}%")
    fit_median(games)


if __name__ == "__main__":
    main(sys.argv[1])
