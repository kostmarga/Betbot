"""Κινήσεις αποδόσεων: τι πέφτει και τι ανεβαίνει από την πρώτη τιμή μέχρι τώρα.

Πώς διαβάζεται:
  • Απόδοση που ΠΕΦΤΕΙ (π.χ. 2.10 → 1.85) = μπαίνουν λεφτά σε αυτή την επιλογή ή η αγορά
    έμαθε κάτι (τραυματισμός αντιπάλου, ενδεκάδα). Συνήθως «έξυπνα» λεφτά.
  • Απόδοση που ΑΝΕΒΑΙΝΕΙ = η αγορά πάει αντίθετα. Αν είναι δική μας επιλογή, προσοχή.

Πηγές αρχικής τιμής:
  1. Sofascore: δίνει μόνο του την αρχική (initialFractionalValue)
  2. Όλες οι άλλες: η πρώτη τιμή που είδαμε εμείς (odds.open_price / odds_history)
     → γι' αυτό το bot τρέχει 2 φορές τη μέρα: όσο περισσότερες λήψεις, τόσο καλύτερη εικόνα.
"""
from __future__ import annotations

from collections import defaultdict


def moves_for_match(db, match_id) -> dict:
    """{(market, selection, line): {"open":…, "now":…, "pct":…, "n_sources":…}} – μέσος όρος πηγών."""
    agg = defaultdict(list)
    for r in db.odds_for(match_id):
        if r["source"].endswith("_max"):      # οι «καλύτερες τιμές» δεν μετράνε στη μέση κίνηση
            continue
        op, cur = r.get("open_price") or r["price"], r["price"]
        if op and cur:
            agg[(r["market"], r["selection"], r["line"])].append((op, cur))
    out = {}
    for k, vals in agg.items():
        op = sum(v[0] for v in vals) / len(vals)
        cur = sum(v[1] for v in vals) / len(vals)
        out[k] = {"open": op, "now": cur, "pct": (cur - op) / op, "n_sources": len(vals)}
    return out


def strength(pct: float) -> str:
    a = abs(pct)
    if a >= 0.15:
        return "πολύ δυνατή"
    if a >= 0.08:
        return "δυνατή"
    if a >= 0.04:
        return "μέτρια"
    return "μικρή"


def describe(pct: float) -> str:
    if pct <= -0.04:
        return f"πέφτει {abs(pct) * 100:.0f}% ({strength(pct)}) – μπαίνουν λεφτά εδώ"
    if pct >= 0.04:
        return f"ανεβαίνει {pct * 100:.0f}% ({strength(pct)}) – η αγορά πάει αντίθετα"
    return "σταθερή"


def biggest_moves(db, matches, leagues, min_abs=0.04, limit=25):
    """Λίστα με τις μεγαλύτερες κινήσεις της ημέρας (για την καρτέλα «Κινήσεις αποδόσεων»)."""
    rows = []
    for m in matches:
        for (mk, sel, line), mv in moves_for_match(db, m["match_id"]).items():
            if abs(mv["pct"]) >= min_abs and mv["now"] <= 15:
                rows.append({"match": m, "league_name": leagues.get(m["league"], {}).get("name", m["league"]),
                             "market": mk, "selection": sel, "line": line, **mv})
    rows.sort(key=lambda r: r["pct"])          # πρώτα οι μεγαλύτερες πτώσεις
    drops = [r for r in rows if r["pct"] < 0][:limit]
    rises = sorted([r for r in rows if r["pct"] > 0], key=lambda r: -r["pct"])[:limit]
    return drops, rises
