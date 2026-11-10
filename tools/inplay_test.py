"""Έλεγχος του live μοντέλου (betbot/inplay.py) στο ημίχρονο: λ από τις τιμές κλεισίματος (μέσος όρος πρακτορείων), σκορ ημιχρόνου,
και σύγκριση των προβλεπόμενων πιθανοτήτων τελικού αποτελέσματος / Over με το τι έγινε. python tools/inplay_test.py > docs/inplay.txt
Περιορισμός: ΔΕΝ υπάρχουν ιστορικές live αποδόσεις, άρα ελέγχεται η ΑΚΡΙΒΕΙΑ του μοντέλου, όχι αν υπάρχει περιθώριο κέρδους έναντι ενός πρακτορείου."""
import sys, os, csv, io, pickle, math
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import numpy as np, yaml
from datetime import datetime, timezone
from betbot.collectors.fdco_history import URL, _date, _i, season_codes
from betbot.util import http_get
cfg = yaml.safe_load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'config.yaml'), encoding='utf-8'))
now = datetime.now(timezone.utc)
cache = '/tmp/betbot_ht_rows.pkl'
def f(r, k):
    try:
        v = float(r.get(k) or ''); return v if v > 1 else None
    except ValueError: return None
if os.path.exists(cache): rows = pickle.load(open(cache, 'rb'))
else:
    rows = []
    for lg in cfg['leagues']:
        if not lg.get('fdco') or lg['sport'] != 'football': continue
        for s in season_codes(now, 3):
            try: text, _ = http_get(URL.format(season=s, div=lg['fdco']), expect='text')
            except Exception: continue
            for r in csv.DictReader(io.StringIO(text.lstrip('﻿'))):
                hg, ag, hh, ha = _i(r.get('FTHG')), _i(r.get('FTAG')), _i(r.get('HTHG')), _i(r.get('HTAG'))
                o = [f(r, c) for c in ('AvgCH', 'AvgCD', 'AvgCA')]; ou = f(r, 'AvgC>2.5'), f(r, 'AvgC<2.5')
                if None in (hg, ag, hh, ha) or not all(o) or not all(ou): continue
                rows.append(dict(lg=lg['id'], hg=hg, ag=ag, hh=hh, ha=ha, o=o, ou=ou, red=(_i(r.get('HR')) or 0) + (_i(r.get('AR')) or 0)))
    pickle.dump(rows, open(cache, 'wb'))
print(len(rows), 'αγώνες με τιμές κλεισίματος 1Χ2 + Over/Under 2.5 και σκορ ημιχρόνου')
N = 10
fact = np.array([math.factorial(k) for k in range(N)], dtype=float)
def pois(l): return np.exp(-l) * l ** np.arange(N) / fact
# πλέγμα λ
LH = np.arange(0.2, 3.6, 0.1); LA = np.arange(0.2, 3.1, 0.1)
grid = []
for lh in LH:
    for la in LA:
        M = np.outer(pois(lh), pois(la)); i, j = np.indices(M.shape)
        grid.append((lh, la, M[i > j].sum(), M[i == j].sum(), M[i < j].sum(), M[i + j >= 3].sum()))
G = np.array(grid); G[:, 2:5] /= G[:, 2:5].sum(1, keepdims=True)
def prop(x):
    v = np.array([1 / a for a in x]); return v / v.sum()
Pm = np.array([list(prop(r['o'])) + [prop(r['ou'])[0]] for r in rows])
idx = ((Pm[:, None, :] - G[None, :, 2:6]) ** 2).sum(2).argmin(1)     # πλησιέστερο λ ανά αγώνα
lam = G[idx, :2]
half1 = sum(r['hh'] + r['ha'] for r in rows) / sum(r['hg'] + r['ag'] for r in rows)
print(f'Ποσοστό γκολ στο 1ο ημίχρονο: {half1:.1%} (το «γραμμικό» μοντέλο θεωρεί 50%)')
def final_probs(lh, la, h, a):
    M = np.outer(pois(lh), pois(la)); i, j = np.indices(M.shape)
    H, A = h + i, a + j; T = H + A
    p1, px, p2 = M[H > A].sum(), M[H == A].sum(), M[H < A].sum(); t = p1 + px + p2
    return p1 / t, px / t, p2 / t, M[T >= 2].sum() / t, M[T >= 3].sum() / t, M[T >= 4].sum() / t
def evaluate(frac_left, label):
    ll, base_ll, cal = [], [], {}
    for r, (lh, la) in zip(rows, lam):
        p = final_probs(lh * frac_left, la * frac_left, r['hh'], r['ha'])
        out = 0 if r['hg'] > r['ag'] else 1 if r['hg'] == r['ag'] else 2
        ll.append(-math.log(max(p[out], 1e-9)))
        for name, pp, win in (('1Χ2', p[out], 1), ('Over 1.5', p[3], int(r['hg'] + r['ag'] >= 2)), ('Over 2.5', p[4], int(r['hg'] + r['ag'] >= 3)), ('Over 3.5', p[5], int(r['hg'] + r['ag'] >= 4))):
            if name == '1Χ2':
                for k, pk in enumerate(p[:3]):
                    cal.setdefault('Αποτέλεσμα', []).append((pk, int(out == k), r['red']))
            else:
                cal.setdefault(name, []).append((pp, win, r['red']))
    print(f'\n== {label}: log-loss τελικού αποτελέσματος {np.mean(ll):.4f}')
    for name, xs in cal.items():
        print(f'  {name}: βαθμονόμηση (προβλεπόμενη -> πραγματική, n)')
        for lo, hi in ((0, .1), (.1, .2), (.2, .35), (.35, .5), (.5, .65), (.65, .8), (.8, .9), (.9, 1.01)):
            b = [x for x in xs if lo <= x[0] < hi]
            if len(b) >= 200: print(f'    {lo:.2f}-{hi:.2f}  {np.mean([x[0] for x in b]):.3f} -> {np.mean([x[1] for x in b]):.3f}  (n={len(b)})')
    return cal
c50 = evaluate(0.5, 'Γραμμικό μοντέλο στο ημίχρονο (50% των γκολ μένουν)')
c55 = evaluate(1 - half1, f'Προσαρμοσμένο ({1 - half1:.0%} των γκολ μένουν, από τα δεδομένα)')
# κόκκινες κάρτες: πόσο αλλάζει η ακρίβεια
for nm, cal in (('προσαρμοσμένο', c55),):
    xs = cal['Αποτέλεσμα']
    for lab, sel in (('χωρίς κόκκινη', [x for x in xs if x[2] == 0]), ('με κόκκινη(ες)', [x for x in xs if x[2] > 0])):
        err = np.mean([(x[0] - x[1]) ** 2 for x in sel]); print(f'\nΚόκκινες κάρτες ({nm}): {lab}: n={len(sel) // 3} αγώνες, Brier {err:.4f}')
