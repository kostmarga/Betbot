"""Paper trading: ταμείο 20€/εβδομάδα για ΚΑΘΕ κατηγορία × ΚΑΘΕ επίπεδο ρίσκου.

Σκοπός: να δούμε με στοιχεία ποιοι συνδυασμοί αξίζουν, πριν παιχτεί πραγματικό χρήμα. Τίποτα εδώ δεν είναι
πραγματικό στοίχημα. Υποθέτουμε ότι κάθε μέρα «παίχτηκε» το δελτίο κάθε ταμείου με σταθερό ποσό, μέχρι να
εξαντληθούν τα 20€ της εβδομάδας (Δευτέρα–Κυριακή, ώρα Ελλάδας).

Επίπεδα (config `tiers`): strong (ψηλότερη πιθανότητα ανά σκέλος, χαμηλότερη απόδοση), balanced (τα κανονικά
δελτία), bold (χαμηλότερη πιθανότητα, ψηλότερη απόδοση). Τα δελτία των strong/bold αποθηκεύονται με
κατάληξη ~s / ~b στο list_name.

Κρίση: ΜΟΝΟ όταν έχουν κριθεί `paper.min_settled` δελτία. Τότε, με bootstrap στο ROI:
  κάτω όριο > 0  -> «αξίζει» · άνω όριο < 0 -> «να αφαιρεθεί» · αλλιώς «αναποφάσιστο».
Οι κατηγορίες χωρίς απόδοση πρακτορείου (fair_*) ΔΕΝ μπαίνουν: η «απόδοσή» τους είναι υποθετική.
"""
from __future__ import annotations

import random
from datetime import timedelta
from zoneinfo import ZoneInfo

from .util import parse_iso

TIERS = ("strong", "balanced", "bold")
SUFFIX = {"strong": "~s", "balanced": "", "bold": "~b"}
TIER_NAME = {"strong": "🟢 Δυνατό", "balanced": "🟡 Ισορροπημένο", "bold": "🟠 Τολμηρό"}
CATS = ("recommended", "safe", "x10", "x30", "x100", "overs", "combo", "corners", "cards")
CAT_NAME = {"recommended": "⭐ Προτεινόμενο", "safe": "🛡️ Safe", "x10": "🎯 10+", "x30": "🔥 30+", "x100": "🎰 100+",
            "overs": "⚽ Over", "combo": "🔀 Συνδυαστικό", "corners": "🚩 Κόρνερ", "cards": "🟨 Κάρτες"}
LOTTERY = ("x30", "x100")


def _stake(cat, pc, cfg) -> float:
    return float(cfg["bankroll"]["lottery_stake"]) if cat in LOTTERY else float(pc["unit"])


def _boot(profits, n=1500, seed=11):
    rng = random.Random(seed)
    m = len(profits)
    means = sorted(sum(profits[rng.randrange(m)] for _ in range(m)) / m for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n)]


def _verdict(settled, roi_ci, need):
    if settled < need:
        return "wait", f"⏳ {settled}/{need}"
    if roi_ci is None:
        return "wait", f"⏳ {settled}/{need}"
    lo, hi = roi_ci
    if lo > 0:
        return "good", "✅ αξίζει"
    if hi < 0:
        return "bad", "❌ να αφαιρεθεί"
    return "mid", "🟡 αναποφάσιστο"


