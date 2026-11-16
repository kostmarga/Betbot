"""ΠΡΟΣΩΡΙΝΟ τεστ (17/11/2026): αγορές «Player Points» NBA στο OddsPapi — ορισμός στον κατάλογο, δομή τιμών, Stoiximan vs Pinnacle. 3 μετρημένες κλήσεις. Το key ΔΕΝ τυπώνεται."""
import json
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
    return r.json() if r.status_code == 200 else None


mk = get("/markets") or []
pp = [m for m in mk if m.get("sportId") == 11 and m.get("playerProp")]
print("NBA playerProp αγορές:", len(pp))
names = {}
for m in pp:
    names.setdefault((m.get("marketName"), m.get("marketType"), m.get("period")), []).append(m)
for k, v in sorted(names.items(), key=lambda x: -len(x[1]))[:14]:
    hs = sorted({x.get("handicap") for x in v if x.get("handicap") is not None})
    print(f"   {k} n={len(v)} γραμμές {hs[:3]}..{hs[-3:]} outcomes {[o.get('outcomeName') for o in (v[0].get('outcomes') or [])][:3]} id {v[0].get('marketId')}")
ids = {str(m["marketId"]): m for m in pp}
for book in ("stoiximan", "pinnacle"):
    d = get("/odds-by-tournaments", tournamentIds="132", bookmaker=book, verbosity=3)
    if not isinstance(d, list) or not d:
        print(book, "χωρίς δεδομένα")
        continue
    fx = d[0]
    ms = ((fx.get("bookmakerOdds") or {}).get(book) or {}).get("markets") or {}
    pts = [(k, ids[k]) for k in ms if k in ids and "Player Points (incl. overtime)" in (ids[k].get("marketName") or "") and "+" not in (ids[k].get("marketName") or "")]
    allp = [k for k in ms if k in ids]
    print(f"[{book}] {fx.get('participant1Name')} - {fx.get('participant2Name')}: αγορές {len(ms)}, props {len(allp)}, Player Points {len(pts)}")
    print("   ονόματα props:", sorted({ids[k].get('marketName') for k in allp})[:8])
    for k, m in pts[:2]:
        print("   ορισμός:", {x: m.get(x) for x in ("marketId", "marketName", "marketType", "period", "handicap")}, [(o.get('outcomeId'), o.get('outcomeName')) for o in m.get('outcomes', [])])
        outs = ms[k].get("outcomes") or {}
        for oid, o in list(outs.items())[:2]:
            for pid, pl in list((o.get("players") or {}).items())[:3]:
                print(f"      outcome {oid} player {pid}: {pl.get('playerName')} price {pl.get('price')} active={pl.get('active')} mainLine={pl.get('mainLine')}")

# --- Euroleague: ποια πρακτορεία έχουν αγορά; ---
fxs = get("/fixtures", tournamentId="138")
fxs = fxs if isinstance(fxs, list) else (fxs or {}).get("fixtures", []) if isinstance(fxs, dict) else []
print("Euroleague fixtures:", len(fxs))
if fxs:
    f0 = fxs[0]
    fid = f0.get("fixtureId") or f0.get("id")
    print("fixture", fid, f0.get("participant1Name"), "-", f0.get("participant2Name"))
    o = get("/odds", fixtureId=fid)
    bo = (o or {}).get("bookmakerOdds") or {}
    print("πρακτορεία με δεδομένα:", len(bo))
    for slug, b in sorted(bo.items()):
        ms = b.get("markets") or {}
        print("   ", slug, "αγορές:", len(ms))
