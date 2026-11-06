"""Agent – football-data.co.uk ιστορικά αποτελέσματα + στατιστικά (δωρεάν, χωρίς κλειδί).

Κατεβάζει τα αρχεία των προηγούμενων σεζόν (https://www.football-data.co.uk/mmz4281/<σεζόν>/<λίγκα>.csv)
που έχουν ανά αγώνα: γκολ, κόρνερ (HC/AC), κίτρινες/κόκκινες (HY/AY/HR/AR), φάουλ (HF/AF),
σουτ (HS/AS), σουτ στην εστία (HST/AST) και διαιτητή. Έτσι τα μοντέλα εκπαιδεύονται σε χιλιάδες
αγώνες αντί για λίγους μήνες. Οι σεζόν του παρελθόντος κατεβαίνουν μία φορά (fetch_cache)·
η τρέχουσα σεζόν ανανεώνεται σε κάθε εκτέλεση.

Αν ο αγώνας υπάρχει ήδη (από ESPN) δεν διπλογράφεται· συμπληρώνονται μόνο όσα λείπουν.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from zoneinfo import ZoneInfo

from ..db import Match, TeamStat
from ..util import http_get, iso, log
from .base import Collector, Context, attach_to_fixture

URL = "https://www.football-data.co.uk/mmz4281/{season}/{div}.csv"
UK = ZoneInfo("Europe/London")


def season_codes(now: datetime, n_back: int) -> list[str]:
    """Τρέχουσα σεζόν + n_back προηγούμενες, π.χ. ['2526', '2425', '2324']."""
    start = now.year if now.month >= 7 else now.year - 1
    return [f"{(start - k) % 100:02d}{(start - k + 1) % 100:02d}" for k in range(n_back + 1)]


def _i(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _date(r) -> datetime | None:
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            d = datetime.strptime(r["Date"].strip(), fmt)
            t = (r.get("Time") or "15:00").strip() or "15:00"
            h, m = t.split(":")[:2]
            return d.replace(hour=int(h), minute=int(m), tzinfo=UK)
        except (ValueError, KeyError, AttributeError):
            continue
    return None


class FdcoHistoryCollector(Collector):
    name = "fdco_history"

    def run(self, ctx: Context) -> str:
        cc = ctx.cfg["collectors"].get("fdco_history", {})
        seasons = season_codes(ctx.now, int(cc.get("seasons_back", 3)))
        current = seasons[0]
        new_matches = new_stats = files = 0
        notes = []
        for lg in ctx.leagues(fdco=True):
            for s in seasons:
                key = f"fdco_hist:{s}:{lg['fdco']}"
                if s != current and ctx.db.cached(key):
                    continue
                try:
                    text, _ = http_get(URL.format(season=s, div=lg["fdco"]), expect="text")
                except Exception as e:  # π.χ. η λίγκα δεν υπήρχε εκείνη τη σεζόν
                    notes.append(f"{lg['id']} {s}: {e}")
                    ctx.db.mark_cached(key, iso(ctx.now), ok=True)
                    continue
                a, b = self._load(ctx, lg, text.lstrip("﻿"))
                new_matches += a
                new_stats += b
                files += 1
                ctx.db.mark_cached(key, iso(ctx.now), ok=True)
        msg = f"{files} αρχεία, {new_matches} νέοι αγώνες, {new_stats} γραμμές στατιστικών"
        return msg + (f" | παραλείψεις: {len(notes)}" if notes else "")

    def _load(self, ctx: Context, lg: dict, text: str) -> tuple[int, int]:
        n_m = n_s = 0
        for r in csv.DictReader(io.StringIO(text)):
            home, away = (r.get("HomeTeam") or "").strip(), (r.get("AwayTeam") or "").strip()
            hg, ag = _i(r.get("FTHG")), _i(r.get("FTAG"))
            ko = _date(r)
            if not home or not away or ko is None or hg is None or ag is None:
                continue
            ext = f"{lg['fdco']}-{ko:%Y%m%d}-{home}"
            mid = attach_to_fixture(ctx, lg, home, away, iso(ko), "fdco", ext, create_if_missing=False)
            if mid is None:
                mid = f"fdco:{ext}"
                ctx.db.upsert_matches([Match(mid, "football", lg["id"], iso(ko), home, away,
                                             hg, ag, "finished", "fdco")])
                n_m += 1
            else:
                m = ctx.db.get_match(mid)
                if m and m["status"] != "finished":
                    ctx.db.upsert_matches([Match(mid, "football", lg["id"], m["kickoff"], m["home"], m["away"],
                                                 hg, ag, "finished", m["source"])])
            if any(t.get("source") == "espn" for t in ctx.db.team_stats_for_match(mid)):
                continue   # υπάρχουν ήδη στατιστικά από ESPN – όχι διπλά
            ref = (r.get("Referee") or "").strip() or None
            if ref:
                ctx.db.set_referee(mid, ref, "fdco")
            key = f"fdco:{ext}"
            rows = []
            for is_home, team, opp, goals, suf in ((1, home, away, hg, "H"), (0, away, home, ag, "A")):
                g = lambda base: _i(r.get(f"{suf}{base}"))
                rows.append(TeamStat(key, mid, lg["id"], iso(ko), team, opp, is_home, goals,
                                     g("C"), g("Y"), g("R"), g("F"), g("S"), g("ST"), None, None, ref, "fdco"))
            n_s += ctx.db.upsert_team_stats(rows)
        return n_m, n_s
