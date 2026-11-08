"""Στατιστικά ιστορικού: ποια δελτία πέρασαν, ποια όχι, και γιατί (για να εξελίσσουμε το bot).

Βασίζεται στα δελτία που αποθηκεύει το bot κάθε μέρα (ΕΝΑ δελτίο ανά κατηγορία) και στα αποτελέσματα που
εκκαθαρίζονται από την επόμενη εκτέλεση (`selector.settle_slips`). Παλιά «μονά» (single, safe1, fair_*-N)
αγνοούνται: ο χρήστης παίζει μόνο δελτία.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import timedelta
from zoneinfo import ZoneInfo

from .util import parse_iso

LISTS = ["recommended", "safe", "x10", "x30", "x100", "overs", "combo",
         "fair_corners", "fair_cards", "fair_throw_ins", "fair_players"]
NAMES = {"recommended": "⭐ Προτεινόμενο", "safe": "🛡️ Safe", "x10": "🎯 10+", "x30": "🔥 30+", "x100": "🎰 100+",
         "overs": "⚽ Over", "combo": "🔀 Συνδυαστικό", "fair_corners": "🚩 Κόρνερ", "fair_cards": "🟨 Κάρτες",
         "fair_throw_ins": "↔️ Πλάγια", "fair_players": "👤 Παίκτες"}
TAB_LIST = {"recommended": "recommended", "safe": "safe", "x10": "x10", "x30": "x30", "x100": "x100", "overs": "overs",
            "combo": "combo", "corners": "fair_corners", "cards": "fair_cards", "throw_ins": "fair_throw_ins",
            "players": "fair_players"}
_LEGACY = re.compile(r"-\d+$")


def real_slips(slips):
    """Μόνο δελτία της νέας μορφής (ένα ανά κατηγορία ανά μέρα)."""
    return [s for s in slips if s.get("list_name") in LISTS and not _LEGACY.search(s["slip_id"])]


def _day(sl, tz):
    return parse_iso(sl["created_at"]).astimezone(tz).date()


def _fair(lid):
    return lid.startswith("fair_")


def summary_by_list(slips):
    """Ανά κατηγορία: δελτία, πέρασαν, δεν πέρασαν, ανοιχτά, ποσοστό, επιτυχία επιλογών, μέση απόδοση/πιθανότητα, Κ/Ζ."""
    out = {}
    for lid in LISTS:
        ss = [s for s in slips if s["list_name"] == lid]
        won = [s for s in ss if s["status"] == "won"]
        lost = [s for s in ss if s["status"] == "lost"]
        void = [s for s in ss if s["status"] == "void"]
        opn = [s for s in ss if s["status"] == "open"]
        settled = won + lost
        legs = [l for s in ss for l in s["legs"] if l.get("result") in ("won", "lost")]
        pl = None if _fair(lid) else sum(s["payout"] - s["stake"] for s in settled)
        out[lid] = {"n": len(ss), "won": len(won), "lost": len(lost), "void": len(void), "open": len(opn),
                    "pass": (len(won) / len(settled)) if settled else None,
                    "leg_hit": (sum(1 for l in legs if l["result"] == "won") / len(legs)) if legs else None,
                    "legs": len(legs),
                    "avg_odds": (sum(s["total_odds"] for s in ss) / len(ss)) if ss else None,
                    "avg_p": (sum(s["model_prob"] for s in settled) / len(settled)) if settled else None,
                    "pl": pl}
    return out


def day_grid(slips, tz, today, days=14):
    """{ημέρα: {κατηγορία: won|lost|void|open}} για τις τελευταίες `days` μέρες (χωρίς σήμερα)."""
    grid = defaultdict(dict)
    for s in slips:
        d = _day(s, tz)
        if today - timedelta(days=days) <= d < today:
            grid[d][s["list_name"]] = s["status"]
    return dict(sorted(grid.items(), reverse=True))


def leg_stats(slips):
    """Επιτυχία ΔΙΑΚΡΙΤΩΝ επιλογών (η ίδια επιλογή σε πολλά δελτία μετράει μία φορά) ανά αγορά, λίγκα, πιθανότητα."""
    seen, legs = set(), []
    for s in slips:
        for l in s["legs"]:
            if l.get("result") not in ("won", "lost"):
                continue
            k = (l["match_id"], l["market"], l["selection"], l.get("line"))
            if k in seen:
                continue
            seen.add(k)
            legs.append(l)

    def agg(keyf, minn=3):
        g = defaultdict(list)
        for l in legs:
            g[keyf(l)].append(l)
        rows = []
        for k, v in g.items():
            if len(v) >= minn:
                rows.append({"key": k, "n": len(v), "won": sum(1 for l in v if l["result"] == "won"),
                             "hit": sum(1 for l in v if l["result"] == "won") / len(v),
                             "p": (sum(l.get("p") or 0 for l in v) / len(v)) if any(l.get("p") for l in v) else None})
        return sorted(rows, key=lambda r: -r["n"])

    def mk(l):
        ln = f" {l['line']:g}" if l.get("line") is not None else ""
        return f"{l['market']} · {l['selection']}{ln}"

    def bucket(l):
        p = l.get("p")
        if p is None:
            return "—"
        for lo, hi in ((0, .5), (.5, .6), (.6, .7), (.7, .8), (.8, 1.01)):
            if lo <= p < hi:
                return f"{lo:.0%}–{min(hi, 1):.0%}"
        return "—"

    return {"n": len(legs), "by_market": agg(mk), "by_league": agg(lambda l: l.get("league_name") or l.get("league"), 5),
            "by_sport": agg(lambda l: {"football": "Ποδόσφαιρο", "basketball": "Μπάσκετ"}.get(l.get("sport"), l.get("sport") or "—"), 1), "by_p": sorted(agg(bucket, 5), key=lambda r: r["key"])}


def build(db, cfg, now):
    """Όλα τα στατιστικά + «χθες» ανά κατηγορία + σκορ αγώνων, έτοιμα για την αναφορά."""
    tz = ZoneInfo(cfg["timezone"])
    today = now.astimezone(tz).date()
    slips = real_slips(db.slips())
    scores = {}
    for s in slips:
        for l in s["legs"]:
            if l["match_id"] not in scores:
                m = db.get_match(l["match_id"])
                scores[l["match_id"]] = ((m["home_score"], m["away_score"], m["status"]) if m else None)
    yesterday = {}
    for lid in LISTS:
        prev = [s for s in slips if s["list_name"] == lid and _day(s, tz) < today]
        if prev:
            last_day = max(_day(s, tz) for s in prev)
            cand = [s for s in prev if _day(s, tz) == last_day]
            yesterday[lid] = dict(max(cand, key=lambda s: s["created_at"]), day=last_day)
    todays = {s["list_name"]: s for s in slips if _day(s, tz) == today}
    return {"yesterday": yesterday, "scores": scores, "summary": summary_by_list(slips),
            "grid": day_grid(slips, tz, today), "legs": leg_stats(slips), "today": today, "n_slips": len(slips), "today_slips": todays,
            "recent": [s for s in sorted(slips, key=lambda s: s["created_at"], reverse=True) if _day(s, tz) < today][:60]}
