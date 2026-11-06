"""Backtest: πόσο καλά θα τα πήγαιναν τα μοντέλα στο παρελθόν;  (`python main.py --backtest`)

Walk-forward: χωρίζουμε το διάστημα ελέγχου σε παράθυρα των 28 ημερών. Για κάθε παράθυρο το μοντέλο
εκπαιδεύεται ΜΟΝΟ με αγώνες πριν από το παράθυρο και προβλέπει τους αγώνες μέσα σε αυτό (χωρίς «να βλέπει
το μέλλον»).

1. Ποδόσφαιρο 1Χ2 και Over/Under 2.5: σύγκριση με την αγορά (αποδόσεις football-data.co.uk, μέσος όρος
   πρακτορείων): log-loss, Brier, βαθμονόμηση (calibration) και προσομοίωση των κανόνων επιλογής
   (ίδια φίλτρα με τη selection του config.yaml): hit-rate και απόδοση ROI με 1€ ανά επιλογή.
2. Κόρνερ και κάρτες: βαθμονόμηση και σύγκριση με απλό μέσο όρο (δεν υπάρχουν ιστορικές αποδόσεις).

Περιορισμοί: οι αποδόσεις είναι μέσοι όροι πρακτορείων (όχι του ΟΠΑΠ), δεν υπάρχουν όρια στοιχήματος
και προμήθειες, και η ανάλυση ισχύει για το παρελθόν· δεν εγγυάται το μέλλον.
"""
from __future__ import annotations

import csv
import io
import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np

from .collectors.fdco_history import URL, _date, _i, season_codes
from .db import DB
from .models import CountModel, FootballModel
from .util import http_get, iso, parse_iso

log = logging.getLogger("betbot")
WINDOW_DAYS = 28
EPS = 1e-9


def _price(r, cols):
    for c in cols:
        try:
            v = float(r.get(c) or "")
            if v > 1.0:
                return v
        except ValueError:
            continue
    return None


def load_fdco(cfg, now):
    """Αγώνες με αποτέλεσμα + αποδόσεις από τα CSV του football-data (τρέχουσα και προηγούμενη σεζόν)."""
    rows = []
    for lg in cfg["leagues"]:
        if not lg.get("fdco") or lg["sport"] != "football":
            continue
        for s in season_codes(now, 1):
            try:
                text, _ = http_get(URL.format(season=s, div=lg["fdco"]), expect="text")
            except Exception as e:
                log.warning("backtest: %s %s: %s", lg["id"], s, e)
                continue
            for r in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
                ko, hg, ag = _date(r), _i(r.get("FTHG")), _i(r.get("FTAG"))
                h, a = (r.get("HomeTeam") or "").strip(), (r.get("AwayTeam") or "").strip()
                if ko is None or hg is None or ag is None or not h or not a:
                    continue
                o1x2 = [_price(r, c) for c in (["AvgH", "PSH", "B365H"], ["AvgD", "PSD", "B365D"], ["AvgA", "PSA", "B365A"])]
                ou = [_price(r, c) for c in (["Avg>2.5", "P>2.5", "B365>2.5"], ["Avg<2.5", "P<2.5", "B365<2.5"])]
                m1x2 = [_price(r, c) for c in (["MaxH"], ["MaxD"], ["MaxA"])]
                mou = [_price(r, c) for c in (["Max>2.5"], ["Max<2.5"])]
                rows.append({"league": lg["id"], "ko": ko.astimezone(timezone.utc), "home": h, "away": a,
                             "hg": hg, "ag": ag, "o1x2": o1x2 if all(o1x2) else None, "ou": ou if all(ou) else None,
                             "m1x2": m1x2 if all(m1x2) else None, "mou": mou if all(mou) else None})
    return rows


def devig(prices):
    inv = [1 / p for p in prices]
    t = sum(inv)
    return [x / t for x in inv]


def ll(p):
    return -math.log(max(p, EPS))


