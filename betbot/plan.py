"""Καθημερινό πλάνο: ΤΙ να παίξεις σήμερα και ΠΟΣΑ ευρώ ακριβώς + κάρτα «Στόχοι».

Κανόνες (από το `bankroll` του config.yaml):
  - εβδομαδιαίο ταμείο (weekly), μονάδα (unit), το πολύ `max_bets_per_day` στοιχήματα τη μέρα,
  - stop όταν η ΕΚΚΑΘΑΡΙΣΜΕΝΗ ζημιά της εβδομάδας φτάσει weekly − stop_at,
  - ποτέ περισσότερα από weekly ευρώ «σε κίνδυνο ή χαμένα» την ίδια εβδομάδα,
  - λαχείο (x30) lottery_stake μία φορά τη βδομάδα, Σάββατο ή Κυριακή, από το ίδιο ταμείο.

Το πλάνο διαβάζει τα δελτία που ΚΛΕΙΔΩΣΕ το bot στην πρώτη εκτέλεση της ημέρας (recommended, single, x30),
ώστε να μην αλλάζουν το απόγευμα. Η εβδομαδιαία λογιστική ΥΠΟΘΕΤΕΙ ότι έπαιξες το πλάνο κάθε μέρα.
Δεν είναι συμβουλή επένδυσης: το αναμενόμενο αποτέλεσμα είναι ζημιά (βλ. docs/backtest.md).
"""
from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

from .util import parse_iso

PLAN_LISTS = ("recommended", "single", "safe", "x30")     # για τη λογιστική της εβδομάδας («single» = παλιά δελτία)
TODAY_LISTS = ("recommended", "safe")                      # τα δελτία (όχι μονά) που προτείνονται καθημερινά
SRC = {"espn": "ESPN", "espn_max": "ESPN", "fdco": "μέσος όρος", "fdco_max": "καλύτερη τιμή",
       "oddsapi": "μέσος όρος", "oddsapi_max": "καλύτερη τιμή"}


def _stake_eur(list_name, br) -> float:
    return float(br["lottery_stake"]) if list_name == "x30" else float(br["unit"])


def _slip_money(sl, br):
    """(stake_eur, profit_eur or None αν ανοιχτό) για δελτίο πλάνου. Το DB κρατά payout σε μονάδες 1."""
    st = _stake_eur(sl.get("list_name"), br)
    if sl["status"] == "won":
        return st, st * sl["total_odds"] - st
    if sl["status"] == "lost":
        return st, -st
    if sl["status"] == "void":
        return st, 0.0
    return st, None


def week_state(db, cfg, now):
    """Λογιστική της εβδομάδας ΠΡΙΝ από σήμερα (τα σημερινά δελτία είναι η πρόταση, όχι ιστορικό)."""
    br = cfg["bankroll"]
    tz = ZoneInfo(cfg["timezone"])
    loc = now.astimezone(tz)
    monday = (loc - timedelta(days=loc.weekday())).date()
    today = loc.date()
    settled_loss = open_stake = 0.0
    lottery_played = False
    for sl in db.slips():
        if sl.get("list_name") not in PLAN_LISTS:
            continue
        d = parse_iso(sl["created_at"]).astimezone(tz).date()
        if not (monday <= d < today):
            continue
        if sl["list_name"] == "x30":
            if d.weekday() < 5:        # το λαχείο προτείνεται μόνο Σάββατο/Κυριακή· τις άλλες μέρες δεν μετράει
                continue
            lottery_played = True
        st, profit = _slip_money(sl, br)
        if profit is None:
            open_stake += st
        else:
            settled_loss -= profit          # κέρδος -> μειώνει τη ζημιά
    settled_loss = max(0.0, settled_loss)
    weekly = float(br["weekly"])
    return {"weekday": loc.weekday(), "today": today, "monday": monday,
            "settled_loss": settled_loss, "open_stake": open_stake,
            "remaining": max(0.0, weekly - settled_loss - open_stake),
            "loss_limit": weekly - float(br["stop_at"]),
            "stop": settled_loss >= weekly - float(br["stop_at"]),
            "lottery_played": lottery_played}


