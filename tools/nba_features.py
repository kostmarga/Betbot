"""Έλεγχος: προσθέτουν τα στοιχεία (ξεκούραση, back-to-back, φόρμα 5, μέση διαφορά 10, σερί νικών, H2H) πληροφορία ΠΕΡΑ από τις αποδόσεις;
Walk-forward: εκπαίδευση στο παλαιότερο 55% των αγώνων NBA, δοκιμή στο πιο πρόσφατο 45% (log-loss). Χρειάζεται πρώτα το tools/nba_backtest.py.
python tools/nba_features.py > docs/nba_features.txt"""
import sys, pickle, math, os
import numpy as np
rows = sorted(pickle.load(open('/tmp/betbot_nba_rows.pkl', 'rb')), key=lambda r: (r["date"], r["id"]))
hist, h2h = {}, {}
def feats(team, date):
    L = hist.get(team, []); last5, last10 = L[-5:], L[-10:]
    rest = (date - L[-1][0]).days if L else 4
    s = 0
    for x in reversed(L):
        w = x[3]
        if s == 0: s = 1 if w else -1
        elif (s > 0) == w: s += 1 if w else -1
        else: break
    return dict(rest=min(rest, 5), b2b=int(rest <= 1), w5=(np.mean([x[3] for x in last5]) if last5 else .5),
                m10=(np.mean([x[1] - x[2] for x in last10]) if last10 else 0.0), streak=s, n=len(L))
data = []
for r in rows:
    fh, fa = feats(r["home"], r["date"]), feats(r["away"], r["date"])
    key = tuple(sorted((r["home"], r["away"]))); H = h2h.get(key, [])
    hh = np.mean([1 if w == r["home"] else 0 for w in H[-3:]]) if H else .5
    if r.get("ml_h") and r.get("ml_a") and fh["n"] >= 5 and fa["n"] >= 5:
        x1, x2 = 1 / r["ml_h"], 1 / r["ml_a"]; p = x1 / (x1 + x2)
        data.append(dict(p=p, y=int(r["hs"] > r["as_"]), f=[fh["rest"] - fa["rest"], fh["b2b"] - fa["b2b"], fh["w5"] - fa["w5"],
                    (fh["m10"] - fa["m10"]) / 10, (fh["streak"] - fa["streak"]) / 5, hh - .5]))
    for t, pf, pa, won in ((r["home"], r["hs"], r["as_"], r["hs"] > r["as_"]), (r["away"], r["as_"], r["hs"], r["as_"] > r["hs"])):
        hist.setdefault(t, []).append((r["date"], pf, pa, bool(won)))
    h2h.setdefault(key, []).append(r["home"] if r["hs"] > r["as_"] else r["away"])
print(len(data), "αγώνες με αρκετό ιστορικό και τιμές")
logit = lambda p: math.log(p / (1 - p))
X = np.array([[logit(d["p"])] + d["f"] for d in data]); y = np.array([d["y"] for d in data], float)
cut = int(len(data) * 0.55)
def fit(X, y, l2=1.0, it=3000, lr=0.05):
    w = np.zeros(X.shape[1]); w[0] = 1.0
    for _ in range(it):
        p = 1 / (1 + np.exp(-(X @ w))); w -= lr * (X.T @ (p - y) / len(y) + l2 * np.r_[0, w[1:]] / len(y))
    return w
def ll(p, y): p = np.clip(p, 1e-6, 1 - 1e-6); return -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
Xtr, ytr, Xte, yte = X[:cut], y[:cut], X[cut:], y[cut:]
pm = 1 / (1 + np.exp(-Xte[:, 0]))
print(f"Δοκιμή σε {len(yte)} αγώνες (οι πιο πρόσφατοι)· εκπαίδευση σε {len(ytr)} παλαιότερους")
print(f"  μόνο αγορά:              log-loss {ll(pm, yte):.4f}")
names = ["ξεκούραση (ημέρες)", "back-to-back", "φόρμα 5 αγώνων", "μέση διαφορά 10 αγώνων", "σερί νικών", "H2H (3 τελευταία)"]
w = fit(Xtr, ytr); pf = 1 / (1 + np.exp(-(Xte @ w)))
print(f"  αγορά + όλα τα στοιχεία: log-loss {ll(pf, yte):.4f}")
for i, n in enumerate(names):
    cols = [0, i + 1]; wi = fit(Xtr[:, cols], ytr); pi = 1 / (1 + np.exp(-(Xte[:, cols] @ wi)))
    print(f"  αγορά + {n:26s} log-loss {ll(pi, yte):.4f}  ({ll(pi, yte) - ll(pm, yte):+.4f})")
print("Θετική διαφορά = χειρότερα από την αγορά μόνη της.")
