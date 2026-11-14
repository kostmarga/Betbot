"""Κανόνες που μάθαμε από τα λάθη + κείμενο «γιατί» για κάθε επιλογή.

ΚΑΘΕ ΚΑΝΟΝΑΣ ΕΧΕΙ ΗΜΕΡΟΜΗΝΙΑ ΚΑΙ ΑΙΤΙΑ. Όταν προσθέτεις νέο κανόνα μετά από ένα
χαμένο δελτίο, γράψε κι εσύ από πάνω τι έγινε. Οι τιμές ρυθμίζονται στο config.yaml → rules.

c["blocked"] περιέχει:
  "recommended" → δεν μπαίνει στο Προτεινόμενο δελτίο
  "safe"        → δεν μπαίνει στη λίστα Safe
  "slips"       → δεν μπαίνει σε κανένα δελτίο (μένει μόνο ως πληροφορία)
c["warnings"]  → εμφανίζονται με ⚠️ δίπλα στην επιλογή
"""
from __future__ import annotations

from . import movement
from .models import COUNT_LABEL, PROP_LABEL

WIN_SELECTIONS = {("1X2", "1"): "home", ("1X2", "2"): "away", ("ML", "HOME"): "home", ("ML", "AWAY"): "away",
                  ("SPREAD", "HOME"): "home", ("SPREAD", "AWAY"): "away"}
ATTACK = {"F", "M"}


def apply(c, ctx, cfg):
    R = cfg["rules"]
    side = WIN_SELECTIONS.get((c["market"], c["selection"]))
    team = ctx.home if side == "home" else ctx.away if side == "away" else None

    # ── Κανόνας 1 (05/11/2026 – Atalanta 1-1 με Kairat): φαβορί σε κακή φόρμα → όχι «νίκη»
    if team and c["sport"] == "football":
        ppg = ctx.ppg(team)
        if ppg is not None and ppg < R["min_ppg_for_win"]:
            c["blocked"] |= {"recommended", "safe"}
            c["warnings"].append(f"{team}: κακή φόρμα ({ppg:.1f} β/ματς στα 5 τελευταία)")
    if team and c["sport"] == "basketball":
        form = ctx.form_home if side == "home" else ctx.form_away
        if form:
            wins = sum(1 for f in form[:5] if f["r"] == "Ν") / min(5, len(form))
            if wins < R["min_basket_win_rate"]:
                c["blocked"] |= {"recommended", "safe"}
                c["warnings"].append(f"{team}: {wins * 100:.0f}% νίκες στα 5 τελευταία")

    # ── Κανόνας 2 (05/11/2026 – Leverkusen 0-1 με 8 απουσίες): πολλές απουσίες στην επίθεση
    heavy = []
    for t in (ctx.home, ctx.away):
        ab = ctx.absences(t)
        att = [a for a in ab if (a.get("position") or "") in ATTACK]
        if len(ab) >= R["max_absences"] or len(att) >= R["max_attack_absences"]:
            heavy.append((t, len(ab), len(att)))
    if heavy:
        txt = "; ".join(f"{t}: {n} απουσίες ({na} επιθετικοί/μέσοι)" for t, n, na in heavy)
        if (c["market"] in ("OU", "TOTAL") and c["selection"] == "OVER") or (c["market"] == "BTTS" and c["selection"] == "YES"):
            c["blocked"] |= {"recommended", "safe"}
            c["warnings"].append(txt)
        if team and any(h[0] == team for h in heavy):
            c["blocked"] |= {"recommended", "safe"}
            c["warnings"].append(txt)

    # ── Κανόνας 7 (14/11/2026 – ο έλεγχος τραυματισμών πρέπει να ΑΠΟΦΑΣΙΖΕΙ): βασικός/κορυφαίος παίκτης της ομάδας που στοιχηματίζουμε
    # λείπει ή είναι αμφίβολος → όχι στο Προτεινόμενο/Safe. (Δεν έχει backtest: δεν υπάρχει δωρεάν ιστορικό τραυματισμών· είναι κανόνας προσοχής.)
    if team:
        ka = ctx.key_absences(team)
        if ka:
            c["blocked"] |= {"recommended", "safe"}
            c["warnings"].append(f"{team}: " + ", ".join(f"{p} ({'εκτός' if st == 'missing' else 'αμφίβολος'})" for p, st in ka[:3]) + " — βασικός παίκτης")

    # ── Κανόνας 8 (14/11/2026): μεγάλη αλλαγή στην ενδεκάδα/πεντάδα της ομάδας που στοιχηματίζουμε (rotation) → όχι στο Προτεινόμενο/Safe
    if team:
        ctx.lineup_note()
        need_ch = 3 if c["sport"] == "basketball" else 6
        ch = ctx.rotation.get(team)
        if ch is not None and ch >= need_ch:
            c["blocked"] |= {"recommended", "safe"}
            c["warnings"].append(f"{team}: {ch} αλλαγές στην αρχική {'πεντάδα' if c['sport'] == 'basketball' else 'ενδεκάδα'} (rotation)")

    # ── Κανόνας 3 (05/11/2026 – Efes/Hapoel/ASVEL όλοι έχασαν): μπάσκετ ≠ «σίγουρο»
    if c["sport"] == "basketball" and c["market"] == "ML" and (c["odds"] or 9) < R["basket_min_ml_odds_safe"]:
        c["blocked"].add("safe")

    # ── Κανόνας 4 (05/11/2026 – Pavlidis στον πάγκο): παίκτες μόνο με ενδεκάδα
    if c["market"] == "PLAYER":
        if not c["extra"].get("confirmed"):
            c["blocked"] |= {"recommended", "safe", "slips"}
            c["warnings"].append("δεν έχει βγει ακόμα ενδεκάδα – έλεγξε ότι ξεκινάει")

    # ── Κανόνας 5: η αγορά πάει κόντρα (απόδοση ανεβαίνει πολύ)
    mv = c.get("move")
    if mv and mv["pct"] >= R["max_drift_against"]:
        c["blocked"] |= {"recommended", "safe"}
        c["warnings"].append(f"η απόδοση ανέβηκε {mv['pct'] * 100:.0f}% (από {mv['open']:.2f} σε {mv['now']:.2f})")

    # ── Κανόνας 6: πολύ μικρό δείγμα για κόρνερ/κάρτες/πλάγια
    if c["family"] in ("corners", "cards", "throw_ins"):
        metric = c["family"]
        cm = ctx.counts.get(metric)
        if cm is None:
            c["blocked"].add("slips")