def bootstrap_roi(profits, n=2000, seed=7):
    if len(profits) < 20:
        return None
    rng = np.random.default_rng(seed)
    a = np.array(profits)
    m = [rng.choice(a, len(a)).mean() for _ in range(n)]
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def bins_table(pairs, edges, label="p"):
    """pairs = [(προβλεπόμενη πιθανότητα, 0/1)] -> γραμμές markdown."""
    out = ["| Προβλεπόμενη πιθανότητα | Πλήθος | Μέση πρόβλεψη | Πραγματική συχνότητα |", "|---|---|---|---|"]
    for lo, hi in zip(edges[:-1], edges[1:]):
        b = [(p, y) for p, y in pairs if lo <= p < hi]
        if len(b) >= 10:
            out.append(f"| {lo:.0%}–{hi:.0%} | {len(b)} | {np.mean([p for p, _ in b]):.1%} | {np.mean([y for _, y in b]):.1%} |")
    return out


def run_football(cfg, db, aliases, now, start, rows=None):
    rows = [r for r in (rows if rows is not None else load_fdco(cfg, now)) if r["ko"] >= start and r["ko"] < now]
    rows.sort(key=lambda r: r["ko"])
    all_matches = db.matches(sport="football")
    sel = cfg["selection"]
    blend = 0.5                      # σταθερό: το «παλιό» σύστημα (μίξη 50/50) για σύγκριση με την αγορά
    min_g = sel["min_team_matches"]
    res = defaultdict(list)       # ονόματα μετρικών -> λίστες
    cands = []                    # όλες οι υποψήφιες επιλογές
    n_total = n_used = 0
    w0 = start
    while w0 < now:
        w1 = w0 + timedelta(days=WINDOW_DAYS)
        batch = [r for r in rows if w0 <= r["ko"] < w1]
        if batch:
            train = [m for m in all_matches if parse_iso(m["kickoff"]) < w0]
            model = FootballModel(cfg["models"]["football"], aliases).fit(train, w0)
            for r in batch:
                n_total += 1
                if not (model.known(r["home"], min_g) and model.known(r["away"], min_g)):
                    continue
                pm = model.market_probs(model.predict(r["home"], r["away"]))
                n_used += 1
                outcome = "1" if r["hg"] > r["ag"] else "X" if r["hg"] == r["ag"] else "2"
                if r["o1x2"]:
                    q = dict(zip("1X2", devig(r["o1x2"])))
                    pmod = {s: pm[("1X2", s, None)] for s in "1X2"}
                    pbl = {s: blend * pmod[s] + (1 - blend) * q[s] for s in "1X2"}
                    res["1x2_model"].append(ll(pmod[outcome])); res["1x2_market"].append(ll(q[outcome]))
                    res["1x2_blend"].append(ll(pbl[outcome]))
                    res["1x2_model_b"].append(sum((pmod[s] - (s == outcome)) ** 2 for s in "1X2"))
                    res["1x2_market_b"].append(sum((q[s] - (s == outcome)) ** 2 for s in "1X2"))
                    for s, price in zip("1X2", r["o1x2"]):
                        cands.append(dict(mk="1X2", sel=s, pm=pmod[s], q=q[s], p=pbl[s], odds=price, win=int(s == outcome)))
                if r["ou"]:
                    q_over, q_under = devig(r["ou"])
                    tot = r["hg"] + r["ag"]
                    over = int(tot > 2.5)
                    po = pm[("OU", "OVER", 2.5)]
                    res["ou_model"].append(ll(po if over else 1 - po)); res["ou_market"].append(ll(q_over if over else q_under))
                    pb = blend * po + (1 - blend) * q_over
                    res["ou_blend"].append(ll(pb if over else 1 - pb))
                    res["ou_model_b"].append((po - over) ** 2); res["ou_market_b"].append((q_over - over) ** 2)
                    cands.append(dict(mk="OU2.5", sel="OVER", pm=po, q=q_over, p=pb, odds=r["ou"][0], win=over))
                    cands.append(dict(mk="OU2.5", sel="UNDER", pm=1 - po, q=q_under, p=1 - pb, odds=r["ou"][1], win=1 - over))
        w0 = w1
    return res, cands, n_total, n_used


def simulate(cands, sel, use_model=True):
    out = []
    for c in cands:
        p = c["p"] if use_model else c["q"]
        edge = p * c["odds"] - 1
        if p >= sel["min_model_prob"] and c["odds"] >= sel["min_odds"] and c["odds"] <= sel["max_odds_any"] \
                and edge >= sel["min_edge"]:
            out.append(c)
    return out


