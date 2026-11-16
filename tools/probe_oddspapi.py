"""ΠΡΟΣΩΡΙΝΟ τεστ (17/11/2026): κύριες αγορές NBA (sportId 11) και NFL (sportId 14) στο OddsPapi — συμπαγής έξοδος. 1 μετρημένη κλήση. Το key ΔΕΝ τυπώνεται."""
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
for sid, nm in ((11, "NBA"), (14, "NFL")):
    ms = [m for m in mk if m.get("sportId") == sid and not m.get("playerProp")]
    grp = collections.defaultdict(list)
    for m in ms:
        grp[(m.get("marketName"), m.get("marketType"), m.get("period"))].append(m)
    print(f"== {nm}: {len(ms)} αγορές, {len(grp)} διαφορετικά (όνομα, τύπος, περίοδος)")
    for (n, t, p), lst in sorted(grp.items(), key=lambda x: (str(x[0][2]), str(x[0][0]))):
        if p not in ("fulltime", "full time", "ft", None):
            continue
        hs = sorted({x.get("handicap") for x in lst if x.get("handicap") is not None})
        o = [oc.get("outcomeName") for oc in (lst[0].get("outcomes") or [])][:3]
        print(f"   [{p}] {n} | {t} | αγορές {len(lst)} | γραμμές {hs[:3]}..{hs[-3:]} | outcomes {o} | πρώτο id {lst[0].get('marketId')}")
