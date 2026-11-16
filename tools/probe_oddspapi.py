"""ΠΡΟΣΩΡΙΝΟ τεστ #3 (17/11/2026): ΟΛΕΣ οι ομάδες αγορών NBA και οι αγορές «overtime» του NFL (περίοδοι). 1 μετρημένη κλήση. Το key ΔΕΝ τυπώνεται."""
import collections
import os
import sys
import time
import requests

KEY = os.environ.get("ODDSPAPI_KEY", "")
if not KEY:
    sys.exit("Δεν υπάρχει ODDSPAPI_KEY")
time.sleep(1.3)
r = requests.get("https://api.oddspapi.io/v4/markets", params={"apiKey": KEY}, timeout=120)
print("markets ->", r.status_code)
mk = r.json() if r.status_code == 200 else []


def show(sid, nm, only=None):
    ms = [m for m in mk if m.get("sportId") == sid and not m.get("playerProp")]
    grp = collections.defaultdict(list)
    for m in ms:
        grp[(m.get("marketName"), m.get("marketType"), m.get("period"))].append(m)
    print(f"== {nm}: {len(ms)} αγορές, {len(grp)} ομάδες")
    for (n, t, p), lst in sorted(grp.items(), key=lambda x: str(x[0])):
        if only and not only(n, p):
            continue
        hs = sorted({x.get("handicap") for x in lst if x.get("handicap") is not None})
        o = [oc.get("outcomeName") for oc in (lst[0].get("outcomes") or [])][:3]
        print(f"   {n} | {t} | περίοδος={p} | n={len(lst)} | γραμμές {hs[:2]}..{hs[-2:]} | {o} | id {lst[0].get('marketId')}")


show(11, "NBA")
show(14, "NFL (μόνο incl. overtime / κύριες)", only=lambda n, p: n and any(k in n.lower() for k in ("overtime", "money", "handicap", "over under", "winner")) and "TD" not in n and "Field" not in n and "Team" not in n and "Quarter" not in n and "Half" not in n and "Asian" not in n and "European" not in n)
