"""ΠΡΟΣΩΡΙΝΟ τεστ #4 (17/11/2026): όριο κλήσεων (ΜΟΝΟ request_limit/request_count), δομή αγορών κόρνερ/καρτών (γραμμές), ονόματα τουρνουά,
και ένα odds-by-tournaments (Stoiximan) για αντιστοίχιση ονομάτων ομάδων. Το key ΔΕΝ τυπώνεται· δεν τυπώνουμε στοιχεία λογαριασμού. Θα σβηστεί μετά."""
import json
import os
import re
import sys
import time
import requests

KEY = os.environ.get("ODDSPAPI_KEY", "")
B = "https://api.oddspapi.io/v4"


def get(path, **p):
    p["apiKey"] = KEY
    for _ in range(4):
        time.sleep(1.3)
        r = requests.get(B + path, params=p, timeout=90)
        if r.status_code == 200:
            return r.json()
        if "RATE_LIMITED" in r.text:
            time.sleep(2.5)
            continue
        print(f"  {path} {r.status_code}: {r.text[:150]}".replace(KEY, "***"))
        return None
    return None


if not KEY:
    sys.exit("Δεν υπάρχει ODDSPAPI_KEY")
a = get("/account") or {}
for s in (a.get("subscriptions") or []):
    print("ΟΡΙΟ ΚΛΗΣΕΩΝ:", {k: s.get(k) for k in ("request_limit", "request_count", "rate_limit", "is_active")})
mk = get("/markets") or []
print("αγορές:", len(mk))
rows = []
for m in mk:
    nm = m.get("marketName") or ""
    if re.search(r"corner|booking|card", nm, re.I) and m.get("period") == "fulltime" and m.get("marketType") in ("totals", "ou", "over_under") and not m.get("playerProp"):
        rows.append((m["marketId"], nm, m.get("handicap"), m.get("marketType"), [o.get("outcomeName") for o in (m.get("outcomes") or [])][:3]))
print("σύνολο corner/booking totals fulltime:", len(rows))
for kind in ("orner", "ooking", "ard"):
    sub = [r for r in rows if kind in r[1]]
    print(f"  --- {kind}: {len(sub)}")
    for r in sub[:14]:
        print("    ", r)
types = sorted({m.get("marketType") for m in mk if re.search(r"corner|booking", m.get("marketName") or "", re.I)})
print("marketTypes κόρνερ/booking:", types)
t = get("/tournaments", sportId=10) or []
want = r"^(Premier League|LaLiga|Serie A|Bundesliga|Ligue 1|Eredivisie|Primeira Liga|Super League|Championship|Süper Lig|Super Lig|Jupiler Pro League|Scottish Premiership|LaLiga 2|League One|League Two)$"
print("τουρνουά (σε ποδόσφαιρο):", [(x["tournamentId"], x["tournamentName"], x.get("categoryName"), x.get("upcomingFixtures"), x.get("futureFixtures")) for x in t if re.match(want, x.get("tournamentName") or "")][:30])
for sid, nm in ((11, "NBA"), (14, "NFL")):
    tt = get("/tournaments", sportId=sid) or []
    print(nm, [(x["tournamentId"], x["tournamentName"], x.get("upcomingFixtures")) for x in tt if re.match(r"^(NBA|NFL|Euroleague|EuroLeague|Liga ACB)", x.get("tournamentName") or "")][:6])
d = get("/odds-by-tournaments", tournamentIds="17", bookmaker="stoiximan", verbosity=3)
if isinstance(d, list):
    print("odds-by-tournaments EPL/stoiximan: fixtures", len(d))
    cs = {str(m["marketId"]): m for m in mk}
    for fx in d[:3]:
        bo = (fx.get("bookmakerOdds") or {}).get("stoiximan") or {}
        ms = bo.get("markets") or {}
        nc = sum(1 for k in ms if "orner" in (cs.get(k, {}).get("marketName") or ""))
        nb = sum(1 for k in ms if re.search(r"ooking|ard", cs.get(k, {}).get("marketName") or ""))
        print("   ", {k: fx.get(k) for k in ("fixtureId", "participant1Name", "participant2Name", "startTime")}, "αγορές", len(ms), "corner", nc, "cards", nb, "| κλειδιά fixture:", sorted(fx.keys())[:14])
else:
    print("odds-by-tournaments:", type(d), (json.dumps(d)[:200] if d else None))