def market_rules(rows, sel):
    """Οι ΤΡΕΧΟΝΤΕΣ κανόνες του συστήματος: πιθανότητα από την αγορά (devig), φίλτρα του config.
    Επιστρέφει (επιλογές) με τιμές μέσου όρου και καλύτερης τιμής."""
    out = []
    avoid = sel.get("avoid") or []
    for r in rows:
        items = []
        if r["o1x2"] and r["m1x2"]:
            q = devig(r["o1x2"]); w = "1" if r["hg"] > r["ag"] else "X" if r["hg"] == r["ag"] else "2"
            items += [("1X2", s_, None, q[i], r["o1x2"][i], r["m1x2"][i], int(s_ == w)) for i, s_ in enumerate("1X2")]
        if r["ou"] and r["mou"]:
            q = devig(r["ou"]); ov = int(r["hg"] + r["ag"] > 2.5)
            items += [("OU", "OVER", 2.5, q[0], r["ou"][0], r["mou"][0], ov), ("OU", "UNDER", 2.5, q[1], r["ou"][1], r["mou"][1], 1 - ov)]
        for mk, s_, ln, q, avg, mx, win in items:
            if any(a.get("market") == mk and a.get("selection") in (None, s_) and a.get("line") in (None, ln) for a in avoid):
                continue
            if q >= sel["min_model_prob"] and sel["min_odds"] <= avg <= sel["max_odds_any"] and q * mx - 1 >= sel["min_edge"]:
                out.append(dict(ko=r["ko"], mk=mk, sel=s_, odds=avg, best=mx, win=win, p=q))
    return out


def rules_table(picks):
    lines = ["| Τιμή | Επιλογές | Hit-rate | ROI ανά επιλογή | 95% διάστημα ROI |", "|---|---|---|---|---|"]
    for name, k in (("Μέση τιμή πρακτορείων", "odds"), ("Καλύτερη τιμή πρακτορείων", "best")):
        pr = [(c[k] if c["win"] else 0) - 1 for c in picks]
        if not pr:
            continue
        ci = bootstrap_roi(pr)
        lines.append(f"| {name} | {len(picks)} | {np.mean([c['win'] for c in picks]):.1%} | {np.mean(pr):+.1%} | "
                     f"{ci[0]:+.1%} … {ci[1]:+.1%} |" if ci else f"| {name} | {len(picks)} | — | — | — |")
    return lines


def roi_line(name, picks):
    if not picks:
        return f"| {name} | 0 | — | — | — | — |"
    profits = [(c["odds"] if c["win"] else 0) - 1 for c in picks]
    ci = bootstrap_roi(profits)
    cis = f"{ci[0]:+.1%} … {ci[1]:+.1%}" if ci else "—"
    return (f"| {name} | {len(picks)} | {np.mean([c['win'] for c in picks]):.1%} | "
            f"{np.mean([c['p'] for c in picks]):.1%} | {np.mean(profits):+.1%} | {cis} |")


def run_counts(cfg, db, aliases, now, start):
    ts = db.team_stats()
    by_ev = defaultdict(dict)
    for r in ts:
        by_ev[r["event_key"]][r["is_home"]] = r
    events = sorted([(parse_iso(s[1]["kickoff"]), k, s) for k, s in by_ev.items() if 1 in s and 0 in s], key=lambda x: x[0])
    out = {}
    for metric, col, lines in (("corners", "corners", (8.5, 9.5, 10.5)), ("cards", "yellow", (3.5, 4.5))):
        pairs = {L: [] for L in lines}
        base_ll = {L: [] for L in lines}
        mod_ll = {L: [] for L in lines}
        w0 = start
        while w0 < now:
            w1 = w0 + timedelta(days=WINDOW_DAYS)
            test = [e for e in events if w0 <= e[0] < w1 and e[2][1].get(col) is not None and e[2][0].get(col) is not None]
            if test:
                train_rows = [r for r in ts if parse_iso(r["kickoff"]) < w0]
                model = CountModel(metric, cfg["models"]["counts"], aliases).fit(train_rows, w0)
                tr_tot = defaultdict(list)
                tr_ev = defaultdict(dict)
                for r in train_rows:
                    if r.get(col) is not None:
                        tr_ev[r["event_key"]][r["is_home"]] = r[col]
                tots = [s[0] + s[1] for s in tr_ev.values() if len(s) == 2]
                for ko, k, s in test:
                    h, a = s[1], s[0]
                    if not (model.known(h["team"], 8) and model.known(a["team"], 8)):
                        continue
                    pred = model.predict(h["team"], a["team"], h["league"], h.get("referee"))
                    total = h[col] + a[col]
                    for L in lines:
                        if L not in pred["lines"]:
                            continue
                        p = pred["lines"][L]
                        y = int(total > L)
                        b = float(np.mean([t > L for t in tots])) if tots else 0.5
                        pairs[L].append((p, y)); mod_ll[L].append(ll(p if y else 1 - p)); base_ll[L].append(ll(b if y else 1 - b))
            w0 = w1
        out[metric] = (pairs, mod_ll, base_ll)
    return out


