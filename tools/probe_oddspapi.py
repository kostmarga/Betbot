"""ΠΡΟΣΩΡΙΝΟ τεστ (17/11/2026): τι καλύπτει το OddsPapi (δωρεάν key) για κόρνερ/κάρτες, NFL, τένις και ποια πρακτορεία ανοίγουν.
Το key έρχεται από το secret ODDSPAPI_KEY και ΔΕΝ τυπώνεται. Λίγες κλήσεις (<20). Θα σβηστεί μετά το τεστ."""
import json
import os
import re
import sys
import requests

KEY = os.environ.get("ODDSPAPI_KEY", "")
B = "https://api.oddspapi.io/v4"


def get(path, **p):
    p["apiKey"] = KEY
    try:
        r = requests.get(B + path, params=p, timeout=40)
    except Exception as e:
        print("  ΣΦΑΛΜΑ δικτύου", path, type(e).__name__)
        return None
    print(f"GET {path} {({k: v for k, v in p.items() if k != 'apiKey'})} -> {r.status_code}")
    if r.status_code != 200:
        print("   ", r.text[:300].replace(KEY, "***"))
        return None
    try:
        return r.json()
    except Exception:
        print("   όχι JSON:", r.text[:200])
        return None


if not KEY:
    sys.exit("Δεν υπάρχει ODDSPAPI_KEY")
print("== 1) account / quota")
a = get("/account")
if a is not None:
    print("  ", json.dumps(a)[:500].replace(KEY, "***"))
print("== 2) sports")
sp = get("/sports") or []
ids = {}
for s in sp if isinstance(sp, list) else []:
    ids[s.get("sportName") or s.get("name")] = s.get("sportId") or s.get("id")
print("  ", {k: v for k, v in ids.items() if re.search(r"soccer|football|tennis|basket|volley|mma|boxing", str(k), re.I)})
print("== 3) bookmakers")
bk = get("/bookmakers") or []
slugs = {}
for b in bk if isinstance(bk, list) else []:
    slugs[b.get("bookmakerSlug") or b.get("slug")] = b
want = ["stoiximan", "novibet", "bet365", "pinnacle", "betsson", "bwin", "unibet", "williamhill", "opap", "betano", "interwetten", "novibet-gr"]
print("  σύνολο:", len(slugs), "| ζητούμενα:", {w: (w in slugs) for w in want})
print("  παράδειγμα εγγραφής:", json.dumps(next(iter(slugs.values()), {}))[:300])
gr = [k for k in slugs if k and re.search(r"stoix|novi|opap|betano|bwin|bet365|pinn", k, re.I)]
print("  σχετικά slugs:", gr[:20])


def first_fixture(sport_id, hint=None):
    t = get("/tournaments", sportId=sport_id) or []
    if not isinstance(t, list) or not t:
        return None, None
    t = sorted(t, key=lambda x: -(x.get("upcomingFixtures") or 0) - (x.get("futureFixtures") or 0) * 0.01)
    print("  κορυφαία τουρνουά:", [(x.get("tournamentName"), x.get("tournamentId"), x.get("upcomingFixtures"), x.get("futureFixtures")) for x in t[:4]])
    for tt in t[:3]:
        f = get("/fixtures", tournamentId=tt.get("tournamentId"))
        if isinstance(f, list) and f:
            f2 = [x for x in f if x.get("hasOdds")] or f
            print("  fixture:", {k: f2[0].get(k) for k in ("fixtureId", "participant1Name", "participant2Name", "startTime", "hasOdds")})
            return f2[0], tt
    return None, None


def odds_summary(fx, bookmakers=None, label=""):
    if not fx:
        print(f"  [{label}] δεν βρέθηκε fixture")
        return
    p = {"fixtureId": fx["fixtureId"], "verbosity": 3}
    if bookmakers:
        p["bookmakers"] = bookmakers
    d = get("/odds", **p)
    if not isinstance(d, dict):
        return
    bo = d.get("bookmakerOdds") or {}
    print(f"  [{label}] πρακτορεία με τιμές:", len(bo), sorted(bo.keys())[:25])
    per = {}
    for slug, v in bo.items():
        per[slug] = len((v.get("markets") or {}))
    print(f"  [{label}] αγορές ανά πρακτορείο (κορυφαία):", sorted(per.items(), key=lambda x: -x[1])[:8])
    return d


print("== 4) ΠΟΔΟΣΦΑΙΡΟ: κόρνερ/κάρτες")
sid = ids.get("Soccer") or ids.get("Football") or 10
fx, _t = first_fixture(sid)
mk = get("/markets") or []
names = {}
for m in mk if isinstance(mk, list) else []:
    mid = m.get("marketId") or m.get("id")
    names[str(mid)] = m.get("marketName") or m.get("name") or ""
print("  αγορές σύνολο:", len(names))
corner = {k: v for k, v in names.items() if re.search(r"corner", v, re.I)}
cards = {k: v for k, v in names.items() if re.search(r"card|booking", v, re.I)}
print("  corner αγορές:", len(corner), list(corner.items())[:6])
print("  card/booking αγορές:", len(cards), list(cards.items())[:6])
d = odds_summary(fx, label="soccer")
if d:
    seen = {}
    for slug, v in (d.get("bookmakerOdds") or {}).items():
        for mid, m in (v.get("markets") or {}).items():
            if str(mid) in corner:
                seen.setdefault("corners", set()).add(slug)
            if str(mid) in cards:
                seen.setdefault("cards", set()).add(slug)
    print("  πρακτορεία με κόρνερ/κάρτες σε αυτό το fixture:", {k: sorted(v)[:15] for k, v in seen.items()})

print("== 5) NFL")
nid = ids.get("American Football") or ids.get("NFL") or 14
fx, _t = first_fixture(nid)
odds_summary(fx, label="nfl")

print("== 6) ΤΕΝΙΣ")
tid = ids.get("Tennis") or 13
fx, _t = first_fixture(tid)
odds_summary(fx, label="tennis")
print("== ΤΕΛΟΣ")
