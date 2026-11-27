"""BetBot – orchestrator.

Χρήση:
  python main.py              # πλήρης εκτέλεση (άντληση → μοντέλα → λίστες → σελίδα → email)
  python main.py --demo       # συνθετικά δεδομένα, χωρίς internet (δοκιμή)
  python main.py --no-fetch   # μόνο μοντέλα/λίστες από ό,τι υπάρχει ήδη στη βάση
  python main.py --no-email
  python main.py --only sofascore,espn_stats   # τρέχει μόνο αυτούς τους collectors
  python main.py --live       # μόνο η live σελίδα των δελτίων (docs/live.html) – ελαφριά
  python main.py --backtest   # έλεγχος των μοντέλων στο παρελθόν → docs/backtest.md (~10 λεπτά)
  python main.py --live --loop   # το ίδιο, κάθε 10 λεπτά, μέχρι να το κλείσεις (για τον υπολογιστή σου)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone

import yaml

from betbot import movement, report, selector
from betbot.collectors import ALL as COLLECTORS
from betbot.collectors.base import Context
from betbot.db import DB
from betbot.models import BasketballModel, CountModel, FootballModel, PlayerModel
from betbot.util import iso, log

SLIM_KEYS = ("match_id", "league", "league_name", "sport", "kickoff", "home", "away", "market",
             "selection", "line", "label", "odds", "p_model", "p_market", "q_sharp", "p", "p_raw", "p_base", "learn", "cal", "min_play", "verdict", "edge", "family", "best_source", "why", "form_home", "form_away", "warnings")


def load_cfg(path="config.yaml"):
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["team_aliases"] = {k.lower(): v for k, v in (cfg.get("team_aliases") or {}).items()}
    return cfg


def slim(c, odds=None):
    d = {k: c.get(k) for k in SLIM_KEYS}
    if odds is not None:
        d["odds"] = odds
    return d


def build_models(db, cfg, ctx, now, notes):
    models = {"basketball": {}, "counts": {}}
    try:
        models["football"] = FootballModel(cfg["models"]["football"], ctx.aliases).fit(db.matches(sport="football"), now)
        log.info("Μοντέλο ποδοσφαίρου: %d ομάδες", len(models["football"].teams))
    except Exception as e:
        notes.append(("μοντέλο ποδοσφαίρου", False, str(e)))
    for lg in ctx.leagues(sport="basketball") + ctx.leagues(sport="nfl"):
        if lg.get("greek_site") and not cfg["collectors"]["greek_site"].get("enabled"):
            continue          # ΕΚΟ Basket League: μόνο αν ρυθμιστεί το ελληνικό site
        try:
            models["basketball"][lg["id"]] = BasketballModel(cfg["models"].get(lg["sport"], cfg["models"]["basketball"]), ctx.aliases).fit(
                db.matches(league=lg["id"]), now)
        except Exception as e:
            notes.append((f"μοντέλο {lg['id']}", False, str(e)))
    since = iso(now - timedelta(days=cfg["models"]["counts"]["history_days"]))
    ts = db.team_stats(since=since)
    for metric in ("corners", "cards", "throw_ins"):
        try:
            models["counts"][metric] = CountModel(metric, cfg["models"]["counts"], ctx.aliases).fit(ts, now)
            log.info("Μοντέλο %s: %d αγώνες", metric, models["counts"][metric].n_rows)
        except Exception as e:
            notes.append((f"μοντέλο {metric}", False, str(e)))
    try:
        models["players"] = PlayerModel(cfg["models"]["players"], ctx.aliases).fit(db.player_stats(since=since), now)
    except Exception as e:
        notes.append(("μοντέλο παικτών", False, str(e)))
    return models


def day_usage(db, cfg, now) -> dict:
    """Για κάθε αγώνα της σημερινής «ημέρας στοιχημάτων»: σε πόσα δελτία ανά ΚΑΤΗΓΟΡΙΑ υπάρχει (match_id -> {κατηγορία: πλήθος}). Δεν μετράνε τα σκιώδη (shadow_).
    Κατηγορία = η βασική λίστα χωρίς επίπεδο/επιπλέον (recommended, safe, overs, x10, fair_corners ...)."""
    from zoneinfo import ZoneInfo
    from betbot.paper import split_list_name
    from betbot.util import slip_day, sport_day
    tz_ = ZoneInfo(cfg["timezone"])
    today = sport_day(now, tz_)
    use = {}
    for s in db.slips():
        ln = str(s.get("list_name") or "")
        if ln.startswith("shadow_") or slip_day(s, tz_) != today:
            continue
        cat = split_list_name(ln)[1]
        for mid in {l["match_id"] for l in s["legs"]}:
            use.setdefault(mid, {})[cat] = use.setdefault(mid, {}).get(cat, 0) + 1
    return use


def day_things(db, cfg, now, cat) -> set:
    """Τα «πράγματα» (αγώνας + οικογένεια αγοράς + επιλογή) που ήδη υπάρχουν σε δελτία ΑΛΛΩΝ κατηγοριών της σημερινής ημέρας στοιχημάτων.
    Αίτημα χρήστη 23/11/2026: ποτέ το ίδιο σκέλος σε 2 δελτία (αν χαθεί, χάνονται και τα δύο) — ακόμα και στην εφεδρική επαναχρησιμοποίηση αγώνα."""
    from zoneinfo import ZoneInfo
    from betbot.paper import split_list_name
    from betbot.util import slip_day, sport_day
    tz_ = ZoneInfo(cfg["timezone"])
    today = sport_day(now, tz_)
    out = set()
    for s in db.slips():
        ln = str(s.get("list_name") or "")
        if ln.startswith("shadow_") or slip_day(s, tz_) != today or split_list_name(ln)[1] == cat:
            continue
        for l in s["legs"]:
            out.add((l["match_id"], l.get("family") or l.get("market"), l.get("selection")))
    return out


def saturated_matches(db, cfg, now, cat=None, fallback=False) -> set:
    """Αγώνες που ΔΕΝ επιτρέπονται σε νέο δελτίο της κατηγορίας `cat`:
      • (αποκλειστικότητα κατηγοριών, `slip.exclusive_categories`) αγώνες που ήδη υπάρχουν σε δελτίο ΑΛΛΗΣ κατηγορίας — αν χαθεί ο αγώνας, να μη χάνονται δελτία
        σε πολλές κατηγορίες (αίτημα χρήστη 21–22/11/2026),
      • αγώνες που έχουν ήδη φτάσει το όριο δελτίων μέσα στην ΙΔΙΑ κατηγορία (`slip.max_slips_per_match`, προεπιλογή 2: επίπεδα/επιπλέον της ίδιας κατηγορίας)."""
    sl = cfg.get("slip") or {}
    cap = int(sl.get("max_slips_per_match", 2))
    excl = bool(sl.get("exclusive_categories", True)) and not fallback
    fb_cap = int(sl.get("fallback_max_slips_per_match", 4)) if fallback else 0      # στην εφεδρική λειτουργία: συνολικό όριο δελτίων ανά αγώνα (όλες οι κατηγορίες)
    out = set()
    for mid, cnt in day_usage(db, cfg, now).items():
        if cat is None:
            if cap > 0 and sum(cnt.values()) >= cap:
                out.add(mid)
            continue
        if cap > 0 and cnt.get(cat, 0) >= cap:
            out.add(mid)
        if excl and any(c != cat and n > 0 for c, n in cnt.items()):
            out.add(mid)
        if fb_cap > 0 and sum(cnt.values()) >= fb_cap:
            out.add(mid)
    return out


def save_lists(db, cfg, now, lists, suffix="", cands=None, cfg_t=None):
    """Καταγράφει κάθε λίστα «στα χαρτιά» (1 μονάδα) για το ιστορικό ανά λίστα.
    Με `cands`: όριο ΔΕΛΤΙΩΝ ΑΝΑ ΑΓΩΝΑ — αν ένα νέο δελτίο περιέχει αγώνα που ήδη υπάρχει στο μέγιστο πλήθος δελτίων της ημέρας, ξαναχτίζεται χωρίς
    τους κορεσμένους αγώνες (με τα ίδια όρια της κατηγορίας)· αν δεν υπάρχει τέτοιο δελτίο, δεν αποθηκεύεται κανένα."""
    from zoneinfo import ZoneInfo
    tz_ = ZoneInfo(cfg["timezone"])
    from betbot.util import sport_day
    day = sport_day(now, tz_).strftime("%Y-%m-%d")    # «ημέρα στοιχημάτων» (06:00–05:59 ώρα Ελλάδας): η ίδια παντού
    # Το πρωινό δελτίο κλειδώνει όλη μέρα· ό,τι φτιάχτηκε πριν τις 06:00 (νυχτερινή εκτέλεση) θεωρείται ξεπερασμένο.
    fresh_after = iso(datetime.strptime(day, "%Y-%m-%d").replace(hour=6, tzinfo=tz_))
    stake = 1.0
    created = iso(now)

    def locked(name):
        row = db.conn.execute("SELECT created_at FROM slips WHERE slip_id=?", (f"{day}#{name}",)).fetchone()
        return bool(row and row["created_at"] >= fresh_after)

    def pick(listkey, sl, cat):
        """Το δελτίο που τελικά αποθηκεύεται (αποκλειστικότητα κατηγοριών + όριο δελτίων ανά αγώνα)."""
        if not sl or cands is None:
            return sl
        sat = saturated_matches(db, cfg, now, cat)
        if not sat or not any(l["match_id"] in sat for l in sl["legs"]):
            return sl
        try:
            alt = (selector.build_lists(cands, cfg_t or cfg, exclude=sat).get(listkey) or {}).get("slip")
            if alt:
                return alt                        # δελτίο ΜΟΝΟ με αγώνες που δεν χρησιμοποιούν άλλες κατηγορίες
            if not (cfg.get("slip") or {}).get("exclusive_fallback", True):
                return None
            # ΕΦΕΔΡΙΚΑ (αίτημα χρήστη 22/11/2026): αν δεν υπάρχουν άλλοι αγώνες για την κατηγορία, επιτρέπεται να ξαναχρησιμοποιηθούν οι ΚΑΛΥΤΕΡΟΙ αγώνες
            # άλλων κατηγοριών (με τα ίδια όρια πιθανότητας), με συνολικό όριο δελτίων ανά αγώνα (`slip.fallback_max_slips_per_match`)
            sat2 = saturated_matches(db, cfg, now, cat, fallback=True)
            things = day_things(db, cfg, now, cat)           # το ίδιο σκέλος ΠΟΤΕ σε 2 δελτία: μόνο διαφορετικό «πράγμα» στον ίδιο αγώνα
            if not any(l["match_id"] in sat2 or selector.thing_key(l) in things for l in sl["legs"]):
                log.info("Εφεδρικά: η κατηγορία %s ξαναχρησιμοποιεί κορυφαίους αγώνες (δεν υπήρχαν άλλοι)", listkey)
                return sl
            alt2 = (selector.build_lists(cands, cfg_t or cfg, exclude=sat2, exclude_things=things).get(listkey) or {}).get("slip")
            if alt2:
                log.info("Εφεδρικά: η κατηγορία %s ξαναχρησιμοποιεί κορυφαίους αγώνες με ΔΙΑΦΟΡΕΤΙΚΕΣ επιλογές (δεν υπήρχαν άλλοι)", listkey)
            return alt2
        except Exception as e:
            log.warning("Όριο ανά αγώνα (%s): %s", listkey, e)
            return None

    def put(name, sl):
        name = name + suffix
        db.save_slip(f"{day}#{name}", created, name, sl["total_odds"], sl["p_win"], stake, [slim(l) for l in sl["legs"]],
                     keep_first=True, fresh_after=fresh_after)

    # ΣΕΙΡΑ ΠΡΟΤΕΡΑΙΟΤΗΤΑΣ: πρώτα το Safe (σκέλη ≥75%, τα πιο σίγουρα), μετά το Προτεινόμενο, Over κ.λπ.· τα λαχεία παίρνουν ό,τι αγώνες απομένουν
    for lid in ("safe", "recommended", "overs", "btts", "nba_pts", "x10", "x30", "x100", "combo"):
        lc_ = cfg["lists"].get(lid) or {}
        if not lc_.get("enabled", True):
            # ΚΛΕΙΣΤΗ λίστα (Συνδυαστικό από 17/11, Over/BTTS/λαχεία από 27/11/2026: χαμηλή πιθανότητα, αίτημα χρήστη): φτιάχνεται και κρίνεται στο
            # παρασκήνιο (list_name shadow_<λίστα>), ΔΕΝ εμφανίζεται ως πρόταση ούτε στο ημερολόγιο· έλεγχος με tools/shadow_check.py
            sl = (lists.get(lid) or {}).get("slip")
            if sl and lc_.get("shadow", False):
                db.save_slip(f"{day}#shadow_{lid}{suffix}", created, f"shadow_{lid}{suffix}", sl["total_odds"], sl["p_win"], stake,
                             [slim(l) for l in sl["legs"]], keep_first=True, fresh_after=fresh_after)
            continue
        sl = (lists.get(lid) or {}).get("slip")
        if not sl or locked(lid + suffix):
            continue
        sl = pick(lid, sl, lid)
        if sl:
            put(lid, sl)
    # Κατηγορίες χωρίς απόδοση πρακτορείου: η «απόδοση» του δελτίου είναι η ελάχιστη (δίκαιη) απόδοση «παίξ' το αν ≥»
    for fam in ("corners", "cards", "throw_ins", "players"):
        sl = (lists.get(fam) or {}).get("slip")
        if not sl:
            continue
        name0 = f"fair_{fam}" if sl.get("fair") else fam
        if locked(name0 + suffix):
            continue
        sl = pick(fam, sl, name0)
        if sl:
            put(f"fair_{fam}" if sl.get("fair") else fam, sl)


def save_shadows(db, cfg, now, cands):
    """«Σκιώδη» εικονικά ταμεία (list_name = shadow_<όνομα>): πειραματικοί κανόνες που φτιάχνονται και κρίνονται στο παρασκήνιο, ΔΕΝ εμφανίζονται στη σελίδα.
    Ορίζονται στο config (`shadow:`)· κάθε μία είναι μια παραλλαγή της βασικής λίστας (π.χ. recommended) με αλλαγμένους κανόνες. Έλεγχος: tools/shadow_check.py."""
    import copy
    from zoneinfo import ZoneInfo
    from betbot.util import sport_day
    sh = cfg.get("shadow") or {}
    if not sh:
        return 0
    tz_ = ZoneInfo(cfg["timezone"])
    day = sport_day(now, tz_).strftime("%Y-%m-%d")
    fresh_after = iso(datetime.strptime(day, "%Y-%m-%d").replace(hour=6, tzinfo=tz_))
    n = 0
    for name, spec in sh.items():
        try:
            c2 = copy.deepcopy(cfg)
            for k, v in (spec.get("selection") or {}).items():
                c2["selection"][k] = v
            for lid, ov in (spec.get("lists") or {}).items():
                c2["lists"][lid].update(ov)
            lists_v = selector.build_lists(cands, c2)
            base = spec.get("base", "recommended")
            sl = (lists_v.get(base) or {}).get("slip")
            if not sl:
                continue
            if db.save_slip(f"{day}#shadow_{name}", iso(now), f"shadow_{name}", sl["total_odds"], sl["p_win"], 1.0,
                            [slim(l) for l in sl["legs"]], keep_first=True, fresh_after=fresh_after) is not False:
                n += 1
        except Exception as e:
            log.warning("Σκιώδες %s: %s", name, e)
    return n


def save_value_scan(db, cfg, now, cands):
    """«Αναζήτηση αξίας» (σκιώδες πείραμα, list_name = shadow_vscan, ΜΟΝΑ στοιχήματα 1 μονάδας): επιλογές όπου η τιμή του Stoiximan είναι
    ΨΗΛΟΤΕΡΗ από τη δίκαιη τιμή του Pinnacle (edge = τιμή_stx × p_pinnacle − 1 ≥ `value_scan.min_edge`). Δεν εμφανίζεται ως πρόταση·
    κρίνεται στο παρασκήνιο (ROI + CLV έναντι κλεισίματος Pinnacle) για να δούμε αν υπάρχει πραγματικό πλεονέκτημα (backtest 24/11: λίγες, αλλά με θετικό CLV)."""
    from zoneinfo import ZoneInfo
    from betbot.util import sport_day
    v = cfg.get("value_scan") or {}
    if not v.get("enabled", False):
        return 0
    tz_ = ZoneInfo(cfg["timezone"])
    day = sport_day(now, tz_).strftime("%Y-%m-%d")
    fresh_after = iso(datetime.strptime(day, "%Y-%m-%d").replace(hour=6, tzinfo=tz_))
    have = db.conn.execute("SELECT slip_id FROM slips WHERE list_name='shadow_vscan' AND slip_id LIKE ?", (day + "#%",)).fetchall()
    room = int(v.get("max_per_day", 6)) - len(have)
    if room <= 0:
        return 0
    me, lo, hi, mo = float(v.get("min_edge", 0.02)), float(v.get("min_p", 0.2)), float(v.get("max_p", 0.9)), float(v.get("max_odds", 6.0))
    found = []
    for c in cands.get("with_odds", []):
        pm = c.get("p_market")
        if not (c.get("q_sharp") and c.get("best_source") == "stoiximan" and c.get("odds") and pm) or c["market"] not in ("1X2", "OU", "BTTS", "ML", "SPREAD", "TOTAL"):
            continue
        edge = pm * c["odds"] - 1
        if edge >= me and lo <= pm <= hi and c["odds"] <= mo:
            found.append((edge, c))
    n = 0
    seen_m = set()
    for edge, c in sorted(found, key=lambda x: -x[0]):
        k = (c["match_id"], c["market"], c.get("line"))
        if k in seen_m or n >= room:
            continue
        seen_m.add(k)
        sid = f"{day}#shadow_vscan:{c['match_id']}:{c['market']}:{c['selection']}:{c.get('line')}"
        if any(r["slip_id"].startswith(f"{day}#shadow_vscan:{c['match_id']}:{c['market']}:") and r["slip_id"].endswith(f":{c.get('line')}") for r in have):
            continue                      # ίδια αγορά/γραμμή του αγώνα έχει ήδη καταγραφεί (κλειδωμένη η πρώτη τιμή)
        if db.save_slip(sid, iso(now), "shadow_vscan", c["odds"], pm, 1.0, [slim(c)], keep_first=True, fresh_after=fresh_after) is not False:
            n += 1
    if n:
        log.info("Αναζήτηση αξίας: %d νέες επιλογές (σκιώδες πείραμα)", n)
    return n


EXTRA_LISTS = ("recommended", "safe", "overs")      # επιπλέον δελτία μόνο στις βασικές κατηγορίες (όχι λαχεία/πειραματικά)


def save_extras(db, cfg, now, cands, tier=None, suffix=""):
    """«Επιπλέον δελτίο» (έως slip.extra_per_day ανά κατηγορία/επίπεδο ανά ημέρα): ΜΟΝΟ με ΕΝΤΕΛΩΣ ΔΙΑΦΟΡΕΤΙΚΟΥΣ αγώνες από το κύριο δελτίο της ίδιας κατηγορίας,
    από τα προηγούμενα επιπλέον, και από δελτίο της ίδιας κατηγορίας που εκδόθηκε χθες και παίζεται σήμερα. Το επιπλέον ΧΤΙΖΕΤΑΙ από τους αγώνες που
    απομένουν με ΤΑ ΙΔΙΑ όρια πιθανότητας/απόδοσης της κατηγορίας· αν δεν υπάρχει τέτοιο δελτίο, δεν βγαίνει τίποτα (17/11/2026)."""
    import json as _j
    from zoneinfo import ZoneInfo
    from betbot.util import sport_day
    mx = int((cfg.get("slip") or {}).get("extra_per_day", 1))
    if mx <= 0:
        return 0
    tz_ = ZoneInfo(cfg["timezone"])
    day = sport_day(now, tz_).strftime("%Y-%m-%d")
    cap = int((cfg.get("slip") or {}).get("extra_total_per_day", 3))        # συνολικό όριο επιπλέον δελτίων ανά ημέρα (όλες οι κατηγορίες/επίπεδα)
    n_today = db.conn.execute("SELECT COUNT(*) FROM slips WHERE slip_id LIKE ? AND slip_id LIKE ?", (f"{day}#%", "%+%")).fetchone()[0]
    fresh_after = iso(datetime.strptime(day, "%Y-%m-%d").replace(hour=6, tzinfo=tz_))
    cfg_t = selector.tier_cfg(cfg, tier) if tier else cfg
    soon = iso(now + timedelta(minutes=45))
    saved = 0
    for lid in EXTRA_LISTS:
        if n_today + saved >= cap:
            break
        if not (cfg["lists"].get(lid) or {}).get("enabled", True):
            continue
        name = lid + suffix
        row = db.conn.execute("SELECT legs_json, created_at, model_prob FROM slips WHERE slip_id=?", (f"{day}#{name}",)).fetchone()
        if not row or row["created_at"] < fresh_after:
            continue                                            # δεν υπάρχει κλειδωμένο κύριο δελτίο σήμερα
        have = db.conn.execute("SELECT slip_id, legs_json FROM slips WHERE slip_id LIKE ?", (f"{day}#{name}+%",)).fetchall()
        if len(have) >= mx:
            continue
        used = {l["match_id"] for l in _j.loads(row["legs_json"])}
        for h in have:
            used |= {l["match_id"] for l in _j.loads(h["legs_json"])}
        for h in db.conn.execute("SELECT legs_json FROM slips WHERE list_name=? AND created_at>=? AND slip_id NOT LIKE ?", (name, iso(now - timedelta(hours=40)), f"{day}#%")):
            used |= {l["match_id"] for l in _j.loads(h["legs_json"])}      # χθεσινό δελτίο που παίζεται ακόμα
        used |= saturated_matches(db, cfg, now, lid)     # και αγώνες άλλων κατηγοριών / που έχουν φτάσει το όριο της κατηγορίας
        try:
            alt = selector.build_lists(cands, cfg_t, exclude=used)
        except Exception as e:
            log.warning("Επιπλέον δελτίο %s: %s", name, e)
            continue
        sl = (alt.get(lid) or {}).get("slip")
        if not sl or any((l.get("kickoff") or "") < soon for l in sl["legs"]):
            continue
        # όριο ποιότητας (18/11/2026): τα επιπλέον φτιάχνονται από αγώνες που περίσσεψαν, άρα συνήθως χειρότερους· δεν βγαίνουν αν η πιθανότητά τους
        # είναι πάνω από `slip.extra_max_p_drop` (5 μονάδες) κάτω από την πιθανότητα του κύριου δελτίου
        if sl["p_win"] < (row["model_prob"] or 0) - float((cfg.get("slip") or {}).get("extra_max_p_drop", 0.05)):
            continue
        legs = [slim(l) for l in sl["legs"]]
        sig = sorted(l["match_id"] + "|" + str(l.get("label")) for l in legs)
        if any(sorted(x["match_id"] + "|" + str(x.get("label")) for x in _j.loads(h["legs_json"])) == sig for h in have):
            continue
        db.save_slip(f"{day}#{name}+{len(have) + 2}", iso(now), name, sl["total_odds"], sl["p_win"], 1.0, legs)
        saved += 1
    return saved


def results_due_iso(db, now):
    """Πότε αναμένεται να τελειώσει ο πρώτος αγώνας δελτίου που ακόμα δεν έχει αποτέλεσμα (για τον φύλακα του live workflow)."""
    from datetime import timedelta
    from betbot.util import parse_iso
    end = {"football": 150, "basketball": 180, "nfl": 210}
    best = None
    # ΟΛΑ τα δελτία (και επίπεδα ~s/~b, επιπλέον δελτία, «χωρίς απόδοση»)· πριν 17/11/2026 μετρούσαν μόνο τα «πραγματικά» και το βράδυ δεν ξεκινούσε
    # νέος γύρος όταν τελείωνε αγώνας που υπήρχε μόνο σε δελτίο επιπέδου -> ❌/✅ έμεναν ασημείωτα για ώρες
    for sl in db.slips():
        for l in sl["legs"]:
            if l.get("result") not in (None, "open"):
                continue
            m = db.get_match(l["match_id"])
            if m and m["status"] in ("finished", "postponed"):
                continue
            try:
                due = parse_iso(l["kickoff"]) + timedelta(minutes=end.get(l.get("sport"), 150))
            except (KeyError, TypeError, ValueError):
                continue
            if now - due > timedelta(hours=12):      # παλιά/ξεχασμένα σκέλη δεν μετράνε
                continue
            if best is None or due < best:
                best = due
    return iso(best) if best else None


def run_live(cfg, loop=False):
    import subprocess
    import time
    from betbot import live
    while True:
        try:
            if loop and os.path.isdir(".git"):   # φέρνει τα νέα δελτία της πρωινής εκτέλεσης
                subprocess.run(["git", "pull", "--rebase", "--autostash", "-q"], check=False, timeout=120)
            now = datetime.now(timezone.utc).replace(microsecond=0)
            log.info("Live σελίδα: %s", live.run(cfg, now))
        except Exception as e:   # η επανάληψη δεν πρέπει να σταματά από ένα σφάλμα δικτύου
            log.error("Live απέτυχε: %s", e)
            if not loop:
                return 1
        if not loop:
            return 0
        time.sleep(600)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--backtest", action="store_true", help="backtest μοντέλων στο παρελθόν")
    ap.add_argument("--live", action="store_true", help="μόνο live σελίδα δελτίων")
    ap.add_argument("--loop", action="store_true", help="με --live: επανάληψη κάθε 10 λεπτά")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    cfg = load_cfg(a.config)
    if a.live:
        return run_live(cfg, a.loop)
    if a.backtest:
        from betbot import backtest
        backtest.run(cfg, datetime.now(timezone.utc).replace(microsecond=0))
        log.info("Backtest: docs/backtest.md")
        return 0
    now = datetime.now(timezone.utc).replace(microsecond=0)
    if a.demo:
        cfg["database"] = "data/demo.sqlite"
        cfg["reports_dir"] = "demo_output"
        cfg["_demo"] = True
        if os.path.exists(cfg["database"]):
            os.remove(cfg["database"])
    db = DB(cfg["database"])
    ctx = Context(db=db, cfg=cfg, now=now, aliases=cfg["team_aliases"])
    notes = []

    # 1) Άντληση (κάθε agent ανεξάρτητα – αν πέσει ένας, συνεχίζουν οι άλλοι)
    if a.demo:
        from betbot.demo import populate
        notes.append(("demo", True, populate(db, cfg, now)))
    elif not a.no_fetch:
        only = {x.strip() for x in a.only.split(",") if x.strip()}
        for C in COLLECTORS:
            c = C()
            if only and c.name not in only:
                continue
            if not cfg["collectors"].get(c.name, {}).get("enabled", False):
                continue
            try:
                msg = c.run(ctx)
                ok = "ΜΠΛΟΚΑΡΙΣΤΗΚΕ" not in msg
                log.info("[%s] %s", c.name, msg)
                notes.append((c.name, ok, msg))
                db.log(iso(now), c.name, ok, msg)
            except Exception as e:
                log.error("[%s] ΑΠΕΤΥΧΕ: %s", c.name, e)
                notes.append((c.name, False, str(e)))
                db.log(iso(now), c.name, False, traceback.format_exc())

    # 2) Εκκαθάριση προηγούμενων δελτίων
    try:
        rc = selector.resettle_cards(db)
        if rc:
            log.info("Επανακρίση κάρτες (κίτρινες+κόκκινες): %d δελτία", rc)
    except Exception as e:
        log.warning("resettle_cards: %s", e)
    settled = selector.settle_slips(db, now)
    if settled:
        log.info("Εκκαθαρίστηκαν %d δελτία", settled)

    # 3) Μοντέλα
    models = build_models(db, cfg, ctx, now, notes)

    # 4) Επιλογές + λίστες
    from betbot import learn as learn_mod
    cfg["_learn"] = learn_mod.build_table(db, cfg)         # διορθώσεις βαθμονόμησης από κριθέντα σκέλη
    cands = selector.build_candidates(db, cfg, models, now)
    lists = selector.build_lists(cands, cfg)
    log.info("Επιλογές με απόδοση: %d · χωρίς απόδοση: %d · αγώνες: %d",
             len(cands["with_odds"]), len(cands["fair"]), len(cands["contexts"]))
    save_lists(db, cfg, now, lists, cands=cands)
    try:
        n_ex = save_extras(db, cfg, now, cands)
        if n_ex:
            log.info("Επιπλέον δελτία: %d", n_ex)
    except Exception as e:
        log.warning("Επιπλέον δελτία: %s", e)
    try:
        save_shadows(db, cfg, now, cands)
        save_value_scan(db, cfg, now, cands)
    except Exception as e:
        log.warning("Σκιώδη ταμεία: %s", e)
    notify_pending = True           # οι ειδοποιήσεις στέλνονται ΜΕΤΑ την αποθήκευση όλων των δελτίων (κύρια, επίπεδα, επιπλέον)
    from betbot import paper as paper_mod
    tier_lists = {}
    for tier, suf in paper_mod.SUFFIX.items():     # επίπεδα ρίσκου «στα χαρτιά» (το balanced είναι τα κανονικά δελτία)
        if suf:
            try:
                tier_lists[tier] = selector.build_lists(cands, selector.tier_cfg(cfg, tier))
                for k, x in tier_lists[tier].items():     # ίδιο δελτίο με το Ισορροπημένο → δεν αποθηκεύεται/δεν εμφανίζεται δεύτερη φορά
                    b = lists.get(k)
                    if isinstance(x, dict) and x.get("slip") and isinstance(b, dict) and b.get("slip") \
                            and paper_mod.leg_sig(x["slip"]["legs"]) == paper_mod.leg_sig(b["slip"]["legs"]):
                        tier_lists[tier][k] = {**x, "slip": None}
                save_lists(db, cfg, now, tier_lists[tier], suffix=suf, cands=cands, cfg_t=selector.tier_cfg(cfg, tier))
                try:
                    save_extras(db, cfg, now, cands, tier=tier, suffix=suf)
                except Exception as e:
                    log.warning("Επιπλέον δελτία %s: %s", tier, e)
            except Exception as e:
                log.warning("Επίπεδο %s: %s", tier, e)
    try:                            # ειδοποίηση push για τα ΝΕΑ δελτία (αν υπάρχει NTFY_TOPIC)
        from betbot import notify as notify_mod
        notify_mod.new_slips(db, cfg, now)
    except Exception as e:
        log.warning("Ειδοποιήσεις: %s", e)

    # 5) Κινήσεις αποδόσεων
    leagues = {lg["id"]: lg for lg in cfg["leagues"]}
    upcoming = [ctx_.m for ctx_ in cands["contexts"].values()]
    moves = movement.biggest_moves(db, upcoming, leagues, min_abs=cfg["rules"]["move_show_min"])

    # 6) Σελίδα
    hist = report.history_by_list(db.slips())
    try:
        from betbot import clv as clv_mod
        clv = clv_mod.clv_summary(db, now)
    except Exception as e:     # δεν πρέπει να ρίχνει τη σελίδα
        log.warning("CLV: %s", e)
        clv = None
    try:
        from betbot import plan as plan_mod
        plan = plan_mod.build_plan(db, cfg, now)
        goals = plan_mod.goals(db, cfg, now, clv)
    except Exception as e:     # το πλάνο δεν πρέπει να ρίχνει τη σελίδα
        log.warning("Πλάνο: %s", e)
        plan = goals = None
    try:
        from betbot import stats as stats_mod
        st = stats_mod.build(db, cfg, now)
        try:                   # προειδοποίηση για το όριο κλήσεων OddsPapi (ο χρήστης ανοίγει δεύτερο λογαριασμό εγκαίρως)
            import json as _json
            qi = _json.loads(db.ext_id("oddspapi:quota", "info") or "null")
            if qi and qi.get("accounts"):
                bad = [a["n"] for a in qi["accounts"] if a.get("ok") is False]
                if bad:
                    st["quota_warn"] = (st.get("quota_warn", "") + f" ΠΡΟΒΛΗΜΑ: ο λογαριασμός {', '.join(map(str, bad))} του OddsPapi δεν διαβάζεται (λάθος key ή δίκτυο).").strip()
                tot_left = sum(a["left"] for a in qi["accounts"])
                if tot_left <= int(qi.get("warn_below", 40)):
                    st["quota_warn"] = (f"Το OddsPapi πλησιάζει το όριο κλήσεων: μένουν {tot_left} για τον μήνα (ανανεώνεται την 1η). "
                                        "Φτιάξε νέο λογαριασμό στο oddspapi.io και βάλε το key στο GitHub ως ODDSPAPI_KEY_2.")
        except Exception:
            pass
        try:                   # προειδοποίηση για το όριο credits του The Odds API
            import json as _json
            qo = _json.loads(db.ext_id("oddsapi:quota", "info") or "null")
            if qo and qo.get("accounts"):
                badq = [a["n"] for a in qo["accounts"] if a.get("ok") is False]
                if badq:
                    st["quota_warn"] = (st.get("quota_warn", "") + f" ΠΡΟΒΛΗΜΑ: ο λογαριασμός {', '.join(map(str, badq))} του The Odds API δεν διαβάζεται (λάθος key ή δίκτυο).").strip()
                tl = sum(a["left"] for a in qo["accounts"])
                if tl <= int(qo.get("warn_below", 60)):
                    w = (f"Το The Odds API πλησιάζει το όριο: μένουν {tl} credits για τον μήνα. "
                         + ("Έχεις και δεύτερο λογαριασμό (ODDS_API_KEY_2)." if len(qo["accounts"]) > 1 else
                            "Βάλε δεύτερο λογαριασμό στο GitHub ως ODDS_API_KEY_2."))
                    st["quota_warn"] = (st.get("quota_warn", "") + " " + w).strip()
        except Exception:
            pass
    except Exception as e:     # τα στατιστικά δεν πρέπει να ρίχνουν τη σελίδα
        log.warning("Στατιστικά: %s", e)
        st = None
    try:
        paper = paper_mod.build(db, cfg, now)
    except Exception as e:     # το paper trading δεν πρέπει να ρίχνει τη σελίδα
        log.warning("Paper trading: %s", e)
        paper = None
    try:
        from betbot import inplay as inplay_mod
        inplay_pri = inplay_mod.priors(cands, cfg, now)
    except Exception as e:     # το live δεν πρέπει να ρίχνει τη σελίδα
        log.warning("Live αξία: %s", e)
        inplay_pri = []
    cidx = {(c["match_id"], c["market"], c["selection"], c["line"]): c for c in cands["with_odds"] + cands["fair"]}
    try:
        from betbot import health as health_mod
        hlt = health_mod.results_health(db, now)
    except Exception as e:     # δεν πρέπει να ρίχνει τη σελίδα
        log.warning("Υγεία αποτελεσμάτων: %s", e)
        hlt = None
    page = report.render_html(cfg, now, lists, cands, moves, hist, notes, clv, plan, goals, st, cidx, paper, tier_lists, inplay_pri, hlt)
    path = report.write_page(cfg["reports_dir"], now, page)
    log.info("Αναφορά: %s", path)
    try:    # πότε έτρεξε τελευταία φορά το bot (το διαβάζει το live workflow για να δει αν η σελίδα είναι ξεπερασμένη)
        with open(os.path.join(cfg["reports_dir"], "last_run.json"), "w", encoding="utf-8") as f:
            json.dump({"generated": iso(now), "results_due": results_due_iso(db, now)}, f)
    except OSError as e:
        log.warning("last_run.json: %s", e)
    try:    # live σελίδα (✅/❌ σε κάθε αγώνα) με τα δελτία της ημέρας
        from betbot import live
        log.info("Live σελίδα: %s", live.run(cfg, now))
    except Exception as e:
        log.warning("Live σελίδα: %s", e)

    # 7) Email
    if cfg["email"]["enabled"] and not a.no_email and not a.demo:
        try:
            from betbot import mailer
            body, imgs = report.render_email(cfg, now, lists, os.environ.get("PAGE_URL"))
            rec = lists["recommended"]["slip"]
            subj = f"{cfg['email']['subject_prefix']} {now:%d/%m}" + (
                f" · προτεινόμενο {rec['total_odds']:.2f}" if rec else " · χωρίς προτεινόμενο")
            mailer.send(subj, body, imgs, cfg["email"]["to"],
                        attachments={f"BetBot-{now:%Y-%m-%d}.html": page.encode("utf-8")})
            log.info("Email εστάλη")
        except Exception as e:
            log.error("Email απέτυχε: %s", e)
            db.log(iso(now), "email", False, str(e))

    if not a.demo:
        db.prune()

    failed = [n for n, ok, _ in notes if not ok]
    if failed:
        log.warning("Προβλήματα σε: %s", ", ".join(failed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