def reasons(c, ctx, count_models) -> list[str]:
    """Σύντομες προτάσεις «γιατί» με βάση τα στατιστικά."""
    out = []
    H, A = ctx.home, ctx.away
    fam = c["family"]

    def form_line(team, form):
        if not form:
            return None
        f = form[:10]
        gf = sum(x["gf"] for x in f) / len(f)
        ga = sum(x["ga"] for x in f) / len(f)
        rec = "".join(x["r"] for x in f)
        unit = "πόντ." if ctx.sport == "basketball" else "γκολ"
        return f"{team}: φόρμα {rec} · {gf:.1f} {unit} υπέρ / {ga:.1f} κατά ανά ματς"

    if fam in ("result", "goals", "points"):
        for t, fo in ((H, ctx.form_home), (A, ctx.form_away)):
            s = form_line(t, fo)
            if s:
                out.append(s)
        if fam == "goals":
            for t, fo in ((H, ctx.form_home), (A, ctx.form_away)):
                if fo:
                    f = fo[:10]
                    if c["market"] == "OU":
                        hit = sum(1 for x in f if (x["gf"] + x["ga"] > c["line"]) == (c["selection"] == "OVER"))
                        out.append(f"{t}: {hit}/{len(f)} τελευταία ματς έβγαλαν «{c['label']}»")
                    else:
                        hit = sum(1 for x in f if ((x["gf"] > 0 and x["ga"] > 0) == (c["selection"] == "YES")))
                        out.append(f"{t}: {hit}/{len(f)} τελευταία ματς έβγαλαν «{c['label']}»")
        if ctx.h2h:
            out.append("H2H (τελευταία " + str(len(ctx.h2h[:5])) + "): " + ", ".join(m["score"] for m in ctx.h2h[:5]))
        if ctx.exp:
            out.append(f"Μοντέλο: αναμενόμενο {ctx.exp}")
    elif fam in ("corners", "cards", "throw_ins"):
        cm = count_models.get(fam)
        pr = ctx.counts.get(fam)
        lab = COUNT_LABEL[fam]
        if cm and pr:
            for t in (H, A):
                av = cm.team_avgs(t)
                if av:
                    s = f"{t}: {av['for']:.1f} {lab} υπέρ / {av['against']:.1f} κατά (τελευταία {av['n']})"
                    if c["market"] in ("CORNERS", "CARDS", "THROWINS"):
                        hit = sum(1 for x in av["totals"] if (x > c["line"]) == (c["selection"] == "OVER"))
                        s += f" · {hit}/{av['n']} ματς «{c['label']}»"
                    out.append(s)
            out.append(f"Μοντέλο: αναμένονται {pr['exp_total']:.1f} {lab} ({pr['exp_home']:.1f} – {pr['exp_away']:.1f})")
            if fam == "cards":
                ri = cm.referee_info(ctx.referee)
                if ri:
                    out.append(f"Διαιτητής {ri['name']}: {ri['avg']:.1f} κάρτες/ματς σε {ri['games']} ματς "
                               f"(×{ri['factor']:.2f} σε σχέση με τον μ.ο.)")
                elif ctx.referee:
                    out.append(f"Διαιτητής {ctx.referee}: δεν έχουμε αρκετά ματς του")
                else:
                    out.append("Διαιτητής: δεν έχει ανακοινωθεί ακόμα")
    elif fam == "players":
        e = c["extra"]
        st = e.get("stats", {})
        k = e.get("k")
        n = st.get("n")
        if st:
            out.append(f"{e['player']}: {st['per90']:.2f} {PROP_LABEL[e['prop']]}/90' · "
                       f"{st['hit'].get(k, 0)}/{n} τελευταία ματς με {k}+")
            out.append(f"Αναμενόμενα λεπτά: ~{e.get('exp_min', 0):.0f}'")
        out.append("Ενδεκάδα: επίσημα βασικός" if e.get("confirmed") else "Ενδεκάδα: πιθανός βασικός (όχι επίσημο)")

    # απουσίες
    for t in (H, A):
        ab = ctx.absences(t)
        if ab:
            names = ", ".join(a["player"] + (" (;)" if a["status"] == "doubtful" else "") for a in ab[:5])
            more = f" +{len(ab) - 5}" if len(ab) > 5 else ""
            out.append(f"Απουσίες {t}: {names}{more}")
    mv = c.get("move")
    if mv and abs(mv["pct"]) >= 0.04:
        out.append(f"Απόδοση {mv['open']:.2f} → {mv['now']:.2f}: {movement.describe(mv['pct'])}")
    return out
