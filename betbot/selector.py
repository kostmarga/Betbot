"""Από πιθανότητες μοντέλων + αποδόσεις → υποψήφιες επιλογές → λίστες / δελτία.

Ροή:
 1. Για κάθε αγώνα των επόμενων ωρών: πιθανότητες από όλα τα μοντέλα
    (γκολ, 1Χ2, κόρνερ, κάρτες, πλάγια, παίκτες, μπάσκετ).
 2. «Καθαρή» πιθανότητα αγοράς (χωρίς γκανιότα) όπου υπάρχουν αποδόσεις.
 3. Blend: p = b·μοντέλο + (1−b)·αγορά (οι αγορές είναι ακριβείς· το blend μάς προστατεύει).
 4. Κανόνες (rules.py): μπλοκάρουν επιλογές με γνωστά «λάθη» (κακή φόρμα, απουσίες, κινήσεις κόντρα).
 5. Επιλογές ΧΩΡΙΣ απόδοση (κόρνερ/κάρτες/πλάγια/παίκτες σε πολλά ματς) → «δίκαιη απόδοση»
    και «παίξ' το αν ≥ Χ». Δεν μπαίνουν σε δελτία, γιατί δεν ξέρουμε την πραγματική απόδοση.
 6. Δελτία: group-knapsack DP – μέγιστη πιθανότητα επιτυχίας για συνολική απόδοση σε εύρος.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import timedelta

import numpy as np

from . import movement, rules
from .models import COUNT_LABEL, PROP_LABEL
from .util import iso

GROUPS = {"1X2": ["1", "X", "2"], "OU": ["OVER", "UNDER"], "BTTS": ["YES", "NO"],
          "ML": ["HOME", "AWAY"], "TOTAL": ["OVER", "UNDER"], "SPREAD": ["HOME", "AWAY"],
          "CORNERS": ["OVER", "UNDER"], "CARDS": ["OVER", "UNDER"], "THROWINS": ["OVER", "UNDER"]}
COUNT_MARKET = {"corners": "CORNERS", "cards": "CARDS", "throw_ins": "THROWINS"}
MARKET_FAMILY = {"1X2": "result", "DC": "result", "ML": "result", "SPREAD": "result",
                 "OU": "goals", "BTTS": "goals", "TOTAL": "points",
                 "CORNERS": "corners", "CORNERS_MORE": "corners", "CARDS": "cards", "THROWINS": "throw_ins",
                 "PLAYER": "players"}


def label(market, sel, line, home, away, extra=None):
    if market == "1X2":
        return {"1": f"1 · Νίκη {home}", "X": "Χ · Ισοπαλία", "2": f"2 · Νίκη {away}"}[sel]
    if market == "DC":
        return {"1X": "1Χ (διπλή ευκαιρία)", "X2": "Χ2 (διπλή ευκαιρία)", "12": "12 (διπλή ευκαιρία)"}[sel]
    if market == "OU":
        return f"{'Over' if sel == 'OVER' else 'Under'} {line:g} γκολ"
    if market == "BTTS":
        return "Goal-Goal" if sel == "YES" else "No Goal"
    if market == "ML":
        return f"Νίκη {home if sel == 'HOME' else away}"
    if market == "TOTAL":
        return f"{'Over' if sel == 'OVER' else 'Under'} {line:g} πόντοι"
    if market == "SPREAD":
        hl = line if sel == "HOME" else -line
        return f"{home if sel == 'HOME' else away} {hl:+g} χάντικαπ"
    if market == "CORNERS":
        return f"{'Over' if sel == 'OVER' else 'Under'} {line:g} κόρνερ"
    if market == "CORNERS_MORE":
        return f"Περισσότερα κόρνερ: {home if sel == 'HOME' else away}"
    if market == "CARDS":
        return f"{'Over' if sel == 'OVER' else 'Under'} {line:g} κάρτες"
    if market == "THROWINS":
        return f"{'Over' if sel == 'OVER' else 'Under'} {line:g} πλάγια"
    if market == "PLAYER" and extra:
        prop, k = extra["prop"], extra["k"]
        if prop == "GOAL":
            return f"{extra['player']} σκόρερ"
        if prop == "CARD":
            return f"{extra['player']} κάρτα"
        return f"{extra['player']} {k}+ {PROP_LABEL[prop]}"
    return f"{market} {sel} {line or ''}"


def _best_odds(rows):
    """Μία γραμμή ανά (αγορά, επιλογή, γραμμή): η πηγή με τα περισσότερα βιβλία (ισοπαλία -> η μεγαλύτερη απόδοση).
    Η τιμή της χρησιμεύει ως «συναίνεση της αγοράς» για τις πιθανότητες. Επιπλέον κάθε γραμμή παίρνει
    `best_price`/`best_source`: η ΥΨΗΛΟΤΕΡΗ τιμή που βρέθηκε σε οποιαδήποτε πηγή (εκεί ψάχνεις να παίξεις).
    Οι πηγές που τελειώνουν σε `_max` (π.χ. fdco_max) δίνουν μόνο καλύτερη τιμή, όχι συναίνεση.
    Backtest 06/11/2026: η καλύτερη τιμή αντί του μέσου όρου βελτιώνει το ROI κατά ~3 μονάδες."""
    best, top = {}, {}
    for r in rows:
        k = (r["market"], r["selection"], r["line"])
        if r["price"] > top.get(k, (0, ""))[0]:
            top[k] = (r["price"], r["source"])
        if r["source"].endswith("_max"):
            continue
        if k not in best or (r["n_books"], r["price"]) > (best[k]["n_books"], best[k]["price"]):
            best[k] = r
    out = {}
    for k, r in best.items():
        r = dict(r)
        r["best_price"], r["best_source"] = top[k]
        out[k] = r
    return out


def _devig(odds: dict) -> dict:
    q, groups = {}, defaultdict(dict)
    for (m, s, l), r in odds.items():
        groups[(m, l)][s] = r["price"]
    for (m, l), sels in groups.items():
        need = GROUPS.get(m, [])
        if need and all(s in sels for s in need):
            inv = {s: 1 / sels[s] for s in need}
            tot = sum(inv.values())
            for s in need:
                q[(m, s, l)] = inv[s] / tot
        else:
            for s, p in sels.items():
                q[(m, s, l)] = 0.94 / p      # χωρίς πλήρες βιβλίο: υποθέτουμε ~6% margin
    return q


# =====================================================================
class MatchContext:
    """Όλα όσα ξέρουμε για έναν επερχόμενο αγώνα (για πιθανότητες + «γιατί»)."""

    def __init__(self, m, lg, models, db, cfg):
        self.m, self.lg, self.db, self.cfg = m, lg, db, cfg
        self.home, self.away = m["home"], m["away"]
        self.sport = lg["sport"]
        self.referee = db.referee_for(m["match_id"])
        self.lineups = db.lineups_for(m["match_id"])
        self.moves = movement.moves_for_match(db, m["match_id"])
        self.model = None
        self.form_home = self.form_away = []
        self.h2h = []
        self.exp = ""
        self.counts = {}
        self.absent = {self.home: [], self.away: []}
        for r in self.lineups:
            if r["status"] in ("missing", "doubtful"):
                self.absent.setdefault(r["team"], []).append(r)

    def absences(self, team):
        return self.absent.get(team, [])

    def lineup_status(self, team, player):
        for r in self.lineups:
            if r["team"] == team and r["player"] == player:
                return r["status"], bool(r["confirmed"])
        return None, False

    def ppg(self, team, n=5):
        form = self.form_home if team == self.home else self.form_away
        form = form[:n]
        if not form:
            return None
        pts = {"Ν": 3, "Ι": 1, "Η": 0}
        return sum(pts[f["r"]] for f in form) / len(form)


def _cand(ctx, key, p_model, odds_row=None, q=None, extra=None, blend=0.5):
    m = ctx.m
    market, sel, line = key
    price = (odds_row.get("best_price") or odds_row["price"]) if odds_row else None
    p = (blend * p_model + (1 - blend) * q) if (odds_row and q is not None) else p_model
    mv = ctx.moves.get(key)
    c = {
        "match_id": m["match_id"], "league": m["league"], "league_name": ctx.lg["name"], "sport": ctx.sport,
        "kickoff": m["kickoff"], "home": ctx.home, "away": ctx.away,
        "market": market, "selection": sel, "line": line, "family": MARKET_FAMILY.get(market, market),
        "label": label(market, sel, line, ctx.home, ctx.away, extra),
        "odds": price, "p_model": p_model, "p_market": q, "p": p,
        "edge": (p * price - 1) if price else None,
        "fair_odds": 1 / p_model if p_model > 0 else None,
        "move": mv, "extra": extra or {}, "source": odds_row["source"] if odds_row else None,
        "exp": ctx.exp, "form_home": ctx.form_home, "form_away": ctx.form_away, "h2h": ctx.h2h,
        "warnings": [], "blocked": set(), "why": [],
    }
    return c


def _avoided(key, avoid, sport) -> bool:
    """Επιλογές που το backtest έδειξε σταθερά ζημιογόνες (config: selection.avoid)."""
    market, sel, line = key
    for a in avoid:
        if a.get("sport", "football") != sport:
            continue
        if a.get("market") == market and a.get("selection") in (None, sel) and a.get("line") in (None, line):
            return True
    return False


def build_candidates(db, cfg, models, now):
    """Επιστρέφει dict: with_odds (λίστα), fair (λίστα χωρίς απόδοση), contexts (match_id -> ctx)."""
    sel_cfg = cfg["selection"]
    leagues = {lg["id"]: lg for lg in cfg["leagues"]}
    horizon = now + timedelta(hours=cfg["slip"]["hours_ahead"])
    upcoming = [m for m in db.matches(status="scheduled", since=iso(now + timedelta(minutes=20)),
                                      until=iso(horizon)) if m["league"] in leagues]
    b = sel_cfg["market_blend"]
    b_fb = sel_cfg.get("market_blend_football", b)    # ποδόσφαιρο: backtest -> βάρος μοντέλου 0
    avoid = sel_cfg.get("avoid") or []
    min_g = sel_cfg["min_team_matches"]
    with_odds, fair, contexts = [], [], {}
    fm, bms, cms, pm = models.get("football"), models.get("basketball", {}), models.get("counts", {}), models.get("players")

    for m in upcoming:
        lg = leagues[m["league"]]
        ctx = MatchContext(m, lg, models, db, cfg)
        odds = _best_odds(db.odds_for(m["match_id"]))
        q = _devig(odds) if odds else {}
        probs = {}                       # key -> (p_model, extra)

        if lg["sport"] == "football":
            if fm and fm.known(m["home"], min_g) and fm.known(m["away"], min_g):
                pred = fm.predict(m["home"], m["away"])
                for k, v in fm.market_probs(pred).items():
                    probs[k] = (v, None)
                g = np.add.outer(np.arange(pred.matrix.shape[0]), np.arange(pred.matrix.shape[1]))
                for (mk, s, l) in odds:
                    if mk == "OU" and l is not None and (mk, s, l) not in probs and l % 1:
                        ov = float(pred.matrix[g > l].sum())
                        probs[("OU", "OVER", l)], probs[("OU", "UNDER", l)] = (ov, None), (1 - ov, None)
                ctx.model = fm
                ctx.exp = f"{pred.lam_home:.2f} – {pred.lam_away:.2f} γκολ"
                ctx.form_home, ctx.form_away = fm.form(m["home"]), fm.form(m["away"])
                ctx.h2h = fm.h2h(m["home"], m["away"])
            for metric, cm in cms.items():
                if not (cm.known(m["home"], 5) and cm.known(m["away"], 5)):
                    continue
                pr = cm.predict(m["home"], m["away"], m["league"], ctx.referee if metric == "cards" else None)
                ctx.counts[metric] = pr
                mk = COUNT_MARKET[metric]
                lines = set(pr["lines"]) | {l for (k2, s, l) in odds if k2 == mk and l is not None}
                for L in lines:
                    if L not in pr["lines"]:
                        continue
                    probs[(mk, "OVER", L)] = (pr["lines"][L], None)
                    probs[(mk, "UNDER", L)] = (1 - pr["lines"][L], None)
                if metric == "corners":
                    probs[("CORNERS_MORE", "HOME", None)] = (pr["more_home"], None)
                    probs[("CORNERS_MORE", "AWAY", None)] = (pr["more_away"], None)
            if pm:
                for team in (m["home"], m["away"]):
                    starters = [r for r in ctx.lineups if r["team"] == team and r["status"] == "starter"]
                    confirmed = any(r["confirmed"] for r in starters)
                    if starters:
                        players = [(r["player"], confirmed) for r in starters]
                    else:   # χωρίς ενδεκάδα: πιθανοί βασικοί από το ιστορικό
                        players = [(pl, False) for (tk, pl) in pm.hist if tk == pm_key(pm, team)
                                   and pm.probable_starter(team, pl)]
                    absent = {r["player"] for r in ctx.absences(team)}
                    for pl, conf in players:
                        if pl in absent:
                            continue
                        pr = pm.predict(team, pl)
                        if not pr:
                            continue
                        for prop, d in pr["props"].items():
                            for k, pk in d["p"].items():
                                key = ("PLAYER", f"{pl}|{prop}", float(k))
                                probs[key] = (pk, {"player": pl, "team": team, "prop": prop, "k": k,
                                                   "confirmed": conf, "stats": d, "exp_min": pr["exp_min"]})
        else:
            bm = bms.get(m["league"])
            if bm and bm.known(m["home"], min_g) and bm.known(m["away"], min_g):
                pred = bm.predict(m["home"], m["away"])
                lines = defaultdict(list)
                for (mk, s, l) in odds:
                    if mk in ("TOTAL", "SPREAD") and l is not None and l % 1:
                        lines[mk].append(l)
                for k, v in bm.market_probs(pred, lines).items():
                    probs[k] = (v, None)
                ctx.model = bm
                ctx.exp = f"{pred.exp_home:.0f} – {pred.exp_away:.0f} πόντοι"
                ctx.form_home, ctx.form_away = bm.form(m["home"]), bm.form(m["away"])
                ctx.h2h = bm.h2h(m["home"], m["away"])
        if not probs:
            continue
        contexts[m["match_id"]] = ctx

        for key, (pm_, extra) in probs.items():
            orow = odds.get(key)
            c = _cand(ctx, key, pm_, orow, q.get(key), extra, blend=b_fb if lg["sport"] == "football" else b)
            rules.apply(c, ctx, cfg)
            c["why"] = rules.reasons(c, ctx, cms)
            if orow:
                if _avoided(key, avoid, lg["sport"]):
                    continue
                if sel_cfg["min_odds"] <= orow["price"] <= sel_cfg["max_odds_any"]:
                    with_odds.append(c)
            elif key[0] in ("CORNERS", "CORNERS_MORE", "CARDS", "THROWINS", "PLAYER"):
                fair_o = 1 / pm_ if pm_ > 0 else 99
                if pm_ >= sel_cfg["fair_min_prob"] and fair_o >= sel_cfg["fair_min_odds"]:
                    c["play_if"] = round((1 / pm_) * (1 + sel_cfg["fair_value_margin"]), 2)
                    fair.append(c)
    return {"with_odds": with_odds, "fair": fair, "contexts": contexts}


def pm_key(pm, team):
    from .util import norm_team
    return norm_team(team, pm.aliases)


# =====================================================================
#  Δελτία
# =====================================================================
def build_slip(cands, lo, hi, min_legs, max_legs, cfg, exclude=frozenset(), max_basket=99,
               step=0.02, keep=6, require_families=None):
    """Group-knapsack DP: το πολύ μία επιλογή ανά αγώνα, μέγιστο Σlog(p),
    με συνολική απόδοση στο [lo, hi]."""
    max_per_league = cfg["selection"]["max_legs_per_league"]
    llo, lhi = math.log(lo), math.log(hi)
    W = int(lhi / step) + 1
    by_match = defaultdict(list)
    for c in cands:
        if c["match_id"] not in exclude and c.get("odds"):
            by_match[c["match_id"]].append(c)
    states = {(0, 0): [(0.0, ())]}
    for mid, items in by_match.items():
        items = sorted(items, key=lambda c: -c["p"])[:8]
        new = {k: list(v) for k, v in states.items()}
        for (k, w), sols in states.items():
            if k >= max_legs:
                continue
            for it in items:
                w2 = w + int(round(math.log(it["odds"]) / step))
                if w2 > W:
                    continue
                for score, legs in sols:
                    if sum(1 for l in legs if l["league"] == it["league"]) >= max_per_league:
                        continue
                    if it["sport"] == "basketball" and sum(1 for l in legs if l["sport"] == "basketball") >= max_basket:
                        continue
                    new.setdefault((k + 1, w2), []).append((score + math.log(it["p"]), legs + (it,)))
        for key in new:
            new[key] = sorted(new[key], key=lambda x: -x[0])[:keep]
        states = new
    best = None
    for (k, w), sols in states.items():
        if k < min_legs or w * step < llo - 2 * step:
            continue
        for score, legs in sols:
            tot = math.prod(l["odds"] for l in legs)
            if not (lo <= tot <= hi):
                continue
            if require_families and len({l["family"] for l in legs}) < require_families:
                continue
            if best is None or score > best[0]:
                best = (score, legs)
    if not best:
        return None
    legs = sorted(best[1], key=lambda l: l["kickoff"])
    total = math.prod(l["odds"] for l in legs)
    p = math.prod(l["p"] for l in legs)
    pq = [l["p_market"] for l in legs if l["p_market"]]
    return {"legs": list(legs), "total_odds": total, "p_win": p,
            "p_market": math.prod(pq) if len(pq) == len(legs) else None, "ev": p * total - 1}


def build_lists(cands: dict, cfg) -> dict:
    """Όλες οι λίστες/δελτία της ημέρας. Επιστρέφει dict list_id -> περιεχόμενο."""
    L = cfg["lists"]
    wo = cands["with_odds"]
    ok = [c for c in wo if (c["edge"] or 0) >= cfg["selection"]["min_edge"]]
    not_blocked = lambda c, what: what not in c["blocked"]
    out = {}

    # ⭐ Προτεινόμενο: 2–3 σκέλη, όλοι οι κανόνες, + ένα μονό
    rc = L["recommended"]
    pool = [c for c in ok if not_blocked(c, "recommended") and c["p"] >= rc["min_leg_prob"]
            and c["odds"] <= rc["max_leg_odds"]]
    slip = build_slip(pool, rc["min_total"], rc["max_total"], rc["min_legs"], rc["max_legs"], cfg,
                      max_basket=rc["max_basketball_legs"])
    used = {l["match_id"] for l in slip["legs"]} if slip else set()
    spool = [c for c in ok if not_blocked(c, "recommended") and c["p"] >= rc["single_min_prob"]
             and rc["single_min_odds"] <= c["odds"] <= rc["single_max_odds"] and c["match_id"] not in used]
    singles = sorted(spool, key=lambda c: -(c["p"] * 0.7 + (c["edge"] or 0) * 0.3))
    out["recommended"] = {"slip": slip, "single": singles[0] if singles else None}

    # 🛡️ Safe: μεμονωμένα με την υψηλότερη πιθανότητα
    sc = L["safe"]
    safe = sorted([c for c in ok if not_blocked(c, "safe") and c["odds"] >= sc["min_odds"]],
                  key=lambda c: -c["p"])
    seen, safe_list = set(), []
    for c in safe:
        if c["match_id"] in seen:
            continue
        seen.add(c["match_id"])
        safe_list.append(c)
        if len(safe_list) >= sc["count"]:
            break
    out["safe"] = {"picks": safe_list}

    # 🎯 10+ · 🔥 30+ · 🎰 100+
    for lid in ("x10", "x30", "x100"):
        x = L[lid]
        pool = [c for c in ok if not_blocked(c, "slips") and c["p"] >= x.get("min_leg_prob", 0)]
        out[lid] = {"slip": build_slip(pool, x["min_total"], x["max_total"], x["min_legs"], x["max_legs"], cfg,
                                       max_basket=x.get("max_basketball_legs", 99))}

    # ⚽ Μόνο Over/Under γκολ
    oc = L["overs"]
    goals = [c for c in ok if c["market"] in ("OU", "BTTS") and not_blocked(c, "slips")
             and c["p"] >= oc.get("min_leg_prob", 0)]
    if oc.get("only_over"):
        goals = [c for c in goals if c["selection"] in ("OVER", "YES")]
    out["overs"] = {"picks": sorted(goals, key=lambda c: -c["p"])[:oc["count"]],
                    "slip": build_slip(goals, oc["min_total"], oc["max_total"], oc["min_legs"], oc["max_legs"], cfg)}

    # 🚩 Κόρνερ · 🟨 Κάρτες · ↔️ Πλάγια · 👤 Παίκτες (με ή χωρίς απόδοση)
    for lid, fam in (("corners", "corners"), ("cards", "cards"), ("throw_ins", "throw_ins"), ("players", "players")):
        x = L[lid]
        priced = [c for c in wo if c["family"] == fam and (c["edge"] or 0) >= x["min_edge"]
                  and c["p"] >= x.get("min_leg_prob", 0.55)]
        unpriced = [c for c in cands["fair"] if c["family"] == fam]
        if fam == "players":
            priced = [c for c in priced if c["extra"].get("confirmed") or x["allow_probable"]]
        allp = _one_per_match_line(sorted(priced + unpriced, key=lambda c: -c["p"]), fam)
        out[lid] = {"picks": allp[:x["count"]],
                    "slip": build_slip(priced, x["min_total"], x["max_total"], x["min_legs"], x["max_legs"], cfg)
                    if len(priced) >= x["min_legs"] else None}

    # 🔀 Συνδυαστικό: διαφορετικές αγορές
    cc = L["combo"]
    pool = [c for c in ok if not_blocked(c, "slips") and c["p"] >= cc.get("min_leg_prob", 0)]
    out["combo"] = {"slip": build_slip(pool, cc["min_total"], cc["max_total"], cc["min_legs"], cc["max_legs"], cfg,
                                       require_families=cc["min_families"])}
    return out


def _one_per_match_line(cs, fam):
    """Για τη λίστα: το πολύ 2 επιλογές ανά αγώνα (π.χ. όχι Over 8.5 ΚΑΙ Over 9.5 ΚΑΙ Over 10.5)."""
    seen, out = defaultdict(int), []
    for c in cs:
        k = (c["match_id"], c["extra"].get("player") if fam == "players" else c["market"])
        if seen[k] >= (1 if fam != "players" else 1):
            continue
        seen[k] += 1
        out.append(c)
    return out


# =====================================================================
#  Εκκαθάριση
# =====================================================================
def settle_leg(leg, match, db=None):
    """won | lost | void | open"""
    if match is None or match["status"] in ("scheduled", "live"):
        return "open"
    if match["status"] == "postponed":
        return "void"
    h, a = match["home_score"], match["away_score"]
    m, s, L = leg["market"], leg["selection"], leg["line"]
    if m == "1X2":
        res = "1" if h > a else "X" if h == a else "2"
        return "won" if res == s else "lost"
    if m == "DC":
        res = "1" if h > a else "X" if h == a else "2"
        return "won" if res in s else "lost"
    if m in ("OU", "TOTAL"):
        t = h + a
        if t == L:
            return "void"
        return "won" if (t > L) == (s == "OVER") else "lost"
    if m == "BTTS":
        return "won" if ((h > 0 and a > 0) == (s == "YES")) else "lost"
    if m == "ML":
        return "won" if (h > a) == (s == "HOME") else "lost"
    if m == "SPREAD":
        v = (h - a) + L
        if v == 0:
            return "void"
        return "won" if (v > 0) == (s == "HOME") else "lost"
    if m in ("CORNERS", "CARDS", "THROWINS", "CORNERS_MORE") and db is not None:
        col = {"CORNERS": "corners", "CORNERS_MORE": "corners", "CARDS": "yellow", "THROWINS": "throw_ins"}[m]
        ts = db.team_stats_for_match(match["match_id"])
        hv = next((r[col] for r in ts if r["is_home"] == 1), None)
        av = next((r[col] for r in ts if r["is_home"] == 0), None)
        if hv is None or av is None:
            return "open"           # θα ξαναδοκιμάσει όταν έρθουν τα στατιστικά
        if m == "CORNERS_MORE":
            if hv == av:
                return "lost"
            return "won" if (hv > av) == (s == "HOME") else "lost"
        t = hv + av
        return "won" if (t > L) == (s == "OVER") else "lost"
    if m == "PLAYER" and db is not None:
        player, prop = s.split("|")
        col = {"SOT": "sot", "SHOTS": "shots", "FOULS": "fouls", "CARD": "yellow", "GOAL": "goals"}[prop]
        rows = [r for r in db.player_stats_for_event(match["match_id"]) if r["player"] == player]
        if not rows:
            ts = db.team_stats_for_match(match["match_id"])
            return "open" if not ts else "void"     # δεν έπαιξε -> συνήθως άκυρο (εξαρτάται από πρακτορείο)
        v = rows[0][col]
        if v is None:
            return "void"           # η πηγή δεν έδωσε αυτό το στατιστικό -> δεν μετράει
        return "won" if v >= L else "lost"
    return "open"


def settle_slips(db):
    done = 0
    for sl in db.slips(status="open"):
        legs = sl["legs"]
        for l in legs:
            if l.get("result") in (None, "open"):
                l["result"] = settle_leg(l, db.get_match(l["match_id"]), db)
        res = [l["result"] for l in legs]
        if "lost" in res:
            db.update_slip(sl["slip_id"], "lost", 0.0, legs); done += 1
        elif all(r in ("won", "void") for r in res):
            mult = math.prod(l["odds"] for l in legs if l["result"] == "won")
            status = "void" if all(r == "void" for r in res) else "won"
            db.update_slip(sl["slip_id"], status, sl["stake"] * mult, legs); done += 1
        else:
            db.update_slip(sl["slip_id"], "open", 0.0, legs)
    return done
