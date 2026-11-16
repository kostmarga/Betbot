"""Πόντοι παικτών NBA (νέα κατηγορία «🏀 Πόντοι NBA», μόνο παπέρ τρέιντινγκ).

Πηγές: πρόβολες (props) από Pinnacle + Stoiximan μέσω OddsPapi (πίνακας `props`), τραυματισμοί ESPN (`ctx.absent`), boxscore ESPN (`nba_box`) για κρίση.

ΠΙΘΑΝΟΤΗΤΑ (το πιο ευαίσθητο σημείο — δεν έχει backtest):
  • Στην ΚΥΡΙΑ γραμμή του Pinnacle (≈50/50) παίρνουμε την πιθανότητα Over από το devig των δύο τιμών.
  • Για ΑΛΛΕΣ γραμμές του ίδιου παίκτη (Stoiximan) υποθέτουμε κανονική κατανομή με μέση τιμή που ταιριάζει στην κύρια γραμμή και τυπική απόκλιση
    σ = max(7.0, 0.42·γραμμή) (backtest 17/11/2026 σε 18.022 παρατηρήσεις: το αρχικό σ=max(3.5,0.30·γραμμή) υπερτιμούσε τα Over κατά ~10 μονάδες· βλ. docs/nba_props_backtest.txt)· η πιθανότητα συστέλλεται προς το 50% (`shrink`) γιατί είναι εκτίμηση χωρίς έλεγχο.
  • Χωρίς γραμμή Pinnacle για τον παίκτη -> δεν υπάρχει επιλογή (δεν εμπιστευόμαστε το Stoiximan μόνο του).
"""
from __future__ import annotations

import math
from statistics import NormalDist

ND = NormalDist()


def devig2(over: float, under: float) -> float:
    """Πιθανότητα Over από δύο τιμές (αναλογικό devig)."""
    a, b = 1 / over, 1 / under
    return a / (a + b)


def p_over_at(line: float, base_line: float, p_base: float, k_sd: float = 0.42, min_sd: float = 7.0) -> float:
    """Πιθανότητα Over `line`, δοσμένης της πιθανότητας Over στην κύρια γραμμή (κανονική προσέγγιση)."""
    if abs(line - base_line) < 1e-9:
        return p_base
    sd = max(min_sd, k_sd * base_line)
    p_base = min(0.97, max(0.03, p_base))
    mu = base_line - sd * ND.inv_cdf(1 - p_base)
    return 1 - ND.cdf((line - mu) / sd)


def norm_name(n: str) -> str:
    return " ".join((n or "").lower().replace(".", "").replace("'", "").split())


def build(ctx, db, cfg) -> list[dict]:
    """Επιλογές «Πόντοι NBA» για έναν αγώνα (ίδια μορφή με τα candidates του selector). Κενό αν δεν υπάρχουν πρόβολες."""
    pc = (cfg.get("lists") or {}).get("nba_pts")
    if not pc or ctx.m["league"] not in (pc.get("leagues") or ["NBA"]):
        return []
    rows = db.props_for(ctx.m["match_id"])
    if not rows:
        return []
    out_of = {norm_name(r["player"]): r["status"] for t in ctx.absent.values() for r in t}      # δηλωμένοι ως missing/doubtful
    key_out = {norm_name(p): st for t in (ctx.home, ctx.away) for p, st in ctx.key_absences(t)}
    pin = {}
    for r in rows:
        if r["source"] == "pinnacle" and r["active"]:
            pin.setdefault(r["player"], []).append(r)
    shrink = float(pc.get("shrink", 0.90))
    cands = []
    for pl, prs in pin.items():
        if norm_name(pl) in out_of or norm_name(pl) in key_out:
            continue
        base = min(prs, key=lambda r: abs(r["over_price"] - r["under_price"]))         # κύρια γραμμή = πιο ίσες τιμές
        p_main = devig2(base["over_price"], base["under_price"])
        lines = [(base["line"], base["over_price"], base["under_price"], "pinnacle", True)]
        for r in rows:
            if r["source"] == "stoiximan" and r["player"] == pl:
                lines.append((r["line"], r["over_price"], r["under_price"], "stoiximan", bool(r["active"])))
        seen = set()
        for ln, o, u, src, act in lines:
            for sel, price in (("OVER", o), ("UNDER", u)):
                if (ln, sel, src) in seen:
                    continue
                seen.add((ln, sel, src))
                if not (pc.get("min_odds", 1.2) <= price <= pc.get("max_odds", 1.9)):
                    continue
                po = p_over_at(ln, base["line"], p_main)
                p_raw = po if sel == "OVER" else 1 - po
                p = p_raw if abs(ln - base["line"]) < 1e-9 else 0.5 + (p_raw - 0.5) * shrink
                if p < pc.get("min_leg_prob", 0.58):
                    continue
                edge = p * price - 1
                if edge < pc.get("min_edge", -0.06):
                    continue
                why = [f"Βάση: Pinnacle {pl} Over/Under {base['line']:g} → Over {p_main * 100:.0f}%"
                       + ("" if abs(ln - base["line"]) < 1e-9 else f" · γραμμή {ln:g} εκτιμάται με κανονική κατανομή (σ≈{max(7.0, 0.42 * base['line']):.1f}), συστολή {int((1 - shrink) * 100)}% προς 50%"),
                       "Τραυματισμοί ESPN: ο παίκτης δεν είναι δηλωμένος ως απών/αμφίβολος",
                       f"Τιμή {src.capitalize()}" + ("" if act else " — ΔΕΝ δηλώνεται ενεργή τώρα· έλεγξε την απόδοση πριν παίξεις"),
                       "Κατηγορία πειραματική: τα props έχουν μεγάλο περιθώριο και δεν υπάρχει backtest — μόνο εικονικά χρήματα"]
                cands.append({
                    "match_id": ctx.m["match_id"], "league": ctx.m["league"], "league_name": ctx.lg["name"], "sport": ctx.sport,
                    "kickoff": ctx.m["kickoff"], "home": ctx.home, "away": ctx.away,
                    "market": "PTS", "selection": f"{sel}|{pl}", "line": ln, "family": "nba_pts",
                    "label": f"{pl} {'Over' if sel == 'OVER' else 'Under'} {ln:g} πόντοι",
                    "odds": price, "p_model": p, "p_market": p_raw if abs(ln - base["line"]) < 1e-9 else None, "p": p, "p_raw": p_raw, "cal": 0.0,
                    "min_play": round(1 / p, 2), "edge": edge, "best_source": src, "fair_odds": 1 / p, "move": None, "extra": {"player": pl},
                    "source": src, "exp": ctx.exp, "form_home": ctx.form_home, "form_away": ctx.form_away, "h2h": ctx.h2h,
                    "warnings": [], "blocked": set(), "why": why, "verdict": None,
                })
    return cands


def settle(leg, match, db):
    """won | lost | void | open για σκέλος αγοράς PTS (selection «OVER|Όνομα»)."""
    sel, pl = leg["selection"].split("|", 1)
    rows = db.box_for(match["match_id"])
    if not rows:
        return "open"                      # το boxscore δεν έχει έρθει ακόμα
    r = next((x for x in rows if norm_name(x["player"]) == norm_name(pl)), None)
    if r is None or not r["minutes"]:
        return "void"                      # δεν έπαιξε -> άκυρο
    L = float(leg["line"])
    if r["points"] == L:
        return "void"
    return "won" if (r["points"] > L) == (sel == "OVER") else "lost"
