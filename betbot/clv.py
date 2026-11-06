"""CLV (closing line value): παίρνουμε καλύτερη τιμή από αυτή που έχει η αγορά λίγο πριν τον αγώνα;

Είναι ο πιο γρήγορος δείκτης πραγματικού πλεονεκτήματος: αν μακροπρόθεσμα η τιμή που προτείνουμε είναι
ΥΨΗΛΟΤΕΡΗ από την τελευταία τιμή πριν το σφύριγμα (θετικό CLV), τότε βρίσκουμε αξία. Χρειάζεται μερικές
εκατοντάδες επιλογές για να έχει νόημα, πολύ λιγότερες από όσες θέλει το ROI.

Κλείσιμο = η ΥΨΗΛΟΤΕΡΗ τιμή (ανάμεσα στις πηγές) από την τελευταία λήψη πριν το ματς. Δεν έχουμε ακριβώς
την τιμή του σφυρίγματος (το bot τρέχει λίγες φορές τη μέρα), άρα είναι προσέγγιση.
"""
from __future__ import annotations

from collections import defaultdict

from .util import parse_iso


def clv_summary(db, now) -> dict:
    """{'n':…, 'mean':…, 'pos':…, 'by_list': {list: (n, mean)}} για επιλογές με απόδοση (όχι «δίκαιες»)."""
    vals, by_list = [], defaultdict(list)
    hist_cache = {}
    seen = set()      # η ίδια επιλογή σε πολλές λίστες μετράει ΜΙΑ φορά (η πρώτη πρόταση)
    for sl in db.slips():
        if str(sl.get("list_name") or "").startswith("fair_"):
            continue
        for leg in sl["legs"]:
            m = db.get_match(leg["match_id"])
            if not m or not leg.get("odds"):
                continue
            key = (leg["match_id"], leg["market"], leg["selection"], leg.get("line"))
            if key in seen:
                continue
            ko = parse_iso(m["kickoff"])
            if ko > now:
                continue
            h = hist_cache.get(leg["match_id"])
            if h is None:
                h = hist_cache[leg["match_id"]] = db.odds_history_for(leg["match_id"])
            last = {}
            for r in h:
                if (r["market"], r["selection"], r["line"]) != (leg["market"], leg["selection"], leg.get("line")):
                    continue
                if parse_iso(r["fetched_at"]) > ko:
                    continue
                last[r["source"]] = r["price"]       # ταξινομημένα κατά fetched_at -> κρατάμε την τελευταία
            if not last:
                continue
            seen.add(key)
            closing = max(last.values())
            v = leg["odds"] / closing - 1
            vals.append(v)
            by_list[sl.get("list_name")].append(v)
    if not vals:
        return {"n": 0}
    return {"n": len(vals), "mean": sum(vals) / len(vals), "pos": sum(1 for v in vals if v > 0.0005) / len(vals),
            "by_list": {k: (len(v), sum(v) / len(v)) for k, v in by_list.items()}}
