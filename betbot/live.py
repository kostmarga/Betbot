"""Live παρακολούθηση των δελτίων της ημέρας (docs/live.html).

Τρέχει ανεξάρτητα από την καθημερινή εκτέλεση (`python main.py --live`) και είναι ελαφρύ:
  - διαβάζει από τη βάση τα ανοιχτά δελτία (και όσα φτιάχτηκαν σήμερα),
  - για κάθε αγώνα που παίζεται τώρα ρωτά το ESPN (summary: σκορ, λεπτό, κόρνερ, κάρτες),
  - κρίνει κάθε επιλογή: ✅ κερδισμένη / ❌ χαμένη / 🟢 πάει καλά / 🔴 πάει άσχημα / ⏳ δεν ξεκίνησε,
  - γράφει docs/live.html. ΔΕΝ γράφει στη βάση (ώστε να μη «φουσκώνει» το repo κάθε 10 λεπτά).

Περιορισμοί: οι παίκτες και τα πλάγια δεν παρακολουθούνται live (το ESPN δεν δίνει αξιόπιστα τα πλάγια
και οι παίκτες θέλουν ξεχωριστή αντιστοίχιση). Live αποδόσεις δεν υπάρχουν δωρεάν.
"""
from __future__ import annotations

import html
import logging
import os
from datetime import timedelta
from zoneinfo import ZoneInfo

from .collectors.espn_stats import TEAM_ALT, _pick
from .db import DB
from .selector import settle_leg
from .util import http_get, parse_iso

log = logging.getLogger("betbot")
E = html.escape
URL = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/summary"
SPORT = {"football": "soccer", "basketball": "basketball"}
MAX_FETCH = 40

LABEL = {  # κωδικός -> (εικονίδιο, κείμενο)
    "won": ("✅", "Κερδισμένη"), "lost": ("❌", "Χαμένη"), "void": ("↩️", "Άκυρη"),
    "sure": ("✅", "Ήδη μέσα"), "dead": ("❌", "Έχει χαθεί"),
    "ok": ("🟢", "Πάει καλά"), "bad": ("🔴", "Πάει άσχημα"),
    "pending": ("⏳", "Δεν ξεκίνησε"), "na": ("➖", "Χωρίς live"),
}


# ---------------------------------------------------------------- ESPN
def fetch_state(sport: str, league_espn: str, event_id: str) -> dict:
    """Σκορ, λεπτό και (ποδόσφαιρο) κόρνερ/κάρτες από το ESPN summary."""
    data, _ = http_get(URL.format(sport=SPORT[sport], league=league_espn), params={"event": event_id})
    comp = data["header"]["competitions"][0]
    st = (comp.get("status") or {}).get("type") or {}
    by = {c["homeAway"]: c for c in comp["competitors"]}

    def sc(side):
        try:
            return int(float(by[side].get("score")))
        except (TypeError, ValueError, KeyError):
            return 0

    out = {"state": st.get("state", "pre"), "clock": st.get("detail") or st.get("shortDetail") or "",
           "hs": sc("home"), "as": sc("away"), "stats": {}}
    for t in (data.get("boxscore") or {}).get("teams", []):
        side = t.get("homeAway")
        if side not in ("home", "away"):
            continue
        s = {x.get("name"): x.get("displayValue", x.get("value")) for x in t.get("statistics", [])}
        out["stats"][side] = {c: _pick(s, alts) for c, alts in TEAM_ALT.items()}
    return out


class _StubDB:
    """Δίνει στο settle_leg τα live στατιστικά σαν να ήταν στη βάση."""
    def __init__(self, st):
        self.st = st

    def team_stats_for_match(self, _mid):
        rows = []
        for side, is_home in (("home", 1), ("away", 0)):
            v = (self.st.get("stats") or {}).get(side)
            if v:
                rows.append({"is_home": is_home, "corners": _n(v.get("corners")), "yellow": _n(v.get("yellow")),
                             "throw_ins": None})
        return rows

    def player_stats_for_event(self, _mid):
        return []


def _n(x):
    return None if x is None else int(x)


