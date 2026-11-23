"""Έλεγχος της «μάθησης»: (α) ποιες διορθώσεις θα εφαρμόζονταν τώρα, (β) εκτίμηση συσχέτισης σκελών (ίδια λίγκα/ίδιος τύπος αγοράς).
Χρήση:  python tools/learn_check.py [data/betbot.sqlite]
Το ρ των ζευγαριών υπολογίζεται από τα residuals (νίκη − p) ανά ημέρα· τα ζευγάρια επικαλύπτονται, άρα είναι ένδειξη και όχι ακριβής μέτρηση."""
import itertools
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import yaml

from betbot import insights, learn
from betbot.db import DB

path = sys.argv[1] if len(sys.argv) > 1 else "data/betbot.sqlite"
cfg = yaml.safe_load(open(Path(__file__).resolve().parent.parent / "config.yaml", encoding="utf-8"))
db = DB(path)
legs = learn.settled_legs(db)
print(f"Κριθέντα μοναδικά σκέλη: {len(legs)}\n")
t = learn.build_table(db, cfg)
print("Διορθώσεις (μονάδες πιθανότητας):")
for r in learn.report_rows(t, cfg)[:15]:
    print(f"  {r['k']}: {r['v']:<22} {r['w']}/{r['n']} (περ. {r['e']:.0f}) z={r['z']:+.1f}  διόρθωση {r['adj']:+.1f}")


def res(l):
    p = l.get("p_base") or l["p"]
    return (1.0 if l["result"] == "won" else 0.0) - p, math.sqrt(p * (1 - p))


def rho(name, same):
    num = den = n = 0
    for a, b in itertools.combinations(legs, 2):
        if a["match_id"] == b["match_id"] or a["kickoff"][:10] != b["kickoff"][:10] or not same(a, b):
            continue
        ra, sa = res(a); rb, sb = res(b)
        num += ra * rb; den += sa * sb; n += 1
    print(f"  {name:<28} ζευγάρια {n:>5}  ρ = {num / den:+.3f}" if den else f"  {name}: —")


print("\nΣυσχέτιση αποτελεσμάτων (ίδια ημέρα):")
rho("ίδια λίγκα", lambda a, b: a["league"] == b["league"])
rho("ίδιος τύπος αγοράς", lambda a, b: insights.grp(a) == insights.grp(b))
rho("διαφορετικά και τα δύο", lambda a, b: a["league"] != b["league"] and insights.grp(a) != insights.grp(b))
print("\nΤρέχουσες ρυθμίσεις:", cfg.get("correlation"))
