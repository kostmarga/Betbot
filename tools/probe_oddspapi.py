"""ΠΡΟΣΩΡΙΝΟ τεστ #3 (17/11/2026): κόρνερ/κάρτες σε αγώνα που ξεκινά σύντομα, Bet365, NFL, δομή τιμών props NBA.
Με παύσεις (όριο ρυθμού). Το key έρχεται από το secret ODDSPAPI_KEY και ΔΕΝ τυπώνεται· δεν τυπώνουμε στοιχεία λογαριασμού. Θα σβηστεί μετά."""
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
import requests

KEY = os.environ.get("ODDSPAPI_KEY", "")
B = "https://api.oddspapi.io/v4"
calls = 0


def get(path, quiet=True, **p):
    global calls
    p["apiKey"] = KEY
    for attempt in range(4):
        calls += 1
        time.sleep(1.3)
        try:
            r = requests.get(B + path, params=p, timeout=60)
        except Exception as e:
            print("  ΣΦΑΛΜΑ δικτύου", path, type(e).__name__)
            return None
        if r.status_code == 200:
            try:
                return r.json()
            except Exception:
                return None
        if "RATE_LIMITED" in r.text:
            time.sleep(2.5)
            continue
        print(f"  {path} {r.status_code}: {r.text[:160]}".replace(KEY, "***"))
        return None
    print("  rate limit συνεχίστηκε", path)
    return None


if not KEY:
    sys.exit("Δεν υπάρχει ODDSPAPI_KEY")
mk = get("/markets") or []
names = {str(m.get("marketId")): (m.get("marketName") or "") for m in mk if isinstance(m, dict)}
sets = {"corners": {k for k, v in names.items() if re.search(r"corner", v, re.I)},
        "cards": {k for k, v in names.items() if re.search(r"card|booking", v, re.I)}}
now = datetime.now(timezone.utc)


def upcoming(sport, within_h, tre=None, max_t=12, max_f=8):
    t = get("/tournaments", sportId=sport) or []
    t = [x for x in t if isinstance(x, dict) and (x.get("upcomingFixtures") or 0) > 0 and (not tre or re.search(tre, x.get("tournamentName") or "", re.I))]
    t = sorted(t, key=lambda x: -(x.get("upcomingFixtures") or 0))[:max_t]
    out = []
    for tt in t:
        f = get("/fixtures", tournamentId=tt["tournamentId"]) or []
        for x in f if isinstance(f, list) else []:
            try:
                st = datetime.fromisoformat(x["startTime"].replace("Z", "+00:00"))
            except Exception:
                continue
            if x.get("hasOdds") and now < st < now + timedelta(hours=within_h):
                out.append((tt["tournamentName"], x))
        if len(out) >= max_f:
            break
    return out


def books_report(fx, books, label):
    for bk in books:
        d = get("/odds", fixtureId=fx["fixtureId"], bookmakers=bk)
        bo = ((d or {}).get("bookmakerOdds") or {}).get(bk) or {}
        ms = bo.get("markets") or {}
        info = {"αγορές": len(ms)}
        for nm, st in sets.items():
            n = sum(1 for m in ms if str(m) in st)
            if n:
                info[nm] = n
        print(f"   [{label}] {bk}: {info}" + ("" if d else "  (καμία απάντηση)"))
        yield bk, ms


print("== ΠΟΔΟΣΦΑΙΡΟ: αγώνες που ξεκινούν σε <48 ώρες")
fl = upcoming(10, 48)
print("  βρέθηκαν:", [(t, f.get("participant1Name"), f.get("participant2Name"), f.get("startTime")[:16]) for t, f in fl[:8]])
done = 0
for t, fx in fl:
    if done >= 3:
        break
    print(f"  --- {t}: {fx.get('participant1Name')} - {fx.get('participant2Name')} ({fx.get('startTime')})")
    had = False
    sample_printed = False
    for bk, ms in books_report(fx, ["stoiximan", "bet365", "pinnacle"], "soccer"):
        for nm in ("corners", "cards"):
            ids = [m for m in ms if str(m) in sets[nm]]
            if ids and not sample_printed:
                m = ids[0]
                print(f"      δείγμα {nm}: {names.get(str(m))} | JSON:", json.dumps(ms[m])[:420])
                sample_printed = True
            had = had or bool(ids)
    done += 1
print("== NFL (Ravens-Chargers)")
fl = upcoming(14, 30, tre=r"^NFL$", max_t=2, max_f=1)
if fl:
    t, fx = fl[0]
    print(f"  {fx.get('participant1Name')} - {fx.get('participant2Name')}")
    for bk, ms in books_report(fx, ["stoiximan", "bet365", "pinnacle", "draftkings"], "nfl"):
        pass
else:
    print("  δεν βρέθηκε")
print("== NBA: δομή τιμής props (stoiximan)")
fl = upcoming(11, 30, tre=r"^NBA$", max_t=2, max_f=1)
if fl:
    t, fx = fl[0]
    d = get("/odds", fixtureId=fx["fixtureId"], bookmakers="stoiximan")
    ms = (((d or {}).get("bookmakerOdds") or {}).get("stoiximan") or {}).get("markets") or {}
    pp = [m for m in ms if re.search(r"player", names.get(str(m), ""), re.I)]
    print("  props αγορές:", len(pp), [names.get(str(m)) for m in pp[:6]])
    if pp:
        print("  JSON δείγμα:", json.dumps(ms[pp[0]])[:600])
print("κλήσεις:", calls)
