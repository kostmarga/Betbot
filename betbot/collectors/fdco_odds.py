"""Agent 3 – football-data.co.uk (δωρεάν, χωρίς κλειδί).

https://www.football-data.co.uk/fixtures.csv  → πρόγραμμα των επόμενων ημερών
με αποδόσεις 1Χ2 και Over/Under 2.5 (μέσος όρος αγοράς: στήλες Avg*).
Καλύπτει top-5 λίγκες + ελληνική Super League (κωδικός G1).
Ενημερώνεται συνήθως Τρίτη και Παρασκευή.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from zoneinfo import ZoneInfo

from ..db import OddsRow
from ..util import http_get, iso
from .base import Collector, Context, attach_to_fixture

URL = "https://www.football-data.co.uk/fixtures.csv"
UK = ZoneInfo("Europe/London")

# (market, selection, line, [στήλες κατά προτεραιότητα])
COLUMNS = [
    ("1X2", "1", None, ["AvgH", "PSH", "B365H"]),
    ("1X2", "X", None, ["AvgD", "PSD", "B365D"]),
    ("1X2", "2", None, ["AvgA", "PSA", "B365A"]),
    ("OU", "OVER", 2.5, ["Avg>2.5", "P>2.5", "B365>2.5"]),
    ("OU", "UNDER", 2.5, ["Avg<2.5", "P<2.5", "B365<2.5"]),
]


def _price(row, cols):
    for c in cols:
        try:
            v = float(row.get(c) or "")
            if v > 1.0:
                return v
        except ValueError:
            continue
    return None


class FdcoOddsCollector(Collector):
    name = "fdco_odds"

    def run(self, ctx: Context) -> str:
        text, _ = http_get(URL, expect="text")
        text = text.lstrip("﻿")
        by_div = {lg["fdco"]: lg for lg in ctx.leagues(fdco=True)}
        rows, n_matches = [], 0
        fetched = iso(ctx.now)
        for r in csv.DictReader(io.StringIO(text)):
            lg = by_div.get((r.get("Div") or "").strip())
            if not lg:
                continue
            try:
                d = datetime.strptime(f"{r['Date']} {r.get('Time') or '15:00'}", "%d/%m/%Y %H:%M")
            except ValueError:
                continue
            ko = d.replace(tzinfo=UK)
            mid = attach_to_fixture(ctx, lg, r["HomeTeam"], r["AwayTeam"], iso(ko),
                                    "fdco", f"{lg['fdco']}-{d:%Y%m%d}-{r['HomeTeam']}")
            n_matches += 1
            for market, sel, line, cols in COLUMNS:
                p = _price(r, cols)
                if p:
                    rows.append(OddsRow(mid, market, sel, line, p, 1, "fdco", fetched))
        ctx.db.upsert_odds(rows)
        return f"{n_matches} αγώνες, {len(rows)} αποδόσεις"
