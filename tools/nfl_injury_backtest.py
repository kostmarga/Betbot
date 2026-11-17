"""Backtest NFL: τιμολογεί η αγορά την απουσία του quarterback; (nflverse: αποτελέσματα + γραμμές + αναφορές τραυματισμών)
QB «εκτός» = ο βασικός QB της ομάδας (αυτός που ξεκίνησε τον προηγούμενο αγώνα της) είναι «Out/Doubtful» στην αναφορά της εβδομάδας.
Ελέγχουμε: (1) κάλυψη χάντικαπ της ομάδας με QB εκτός (αν η αγορά είναι σωστή = 50%), (2) Over/Under στο σύνολο.
Χρήση: python tools/nfl_injury_backtest.py > docs/nfl_injury_backtest.txt
"""
import csv
import io
import sys
from collections import defaultdict

sys.path.insert(0, ".")
from betbot.util import http_get  # noqa: E402


def csv_text(url):
    t, _ = http_get(url, expect="text", timeout=90, retries=2)
    return list(csv.DictReader(io.StringIO(t)))


def main():
    games = csv_text("https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv")
    games = [g for g in games if g["home_score"] not in ("", "NA") and g["spread_line"] not in ("", "NA") and g["game_type"] == "REG" and int(g["season"]) >= 2012]
    games.sort(key=lambda g: (int(g["season"]), int(g["week"])))
    inj = defaultdict(set)         # (season, week, team) -> {gsis_id QB με Out/Doubtful}
    seasons = sorted({int(g["season"]) for g in games})
    for s in seasons:
        try:
            for r in csv_text(f"https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{s}.csv"):
                if r["position"] == "QB" and r["report_status"] in ("Out", "Doubtful") and r["game_type"] == "REG":
                    inj[(s, int(r["week"]), r["team"])].add(r["gsis_id"])
        except Exception as e:
            print(f"# σεζόν {s}: χωρίς αναφορά ({str(e)[:60]})", file=sys.stderr)
    last_qb = {}
    R = []
    for g in games:
        s, w = int(g["season"]), int(g["week"])
        res = float(g["home_score"]) - float(g["away_score"])
        sp = float(g["spread_line"])                    # θετικό = φαβορί γηπεδούχος
        tot = float(g["total_line"]) if g["total_line"] not in ("", "NA") else None
        out = {}
        for side, team in (("home", g["home_team"]), ("away", g["away_team"])):
            q = last_qb.get(team)
            out[side] = bool(q and q in inj.get((s, w, team), set()))
            if g.get(f"{side}_qb_id") not in ("", "NA", None):
                last_qb[team] = g[f"{side}_qb_id"]
        if res - sp == 0:
            continue
        R.append({"home_out": out["home"], "away_out": out["away"], "home_cov": res > sp, "sp": sp, "tot": tot, "pts": float(g["home_score"]) + float(g["away_score"]), "res": res})
    print(f"Backtest QB εκτός (NFL, {seasons[0]}–{seasons[-1]}): {len(R)} αγώνες με γραμμή\n")
    only_h = [r for r in R if r["home_out"] and not r["away_out"]]
    only_a = [r for r in R if r["away_out"] and not r["home_out"]]
    cov = [r["home_cov"] for r in only_h] + [not r["home_cov"] for r in only_a]
    print(f"Ομάδα με τον βασικό QB εκτός/αμφίβολο (η άλλη πλήρης): n={len(cov)} · κάλυψε χάντικαπ {sum(cov) / max(len(cov), 1) * 100:.1f}% (αν η αγορά τιμολογούσε σωστά = 50%)")
    # μέσο σφάλμα γραμμής από την πλευρά της ομάδας με QB εκτός (θετικό = η ομάδα έκανε ΚΑΛΥΤΕΡΑ από τη γραμμή)
    err = [-(r["res"] - r["sp"]) for r in only_h] + [(r["res"] - r["sp"]) for r in only_a]
    print(f"   μέσο σφάλμα γραμμής: {sum(err) / max(len(err), 1):+.2f} πόντοι υπέρ της ομάδας με QB εκτός")
    clean = [r for r in R if not r["home_out"] and not r["away_out"]]
    print(f"Κανείς QB εκτός: n={len(clean)} · γηπεδούχος κάλυψε {sum(r['home_cov'] for r in clean) / len(clean) * 100:.1f}%")
    both = [r for r in R if r["home_out"] and r["away_out"]]
    print(f"Και οι δύο QB εκτός: n={len(both)}\n")
    print("Φαβορί (|spread|≥3) με τον QB τους εκτός — κάλυψη του ΦΑΒΟΡΙ:")
    fv = []
    for r in R:
        if abs(r["sp"]) < 3:
            continue
        home_fav = r["sp"] > 0
        fav_out = r["home_out"] if home_fav else r["away_out"]
        dog_out = r["away_out"] if home_fav else r["home_out"]
        fv.append((fav_out, dog_out, r["home_cov"] if home_fav else not r["home_cov"]))
    for lab, rows in (("φαβορί με QB εκτός (αουτσάιντερ πλήρης)", [x for x in fv if x[0] and not x[1]]),
                      ("αουτσάιντερ με QB εκτός (φαβορί πλήρες)", [x for x in fv if x[1] and not x[0]]),
                      ("κανείς", [x for x in fv if not x[0] and not x[1]])):
        if len(rows) >= 10:
            print(f"  {lab}: n={len(rows)}  φαβορί κάλυψε {sum(c for _, _, c in rows) / len(rows) * 100:.1f}%")
    print("\nΣύνολο πόντων (Over %):")
    for lab, rows in (("κάποιος QB εκτός", [r for r in R if (r["home_out"] or r["away_out"]) and r["tot"] and r["pts"] != r["tot"]]),
                      ("κανείς", [r for r in clean if r["tot"] and r["pts"] != r["tot"]])):
        if rows:
            print(f"  {lab}: n={len(rows)}  Over {sum(r['pts'] > r['tot'] for r in rows) / len(rows) * 100:.1f}%  μέσο σφάλμα {sum(r['pts'] - r['tot'] for r in rows) / len(rows):+.2f} πόντοι")


if __name__ == "__main__":
    main()
