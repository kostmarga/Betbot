"""Agent 5 – Ελληνικό site στοιχήματος (ΑΠΕΝΕΡΓΟΠΟΙΗΜΕΝΟ μέχρι να ρυθμιστεί).

Γιατί είναι ξεχωριστό και κλειστό από προεπιλογή:
  - Τα ελληνικά sites (Stoiximan, Novibet, Pame Stoixima κ.λπ.) δεν έχουν δημόσιο API.
    Η σελίδα τους φορτώνει τις αποδόσεις από εσωτερικά JSON endpoints, που αλλάζουν
    χωρίς προειδοποίηση.
  - Έχουν προστασία από bots (Cloudflare κ.λπ.). Ο collector ΔΕΝ προσπαθεί να την
    παρακάμψει (captcha, κρυφά headers κ.λπ.). Αν το site μπλοκάρει, απλώς παραλείπεται.
  - Οι όροι χρήσης τους συχνά απαγορεύουν αυτοματοποιημένη άντληση. Έλεγξέ τους.

Πώς ενεργοποιείται (README §7):
  1. Ανοίγεις τη σελίδα του αγώνα στον browser → DevTools → Network → φίλτρο "json".
  2. Βρίσκεις το request που φέρνει τις αποδόσεις (π.χ. .../events?...) και το βάζεις
     στο config: collectors.greek_site.events_url
  3. Συμπληρώνεις τη συνάρτηση `parse_events` παρακάτω για τη μορφή του JSON.
  4. enabled: true
Μπορούμε να το κάνουμε μαζί: ανοίγω εγώ τη σελίδα στον browser σου και βρίσκω το endpoint.
"""
from __future__ import annotations

from ..db import OddsRow
from ..util import http_get, iso
from .base import Collector, Context, attach_to_fixture


def parse_events(payload) -> list[dict]:
    """Μετατρέπει το JSON του site σε λίστα:
    [{"league_id": "GBL", "ext_id": "...", "home": "...", "away": "...", "kickoff": "ISO",
      "odds": [("ML","HOME",None,1.55), ("TOTAL","OVER",158.5,1.85), ...]}]
    TODO: υλοποίηση μετά τον εντοπισμό του endpoint (βλ. docstring).
    """
    raise NotImplementedError("Ο parser του ελληνικού site δεν έχει ρυθμιστεί ακόμα (README §7).")


class GreekSiteCollector(Collector):
    name = "greek_site"

    def run(self, ctx: Context) -> str:
        cc = ctx.cfg["collectors"]["greek_site"]
        if not cc.get("events_url"):
            return "παράλειψη: δεν έχει οριστεί events_url"
        payload, _ = http_get(cc["events_url"], timeout=cc.get("timeout", 20))
        leagues = {lg["id"]: lg for lg in ctx.cfg["leagues"]}
        rows, fetched = [], iso(ctx.now)
        for ev in parse_events(payload):
            lg = leagues.get(ev["league_id"])
            if not lg:
                continue
            mid = attach_to_fixture(ctx, lg, ev["home"], ev["away"], ev["kickoff"], "greek", ev["ext_id"])
            for market, sel, line, price in ev["odds"]:
                rows.append(OddsRow(mid, market, sel, line, float(price), 1, f"greek:{cc['name']}", fetched))
        ctx.db.upsert_odds(rows)
        return f"{len(rows)} αποδόσεις από {cc.get('name') or 'ελληνικό site'}"
