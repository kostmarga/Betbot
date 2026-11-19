"""Έλεγχος ΟΛΩΝ των «σκιωδών» ταμείων (list_name = shadow_<όνομα>[~s|~b]) σε σύγκριση με το κανονικό Προτεινόμενο της ίδιας περιόδου.
Τα σκιώδη ΔΕΝ εμφανίζονται στη σελίδα· φτιάχνονται και κρίνονται στο παρασκήνιο με εικονικά 2€ (βλ. config.yaml: shadow:, lists.combo.shadow).
Για κάθε ταμείο: δελτία, κριθέντα, νίκες vs αναμενόμενες (άθροισμα πιθανοτήτων), επιτυχία, ROI, ημέρες με δελτίο vs ημέρες που έτρεξε ο bot.
Αξιόπιστο συμπέρασμα από 30+ κριθέντα δελτία ανά ταμείο.
Χρήση: python tools/shadow_check.py <betbot.sqlite>   (η βάση είναι στο branch data: data/betbot.sqlite)
"""
import math
import re
import sqlite3
import sys


def stats(rows):
    done = [r for r in rows if r[1] in ("won", "lost")]
    n = len(done)
    if not n:
        return None
    exp = sum(r[3] for r in done)
    won = sum(1 for r in done if r[1] == "won")
    sd = math.sqrt(sum(r[3] * (1 - r[3]) for r in done))
    pl = sum((2 * r[2] - 2) if r[1] == "won" else -2 for r in done)
    return {"n": n, "won": won, "exp": exp, "sd": sd, "roi": pl / (2 * n), "pl": pl, "avg_odds": sum(r[2] for r in done) / n}


def line(name, rows, days_all, since):
    allr = [r for r in rows]
    days = {r[0].split("#")[0] for r in allr}
    open_n = sum(1 for r in allr if r[1] == "open")
    s = stats(allr)
    head = f"{name:22s} δελτία {len(allr):3d} σε {len(days):2d}/{len(days_all)} ημέρες (ανοιχτά {open_n})"
    if not s:
        return head + " · κανένα κριθέν ακόμα"
    return (head + f" · κριθέντα {s['n']:3d} · νίκες {s['won']:2d} (αναμενόταν {s['exp']:.1f}±{s['sd']:.1f}) · επιτυχία {s['won'] / s['n'] * 100:3.0f}% · "
            f"μέση απόδοση {s['avg_odds']:.2f} · ROI {s['roi'] * 100:+4.0f}% ({s['pl']:+.1f}€)")


def main(db):
    c = sqlite3.connect(db)
    q = "select slip_id,status,total_odds,model_prob,list_name,created_at from slips where list_name {} order by created_at"
    shadow = c.execute(q.format("like 'shadow_%'")).fetchall()
    if not shadow:
        print("Δεν υπάρχουν ακόμα σκιώδη δελτία.")
        return
    since = min(r[5] for r in shadow)[:10]
    days_all = {r[0][:10] for r in c.execute("select slip_id from slips where created_at>=? and slip_id like '____-__-__#%'", (since,))}
    base = [r for r in c.execute(q.format("in ('recommended')")) if r[5][:10] >= since and "+" not in r[0]]
    print(f"Σύγκριση από {since} ({len(days_all)} ημέρες λειτουργίας του bot)\n")
    print(line("ΚΑΝΟΝΙΚΟ Προτεινόμενο", [(r[0], r[1], r[2], r[3]) for r in base], days_all, since))
    groups = {}
    for r in shadow:
        groups.setdefault(re.sub(r"~[sb]$", "", r[4]), []).append((r[0], r[1], r[2], r[3]))
    for name, rows in sorted(groups.items()):
        print(line(name, rows, days_all, since))
    print("\nΑν ένα σκιώδες έχει 30+ κριθέντα ΚΑΙ νίκες ≥ αναμενόμενες+1σ ΚΑΙ ROI > του κανονικού, πρότεινέ το στον χρήστη. Αλλιώς μένει κλειστό.")


if __name__ == "__main__":
    main(sys.argv[1])
