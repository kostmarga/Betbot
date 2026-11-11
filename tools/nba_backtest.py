"""Backtest NBA: αποτελέσματα + αποδόσεις (DraftKings, από το ESPN) για ~13 μήνες, και έλεγχος παραγόντων (σερί νικών αντιπάλου κ.ά.).
python tools/nba_backtest.py > docs/nba_backtest.txt   (κάνει ~1.800 κλήσεις στο ESPN, ~10 λεπτά)
Περιορισμός: οι τιμές είναι αυτές που δίνει το ESPN για τελειωμένους αγώνες (πιθανώς κλείσιμο)· ΜΟΝΟ DraftKings."""
import sys, os, pickle, math
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import numpy as np
from betbot.util import http_get
from betbot.collectors.espn_odds import american_to_decimal

SB = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
SM = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
cache = '/tmp/betbot_nba_rows.pkl'

def day_events(d):
    try:
        j, _ = http_get(SB, params={"dates": d.strftime("%Y%m%d")}, timeout=20, retries=2)
    except Exception:
        return []
    out = []
    for e in j.get("events") or []:
        c = e["competitions"][0]
        if (e["status"]["type"]["state"] != "post"):
            continue
        by = {x["homeAway"]: x for x in c["competitors"]}
        try:
            out.append(dict(id=e["id"], date=d, home=by["home"]["team"]["displayName"], away=by["away"]["team"]["displayName"],
                            hs=int(float(by["home"]["score"])), as_=int(float(by["away"]["score"]))))
        except (KeyError, ValueError):
            pass
    return out

def odds_for(ev):
    try:
        j, _ = http_get(SM, params={"event": ev["id"]}, timeout=20, retries=2)
    except Exception:
        return ev
    pc = (j.get("pickcenter") or [])
    if pc:
        o = pc[0]
        h = american_to_decimal((o.get("homeTeamOdds") or {}).get("moneyLine"))
        a = american_to_decimal((o.get("awayTeamOdds") or {}).get("moneyLine"))
        ev = dict(ev, ml_h=h, ml_a=a, total=o.get("overUnder"), over=american_to_decimal(o.get("overOdds")), under=american_to_decimal(o.get("underOdds")))
    return ev

if os.path.exists(cache):
    rows = pickle.load(open(cache, 'rb'))
else:
    today = date.today(); start = date(2025, 10, 20)
    days = [start + timedelta(days=i) for i in range((today - start).days)]
    with ThreadPoolExecutor(8) as ex:
        evs = [e for lst in ex.map(day_events, days) for e in lst]
    print(len(evs), "τελειωμένοι αγώνες NBA", file=sys.stderr)
    with ThreadPoolExecutor(8) as ex:
        rows = list(ex.map(odds_for, evs))
    pickle.dump(rows, open(cache, 'wb'))
rows = sorted(rows, key=lambda r: (r["date"], r["id"]))
priced = [r for r in rows if r.get("ml_h") and r.get("ml_a")]
print(f"{len(rows)} αγώνες, {len(priced)} με moneyline")

def prop(a, b):
    x, y = 1 / a, 1 / b; return x / (x + y)

# 1) βαθμονόμηση φαβορί
print("\nΒαθμονόμηση φαβορί (devig DraftKings): κάδος, n, προβλεπόμενη, πραγματική, ROI στην τιμή")
fav = []
for r in priced:
    ph = prop(r["ml_h"], r["ml_a"])
    if ph >= .5: fav.append((ph, int(r["hs"] > r["as_"]), r["ml_h"], r, "H"))
    else: fav.append((1 - ph, int(r["as_"] > r["hs"]), r["ml_a"], r, "A"))
for lo, hi in ((.5, .6), (.6, .7), (.7, .8), (.8, .9), (.9, 1.01)):
    b = [x for x in fav if lo <= x[0] < hi]
    if len(b) >= 30:
        print(f"  {lo:.1f}-{hi:.1f}  n={len(b):4d}  {np.mean([x[0] for x in b]):.3f}  {np.mean([x[1] for x in b]):.3f}  ROI {np.mean([(x[2] if x[1] else 0) - 1 for x in b]):+.1%}")

# 2) σερί νικών αντιπάλου (πριν τον αγώνα)
streak, last = {}, {}
for r in rows:
    r["str_h"], r["str_a"] = streak.get(r["home"], 0), streak.get(r["away"], 0)
    for t, won in ((r["home"], r["hs"] > r["as_"]), (r["away"], r["as_"] > r["hs"])):
        streak[t] = (max(streak.get(t, 0), 0) + 1) if won else min(streak.get(t, 0), 0) - 1
print("\nΣερί νικών ΤΟΥ ΑΝΤΙΠΑΛΟΥ του φαβορί (φαβορί ≥60%): n, προβλεπόμενη, πραγματική, ROI@τιμή")
groups = {"αντίπαλος ≥5 νίκες στη σειρά": [], "αντίπαλος 2–4 νίκες": [], "αντίπαλος χωρίς σερί νικών": []}
for p, w, odds, r, side in fav:
    if p < .6: continue
    opp = r["str_a"] if side == "H" else r["str_h"]
    k = "αντίπαλος ≥5 νίκες στη σειρά" if opp >= 5 else "αντίπαλος 2–4 νίκες" if opp >= 2 else "αντίπαλος χωρίς σερί νικών"
    groups[k].append((p, w, odds))
for k, v in groups.items():
    if v:
        pr = [(x[2] if x[1] else 0) - 1 for x in v]
        rng = np.random.default_rng(3); bb = [np.mean(rng.choice(pr, len(pr))) for _ in range(800)] if len(v) >= 20 else [np.nan, np.nan]
        print(f"  {k}: n={len(v)}  {np.mean([x[0] for x in v]):.3f} -> {np.mean([x[1] for x in v]):.3f}  ROI {np.mean(pr):+.1%}  [{np.percentile(bb, 2.5):+.1%}, {np.percentile(bb, 97.5):+.1%}]")

# 3) Over/Under σε σχέση με τη γραμμή
tot = [r for r in rows if r.get("total") and r.get("over") and r.get("under")]
print(f"\nΣύνολο πόντων: {len(tot)} αγώνες με γραμμή")
if tot:
    ov = [int(r["hs"] + r["as_"] > r["total"]) for r in tot]; push = [int(r["hs"] + r["as_"] == r["total"]) for r in tot]
    print(f"  Over βγήκε {np.mean(ov):.1%} (push {np.mean(push):.1%}) · μέση απόδοση Over {np.mean([r['over'] for r in tot]):.3f} / Under {np.mean([r['under'] for r in tot]):.3f}")
    pr_o = [((r['over'] if o else 0) - 1) if not p else 0 for r, o, p in zip(tot, ov, push)]
    pr_u = [((r['under'] if (not o and not p) else 0) - 1) if not p else 0 for r, o, p in zip(tot, ov, push)]
    print(f"  ROI Over {np.mean(pr_o):+.1%} · ROI Under {np.mean(pr_u):+.1%}")
