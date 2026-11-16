"""ΠΡΟΣΩΡΙΝΟ τεστ (17/11/2026): γιατί λείπει το Pinnacle για την Euroleague (tournamentId 138); 2 μετρημένες κλήσεις. Το key ΔΕΝ τυπώνεται."""
import os
import sys
import time
import requests

KEY = os.environ.get("ODDSPAPI_KEY", "")
if not KEY:
    sys.exit("Δεν υπάρχει ODDSPAPI_KEY")


def get(path, **p):
    p["apiKey"] = KEY
    time.sleep(1.3)
    r = requests.get("https://api.oddspapi.io/v4" + path, params=p, timeout=120)
    print(f"GET {path} { {k: v for k, v in p.items() if k != 'apiKey'} } -> {r.status_code}")
    if r.status_code != 200:
        print("  ", r.text[:200].replace(KEY, "***"))
        return None
    return r.json()


for book in ("pinnacle", "stoiximan"):
    d = get("/odds-by-tournaments", tournamentIds="138", bookmaker=book, verbosity=3)
    if not isinstance(d, list):
        continue
    print(f"[{book}] fixtures Euroleague: {len(d)}")
    for fx in d[:12]:
        bo = (fx.get("bookmakerOdds") or {}).get(book) or {}
        ms = bo.get("markets") or {}
        has = {k: (k in ms) for k in ("111", "116")}
        print(f"   {fx.get('participant1Name')} - {fx.get('participant2Name')} {str(fx.get('startTime'))[:16]} | bookmakerOdds κλειδιά: {list((fx.get('bookmakerOdds') or {}).keys())} | αγορές: {len(ms)} | 111/116: {has} | hasOdds={fx.get('hasOdds')}")
