"""CLV (closing line value): παίρνουμε καλύτερη τιμή από αυτή που έχει η αγορά λίγο πριν τον αγώνα;

Είναι ο πιο γρήγορος δείκτης πραγματικού πλεονεκτήματος: αν μακροπρόθεσμα η τιμή που προτείνουμε είναι
ΥΨΗΛΟΤΕΡΗ από την τελευταία τιμή πριν το σφύριγμα (θετικό CLV), τότε βρίσκουμε αξία. Χρειάζεται μερικές
εκατοντάδες επιλογές για να έχει νόημα, πολύ λιγότερες από όσες θέλει το ROI.

ΑΝΑΘΕΩΡΗΣΗ 24/11/2026: ως κλείσιμο χρησιμοποιείται η τελευταία τιμή του Stoiximan (εκεί παίζεται το δελτίο)· αν δεν υπάρχει, η ΥΨΗΛΟΤΕΡΗ
των υπόλοιπων. Επιπλέον, `fair_mean`: αναμενόμενο κέρδος της τιμής μας έναντι της ΔΙΚΑΙΗΣ πιθανότητας κλεισίματος του Pinnacle (τιμή × p − 1) — ο
πιο αξιόπιστος δείκτης πλεονεκτήματος.

(παλιό) Κλείσιμο = η ΥΨΗΛΟΤΕΡΗ τιμή (ανάμεσα στις πηγές) από την τελευταία λήψη πριν το ματς. Δεν έχουμε ακριβώς
την τιμή του σφυρίγματος (το bot τρέχει λίγες φορές τη μέρα), άρα είναι προσέγγιση.
"""
from __future__ import annotations

from collections import defaultdict

from .util import parse_iso


def pinnacle_close_fair(hist, market, line, selection, ko):
    """Δίκαιη πιθανότητα (devig) από το ΤΕΛΕΥΤΑΙΟ πλήρες snapshot Pinnacle πριν το ματς, ή None."""
    from .selector import GROUPS
    need = GROUPS.get(market)
    if not need or selection not in need:
        return None
    snaps = defaultdict(dict)
    for r in hist:
        if r["source"] == "pinnacle" and r["market"] == market and r["line"] == line and parse_iso(r["fetched_at"]) <= ko:
            snaps[r["fetched_at"]][r["selection"]] = r["price"]
    full = [t for t, v in snaps.items() if all(x in v for x in need)]
    if not full:
        return None
    v = snaps[max(full)]
    return (1 / v[selection]) / sum(1 / v[x] for x in need)


def value_summary(db, now) -> dict:
    """Σκιώδες πείραμα «αναζήτηση αξίας» (list_name shadow_vscan): n, κριθέντα, ROI (1 μονάδα), μέσο edge κατά την καταγραφή, CLV έναντι Pinnacle."""
    rows, edges, clvs = [], [], []
    for sl in db.slips():
        if sl.get("list_name") != "shadow_vscan" or not sl["legs"]:
            continue
        leg = sl["legs"][0]
        m = db.get_match(leg["match_id"])
        if not m:
            continue
        ko = parse_iso(m["kickoff"])
        pm = leg.get("p_market") or sl.get("model_prob")
        edge = pm * leg["odds"] - 1 if pm and leg.get("odds") else None
        fair = None
        if ko <= now:
            fair = pinnacle_close_fair(db.odds_history_for(leg["match_id"]), leg["market"], leg.get("line"), leg["selection"], ko)
        clv = leg["odds"] * fair - 1 if fair else None
        rows.append({"lb": leg.get("label"), "m": f"{leg.get('home', '')} – {leg.get('away', '')}", "o": leg["odds"], "e": edge, "st": sl["status"], "clv": clv, "ko": m["kickoff"]})
        if edge is not None:
            edges.append(edge)
        if clv is not None:
            clvs.append(clv)
    if not rows:
        return {"n": 0}
    done = [r for r in rows if r["st"] in ("won", "lost")]
    pl = sum((r["o"] - 1) if r["st"] == "won" else -1 for r in done)
    return {"n": len(rows), "settled": len(done), "won": sum(1 for r in done if r["st"] == "won"),
            "roi": (pl / len(done)) if done else None, "pl": pl, "edge": (sum(edges) / len(edges)) if edges else None,
            "clv": (sum(clvs) / len(clvs)) if clvs else None, "clv_n": len(clvs), "clv_pos": (sum(1 for c in clvs if c > 0) / len(clvs)) if clvs else None,
            "rows": sorted(rows, key=lambda r: r["ko"], reverse=True)[:8]}


def clv_summary(db, now) -> dict:
    """{'n':…, 'mean':…, 'pos':…, 'by_list': {list: (n, mean)}} για επιλογές με απόδοση (όχι «δίκαιες»)."""
    vals, by_list, fair_vals = [], defaultdict(list), []
    hist_cache = {}
    seen = set()      # η ίδια επιλογή σε πολλές λίστες μετράει ΜΙΑ φορά (η πρώτη πρόταση)
    for sl in db.slips():
        if str(sl.get("list_name") or "").startswith(("fair_", "shadow_")):
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
            closing = last.get("stoiximan") or max(last.values())
            fp = pinnacle_close_fair(h, leg["market"], leg.get("line"), leg["selection"], ko)
            if fp:
                fair_vals.append(leg["odds"] * fp - 1)
            v = leg["odds"] / closing - 1
            vals.append(v)
            by_list[sl.get("list_name")].append(v)
    if not vals:
        return {"n": 0}
    return {"n": len(vals), "mean": sum(vals) / len(vals), "pos": sum(1 for v in vals if v > 0.0005) / len(vals),
            "fair_mean": (sum(fair_vals) / len(fair_vals)) if fair_vals else None, "fair_n": len(fair_vals),
            "by_list": {k: (len(v), sum(v) / len(v)) for k, v in by_list.items()}}
