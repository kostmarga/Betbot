"""Συνθετικά δεδομένα για δοκιμή χωρίς internet (python main.py --demo).

Οι ομάδες και οι παίκτες είναι ΦΑΝΤΑΣΤΙΚΟΙ, ώστε το demo να μη μπερδευτεί ποτέ με πραγματικό δελτίο.
Κάθε ομάδα έχει «αληθινές» δυνάμεις (γκολ, κόρνερ, κάρτες, πλάγια) και οι διαιτητές «αυστηρότητα».
Το «πρακτορείο» βγάζει αποδόσεις με margin ~6% και θόρυβο, και μια αρχική τιμή (open)
λίγο διαφορετική από την τρέχουσα, ώστε να φαίνονται κινήσεις αποδόσεων.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
from scipy.stats import nbinom, norm, poisson

from .db import LineupRow, Match, OddsRow, PlayerStat, TeamStat
from .util import iso

RNG = np.random.default_rng(7)
SYL = ["Ar", "Bel", "Cor", "Dar", "El", "Fen", "Gal", "Hel", "Ir", "Kal", "Lor", "Mor", "Nor", "Or", "Pel",
       "Ros", "Sal", "Tor", "Val", "Zan"]
FIRST = ["Alex", "Bruno", "Carl", "Dino", "Emil", "Filip", "Goran", "Hugo", "Ivo", "Jonas", "Kai", "Leon",
         "Milo", "Nico", "Otto", "Pavel", "Rafa", "Stefan", "Tomas", "Viktor"]
LAST = ["Arvo", "Brenn", "Castel", "Dorn", "Ekko", "Falk", "Grimm", "Holt", "Iske", "Jorr", "Krag", "Lund",
        "Marr", "Nyx", "Orsk", "Prax", "Quill", "Rook", "Sorr", "Tarn", "Ulme", "Vex", "Wold", "Yarr"]
POSITIONS = ["G", "D", "D", "D", "D", "M", "M", "M", "F", "F", "F", "D", "M", "F", "M", "F"]


def _names(prefix, n):
    out = set()
    while len(out) < n:
        out.add(f"{RNG.choice(SYL)}{RNG.choice(['ia', 'on', 'ville', 'ora', 'eus', 'ton'])} {prefix}")
    return sorted(out)


def _odds_from(probs, margin=0.06):
    noisy = np.clip(np.array(probs) * RNG.normal(1, 0.04, len(probs)), 0.01, None)
    noisy /= noisy.sum()
    return [round(1 / (p * (1 + margin)), 2) for p in noisy]


def _nb(mu, phi=1.3):
    r = mu / (phi - 1)
    return int(nbinom.rvs(r, r / (r + mu), random_state=RNG))


def _ou_probs(mu, line, phi):
    r = mu / (phi - 1)
    over = 1 - nbinom.cdf(int(np.floor(line)), r, r / (r + mu))
    return [over, 1 - over]


def populate(db, cfg, now) -> str:
    matches, odds, tstats, pstats, lineups = [], [], [], [], []
    fetched = iso(now)
    earlier = iso(now - timedelta(hours=9))
    fb_leagues = [lg for lg in cfg["leagues"] if lg["sport"] == "football" and lg.get("fdco")]
    teams_by_lg, S, squads = {}, {}, {}
    for k, lg in enumerate(fb_leagues):
        names = _names(["FC", "United", "City", "Athletic", "Sporting", "Rovers"][k % 6], 16)
        teams_by_lg[lg["id"]] = names
        lvl = 0.25 - 0.08 * k
        for n in names:
            S[n] = {"att": RNG.normal(lvl, 0.25), "def": RNG.normal(lvl, 0.22),
                    "cor": RNG.normal(1, 0.18), "cor_ag": RNG.normal(1, 0.15),
                    "crd": RNG.normal(1, 0.22), "thr": RNG.normal(1, 0.10), "thr_ag": RNG.normal(1, 0.08)}
            used = set()
            squad = []
            for pos in POSITIONS:
                while True:
                    nm = f"{RNG.choice(FIRST)} {RNG.choice(LAST)}"
                    if nm not in used:
                        used.add(nm)
                        break
                rate = {"G": 0.02, "D": 0.35, "M": 0.9, "F": 1.9}[pos] * RNG.uniform(0.6, 1.5)
                squad.append({"name": nm, "pos": pos, "shots90": rate, "sot_share": RNG.uniform(0.3, 0.5),
                              "fouls90": {"G": 0.1, "D": 1.2, "M": 1.3, "F": 0.9}[pos] * RNG.uniform(0.6, 1.6),
                              "card90": RNG.uniform(0.05, 0.3)})
            squads[n] = squad
    referees = {f"Ref {RNG.choice(LAST)} {i}": RNG.normal(1, 0.25) for i in range(14)}
    ref_names = list(referees)

    def sim_fb(h, a):
        lh = np.exp(0.15 + 0.22 + S[h]["att"] - S[a]["def"])
        la = np.exp(0.15 + S[a]["att"] - S[h]["def"])
        return lh, la

    def exp_counts(h, a, ref=None):
        ch = 5.4 * S[h]["cor"] * S[a]["cor_ag"]; ca = 4.4 * S[a]["cor"] * S[h]["cor_ag"]
        f = referees.get(ref, 1.0)
        yh = 1.9 * S[h]["crd"] * f; ya = 2.2 * S[a]["crd"] * f
        th = 21 * S[h]["thr"] * S[a]["thr_ag"]; ta = 20 * S[a]["thr"] * S[h]["thr_ag"]
        return (ch, ca), (yh, ya), (th, ta)

    mid = 0

    def add_finished(lg_id, h, a, ko):
        nonlocal mid
        mid += 1
        m_id = f"demo:{mid}"
        lh, la = sim_fb(h, a)
        gh, ga = int(RNG.poisson(lh)), int(RNG.poisson(la))
        matches.append(Match(m_id, "football", lg_id, iso(ko), h, a, gh, ga, "finished", "demo"))
        ref = RNG.choice(ref_names)
        (ch, ca), (yh, ya), (th, ta) = exp_counts(h, a, ref)
        for side, team, opp, g, c, y, t in ((1, h, a, gh, ch, yh, th), (0, a, h, ga, ca, ya, ta)):
            sh = _nb(12 * np.exp(S[team]["att"] * 0.6), 1.4)
            tstats.append(TeamStat(m_id, m_id, lg_id, iso(ko), team, opp, side, g, _nb(c, 1.35), _nb(y, 1.25),
                                   int(RNG.random() < 0.06), _nb(11, 1.2), sh, max(0, int(sh * RNG.uniform(.25, .45))),
                                   _nb(t, 1.08), round(RNG.uniform(35, 65), 1), ref, "demo"))
            for i, p in enumerate(squads[team]):
                starter = i < 11
                if not starter and RNG.random() < 0.45:
                    continue
                mins = int(RNG.integers(60, 91)) if starter else int(RNG.integers(10, 35))
                sh_ = int(RNG.poisson(p["shots90"] * mins / 90))
                pstats.append(PlayerStat(m_id, iso(ko), lg_id, team, p["name"], int(starter), mins, sh_,
                                         int(RNG.binomial(sh_, p["sot_share"])), int(RNG.poisson(p["fouls90"] * mins / 90)),
                                         int(RNG.random() < p["card90"] * mins / 90), int(RNG.poisson(p["shots90"] * 0.11 * mins / 90)),
                                         "demo"))

    for lg in fb_leagues:
        names = teams_by_lg[lg["id"]]
        for d in range(320, 0, -3):
            perm = RNG.permutation(names)
            for i in range(0, len(perm), 2):
                add_finished(lg["id"], perm[i], perm[i + 1], (now - timedelta(days=d)).replace(hour=18, minute=0, second=0))
    allfb = [n for v in teams_by_lg.values() for n in v]
    for d in range(300, 0, -14):
        perm = RNG.permutation(allfb)[:24]
        for i in range(0, 24, 2):
            add_finished("UCL", perm[i], perm[i + 1], (now - timedelta(days=d)).replace(hour=20, minute=0, second=0))

    # ---------- επερχόμενοι ----------
    def add_odds(m_id, market, sels, probs, line=None, margin=0.06, books=8):
        cur = _odds_from(probs, margin)
        for s, o in zip(sels, cur):
            drift = RNG.normal(0, 0.06)
            opn = round(max(1.02, o * (1 + drift)), 2)
            odds.append(OddsRow(m_id, market, s, line, opn, books, "demo", earlier, open_price=opn))
            odds.append(OddsRow(m_id, market, s, line, o, books, "demo", fetched, open_price=opn))

    up_i = 0
    for lg in fb_leagues:
        perm = RNG.permutation(teams_by_lg[lg["id"]])
        for i in range(0, 12, 2):
            h, a = perm[i], perm[i + 1]
            ko = (now + timedelta(hours=int(RNG.integers(3, 26)))).replace(minute=0, second=0)
            mid += 1
            up_i += 1
            m_id = f"demo:{mid}"
            matches.append(Match(m_id, "football", lg["id"], iso(ko), h, a, None, None, "scheduled", "demo"))
            ref = RNG.choice(ref_names)
            db.set_referee(m_id, ref, "demo")
            lh, la = sim_fb(h, a)
            mat = np.outer(poisson.pmf(range(11), lh), poisson.pmf(range(11), la))
            p1, px, p2 = np.tril(mat, -1).sum(), np.trace(mat), np.triu(mat, 1).sum()
            add_odds(m_id, "1X2", ["1", "X", "2"], [p1, px, p2])
            for s, pdc in zip(["1X", "X2", "12"], [p1 + px, px + p2, p1 + p2]):
                o = round(1 / (min(0.97, pdc * RNG.normal(1, 0.02)) * 1.04), 2)
                odds.append(OddsRow(m_id, "DC", s, None, max(1.02, o), 6, "demo", fetched))
            g = np.add.outer(np.arange(11), np.arange(11))
            for line in (1.5, 2.5, 3.5):
                ov = mat[g > line].sum()
                add_odds(m_id, "OU", ["OVER", "UNDER"], [ov, 1 - ov], line)
            bt = mat[1:, 1:].sum()
            add_odds(m_id, "BTTS", ["YES", "NO"], [bt, 1 - bt])
            (ch, ca), (yh, ya), (th, ta) = exp_counts(h, a, ref)
            if up_i % 2 == 0:                 # μερικά ματς έχουν αποδόσεις κόρνερ/καρτών/πλαγίων
                add_odds(m_id, "CORNERS", ["OVER", "UNDER"], _ou_probs(ch + ca, 9.5, 1.35), 9.5, 0.08, 1)
                add_odds(m_id, "CARDS", ["OVER", "UNDER"], _ou_probs(yh + ya, 4.5, 1.25), 4.5, 0.08, 1)
            if up_i % 4 == 0:
                add_odds(m_id, "THROWINS", ["OVER", "UNDER"], _ou_probs(th + ta, 40.5, 1.08), 40.5, 0.08, 1)
            # ενδεκάδες: επίσημες για τα μισά ματς, απουσίες για όλα
            confirmed = int(up_i % 2 == 1)
            for team in (h, a):
                sq = squads[team]
                n_miss = 6 if up_i == 3 and team == h else int(RNG.integers(0, 3))
                missing = list(RNG.choice(range(11), size=n_miss, replace=False)) if n_miss else []
                for j, p in enumerate(sq):
                    if j in missing:
                        lineups.append(LineupRow(m_id, team, p["name"], "missing", p["pos"],
                                                 RNG.choice(["τραυματισμός", "τιμωρία"]), 0, "demo", fetched))
                    elif confirmed and j < 11:
                        lineups.append(LineupRow(m_id, team, p["name"], "starter", p["pos"], None, 1, "demo", fetched))

    # ---------- μπάσκετ ----------
    for lg, base, n_t in (("NBA", 113, 20), ("EL", 82, 18)):
        names = _names("Hoops" if lg == "NBA" else "BC", n_t)
        st = {n: (RNG.normal(0, 4), RNG.normal(0, 4)) for n in names}
        sd = 11 if lg == "NBA" else 10
        for d in range(250, 0, -2):
            perm = RNG.permutation(names)
            for i in range(0, len(perm) - 1, 2):
                h, a = perm[i], perm[i + 1]
                hp = base + 2.5 + st[h][0] - st[a][1] + RNG.normal(0, sd)
                ap = base + st[a][0] - st[h][1] + RNG.normal(0, sd)
                if round(hp) == round(ap):
                    hp += 3
                mid += 1
                matches.append(Match(f"demo:{mid}", "basketball", lg, iso((now - timedelta(days=d)).replace(hour=21, minute=0, second=0)),
                                     h, a, int(round(hp)), int(round(ap)), "finished", "demo"))
        perm = RNG.permutation(names)
        for i in range(0, 10, 2):
            h, a = perm[i], perm[i + 1]
            ko = (now + timedelta(hours=int(RNG.integers(4, 26)))).replace(minute=0, second=0)
            mid += 1
            m_id = f"demo:{mid}"
            matches.append(Match(m_id, "basketball", lg, iso(ko), h, a, None, None, "scheduled", "demo"))
            eh = base + 2.5 + st[h][0] - st[a][1]
            ea = base + st[a][0] - st[h][1]
            ph = 1 - norm.cdf(0, eh - ea, sd * 1.41)
            add_odds(m_id, "ML", ["HOME", "AWAY"], [ph, 1 - ph], None, 0.05)
            line = round((eh + ea) * 2) / 2
            if line % 1 == 0:
                line += 0.5
            ov = 1 - norm.cdf(line, eh + ea, sd * 1.41)
            add_odds(m_id, "TOTAL", ["OVER", "UNDER"], [ov, 1 - ov], line, 0.05)
            sp = -round((eh - ea) * 2) / 2 - 0.5
            hc = 1 - norm.cdf(-sp, eh - ea, sd * 1.41)
            add_odds(m_id, "SPREAD", ["HOME", "AWAY"], [hc, 1 - hc], sp, 0.05)

    db.upsert_matches(matches)
    db.upsert_odds([o for o in odds if o.fetched_at == earlier])
    db.upsert_odds([o for o in odds if o.fetched_at != earlier])
    db.upsert_team_stats(tstats)
    db.upsert_player_stats(pstats)
    db.upsert_lineups(lineups)
    return (f"συνθετικά δεδομένα: {len(matches)} αγώνες, {len(odds)} αποδόσεις, {len(tstats)} γραμμές στατιστικών, "
            f"{len(pstats)} γραμμές παικτών (φανταστικές ομάδες/παίκτες)")