# ---------------------------------------------------------------- κρίση επιλογής
def judge(leg: dict, st: dict | None, db_match: dict | None, db) -> tuple[str, str]:
    """Επιστρέφει (κωδικός, σύντομο κείμενο προόδου)."""
    m, s, L = leg["market"], leg["selection"], leg.get("line")
    if m in ("THROWINS", "PLAYER"):
        return "na", "δεν παρακολουθείται live"
    if st is None:   # δεν ρωτήσαμε το ESPN
        if db_match and db_match["status"] in ("finished", "postponed"):
            r = settle_leg(leg, db_match, db)
            return (r, "") if r != "open" else ("na", "")
        return "pending", ""
    if st["state"] == "pre":
        return "pending", ""
    h, a = st["hs"], st["as"]
    if st["state"] == "post":
        fake = {"match_id": leg["match_id"], "status": "finished", "home_score": h, "away_score": a}
        r = settle_leg(leg, fake, _StubDB(st))
        return (r, f"{h}-{a}") if r != "open" else ("na", f"{h}-{a}")

    # --- σε εξέλιξη ---
    stats = st.get("stats") or {}
    def tot(col):
        v = [(stats.get(side) or {}).get(col) for side in ("home", "away")]
        return None if any(x is None for x in v) else int(v[0] + v[1])
    res = "1" if h > a else "X" if h == a else "2"

    def over_under(cur, what):
        if cur is None:
            return "na", f"{what}: χωρίς live στοιχεία"
        if s == "OVER":
            return ("sure" if cur > L else "ok"), f"{what} {cur} / {L:g}"
        return ("dead" if cur > L else "ok"), f"{what} {cur} / κάτω από {L:g}"

    if m in ("OU", "TOTAL"):
        return over_under(h + a, "γκολ" if m == "OU" else "πόντοι")
    if m == "CORNERS":
        return over_under(tot("corners"), "κόρνερ")
    if m == "CARDS":
        return over_under(tot("yellow"), "κίτρινες")
    if m == "CORNERS_MORE":
        hv, av = (stats.get("home") or {}).get("corners"), (stats.get("away") or {}).get("corners")
        if hv is None or av is None:
            return "na", "κόρνερ: χωρίς live στοιχεία"
        good = hv != av and (hv > av) == (s == "HOME")
        return ("ok" if good else "bad"), f"κόρνερ {int(hv)}-{int(av)}"
    if m == "BTTS":
        both = h > 0 and a > 0
        if s == "YES":
            return ("sure" if both else "ok"), f"{h}-{a}"
        return ("dead" if both else "ok"), f"{h}-{a}"
    if m == "1X2":
        return ("ok" if res == s else "bad"), f"{h}-{a}"
    if m == "DC":
        return ("ok" if res in s else "bad"), f"{h}-{a}"
    if m == "ML":
        return ("ok" if (h > a) == (s == "HOME") and h != a else "bad"), f"{h}-{a}"
    if m == "SPREAD":
        v = (h - a) + L
        return ("ok" if v != 0 and (v > 0) == (s == "HOME") else "bad"), f"{h}-{a}"
    return "na", f"{h}-{a}"


def slip_state(codes: list[str]) -> tuple[str, str]:
    if any(c in ("lost", "dead") for c in codes):
        return "lost", "❌ Χαμένο"
    if all(c in ("won", "void") for c in codes):
        return "won", "✅ Κερδισμένο"
    if all(c in ("won", "void", "sure") for c in codes):
        return "sure", "✅ Κερδισμένο αν κρατήσουν τα αποτελέσματα"
    if any(c == "bad" for c in codes):
        return "bad", "🔴 Κάποια επιλογή πάει άσχημα"
    if all(c in ("pending", "na") for c in codes):
        return "pending", "⏳ Δεν ξεκίνησε"
    return "ok", "🟢 Σε εξέλιξη"


# ---------------------------------------------------------------- εκτέλεση
def collect(db: DB, cfg: dict, now, fetch=fetch_state) -> list[dict]:
    """Επιστρέφει τα δελτία με την κρίση για κάθε επιλογή."""
    tz = ZoneInfo(cfg["timezone"])
    today = now.astimezone(tz).date().isoformat()
    leagues = {lg["id"]: lg for lg in cfg["leagues"]}
    slips = [s for s in db.slips()
             if s["status"] == "open" or parse_iso(s["created_at"]).astimezone(tz).date().isoformat() == today]
    states: dict[str, dict | None] = {}
    fetched = 0
    for sl in slips:
        for leg in sl["legs"]:
            mid = leg["match_id"]
            if mid in states:
                continue
            states[mid] = None
            mt = db.get_match(mid)
            lg = leagues.get(leg.get("league") or (mt or {}).get("league"))
            if not mid.startswith("espn:") or not lg or not lg.get("espn") or mt is None:
                continue
            ko = parse_iso(mt["kickoff"])
            if not (ko - timedelta(minutes=15) <= now <= ko + timedelta(hours=6)):
                continue
            if fetched >= MAX_FETCH:
                break
            try:
                states[mid] = fetch(lg["sport"], lg["espn"], mid[5:])
                fetched += 1
            except Exception as e:
                log.warning("live: %s απέτυχε (%s)", mid, e)
    out = []
    for sl in slips:
        legs = []
        for leg in sl["legs"]:
            code, txt = judge(leg, states.get(leg["match_id"]), db.get_match(leg["match_id"]), db)
            legs.append({**leg, "code": code, "progress": txt, "st": states.get(leg["match_id"])})
        code, label = slip_state([l["code"] for l in legs])
        out.append({**sl, "legs": legs, "code": code, "label": label})
    out.sort(key=lambda s: ({"ok": 0, "bad": 0, "sure": 0, "pending": 1}.get(s["code"], 2), s["slip_id"]))
    log.info("live: %d δελτία, %d κλήσεις ESPN", len(out), fetched)
    return out


