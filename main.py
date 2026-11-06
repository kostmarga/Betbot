"""BetBot – orchestrator.

Χρήση:
  python main.py              # πλήρης εκτέλεση (άντληση → μοντέλα → λίστες → σελίδα → email)
  python main.py --demo       # συνθετικά δεδομένα, χωρίς internet (δοκιμή)
  python main.py --no-fetch   # μόνο μοντέλα/λίστες από ό,τι υπάρχει ήδη στη βάση
  python main.py --no-email
  python main.py --only sofascore,espn_stats   # τρέχει μόνο αυτούς τους collectors
"""
from __future__ import annotations

import argparse
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
             "selection", "line", "label", "odds", "p_model", "p_market", "p", "edge", "family")


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
    for lg in ctx.leagues(sport="basketball"):
        if lg.get("greek_site") and not cfg["collectors"]["greek_site"].get("enabled"):
            continue          # ΕΚΟ Basket League: μόνο αν ρυθμιστεί το ελληνικό site
        try:
            models["basketball"][lg["id"]] = BasketballModel(cfg["models"]["basketball"], ctx.aliases).fit(
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


def save_lists(db, cfg, now, lists):
    """Καταγράφει κάθε λίστα «στα χαρτιά» (1 μονάδα) για το ιστορικό ανά λίστα."""
    day = now.astimezone().strftime("%Y-%m-%d")
    stake = 1.0
    created = iso(now)

    def put(lid, legs_full, total, p, odds_override=None):
        legs = [slim(l, (odds_override or {}).get(id(l))) for l in legs_full]
        db.save_slip(f"{day}#{lid}", created, lid, total, p, stake, legs)

    for lid in ("x10", "x30", "x100", "combo"):
        sl = lists[lid]["slip"]
        if sl:
            put(lid, sl["legs"], sl["total_odds"], sl["p_win"])
    rec = lists["recommended"]
    if rec["slip"]:
        put("recommended", rec["slip"]["legs"], rec["slip"]["total_odds"], rec["slip"]["p_win"])
    if rec["single"]:
        put("single", [rec["single"]], rec["single"]["odds"], rec["single"]["p"])
    if lists["overs"]["slip"]:
        sl = lists["overs"]["slip"]
        put("overs", sl["legs"], sl["total_odds"], sl["p_win"])
    for i, c in enumerate(lists["safe"]["picks"][:5]):
        db.save_slip(f"{day}#safe1-{i + 1}", created, "safe1", c["odds"], c["p"], stake, [slim(c)])
    # επιλογές χωρίς απόδοση: καταγραφή με την ελάχιστη αποδεκτή απόδοση («παίξ' το αν ≥»)
    for fam in ("corners", "cards", "throw_ins", "players"):
        for i, c in enumerate([c for c in lists[fam]["picks"] if c.get("play_if")][:3]):
            db.save_slip(f"{day}#fair_{fam}-{i + 1}", created, f"fair_{fam}", c["play_if"], c["p"], stake,
                         [slim(c, c["play_if"])])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    cfg = load_cfg(a.config)
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
    settled = selector.settle_slips(db)
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

    # 5) Κινήσεις αποδόσεων
    leagues = {lg["id"]: lg for lg in cfg["leagues"]}
    upcoming = [ctx_.m for ctx_ in cands["contexts"].values()]
    moves = movement.biggest_moves(db, upcoming, leagues, min_abs=cfg["rules"]["move_show_min"])

    # 6) Σελίδα
    hist = report.history_by_list(db.slips())
    page = report.render_html(cfg, now, lists, cands, moves, hist, notes)
    path = report.write_page(cfg["reports_dir"], now, page)
    log.info("Αναφορά: %s", path)

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
