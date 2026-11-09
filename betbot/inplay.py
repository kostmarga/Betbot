"""Live «δίκαιες τιμές»: από τις προαγωνιστικές πιθανότητες της αγοράς βγάζουμε τους αναμενόμενους ρυθμούς γκολ κάθε ομάδας (λ),
και ο browser υπολογίζει ΖΩΝΤΑΝΑ (σκορ + λεπτό) τη δίκαιη απόδοση κάθε αγοράς. Δεν υπάρχει δωρεάν πηγή live αποδόσεων: ο χρήστης βάζει
την απόδοση του πρακτορείου του και η σελίδα λέει αν αξίζει. ΧΩΡΙΣ backtest: αγνοεί κόκκινες κάρτες/τραυματισμούς.
"""
from __future__ import annotations

import math
from datetime import timedelta

from .util import parse_iso


def _pois(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def _probs(lh, la, n=9):
    ph = [_pois(i, lh) for i in range(n)]
    pa = [_pois(j, la) for j in range(n)]
    p1 = px = p2 = pov = 0.0
    for i in range(n):
        for j in range(n):
            p = ph[i] * pa[j]
            if i > j:
                p1 += p
            elif i == j:
                px += p
            else:
                p2 += p
            if i + j >= 3:
                pov += p
    t = p1 + px + p2
    return p1 / t, px / t, p2 / t, pov / t


def fit_lambdas(p1, px, p2, p_over25=None):
    """Αναζήτηση πλέγματος για (λ_γηπεδούχου, λ_φιλοξενούμενου) που ταιριάζουν στο 1Χ2 (και στο Over 2.5 αν υπάρχει)."""
    best, arg = 1e9, (1.4, 1.1)
    t = p1 + px + p2
    p1, px, p2 = p1 / t, px / t, p2 / t
    for a in range(4, 41):
        lh = a * 0.075
        for b in range(3, 36):
            la = b * 0.075
            q1, qx, q2, qo = _probs(lh, la)
            err = (q1 - p1) ** 2 + (qx - px) ** 2 + (q2 - p2) ** 2
            if p_over25 is not None:
                err += (qo - p_over25) ** 2
            if err < best:
                best, arg = err, (lh, la)
    return arg


def priors(cands, cfg, now, hours_before=14, hours_after=4) -> list[dict]:
    """Ποδοσφαιρικοί αγώνες γύρω από τώρα με λ από την αγορά. Επιστρέφει λίστα για τη σελίδα."""
    by = {}
    for c in cands["with_odds"]:
        if c["sport"] != "football" or c.get("p_market") is None:
            continue
        if c["market"] == "1X2":
            by.setdefault(c["match_id"], {})[c["selection"]] = c["p_market"]
        elif c["market"] == "OU" and c["selection"] == "OVER" and c["line"] == 2.5:
            by.setdefault(c["match_id"], {})["OV"] = c["p_market"]
    lg_espn = {lg["id"]: lg.get("espn") for lg in cfg["leagues"]}
    out = []
    for mid, ctx in cands["contexts"].items():
        m = ctx.m
        pr = by.get(mid) or {}
        if not all(k in pr for k in ("1", "X", "2")) or not str(mid).startswith("espn:") or not lg_espn.get(m["league"]):
            continue
        ko = parse_iso(m["kickoff"])
        if not (now - timedelta(hours=hours_after) <= ko <= now + timedelta(hours=hours_before)):
            continue
        lh, la = fit_lambdas(pr["1"], pr["X"], pr["2"], pr.get("OV"))
        out.append({"eid": mid[5:], "lg": lg_espn[m["league"]], "home": m["home"], "away": m["away"], "league": ctx.lg["name"],
                    "ko": m["kickoff"], "lh": round(lh, 3), "la": round(la, 3), "p": [round(pr["1"], 3), round(pr["X"], 3), round(pr["2"], 3)]})
    return sorted(out, key=lambda x: x["ko"])
