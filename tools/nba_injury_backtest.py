"""Backtest NBA: ΤΙΜΟΛΟΓΕΙ η αγορά τους τραυματισμούς; (αν όχι, το veto «βασικός παίκτης εκτός» προστατεύει· αν ναι, δεν προσφέρει πλεονέκτημα)
Δεδομένα: ESPN summary για όλους τους τελειωμένους αγώνες NBA της βάσης (αυτή + προηγούμενη σεζόν): γραμμές κλεισίματος (πρώτος πάροχος του pickcenter)
και boxscore. «Αστέρι» ομάδας = ένας από τους 2 κορυφαίους σκόρερ των 10 τελευταίων αγώνων της (≥3 παρουσίες, ≥24' μέσο όρο). «Λείπει» = δεν έπαιξε (0 λεπτά/όχι στο boxscore).
Δεν χρησιμοποιούνται οι αναφορές τραυματισμών της εποχής (δεν υπάρχουν ιστορικά)· το «δεν έπαιξε» ΕΙΝΑΙ γνωστό πριν τον αγώνα στη μεγάλη πλειονότητα (εκτός ξαφνικών).
Χρήση: python tools/nba_injury_backtest.py <betbot.sqlite> > docs/nba_injury_backtest.txt
"""
import math
import os
import pickle
import sqlite3
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, ".")
from betbot.collectors.nba_box import parse_box  # noqa: E402
from betbot.util import http_get  # noqa: E402

SM = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
CACHE = "/tmp/claude-0/-home-user-Betbot/e24bde83-1419-549d-9411-52e6b1a81f97/scratchpad/nba_inj_cache.pkl"


def fetch(m):
    try:
        d, _ = http_get(SM, params={"event": m["match_id"][5:]}, timeout=25, retries=2)
    except Exception:
        return m["match_id"], None
    pc = (d.get("pickcenter") or [])
    odds = None
    if pc:
        o = pc[0]
        odds = {"spread": o.get("spread"), "total": o.get("overUnder"), "fav_home": (o.get("homeTeamOdds") or {}).get("favorite")}
    return m["match_id"], {"box": parse_box(d, m), "odds": odds}


