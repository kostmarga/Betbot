"""Agent – αποδόσεις από το ESPN (δωρεάν, χωρίς κλειδί).

Το «summary» κάθε αγώνα του ESPN περιέχει αποδόσεις πρακτορείων (συνήθως DraftKings και Bet365) με
τιμή ανοίγματος και τιμή τώρα, σε αμερικάνικη μορφή (+300 / -145). Τις μετατρέπουμε σε δεκαδικές και
τις γράφουμε στον πίνακα `odds` (πηγή "espn"). Η τιμή ανοίγματος τροφοδοτεί τις «κινήσεις αποδόσεων».

Ποδόσφαιρο: 1Χ2 και Over/Under (η κύρια γραμμή, συνήθως 2.5).
Μπάσκετ (NBA): νικητής (ML), σύνολο πόντων (TOTAL) και χάντικαπ (SPREAD).

Προσοχή: είναι αποδόσεις αμερικάνικων πρακτορείων – διαφέρουν λίγο από του ΟΠΑΠ. Χρησιμεύουν ως
τιμή αγοράς/σημείο αναφοράς. Αν υπάρχει ODDS_API_KEY ή fdco, προτιμάται η πηγή με τα περισσότερα βιβλία.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import timedelta

from ..db import OddsRow
from ..util import http_get, iso, parse_iso
from .base import Collector, Context

URL = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/summary"
SPORT = {"football": "soccer", "basketball": "basketball"}


def american_to_decimal(s) -> float | None:
    """'+300' -> 4.0 · '-145' -> 1.690 · 'EVEN' -> 2.0 · άκυρο -> None."""
    if s is None:
        return None
    t = str(s).strip().upper().replace("−", "-")
    if t in ("EVEN", "EV", "PK"):
        return 2.0
    try:
        v = float(t)
    except ValueError:
        return None
    if v == 0 or abs(v) < 100:
        return None
    return round(1 + v / 100, 3) if v > 0 else round(1 + 100 / abs(v), 3)


def _num_line(s) -> float | None:
    m = re.search(r"[-+]?\d+(?:\.\d+)?", str(s or ""))
    return float(m.group()) if m else None


def _side(block, which):
    """(τιμή τώρα, τιμή ανοίγματος, γραμμή) από ένα μπλοκ τύπου {'close': {...}, 'open': {...}}."""
    b = (block or {}).get(which) or {}
    cur, op = b.get("close") or {}, b.get("open") or {}
    return (american_to_decimal(cur.get("odds")), american_to_decimal(op.get("odds")),
            _num_line(cur.get("line")))


def parse_odds(sport: str, data: dict) -> list[tuple]:
    """Επιστρέφει [(market, selection, line, price, open_price, n_books)] με μέσο όρο των πρακτορείων."""
    agg = defaultdict(list)   # (market, sel, line) -> [(price, open)]
    for prov in data.get("odds") or []:
        ml, tot, sp = prov.get("moneyline"), prov.get("total"), prov.get("pointSpread")
        if sport == "football":
            for key, sel in (("home", "1"), ("draw", "X"), ("away", "2")):
                p, o, _ = _side(ml, key)
                if p:
                    agg[("1X2", sel, None)].append((p, o))
            for key, sel in (("over", "OVER"), ("under", "UNDER")):
                p, o, ln = _side(tot, key)
                if p and ln is not None:
                    agg[("OU", sel, ln)].append((p, o))
        else:
            for key, sel in (("home", "HOME"), ("away", "AWAY")):
                p, o, _ = _side(ml, key)
                if p:
                    agg[("ML", sel, None)].append((p, o))
            for key, sel in (("over", "OVER"), ("under", "UNDER")):
                p, o, ln = _side(tot, key)
                if p and ln is not None:
                    agg[("TOTAL", sel, ln)].append((p, o))
            _, _, hl = _side(sp, "home")          # η γραμμή γράφεται πάντα από την πλευρά της γηπεδούχου
            if hl is not None:
                for key, sel in (("home", "HOME"), ("away", "AWAY")):
                    p, o, _ = _side(sp, key)
                    if p:
                        agg[("SPREAD", sel, hl)].append((p, o))
    out = []
    for (market, sel, line), vals in agg.items():
        prices = [v[0] for v in vals]
        opens = [v[1] for v in vals if v[1]]
        out.append((market, sel, line, round(sum(prices) / len(prices), 3),
                    round(sum(opens) / len(opens), 3) if opens else None, len(prices)))
    return out


class EspnOddsCollector(Collector):
    name = "espn_odds"

    def run(self, ctx: Context) -> str:
        cc = ctx.cfg["collectors"].get("espn_odds", {})
        days = int(cc.get("days_ahead", 3))
        cap = int(cc.get("max_calls_per_run", 150))
        leagues = {lg["id"]: lg for lg in ctx.leagues() if lg.get("espn")}
        fetched = iso(ctx.now)
        ms = ctx.db.matches(status="scheduled", since=iso(ctx.now - timedelta(hours=1)),
                            until=iso(ctx.now + timedelta(days=days)))
        calls = n_rows = n_with = fails = 0
        for m in sorted(ms, key=lambda x: x["kickoff"]):
            lg = leagues.get(m["league"])
            if not lg or not m["match_id"].startswith("espn:"):
                continue
            if calls >= cap:
                break
            calls += 1
            try:
                data, _ = http_get(URL.format(sport=SPORT[lg["sport"]], league=lg["espn"]),
                                   params={"event": m["match_id"][5:]})
            except Exception:
                fails += 1
                continue
            rows = [OddsRow(m["match_id"], mk, sel, ln, pr, nb, "espn", fetched, op)
                    for mk, sel, ln, pr, op, nb in parse_odds(lg["sport"], data)]
            if rows:
                n_with += 1
                n_rows += ctx.db.upsert_odds(rows)
        return f"{n_with}/{calls} αγώνες με αποδόσεις, {n_rows} γραμμές" + (f" | {fails} αποτυχίες" if fails else "")