def build(db, cfg, now) -> dict:
    pc = cfg.get("paper") or {}
    weekly, need = float(pc.get("weekly", 20)), int(pc.get("min_settled", 30))
    tz = ZoneInfo(cfg["timezone"])
    loc = now.astimezone(tz)
    monday = (loc - timedelta(days=loc.weekday())).date()
    by = {}
    for sl in db.slips():
        ln = sl.get("list_name") or ""
        tier, cat = "balanced", ln
        for t, suf in SUFFIX.items():
            if suf and ln.endswith(suf):
                tier, cat = t, ln[:-len(suf)]
        if cat in CATS:
            by.setdefault((cat, tier), []).append(sl)
    rows = []
    for cat in CATS:
        for tier in TIERS:
            slips = sorted(by.get((cat, tier), []), key=lambda s: s["created_at"])
            st = _stake(cat, pc, cfg)
            spent_w, week_spent = {}, {}
            bets = []
            for sl in slips:
                d = parse_iso(sl["created_at"]).astimezone(tz).date()
                wk = d - timedelta(days=d.weekday())
                if spent_w.get(wk, 0.0) + st > weekly + 1e-9:
                    continue                                   # το ταμείο της εβδομάδας εξαντλήθηκε
                spent_w[wk] = spent_w.get(wk, 0.0) + st
                profit = (st * sl["total_odds"] - st) if sl["status"] == "won" else (-st if sl["status"] == "lost" else (0.0 if sl["status"] == "void" else None))
                bets.append({"day": d, "wk": wk, "stake": st, "profit": profit, "status": sl["status"], "odds": sl["total_odds"], "p": sl["model_prob"]})
            settled = [b for b in bets if b["profit"] is not None and b["status"] != "void"]
            won = sum(1 for b in settled if b["status"] == "won")
            staked = sum(b["stake"] for b in settled)
            profit = sum(b["profit"] for b in settled)
            roi = (profit / staked) if staked else None
            ci = _boot([b["profit"] / b["stake"] for b in settled]) if len(settled) >= need else None
            vkey, vtxt = _verdict(len(settled), ci, need)
            wk_bets = [b for b in bets if b["wk"] == monday]
            wk_open = sum(b["stake"] for b in wk_bets if b["profit"] is None)
            wk_pl = sum(b["profit"] for b in wk_bets if b["profit"] is not None)
            cum, series = 0.0, []
            for b in sorted((b for b in bets if b["profit"] is not None), key=lambda b: b["day"]):
                cum += b["profit"]
                series.append([b["day"].isoformat(), round(cum, 2)])
            weeks = {}
            for b in bets:
                if b["profit"] is not None:
                    weeks[b["wk"]] = weeks.get(b["wk"], 0.0) + b["profit"]
            # Στόχος «5 στις 7»: σε πόσες μέρες της εβδομάδας πέρασε το δελτίο
            wk_pass = sum(1 for b in wk_bets if b["status"] == "won")
            wk_fail = sum(1 for b in wk_bets if b["status"] == "lost")
            done_weeks = {}
            for b in bets:
                if b["wk"] < monday and b["status"] in ("won", "lost"):
                    w = done_weeks.setdefault(b["wk"], [0, 0])
                    w[0] += b["status"] == "won"
                    w[1] += 1
            avg_days = (sum(w[0] / w[1] * 7 for w in done_weeks.values()) / len(done_weeks)) if done_weeks else None
            rows.append({"cat": cat, "tier": tier, "n": len(bets), "settled": len(settled), "won": won,
                         "lost": len(settled) - won, "open": len(bets) - len([b for b in bets if b["profit"] is not None]),
                         "hit": (won / len(settled)) if settled else None, "staked": staked, "profit": profit, "roi": roi,
                         "ci": ci, "verdict": vkey, "verdict_text": vtxt, "avg_odds": (sum(b["odds"] for b in settled) / len(settled)) if settled else None,
                         "avg_p": (sum(b["p"] for b in settled) / len(settled)) if settled else None,
                         "wk_bets": len(wk_bets), "wk_spent": sum(b["stake"] for b in wk_bets), "wk_open": wk_open, "wk_pl": wk_pl,
                         "series": series, "wk_pass": wk_pass, "wk_fail": wk_fail, "avg_days": avg_days, "wk_left": max(0.0, weekly - sum(b["stake"] for b in wk_bets)), "weeks": dict(sorted(weeks.items())[-6:])})
    return {"rows": rows, "weekly": weekly, "need": need, "monday": monday}
