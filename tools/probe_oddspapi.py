"""ΠΡΟΣΩΡΙΝΟ τεστ (17/11/2026): πώς ονομάζονται οι κύριες αγορές NBA (sportId 11) και NFL (sportId 14) στο OddsPapi; 1 μετρημένη κλήση (/markets).
Το key ΔΕΝ τυπώνεται. Θα σβηστεί μετά."""
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
for sid, nm in ((11, "ΜΠΑΣΚΕΤ/NBA"), (14, "NFL")):
    ms = [m for m in mk if m.get("sportId") == sid and not m.get("playerProp")]
    print(f"== {nm}: {len(ms)} αγορές (χωρίς props)")
    names = collections.Counter(m.get("marketName") for m in ms)
    print("  πιο συχνά ονόματα:", names.most_common(14))
    types = collections.Counter((m.get("marketType"), m.get("period")) for m in ms)
    print("  (marketType, period):", types.most_common(16))
    for m in ms:
        n = (m.get("marketName") or "").lower()
        if m.get("period") in ("fulltime", "full time", "ft", None) and any(k in n for k in ("moneyline", "winner", "match", "handicap", "spread", "total", "over under")) and "team" not in n and "quarter" not in n and "half" not in n:
            print("   ", {k: m.get(k) for k in ("marketId", "marketName", "marketType", "period", "handicap")}, [o.get("outcomeName") for o in (m.get("outcomes") or [])][:3])
            if sum(1 for _ in range(0)) > 0:
                break
