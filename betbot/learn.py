"""Μάθηση από τα αποτελέσματά μας (διορθώσεις πιθανότητας) και συσχέτιση σκελών μέσα στο δελτίο.

1) ΔΙΟΡΘΩΣΗ ΒΑΘΜΟΝΟΜΗΣΗΣ: για κάθε χαρακτηριστικό (αγορά, λίγκα, ζώνη πιθανότητας, προειδοποίηση πριν τον αγώνα) συγκρίνουμε
   νίκες με όσες περίμενε το μοντέλο στα ΚΡΙΘΕΝΤΑ μοναδικά σκέλη. Αν υπάρχει συστηματική απόκλιση, η πιθανότητα των επόμενων
   σκελών διορθώνεται, με ισχυρή «συρρίκνωση» (λίγα δεδομένα → μικρή διόρθωση) και όρια. Προς τα κάτω εφαρμόζεται πλήρως,
   προς τα πάνω στο μισό (προτιμάμε να χάσουμε μια ευκαιρία παρά να φουσκώσουμε πιθανότητες).
   Για να μην πέφτουμε σε φαύλο κύκλο, η μάθηση μετράει την πιθανότητα ΠΡΙΝ τη διόρθωση (`p_base`).
2) ΣΥΣΧΕΤΙΣΗ: τα σκέλη ενός δελτίου δεν είναι ανεξάρτητα (ίδια λίγκα/ίδιος τύπος αγοράς). Η πιθανότητα δελτίου υπολογίζεται
   με μοντέλο κοινών παραγόντων (Gaussian copula, Monte Carlo με σταθερό seed) αντί για απλό γινόμενο."""
from __future__ import annotations

import math
import random
from collections import defaultdict
from statistics import NormalDist

_ND = NormalDist()


def _grp(l) -> str:
    from .insights import grp
    return grp(l)


def _pband(p: float) -> str:
    return "<60%" if p < .6 else "60–70%" if p < .7 else "70–80%" if p < .8 else "80%+"


def features(l) -> list:
    """Τα χαρακτηριστικά ενός σκέλους στα οποία μαθαίνουμε διορθώσεις: (είδος, τιμή)."""
    p = l.get("p_base") or l.get("p") or 0.5
    out = [("Γενικά", "όλα τα σκέλη"), ("Αγορά", _grp(l)), ("Λίγκα", l.get("league_name") or l.get("league") or ""), ("Πιθανότητα", _pband(p))]
    if [x for x in (l.get("warnings") or []) if x]:
        out.append(("Προειδοποίηση", "είχε"))
    return [(a, b) for a, b in out if b]


def settled_legs(db) -> list:
    """Μοναδικά κριθέντα σκέλη (το ίδιο σκέλος σε πολλά δελτία μετράει μία φορά)."""
    seen, legs = {}, []
    for s in db.slips():
        if str(s.get("list_name") or "").startswith("shadow_") or str(s["slip_id"]).startswith("legacy"):
            continue
        for l in s["legs"]:
            if l.get("result") in ("won", "lost") and (l.get("p_base") or l.get("p")):
                k = (l["match_id"], l["market"], l["selection"], l.get("line"))
                if k not in seen:
                    seen[k] = 1
                    legs.append(l)
    return legs


def build_table(db, cfg) -> dict:
    """{(είδος, τιμή): {n, w, e, z, adj}} με συρρικνωμένη διόρθωση ανά χαρακτηριστικό."""
    c = (cfg or {}).get("learn") or {}
    if not c.get("enabled", False):
        return {}
    k0 = float(c.get("prior_n", 40))
    min_n = int(c.get("min_n", 20))
    min_z = float(c.get("min_abs_z", 1.0))
    agg = defaultdict(lambda: [0, 0, 0.0, 0.0, 0.0])
    for l in settled_legs(db):
        p = l.get("p_base") or l.get("p")
        o = l.get("odds") or 0
        for f in features(l):
            a = agg[f]
            a[0] += 1; a[1] += l["result"] == "won"; a[2] += p; a[3] += p * (1 - p)
            if o:
                a[4] += (o - 1) if l["result"] == "won" else -1          # ROI αν το σκέλος παιζόταν μόνο του (1 μονάδα)
    table = {}
    for f, (n, w, e, var, pl) in agg.items():
        sd = math.sqrt(var)
        z = (w - e) / sd if sd else 0.0
        adj = 0.0
        if n >= min_n and abs(z) >= min_z:
            adj = (w - e) / (n + k0)          # μονάδες πιθανότητας, συρρικνωμένη προς το 0
        table[f] = {"n": n, "w": int(w), "e": round(e, 1), "z": round(z, 1), "adj": adj, "roi": (pl / n) if n else 0.0}
    return table


def is_weak(kind, v, cfg) -> bool:
    """Αδύναμη αγορά: αρκετά σκέλη, ξεκάθαρα κάτω από το αναμενόμενο ΚΑΙ αρνητικό ROI ως μονό (βρέθηκε 27/11/2026: Over γκολ −19%, Χάντικαπ −26%)."""
    c = (cfg or {}).get("learn") or {}
    return (kind == "Αγορά" and v["n"] >= int(c.get("weak_n", 20)) and v["z"] <= float(c.get("weak_z", -1.5))
            and v.get("roi", 0) <= float(c.get("weak_roi", -0.12)))


