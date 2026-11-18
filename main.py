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
             "selection", "line", "label", "odds", "p_model", "p_market", "p", "p_raw", "cal", "min_play", "verdict", "edge", "family", "best_source", "why", "form_home", "form_away", "warnings")


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


def save_lists(db, cfg, now, lists, suffix=""):
    """Καταγράφει κάθε λίστα «στα χαρτιά» (1 μονάδα) για το ιστορικό ανά λίστα."""
    from zoneinfo import ZoneInfo
    tz_ = ZoneInfo(cfg["timezone"])
    from betbot.util import sport_day
    day = sport_day(now, tz_).strftime("%Y-%m-%d")    # «ημέρα στοιχημάτων» (06:00–05:59 ώρα Ελλάδας): η ίδια παντού
    # Το πρωινό δελτίο κλειδώνει όλη μέρα· ό,τι φτιάχτηκε πριν τις 06:00 (νυχτερινή εκτέλεση) θεωρείται ξεπερασμένο.
    fresh_after = iso(datetime.strptime(day, "%Y-%m-%d").replace(hour=6, tzinfo=tz_))
    stake = 1.0
    created = iso(now)

    def put(lid, legs_full, total, p, odds_override=None):
        lid = lid + suffix
        legs = [slim(l, (odds_override or {}).get(id(l))) for l in legs_full]
        db.save_slip(f"{day}#{lid}", created, lid, total, p, stake, legs, keep_first=True, fresh_after=fresh_after)

    for lid in ("x10", "x30", "x100", "combo"):
        sl = lists[lid]["slip"]
        if lid == "combo" and not (cfg["lists"].get("combo") or {}).get("enabled", True):
            # «σκιώδες» Συνδυαστικό: φτιάχνεται και κρίνεται στο παρασκήνιο (list_name shadow_combo), ΔΕΝ εμφανίζεται πουθενά· έλεγχος με tools/shadow_combo_check.py
            if sl and (cfg["lists"].get("combo") or {}).get("shadow", False):
                db.save_slip(f"{day}#shadow_combo{suffix}", created, f"shadow_combo{suffix}", sl["total_odds"], sl["p_win"], stake,
                             [slim(l) for l in sl["legs"]], keep_first=True, fresh_after=fresh_after)
            continue
        if sl:
            put(lid, sl["legs"], sl["total_odds"], sl["p_win"])
    rec = lists["recommended"]
    if rec["slip"]:
        put("recommended", rec["slip"]["legs"], rec["slip"]["total_odds"], rec["slip"]["p_win"])
    # Ένα δελτίο ανά κατηγορία (ο χρήστης παίζει ΜΟΝΟ δελτία): safe, over, κόρνερ, κάρτες, πλάγια, παίκτες
    for lid in ("safe", "overs", "btts", "nba_pts"):
        sl = lists[lid].get("slip")
        if sl:
            put(lid, sl["legs"], sl["total_odds"], sl["p_win"])
    # Κατηγορίες χωρίς απόδοση πρακτορείου: η «απόδοση» του δελτίου είναι η ελάχιστη (δίκαιη) απόδοση «παίξ' το αν ≥»
    for fam in ("corners", "cards", "throw_ins", "players"):
        sl = lists[fam].get("slip")
        if sl:
            put(f"fair_{fam}" if sl.get("fair") else fam, sl["legs"], sl["total_odds"], sl["p_win"])


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
        if lid == "combo" and not (cfg["lists"].get("combo") or {}).get("enabled", True):
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
    cands = selector.build_candidates(db, cfg, models, now)
    lists = selector.build_lists(cands, cfg)
    log.info("Επιλογές με απόδοση: %d · χωρίς απόδοση: %d · αγώνες: %d",
             len(cands["with_odds"]), len(cands["fair"]), len(cands["contexts"]))
    save_lists(db, cfg, now, lists)
    try:
        n_ex = save_extras(db, cfg, now, cands)
        if n_ex:
            log.info("Επιπλέον δελτία: %d", n_ex)
    except Exception as e:
        log.warning("Επιπλέον δελτία: %s", e)
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
                save_lists(db, cfg, now, tier_lists[tier], suffix=suf)
                try:
                    save_extras(db, cfg, now, cands, tier=tier, suffix=suf)
                except Exception as e:
                    log.warning("Επιπλέον δελτία %s: %s", tier, e)
            except Exception as e:
                log.warning("Επίπεδο %s: %s", tier, e)

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