def main(db):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    ms = [dict(r) for r in c.execute("select match_id,kickoff,home,away,home_score,away_score from matches where league='NBA' and status='finished' and match_id like 'espn:%' order by kickoff")]
    cache = pickle.load(open(CACHE, "rb")) if os.path.exists(CACHE) else {}
    todo = [m for m in ms if m["match_id"] not in cache]
    with ThreadPoolExecutor(8) as ex:
        for mid, v in ex.map(fetch, todo):
            if v:
                cache[mid] = v
    pickle.dump(cache, open(CACHE, "wb"))
    games = [(m, cache[m["match_id"]]) for m in ms if m["match_id"] in cache and cache[m["match_id"]]["box"]]
    print(f"Backtest τραυματισμών NBA: {len(games)} αγώνες με boxscore ({sum(1 for m, v in games if v['odds'] and v['odds']['spread'] is not None)} με γραμμή αγοράς)\n")
    # έλεγχος προσήμου: spread ESPN = γραμμή γηπεδούχου (αρνητική = φαβορί γηπεδούχος);  συσχέτιση με πραγματική διαφορά πρέπει να είναι αρνητική
    xs = [(v["odds"]["spread"], m["home_score"] - m["away_score"]) for m, v in games if v["odds"] and v["odds"]["spread"] is not None]
    mx, my = sum(x for x, _ in xs) / len(xs), sum(y for _, y in xs) / len(xs)
    cov = sum((x - mx) * (y - my) for x, y in xs); vx = sum((x - mx) ** 2 for x, _ in xs); vy = sum((y - my) ** 2 for _, y in xs)
    print(f"Έλεγχος προσήμου χάντικαπ: συσχέτιση spread–διαφορά {cov / math.sqrt(vx * vy):+.2f} (αναμένεται ΑΡΝΗΤΙΚΗ)\n")
    hist = defaultdict(list)        # ομάδα -> [{player: (min, pts)}] πρόσφατοι αγώνες
    R = []
    for m, v in games:
        by_team = defaultdict(dict)
        for r in v["box"]:
            by_team[r["team"]][r["player"]] = (r["minutes"] or 0, r["points"] or 0)
        teams = list(by_team)
        info = {}
        for t in teams:
            past = hist[t][-10:]
            if len(past) >= 6:
                agg = defaultdict(lambda: [0, 0.0, 0.0])
                for g in past:
                    for p, (mn, pt) in g.items():
                        if mn > 0:
                            a = agg[p]; a[0] += 1; a[1] += mn; a[2] += pt
                cand = [(a[2] / a[0], p) for p, a in agg.items() if a[0] >= 3 and a[1] / a[0] >= 24]
                stars = [p for _, p in sorted(cand, reverse=True)[:2]]
                missing = [p for p in stars if by_team[t].get(p, (0, 0))[0] == 0]
                info[t] = (stars, missing)
        for t in teams:
            hist[t].append(by_team[t])
        o = v["odds"]
        if not o or o["spread"] is None or len(info) < 2:
            continue
        # ομάδα με όνομα όπως στο boxscore (team displayName) -> ποια είναι γηπεδούχος
        th = next((t for t in teams if t.lower() in m["home"].lower() or m["home"].lower() in t.lower()), None)
        ta = next((t for t in teams if t != th), None)
        if th is None or th not in info or ta not in info:
            continue
        margin = m["home_score"] - m["away_score"]
        cover_h = margin + o["spread"]                      # >0: ο γηπεδούχος κάλυψε
        if cover_h == 0:
            continue
        R.append({"mh": len(info[th][1]), "ma": len(info[ta][1]), "cover_h": cover_h > 0, "spread": o["spread"], "total": o["total"], "pts": m["home_score"] + m["away_score"]})
    n = len(R)
    print(f"{n} αγώνες με γραμμή + ιστορικό 6+ αγώνων και για τις δύο ομάδες\n")

    def rate(rows, f):
        return (sum(f(r) for r in rows) / len(rows) * 100) if rows else float("nan")

    # Κάλυψη χάντικαπ ανά αριθμό αστέρων που λείπουν από κάθε ομάδα
    print("Κάλυψη χάντικαπ της ομάδας ΜΕ απόντες (αν η αγορά τιμολογούσε σωστά = 50%):")
    for k in (1, 2):
        sub_h = [r for r in R if r["mh"] >= k and r["ma"] == 0]          # μόνο ο γηπεδούχος έχει απόντες
        sub_a = [r for r in R if r["ma"] >= k and r["mh"] == 0]
        team_cov = [not r["cover_h"] for r in sub_a] + [r["cover_h"] for r in sub_h]
        if team_cov:
            print(f"  ≥{k} αστέρι εκτός (η άλλη ομάδα πλήρης): n={len(team_cov)}  η ομάδα με τους απόντες κάλυψε {sum(team_cov) / len(team_cov) * 100:.1f}%")
    both = [r for r in R if r["mh"] >= 1 and r["ma"] >= 1]
    none = [r for r in R if r["mh"] == 0 and r["ma"] == 0]
    print(f"  και οι δύο με απόντες: n={len(both)} · κανείς: n={len(none)} (γηπεδούχος κάλυψε {rate(none, lambda r: r['cover_h']):.1f}%)")
    print("\nΣύνολο πόντων (Over %, αν η αγορά τιμολογούσε σωστά = ~50%):")
    for name, rows in (("κανείς εκτός", none), ("εκτός ≥1 αστέρι σε κάποια ομάδα", [r for r in R if r["mh"] + r["ma"] >= 1]),
                       ("εκτός ≥2 αστέρια συνολικά", [r for r in R if r["mh"] + r["ma"] >= 2])):
        rows = [r for r in rows if r["total"] and r["pts"] != r["total"]]
        if rows:
            print(f"  {name}: n={len(rows)}  Over {rate(rows, lambda r: r['pts'] > r['total']):.1f}%  (μέσο σφάλμα {sum(r['pts'] - r['total'] for r in rows) / len(rows):+.1f} πόντοι)")
    print("\nΦαβορί (|spread|≥5) όταν ΤΟ ΦΑΒΟΡΙ έχει απόντες vs όταν δεν έχει — κάλυψη του φαβορί:")
    fav = []
    for r in R:
        if abs(r["spread"]) < 5:
            continue
        home_fav = r["spread"] < 0
        fm = r["mh"] if home_fav else r["ma"]
        fc = r["cover_h"] if home_fav else not r["cover_h"]
        fav.append((fm, fc))
    for lab, rows in (("φαβορί με ≥1 αστέρι εκτός", [x for x in fav if x[0] >= 1]), ("φαβορί πλήρες", [x for x in fav if x[0] == 0])):
        if rows:
            print(f"  {lab}: n={len(rows)} κάλυψε {sum(c for _, c in rows) / len(rows) * 100:.1f}%")


if __name__ == "__main__":
    main(sys.argv[1])
