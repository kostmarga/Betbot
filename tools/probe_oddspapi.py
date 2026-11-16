"""ΠΡΟΣΩΡΙΝΟ τεστ τένις (17/11/2026): υπάρχουν τελειωμένοι αγώνες ATP/WTA κύριου tour με ιστορικές τιμές (δωρεάν endpoint) και αποτελέσματα;
Έχει το Stoiximan αγορές στο κύριο tour; ~8 μετρημένες κλήσεις. Το key ΔΕΝ τυπώνεται· δεν τυπώνουμε στοιχεία λογαριασμού. Θα σβηστεί μετά."""
import json
import os
import re
import sys
import time
import requests

KEY = os.environ.get("ODDSPAPI_KEY", "")
B = "https://api.oddspapi.io/v4"
billable = 0


def get(path, bill=True, wait=1.3, **p):
    global billable
    p["apiKey"] = KEY
    for _ in range(4):
        time.sleep(wait)
        r = requests.get(B + path, params=p, timeout=120)
        if r.status_code == 200:
            billable += 1 if bill else 0
            return r.json()
        if "RATE_LIMITED" in r.text:
            time.sleep(2.5)
            continue
        print(f"  {path} {r.status_code}: {r.text[:150]}".replace(KEY, "***"))
        return None
    return None


if not KEY:
    sys.exit("Δεν υπάρχει ODDSPAPI_KEY")
t = get("/tournaments", sportId=12) or []
print("τουρνουά τένις:", len(t))
main = [x for x in t if re.search(r"(ATP|WTA)", x.get("tournamentName") or "") and not re.search(r"Challenger|ITF|UTR|Doubles|Qualif|Davis|Exhibition|Juniors|125", x.get("tournamentName") or "", re.I)]
main = sorted(main, key=lambda x: -(x.get("futureFixtures") or 0))
print("κύριο tour (ATP/WTA, όχι Challenger/ITF):", len(main))
for x in main[:25]:
    print("   ", x["tournamentId"], x["tournamentName"], "| upcoming", x.get("upcomingFixtures"), "future", x.get("futureFixtures"))
slam = [x for x in t if re.search(r"(Wimbledon|US Open|French Open|Roland|Australian Open|Masters|ATP Finals|Paris|Shanghai)", x.get("tournamentName") or "") and "Doubles" not in (x.get("tournamentName") or "") and "Challenger" not in (x.get("tournamentName") or "")]
print("πιθανά Slam/Masters:", [(x["tournamentId"], x["tournamentName"], x.get("futureFixtures")) for x in slam[:14]])
# 1) τελειωμένοι αγώνες ενός κύριου τουρνουά
pick = next((x for x in main if re.search(r"Men|ATP", x["tournamentName"])), None)
done = None
if pick:
    f = get("/fixtures", tournamentId=pick["tournamentId"], statusId=2, hasOdds=True)
    print(f"fixtures τελειωμένα [{pick['tournamentName']}]:", len(f) if isinstance(f, list) else f)
    if isinstance(f, list) and f:
        print("  κλειδιά fixture:", sorted(f[0].keys()))
        print("  δείγμα:", {k: f[0].get(k) for k in ("fixtureId", "participant1Name", "participant2Name", "startTime", "statusId", "hasOdds")})
        done = f[:2]
# 2) ιστορικές τιμές (ΔΩΡΕΑΝ) + σκορ (1 κλήση)
for fx in (done or []):
    h = get("/historical-odds", bill=False, wait=1.3, fixtureId=fx["fixtureId"], bookmakers="pinnacle,stoiximan")
    if isinstance(h, dict):
        bk = h.get("bookmakers") or {}
        for slug, v in bk.items():
            ms = v.get("markets") or {}
            print(f"  historical-odds {fx['participant1Name']} - {fx['participant2Name']} | {slug}: αγορές {len(ms)}")
            for mid, m in list(ms.items())[:2]:
                for oid, o in list((m.get("outcomes") or {}).items())[:2]:
                    hist = (o.get("players") or {}).get("0") or []
                    print(f"     αγορά {mid} outcome {oid}: {len(hist)} ενημερώσεις, τελευταία:", [(x.get('createdAt', '')[:16], x.get('price')) for x in hist[:2]])
    sc = get("/scores", fixtureId=fx["fixtureId"])
    print("  scores:", json.dumps(sc)[:260] if sc else None)
# 3) τωρινός αγώνας κύριου tour: έχει αγορές το Stoiximan;
cur = next((x for x in main if (x.get("upcomingFixtures") or 0) > 0), None)
if cur:
    d = get("/odds-by-tournaments", tournamentIds=str(cur["tournamentId"]), bookmaker="stoiximan", verbosity=3)
    print(f"odds-by-tournaments [{cur['tournamentName']}] stoiximan:", type(d).__name__, len(d) if isinstance(d, list) else "")
    for fx in (d or [])[:3] if isinstance(d, list) else []:
        ms = ((fx.get("bookmakerOdds") or {}).get("stoiximan") or {}).get("markets") or {}
        print("   ", fx.get("participant1Name"), "-", fx.get("participant2Name"), fx.get("startTime", "")[:16], "αγορές Stoiximan:", len(ms))
print("μετρημένες κλήσεις:", billable)