def run(cfg, now, out_path="docs/backtest.md", months=13):
    db = DB(cfg["database"])
    aliases = cfg["team_aliases"]
    start = now - timedelta(days=int(months * 30.4))
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    log.info("backtest ποδοσφαίρου από %s…", start.date())
    all_rows = load_fdco(cfg, now)
    res, cands, n_total, n_used = run_football(cfg, db, aliases, now, start, rows=all_rows)
    sel = cfg["selection"]
    old = dict(sel, min_edge=-0.03, max_odds_any=4.0, avoid=[])      # ο κανόνας ΠΡΙΝ το backtest (για σύγκριση)
    L = [f"# BetBot – Backtest ({now:%d/%m/%Y})", "",
         f"Διάστημα ελέγχου: {start:%d/%m/%Y} – {now:%d/%m/%Y}, παράθυρα {WINDOW_DAYS} ημερών (walk-forward). "
         f"Αγώνες με αποδόσεις: {n_total}, με αρκετό ιστορικό και για τις δύο ομάδες: {n_used}.", "",
         "## 1. Πιθανότητες: μοντέλο έναντι αγοράς (χαμηλότερο log-loss/Brier = καλύτερο)", "",
         "| Αγορά | Μοντέλο (log-loss) | Αγορά (log-loss) | Μίξη 50/50 | Brier μοντέλου | Brier αγοράς |", "|---|---|---|---|---|---|"]
    for name, k in (("1Χ2", "1x2"), ("Over/Under 2.5", "ou")):
        if res[f"{k}_model"]:
            L.append(f"| {name} (n={len(res[f'{k}_model'])}) | {np.mean(res[f'{k}_model']):.4f} | {np.mean(res[f'{k}_market']):.4f} | "
                     f"{np.mean(res[f'{k}_blend']):.4f} | {np.mean(res[f'{k}_model_b']):.4f} | {np.mean(res[f'{k}_market_b']):.4f} |")
    L += ["", "Αν το log-loss της αγοράς είναι χαμηλότερο, η αγορά προβλέπει καλύτερα από το μοντέλο· η μίξη 50/50 προσπαθεί να πάρει το καλύτερο από τα δύο.", "",
          "## 2. Βαθμονόμηση του μοντέλου (όλες οι επιλογές 1Χ2 και Over/Under 2.5)", ""]
    L += bins_table([(c["pm"], c["win"]) for c in cands], [0, .1, .2, .3, .4, .5, .6, .7, .8, 1.01])
    L += ["", "Σε καλό μοντέλο, οι δύο τελευταίες στήλες είναι κοντά. Αν η πρόβλεψη είναι πολύ μεγαλύτερη από την πραγματική συχνότητα, το μοντέλο είναι υπερβολικά σίγουρο.", "",
          "## 3. Προσομοίωση του ΠΑΛΙΟΥ συστήματος (μίξη μοντέλου/αγοράς 50/50 – πριν το backtest)", "",
          f"1€ ανά επιλογή, αποδόσεις: μέσος όρος πρακτορείων. Φίλτρα: πιθανότητα ≥ {old['min_model_prob']:.0%}, απόδοση {old['min_odds']}–{old['max_odds_any']:g}, "
          f"value ≥ {old['min_edge']:+.2f}.", "",
          "| Στρατηγική | Επιλογές | Hit-rate | Μέση πιθανότητα | ROI ανά επιλογή | 95% διάστημα ROI |", "|---|---|---|---|---|---|"]
    mine = simulate(cands, old)
    L.append(roi_line("Παλιό σύστημα (μοντέλο+αγορά 50/50)", mine))
    L.append(roi_line(" └ μόνο 1Χ2", [c for c in mine if c["mk"] == "1X2"]))
    L.append(roi_line(" └ μόνο Over/Under 2.5", [c for c in mine if c["mk"] == "OU2.5"]))
    L.append(roi_line(" └ μόνο Under", [c for c in mine if c["sel"] == "UNDER"]))
    L.append(roi_line(" └ μόνο Over", [c for c in mine if c["sel"] == "OVER"]))
    big = [c for c in mine if c["pm"] - c["q"] >= 0.15]
    L.append(roi_line("Επιλογές όπου το μοντέλο ξεπερνά την αγορά κατά ≥15 μονάδες", big))
    L.append(roi_line("Όλες οι επιλογές με απόδοση 1.5–2.5 (τυφλά)", [dict(c, p=c["q"]) for c in cands if 1.5 <= c["odds"] <= 2.5]))
    L += ["", "Το ROI είναι το κέρδος ανά 1€: −5% σημαίνει ότι κατά μέσο όρο χάνεις 5 λεπτά ανά ευρώ. Το πρακτορείο κρατά περίπου 5–8% προμήθεια, "
          "άρα ROI γύρω στο −5% είναι «κανονικό» για τυχαίες επιλογές. Αν το διάστημα περιλαμβάνει το 0, δεν μπορούμε να πούμε ότι υπάρχει πραγματικό πλεονέκτημα.", ""]
    cur = market_rules([r for r in all_rows if start <= r["ko"] < now], sel)
    mid = start + (now - start) / 2
    L += ["## 3β. ΝΕΟ σύστημα σε ισχύ (πιθανότητα από την αγορά, χωρίς Under 2.5, απόδοση έως "
          f"{sel['max_odds_any']:g}) – ίδιος έλεγχος", "",
          f"Πιθανότητα αγοράς ≥ {sel['min_model_prob']:.0%}, απόδοση {sel['min_odds']}–{sel['max_odds_any']}, "
          f"value ≥ {sel['min_edge']:+.2f}. Πλήρης περίοδος:", ""] + rules_table(cur)
    for nm, f in (("1η μισή περιόδου", lambda c: c["ko"] < mid), ("2η μισή περιόδου", lambda c: c["ko"] >= mid)):
        L += ["", f"{nm}:", ""] + rules_table([c for c in cur if f(c)])
    L += ["", "Η «καλύτερη τιμή» είναι το μέγιστο ανάμεσα στα πρακτορεία του football-data: αισιόδοξη, γιατί δεν έχεις πάντα πρόσβαση σε όλα και υπάρχουν όρια στοιχήματος.", ""]
    log.info("backtest κόρνερ/καρτών…")
    counts = run_counts(cfg, db, aliases, now, start)
    L += ["## 4. Κόρνερ και κάρτες (χωρίς ιστορικές αποδόσεις: μόνο ακρίβεια πιθανοτήτων)", "",
          "| Μετρική | Γραμμή | Αγώνες | Log-loss μοντέλου | Log-loss απλού μέσου όρου | Μέση πρόβλεψη Over | Πραγματικό Over |", "|---|---|---|---|---|---|---|"]
    for metric, (pairs, mod, base) in counts.items():
        for Ln, pr in pairs.items():
            if len(pr) >= 30:
                L.append(f"| {'Κόρνερ' if metric == 'corners' else 'Κίτρινες'} | {Ln} | {len(pr)} | {np.mean(mod[Ln]):.4f} | "
                         f"{np.mean(base[Ln]):.4f} | {np.mean([p for p, _ in pr]):.1%} | {np.mean([y for _, y in pr]):.1%} |")
    L += ["", "Αν το log-loss του μοντέλου δεν είναι χαμηλότερο από τον απλό μέσο όρο, το μοντέλο δεν προσθέτει πληροφορία για αυτή τη γραμμή.", ""]
    for metric, (pairs, _, _) in counts.items():
        allp = [x for pr in pairs.values() for x in pr]
        if len(allp) >= 100:
            L += [f"### Βαθμονόμηση: {'κόρνερ' if metric == 'corners' else 'κίτρινες'} (όλες οι γραμμές μαζί)", ""]
            L += bins_table(allp, [0, .2, .3, .4, .5, .6, .7, .8, 1.01]) + [""]
    text = "\n".join(L)
    import os
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    return text