def adjustment(l, table, cfg):
    """Συνολική διόρθωση (μονάδες πιθανότητας) για ένα σκέλος + λίστα (χαρακτηριστικό, διόρθωση) που την προκάλεσαν."""
    c = (cfg or {}).get("learn") or {}
    if not table:
        return 0.0, []
    parts = [(f, table[f]["adj"]) for f in features(l) if f in table and table[f]["adj"]]
    if not parts:
        return 0.0, []
    w_down, w_up = 1.0, float(c.get("up_weight", 0.5))
    share = float(c.get("combine", 0.6))          # τα χαρακτηριστικά επικαλύπτονται· δεν αθροίζονται 1:1
    tot = sum((a * w_down if a < 0 else a * w_up) for _, a in parts) * share
    tot = max(-float(c.get("max_down", 0.08)), min(float(c.get("max_up", 0.04)), tot))
    return tot, parts


def _block_weak(c_, table, cfg):
    """Αδύναμο χαρακτηριστικό (πολύ κάτω από το αναμενόμενο ή αδύναμη αγορά) → όχι στα «πιο σίγουρα» δελτία (Προτεινόμενο/Safe)."""
    lc = (cfg or {}).get("learn") or {}
    bz, bn = float(lc.get("block_z", -2.5)), int(lc.get("block_n", 25))
    bad = [f for f in features(c_) if f[0] != "Γενικά" and f in table and ((table[f]["z"] <= bz and table[f]["n"] >= bn) or is_weak(f[0], table[f], cfg))]
    if bad:
        c_["blocked"].update({"recommended", "safe"})
        t = table[bad[0]]
        c_.setdefault("warnings", []).append(f"Ιστορικά αδύναμο: {bad[0][0]} «{bad[0][1]}» ({t['w']} νίκες στα {t['n']}, αναμ. {t['e']:.0f}) — εκτός Προτεινόμενου/Safe")


def apply(c_, table, cfg):
    """Εφαρμόζει τη διόρθωση σε υποψήφιο (`p`, `edge`, `min_play`, `p_base`, `learn`). Καλείται από το selector._cand."""
    p0 = c_["p"]
    c_["p_base"] = p0
    adj, parts = adjustment(c_, table, cfg)
    c_["learn"] = round(adj, 4)
    _block_weak(c_, table, cfg)
    if abs(adj) < 0.0005:
        return c_
    p = min(0.97, max(0.01, p0 + adj))
    c_["p"] = p
    if c_.get("odds"):
        c_["edge"] = p * c_["odds"] - 1
        c_["min_play"] = round(1 / p, 2)
    top = max(parts, key=lambda x: abs(x[1]))[0]
    t = table[top]
    c_.setdefault("notes_tail", []).append(
        f"Διόρθωση από την εμπειρία μας: {adj * 100:+.1f} μονάδες στην πιθανότητα ({top[0]} «{top[1]}»: {t['w']} νίκες στα {t['n']}, το μοντέλο περίμενε {t['e']:.0f})")
    return c_


# ---------------------------------------------------------------- συσχέτιση
def slip_probability(legs, cfg, n_sim: int = 20000) -> tuple:
    """(πιθανότητα με συσχέτιση, πιθανότητα με ανεξαρτησία).
    Παράγοντες: ίδια λίγκα, ίδιος τύπος αγοράς (και προαιρετικά καθολικός). ΠΡΟΣΟΧΗ: με θετική συσχέτιση η πιθανότητα να περάσουν ΟΛΑ τα σκέλη
    είναι ελαφρά ΥΨΗΛΟΤΕΡΗ από το γινόμενο (αλλά και οι αποτυχίες έρχονται μαζί → μεγαλύτερη διακύμανση). Δεν είναι «ποινή»· είναι ειλικρίνεια.
    Ανάλυση: δειγματοληψία των κοινών παραγόντων και ακριβής ολοκλήρωση του ατομικού θορύβου (χαμηλή διασπορά)."""
    import numpy as np
    from scipy.special import ndtr, ndtri
    ps = np.array([max(1e-6, min(1 - 1e-6, l["p"])) for l in legs])
    ind = float(np.prod(ps))
    c = (cfg or {}).get("correlation") or {}
    if not c.get("enabled", False) or len(legs) < 2:
        return ind, ind
    r_g, r_l, r_f = float(c.get("global", 0.0)), float(c.get("same_league", 0.06)), float(c.get("same_group", 0.03))
    load = math.sqrt(max(1e-9, 1 - r_g - r_l - r_f))
    thr = ndtri(ps)                                   # νίκη όταν X_i < thr_i
    leagues = sorted({l.get("league") for l in legs}, key=str)
    groups = sorted({_grp(l) for l in legs})
    li = np.array([leagues.index(l.get("league")) for l in legs])
    gi = np.array([groups.index(_grp(l)) for l in legs])
    rng = np.random.default_rng(7)
    g = rng.standard_normal((n_sim, 1))
    lz = rng.standard_normal((n_sim, len(leagues)))[:, li]
    fz = rng.standard_normal((n_sim, len(groups)))[:, gi]
    cond = ndtr((thr[None, :] - math.sqrt(r_g) * g - math.sqrt(r_l) * lz - math.sqrt(r_f) * fz) / load)
    return float(np.prod(cond, axis=1).mean()), ind


def report_rows(table, cfg) -> list:
    """Γραμμές για την Ανάλυση: ενεργές διορθώσεις (|διόρθωση| ≥ 0,5 μονάδα) και χαρακτηριστικά με αρκετά δεδομένα."""
    rows = []
    for (kind, val), v in table.items():
        if v["n"] >= 12:
            rows.append({"k": kind, "v": val, "n": v["n"], "w": v["w"], "e": v["e"], "z": v["z"], "adj": round(v["adj"] * 100, 1),
                         "roi": round(v.get("roi", 0) * 100, 1), "weak": is_weak(kind, v, cfg)})
    rows.sort(key=lambda r: (-abs(r["adj"]), -r["n"]))
    return rows