CSS = """
:root{--bg:#f9f9f7;--card:#fcfcfb;--ink:#0b0b0b;--muted:#6b6a66;--line:#e1e0d9;--ok:#0a7a0a;--bad:#c62f2f}
@media(prefers-color-scheme:dark){:root{--bg:#0d0d0d;--card:#1a1a19;--ink:#f0efec;--muted:#a8a79f;--line:#2c2c2a;--ok:#35c035;--bad:#ef6a6a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:860px;margin:0 auto;padding:16px}h1{font-size:22px;margin:0 0 2px}.sub{color:var(--muted);margin:0 0 14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:12px 0}
.card h3{margin:0 0 6px;font-size:16px}.tot{color:var(--muted);font-weight:400;font-size:14px}
.leg{display:grid;grid-template-columns:28px 1fr auto;gap:8px;padding:8px 0;border-top:1px solid var(--line);align-items:start}
.leg:first-of-type{border-top:0}.m{font-size:13px;color:var(--muted)}.p{text-align:right;font-variant-numeric:tabular-nums;font-size:14px}
.won,.sure,.ok{color:var(--ok)}.lost,.dead,.bad{color:var(--bad)}.n{color:var(--muted);padding:20px 0}
a{color:inherit}
"""


def render(cfg, now, slips, names: dict | None = None) -> str:
    tz = ZoneInfo(cfg["timezone"])
    loc = now.astimezone(tz)
    names = names or {}
    body = []
    for sl in slips:
        legs = []
        for l in sl["legs"]:
            ic, _ = LABEL[l["code"]]
            st = l.get("st")
            score = f" · {st['hs']}-{st['as']} {E(st['clock'])}" if st and st["state"] == "in" else ""
            ko = parse_iso(l["kickoff"]).astimezone(tz) if l.get("kickoff") else None
            when = f"{ko:%H:%M} · " if ko and l["code"] == "pending" else ""
            legs.append(
                f'<div class="leg"><div>{ic}</div><div><b>{E(l["home"])} – {E(l["away"])}</b>'
                f'<div class="m">{when}{E(str(l.get("label") or l["selection"]))} @ {l["odds"]:.2f}{score}</div></div>'
                f'<div class="p {l["code"]}">{E(l["progress"])}</div></div>')
        name = names.get(sl.get("list_name"), sl.get("list_name") or "")
        body.append(f'<div class="card"><h3>{E(name)} <span class="tot">· απόδοση {sl["total_odds"]:.2f} · '
                    f'{sl["stake"]:.2f}€</span></h3><div class="{sl["code"]}"><b>{E(sl["label"])}</b></div>'
                    + "".join(legs) + "</div>")
    if not body:
        body.append('<div class="n">Δεν υπάρχουν ανοιχτά δελτία. Τα δελτία φτιάχνονται στην πρωινή εκτέλεση.</div>')
    return f"""<!doctype html><html lang="el"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="300">
<title>BetBot Live</title><style>{CSS}</style></head><body><main>
<h1>🔴 BetBot Live</h1><p class="sub">Ενημερώθηκε {loc:%d/%m %H:%M} · η σελίδα ανανεώνεται κάθε ~10 λεπτά ·
<a href="index.html">← Κύρια σελίδα</a></p>{''.join(body)}
<p class="sub">Πηγή: ESPN. Οι αποδόσεις δεν ανανεώνονται live. Παίκτες και πλάγια δεν παρακολουθούνται.</p>
</main></body></html>"""


def run(cfg: dict, now, out_path: str | None = None) -> str:
    from .report import LIST_NAMES
    db = DB(cfg["database"])
    slips = collect(db, cfg, now)
    page = render(cfg, now, slips, LIST_NAMES)
    path = out_path or os.path.join(cfg["reports_dir"], "live.html")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    return path
