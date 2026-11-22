"""Ειδοποιήσεις push όταν βγαίνει ΝΕΟ δελτίο (22/11/2026) — μέσω ntfy.sh (δωρεάν, χωρίς λογαριασμό, εφαρμογή iOS/Android).
Ρύθμιση (μία φορά): (1) εγκατάσταση της εφαρμογής «ntfy», (2) εγγραφή σε ένα ΙΔΙΩΤΙΚΟ όνομα θέματος (π.χ. betbot-xxxxxxxx), (3) το ίδιο όνομα ως GitHub secret `NTFY_TOPIC`.
Χωρίς secret δεν στέλνεται τίποτα. Το θέμα λειτουργεί σαν κωδικός: όποιος το ξέρει βλέπει τις ειδοποιήσεις, γι' αυτό είναι τυχαίο.
Στέλνεται ΜΙΑ ειδοποίηση ανά εκτέλεση με όλα τα νέα δελτία των κατηγοριών που ορίζονται στο config (`notify:`)· κάθε δελτίο ειδοποιείται μία φορά.
"""
from __future__ import annotations

import os

import requests

from .paper import CAT_NAME, TIER_NAME, split_list_name
from .util import iso, log, slip_day, sport_day

NS = "notified"
DEFAULT_URL = "https://kostmarga.github.io/Betbot/"


def _fmt_slip(s, tz) -> str:
    tier, cat = split_list_name(s["list_name"])
    extra = "+" in str(s["slip_id"]).split("#")[-1]
    name = CAT_NAME.get(cat, cat) + ("" if tier == "balanced" else f" · {TIER_NAME[tier]}") + (" · ➕ επιπλέον" if extra else "")
    lines = [f"{name} — απόδοση {s['total_odds']:.2f} · πιθανότητα {s['model_prob'] * 100:.0f}%"]
    for l in s["legs"]:
        ko = str(l.get("kickoff") or "")
        hhmm = ""
        try:
            from .util import parse_iso
            hhmm = parse_iso(ko).astimezone(tz).strftime("%d/%m %H:%M")
        except Exception:
            pass
        odd = f" @{l['odds']:.2f}" if l.get("odds") else ""
        lines.append(f"  • {hhmm} {l.get('home', '')}–{l.get('away', '')}: {str(l.get('label') or '')}{odd}")
    return "\n".join(lines)


def new_slips(db, cfg, now) -> int:
    """Στέλνει ειδοποίηση για δελτία της σημερινής ημέρας που δεν έχουν ειδοποιηθεί ακόμα. Επιστρέφει πόσα ειδοποιήθηκαν."""
    nc = cfg.get("notify") or {}
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not nc.get("enabled", False) or not topic:
        return 0
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(cfg["timezone"])
    today = sport_day(now, tz)
    cats = set(nc.get("categories") or ["recommended", "safe", "overs"])
    tiers = set(nc.get("tiers") or ["strong", "balanced", "bold"])
    todays = [s for s in db.slips() if slip_day(s, tz) == today and not str(s.get("list_name") or "").startswith(("shadow_", "fair_"))]
    first = db.ext_id("notify", "init") is None
    fresh = []
    for s in todays:
        already = db.ext_id(NS, s["slip_id"]) is not None
        if first:                          # πρώτη ενεργοποίηση: τα υπάρχοντα δεν στέλνονται (μόνο δοκιμαστικό μήνυμα)
            db.set_ext_id(NS, s["slip_id"], "1")
            continue
        if already:
            continue
        tier, cat = split_list_name(s["list_name"])
        db.set_ext_id(NS, s["slip_id"], "1")
        if cat in cats and tier in tiers and s["status"] == "open":
            fresh.append(s)
    url = os.environ.get("PAGE_URL") or DEFAULT_URL
    try:
        if first:
            r = requests.post(os.environ.get("NTFY_URL","https://ntfy.sh/"), json={"topic": topic, "title": "BetBot: ενεργές οι ειδοποιήσεις ✓", "message": "Θα έρχεται ειδοποίηση όταν βγαίνει νέο δελτίο.",
                                                         "click": url, "tags": ["white_check_mark"]}, timeout=20)
            ok = r.status_code < 300
            if ok:
                db.set_ext_id("notify", "init", iso(now))
            log.info("Ειδοποιήσεις: δοκιμαστικό μήνυμα %s", "εστάλη" if ok else f"απέτυχε ({r.status_code})")
            return 0
        if not fresh:
            return 0
        fresh.sort(key=lambda s: (0 if split_list_name(s["list_name"])[1] == "safe" else 1, s["created_at"]))
        shown = fresh[:6]
        body = "\n\n".join(_fmt_slip(s, tz) for s in shown) + (f"\n\n+{len(fresh) - len(shown)} ακόμα στη σελίδα" if len(fresh) > len(shown) else "")
        title = "BetBot: 1 νέο δελτίο" if len(fresh) == 1 else f"BetBot: {len(fresh)} νέα δελτία"
        r = requests.post(os.environ.get("NTFY_URL","https://ntfy.sh/"), json={"topic": topic, "title": title, "message": body[:3800], "click": url, "tags": ["ticket"], "priority": 3}, timeout=20)
        log.info("Ειδοποιήσεις: %d νέα δελτία -> %s", len(fresh), r.status_code)
        return len(fresh) if r.status_code < 300 else 0
    except Exception as e:                  # οι ειδοποιήσεις ΠΟΤΕ δεν ρίχνουν το τρέξιμο
        log.warning("Ειδοποιήσεις: %s", e)
        return 0
