"""Agent – ειδήσεις τραυματισμών/αποκλεισμών από το δωρεάν feed ειδήσεων του ESPN (χωρίς κλειδί).

Για κάθε διοργάνωση ποδοσφαίρου με αγώνες στις επόμενες `hours_ahead` ώρες διαβάζει τα τελευταία άρθρα και κρατά όσα
αφορούν τραυματισμούς/αποκλεισμούς (λέξεις: injury, ruled out, doubtful, suspended, sidelined…). Δεν είναι πλήρης λίστα τραυματισμών·
πιάνει μόνο ό,τι γράφτηκε ως είδηση. Εμφανίζεται στο «γιατί» των επιλογών ως «Νέα: …» με ημερομηνία.
"""
from __future__ import annotations

import re
from datetime import timedelta

from ..util import http_get, iso
from .base import Collector, Context

URL = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/news"
SPORT = {"football": "soccer"}      # NBA: οι τραυματισμοί έρχονται ήδη από το ESPN injuries
KEYS = re.compile(r"injur|ruled out|rules out|doubt|suspen|sidelined|miss(es|ed)? (the|a|\d)|set to miss|out for|return from|surgery|knee|hamstring|ankle", re.I)


class EspnNewsCollector(Collector):
    name = "espn_news"

    def run(self, ctx: Context) -> str:
        cc = ctx.cfg["collectors"].get("espn_news", {})
        hours = float(cc.get("hours_ahead", 48))
        leagues = {lg["id"]: lg for lg in ctx.leagues() if lg.get("espn") and lg["sport"] in SPORT}
        ms = ctx.db.matches(status="scheduled", since=iso(ctx.now - timedelta(hours=1)), until=iso(ctx.now + timedelta(hours=hours)))
        need = sorted({m["league"] for m in ms if m["league"] in leagues})
        n_lg = n_rows = 0
        fetched = iso(ctx.now)
        for lid in need:
            lg = leagues[lid]
            try:
                d, _ = http_get(URL.format(sport=SPORT[lg["sport"]], league=lg["espn"]), params={"limit": 50}, timeout=15, retries=2)
            except Exception:
                continue
            rows = []
            for a in d.get("articles") or []:
                text = (a.get("headline") or "") + " " + (a.get("description") or "")
                url = (((a.get("links") or {}).get("web") or {}).get("href")) or ""
                if not url or not KEYS.search(text):
                    continue
                rows.append({"league": lid, "url": url, "published": a.get("published") or "", "headline": (a.get("headline") or "")[:200],
                             "summary": (a.get("description") or "")[:300], "fetched": fetched})
            if rows:
                n_lg += 1
                n_rows += ctx.db.upsert_news(rows)
        return f"{n_lg}/{len(need)} διοργανώσεις, {n_rows} ειδήσεις τραυματισμών"