def build_plan(db, cfg, now) -> dict:
    br = cfg["bankroll"]
    tz = ZoneInfo(cfg["timezone"])
    ws = week_state(db, cfg, now)
    todays = {s["list_name"]: s for s in db.slips()
              if s["list_name"] in PLAN_LISTS and parse_iso(s["created_at"]).astimezone(tz).date() == ws["today"]}
    unit, lot = float(br["unit"]), float(br["lottery_stake"])
    plan = {"week": ws, "items": [], "notes": [], "total": 0.0}
    if ws["stop"]:
        plan["notes"].append(f"🛑 Η ζημιά της εβδομάδας έφτασε το όριο ({ws['settled_loss']:.2f}€ από {ws['loss_limit']:.0f}€). "
                             "Σήμερα ΔΕΝ παίζεις τίποτα. Τη Δευτέρα ξεκινά νέα εβδομάδα.")
        return plan
    reserve = 0.0 if ws["lottery_played"] else lot       # κρατάμε το ποσό του λαχείου
    avail = max(0.0, ws["remaining"] - reserve)
    n_max = int(br["max_bets_per_day"])
    regular = [todays[k] for k in TODAY_LISTS if k in todays][:n_max]
    for sl in regular:
        stake = min(unit, avail)
        if stake < 1.0:
            plan["notes"].append("Το εβδομαδιαίο ποσό εξαντλήθηκε (ή δεσμεύεται για τα ανοιχτά στοιχήματα)· δεν παίζεις άλλο σήμερα.")
            break
        avail -= stake
        plan["items"].append(_item(sl, stake, tz))
    if not regular:
        plan["notes"].append("Σήμερα δεν βρέθηκε επιλογή που να περνά τους κανόνες. Η σωστή απόφαση είναι να μην παίξεις τίποτα.")
    # λαχείο: Σάββατο/Κυριακή, μία φορά τη βδομάδα
    if "x30" in todays and not ws["lottery_played"] and ws["weekday"] >= 5 and ws["remaining"] >= lot:
        plan["items"].append(_item(todays["x30"], lot, tz, lottery=True))
    elif "x30" in todays and not ws["lottery_played"]:
        plan["notes"].append(f"Λαχείο ({lot:.2f}€, μία φορά τη βδομάδα): το προτείνουμε Σάββατο ή Κυριακή.")
    plan["total"] = sum(i["stake"] for i in plan["items"])
    return plan


def _item(sl, stake, tz, lottery=False):
    return {"title": "🔥 Λαχείο (για πλάκα)" if lottery else ("⭐ Δελτίο της ημέρας" if sl["list_name"] == "recommended" else "🛡️ Safe δελτίο"),
            "list": sl["list_name"], "stake": stake, "total_odds": sl["total_odds"], "p_win": sl["model_prob"],
            "ret": stake * sl["total_odds"], "ev": sl["model_prob"] * sl["total_odds"] - 1,
            "legs": sl["legs"], "lottery": lottery}


# ---------------------------------------------------------------- στόχοι
def goals(db, cfg, now, clv) -> dict:
    """Πρόοδος προς τους στόχους (συμφωνήθηκαν 06/11/2026)."""
    tz = ZoneInfo(cfg["timezone"])
    slips = db.slips()
    first = min((parse_iso(s["created_at"]) for s in slips), default=None)
    weeks = ((now - first).days / 7) if first else 0.0
    rec = [s for s in slips if s.get("list_name") == "recommended" and s["status"] in ("won", "lost")]
    rec_hit = (sum(1 for s in rec if s["status"] == "won") / len(rec)) if rec else None
    ws = week_state(db, cfg, now)
    return {"weeks": weeks, "n_clv": (clv or {}).get("n", 0), "clv_mean": (clv or {}).get("mean"),
            "clv_pos": (clv or {}).get("pos"), "rec_n": len(rec), "rec_hit": rec_hit, "week": ws,
            "targets": {"clv_n": 125, "clv_mean": 0.01, "weeks": 4, "rec_days": 20, "rec_hit": (0.55, 0.60)}}
