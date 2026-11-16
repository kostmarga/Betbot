"""ΠΡΟΣΩΡΙΝΟ τεστ #2 (17/11/2026): δίνουν τιμές Stoiximan/Bet365 στο δωρεάν πακέτο; Υπάρχουν κόρνερ/κάρτες σε μεγάλη λίγκα;
Υπάρχουν props NFL/NBA/τένις; Το key έρχεται από το secret ODDSPAPI_KEY και ΔΕΝ τυπώνεται· ΔΕΝ τυπώνουμε στοιχεία λογαριασμού. Θα σβηστεί μετά."""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
import requests

KEY = os.environ.get("ODDSPAPI_KEY", "")
B = "https://api.oddspapi.io/v4"
calls = 0


def get(path, quiet=False, **p):
    global calls
    calls += 1
    p["apiKey"] = KEY
    try:
        r = requests.get(B + path, params=p, timeout=60)
    except Exception as e:
        print("  ΣΦΑΛΜΑ δικτύου", path, type(e).__name__)
        return None
    if not quiet:
        print(f"GET {path} { {k: v for k, v in p.items() if k not in ('apiKey',)} } -> {r.status_code}")
    if r.status_code != 200:
        print("   ", r.text[:200].replace(KEY, "***"))
        return None
    try:
        return r.json()
    except Exception:
        return None


if not KEY:
    sys.exit("Δεν υπάρχει ODDSPAPI_KEY")
mk = get("/markets", quiet=True) or []
names = {str(m.get("marketId")): (m.get("marketName") or "") for m in mk if isinstance(m, dict)}
sets = {
    "corners": {k for k, v in names.items() if re.search(r"corner", v, re.I)},
    "cards": {k for k, v in names.items() if re.search(r"card|booking", v, re.I)},
    "player_props": {k for k, v in names.items() if re.search(r"player|passing|rushing|receiving|points \(player|assists \(player|rebounds \(player", v, re.I)},
}
print("κατάλογος αγορών:", len(names), {k: len(v) for k, v in sets.items()})
now = datetime.now(timezone.utc)


def fixtures(sport, tname_re, days=4, limit=1):
    t = get("/tournaments", quiet=True, sportId=sport) or []
    cand = [x for x in t if isinstance(x, dict) and re.search(tname_re, x.get("tournamentName") or "", re.I) and "U2" not in (x.get("tournamentName") or "")]
    cand = sorted(cand, key=lambda x: -(x.get("futureFixtures") or 0))
    out = []
    for tt in cand[:4]:
        f = get("/fixtures", quiet=True, tournamentId=tt["tournamentId"]) or []
        for x in f if isinstance(f, list) else []:
            try:
                st = datetime.fromisoformat(x["startTime"].replace("Z", "+00:00"))
            except Exception:
                continue
            if x.get("hasOdds") and now < st < now + timedelta(days=days):
                out.append((tt.get("tournamentName"), x))
        if len(out) >= limit:
            break
    return out[:limit]


def probe(label, sport, tre, books, days=4):
    fl = fixtures(sport, tre, days)
    if not fl:
        print(f"[{label}] δεν βρέθηκε αγώνας με αποδόσεις στις επόμενες {days} μέρες")
        return
    tname, fx = fl[0]
    print(f"[{label}] {tname}: {fx.get('participant1Name')} - {fx.get('participant2Name')} ({fx.get('startTime')})")
    for bk in books:
        d = get("/odds", quiet=True, fixtureId=fx["fixtureId"], bookmakers=bk)
        if not isinstance(d, dict):
            print(f"   {bk}: ΚΑΜΙΑ απάντηση / περιορισμένο")
            continue
        bo = (d.get("bookmakerOdds") or {}).get(bk) or {}
        ms = bo.get("markets") or {}
        info = {"αγορές": len(ms)}
        for nm, st in sets.items():
            ids = [m for m in ms if str(m) in st]
            if ids:
                info[nm] = len(ids)
        print(f"   {bk}: {info}")
        # δείγμα τιμών κόρνερ/κάρτες/props
        for nm in ("corners", "cards", "player_props"):
            ids = [m for m in ms if str(m) in sets[nm]][:2]
            for m in ids:
                outs = (ms[m].get("outcomes") or {})
                sample = []
                for oid, o in list(outs.items())[:3]:
                    pr = ((o.get("players") or {}).get("0") or {}).get("price")
                    sample.append(pr)
                print(f"        {nm}: {names.get(str(m))} | τιμές {sample}")


books = ["stoiximan", "bet365", "pinnacle", "novibet"]
print("== ΠΟΔΟΣΦΑΙΡΟ (μεγάλη λίγκα)")
for lab, tre in (("EPL", r"^Premier League$"), ("LaLiga", r"^LaLiga$"), ("Bundesliga", r"^Bundesliga$")):
    probe(lab, 10, tre, books, days=5)
print("== NFL")
probe("NFL", 14, r"^NFL$", ["stoiximan", "bet365", "pinnacle", "draftkings"], days=5)
print("== NBA")
probe("NBA", 11, r"^NBA$", ["stoiximan", "bet365", "pinnacle", "draftkings"], days=3)
print("== ΤΕΝΙΣ")
probe("ATP", 12, r"ATP", ["stoiximan", "bet365", "pinnacle"], days=2)
print("κλήσεις:", calls)
