"""ΠΡΟΣΩΡΙΝΟ τεστ #5 (17/11/2026): μόνο η δομή των αγορών totals-corners / totals-bookings (1 κλήση). Το key ΔΕΝ τυπώνεται. Θα σβηστεί μετά."""
import collections
import os
import sys
import time
import requests

KEY = os.environ.get("ODDSPAPI_KEY", "")
if not KEY:
    sys.exit("Δεν υπάρχει ODDSPAPI_KEY")
time.sleep(1.3)
r = requests.get("https://api.oddspapi.io/v4/markets", params={"apiKey": KEY}, timeout=90)
print("markets ->", r.status_code)
mk = r.json() if r.status_code == 200 else []
for typ in ("totals-corners", "totals-bookings", "spreads-bookings", "1x2-bookings"):
    ms = [m for m in mk if m.get("marketType") == typ and not m.get("playerProp")]
    per = collections.Counter(m.get("period") for m in ms)
    print(f"== {typ}: {len(ms)} αγορές, περίοδοι {dict(per)}")
    ft = [m for m in ms if m.get("period") in ("fulltime", "full time", "ft", None)]
    print("   ονόματα:", sorted({m.get("marketName") for m in ms})[:6])
    hs = sorted({m.get("handicap") for m in ft if m.get("handicap") is not None})
    print("   γραμμές (fulltime):", hs[:40], "... πλήθος", len(hs))
    for m in ft[:3]:
        print("   δείγμα:", {k: m.get(k) for k in ("marketId", "marketName", "handicap", "period", "sportId")}, [o.get("outcomeName") for o in (m.get("outcomes") or [])])
