"""Έλεγχος «σκιώδους» Συνδυαστικού (list_name = shadow_combo, shadow_combo~s, shadow_combo~b): ΔΕΝ εμφανίζεται στη σελίδα, φτιάχνεται και κρίνεται στο παρασκήνιο με εικονικά 2€.
Σύγκριση: πόσες νίκες περίμενε το μοντέλο (άθροισμα πιθανοτήτων δελτίων) και πόσες ήρθαν· ROI. Αξιόπιστο συμπέρασμα από 30+ κριθέντα δελτία.
Χρήση: python tools/shadow_combo_check.py <betbot.sqlite>   (η βάση είναι στο branch data: data/betbot.sqlite)
"""
import math
import sqlite3
import sys


def main(db):
    c = sqlite3.connect(db)
    rows = c.execute("select slip_id,status,total_odds,model_prob from slips where list_name like 'shadow_combo%' order by created_at").fetchall()
    done = [r for r in rows if r[1] in ("won", "lost")]
    print(f"Σκιώδες Συνδυαστικό: {len(rows)} δελτία συνολικά, {len(done)} κριθέντα, {len(rows) - len(done) - sum(1 for r in rows if r[1] == 'void')} ανοιχτά")
    if not done:
        print("Δεν έχει κριθεί ακόμα δελτίο.")
        return
    n = len(done)
    exp = sum(r[3] for r in done)
    won = sum(1 for r in done if r[1] == "won")
    sd = math.sqrt(sum(r[3] * (1 - r[3]) for r in done))
    pl = sum((2 * r[2] - 2) if r[1] == "won" else -2 for r in done)
    print(f"Νίκες: {won} (το μοντέλο περίμενε {exp:.1f} ± {sd:.1f}) · επιτυχία {won / n * 100:.0f}% · ROI {pl / (2 * n) * 100:+.0f}% ({pl:+.2f}€ από {2 * n}€)")
    print("Για σύγκριση, το κανονικό Συνδυαστικό μέχρι 17/11/2026: 2 νίκες στα 19, περίμενε ~4,1, ROI −57%.")
    if n < 30:
        print(f"ΑΝΑΜΟΝΗ: χρειάζονται 30 κριθέντα (έχουμε {n}).")
    elif won >= exp + sd and pl > 0:
        print("ΕΝΔΕΙΞΗ ΒΕΛΤΙΩΣΗΣ: πάνω από το αναμενόμενο και θετικό ROI — πρότεινε στον χρήστη να ξανανοίξει (lists.combo.enabled: true).")
    else:
        print("ΟΧΙ βελτίωση: μένει κλειστό ή αναθεωρούνται οι κανόνες του (λιγότερα σκέλη / υψηλότερη πιθανότητα ανά σκέλος).")


if __name__ == "__main__":
    main(sys.argv[1])
