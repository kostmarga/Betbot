"""Υγεία αποτελεσμάτων: γράφονται εγκαίρως τα ✅/❌; (17/11/2026, μετά από καθυστέρηση ωρών σε δελτία επιπέδου)

Δύο ενδείξεις:
  1. ΤΩΡΑ: σκέλη δελτίων που έπρεπε να έχουν κριθεί (έναρξη + εκτιμώμενη διάρκεια + ανοχή) και ακόμα είναι «ανοιχτά», και σκέλη με αγώνα ήδη «finished» στη βάση
     που δεν έχουν κριθεί (δεν πρέπει ποτέ να υπάρχουν).
  2. ΙΣΤΟΡΙΚΟ: πόσα λεπτά μετά το (εκτιμώμενο) τέλος του αγώνα γράφτηκε το αποτέλεσμα (πεδίο `settled_at` στα σκέλη, από 17/11/2026 και μετά).
"""
from __future__ import annotations

import statistics
from datetime import timedelta

from .util import iso, parse_iso

END_MIN = {"football": 150, "basketball": 180, "nfl": 210}      # εκτίμηση διάρκειας αγώνα (λεπτά)
GRACE_MIN = 20                                                  # ανοχή πριν θεωρηθεί καθυστέρηση
LOOKBACK_DAYS = 14


def _end(leg):
    return parse_iso(leg["kickoff"]) + timedelta(minutes=END_MIN.get(leg.get("sport"), 150))


def results_health(db, now) -> dict:
    late, stuck, lat = [], [], []
    horizon = now - timedelta(days=LOOKBACK_DAYS)
    for sl in db.slips():
        for l in sl["legs"]:
            try:
                end = _end(l)
            except (KeyError, ValueError, TypeError):
                continue
            if end < horizon:
                continue
            res = l.get("result") or "open"
            m = db.get_match(l["match_id"]) if res == "open" else None
            if res == "open":
                if m and m["status"] in ("finished", "postponed"):
                    stuck.append((sl["slip_id"], l.get("label", "")[:40]))
                elif now > end + timedelta(minutes=GRACE_MIN):
                    late.append({"slip": sl["slip_id"], "label": (l.get("label") or "")[:40], "min": int((now - end).total_seconds() // 60)})
            elif l.get("settled_at"):
                lat.append(max(0.0, (parse_iso(l["settled_at"]) - end).total_seconds() / 60))
    out = {"late": sorted(late, key=lambda x: -x["min"]), "stuck": stuck, "n_lat": len(lat)}
    if lat:
        out |= {"avg": sum(lat) / len(lat), "med": statistics.median(lat), "max": max(lat),
                "within30": sum(1 for x in lat if x <= 30) / len(lat)}
    # σκέλη ΑΝΟΙΧΤΑ που ΔΕΝ είναι ακόμα αργά (απλά εκκρεμούν): μόνο για πληροφορία
    out["ok"] = not out["late"] and not out["stuck"]
    return out
