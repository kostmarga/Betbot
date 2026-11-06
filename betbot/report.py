"""Αναφορά: μία HTML σελίδα με καρτέλες (dashboards) + email.

Καρτέλες: ⭐ Προτεινόμενο · 🛡️ Safe · 🎯 10+ · 🔥 30+ · 🎰 100+ · ⚽ Over · 🚩 Κόρνερ ·
          🟨 Κάρτες · ↔️ Πλάγια · 👤 Παίκτες · 🔀 Συνδυαστικό · 📉 Κινήσεις · 📊 Ιστορικό · ⚙️ Πηγές

Η σελίδα γράφεται στο docs/index.html (GitHub Pages) + docs/archive/ΗΗΗΗ-ΜΜ-ΗΗ.html.
Διαγράμματα: Chart.js (CDN). Χρώματα: validated παλέτα (μπλε = μοντέλο, πορτοκαλί = αγορά).
"""
from __future__ import annotations

import html
import io
import json
import math
import os
from collections import defaultdict
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .util import parse_iso

BLUE, ORANGE, MUTED = "#2a78d6", "#eb6834", "#898781"
SERIES = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)", "var(--s6)", "var(--s7)", "var(--s8)"]
E = html.escape

TABS = [
    ("today", "🎯 Σήμερα"), ("recommended", "⭐ Προτεινόμενο"), ("safe", "🛡️ Safe"), ("x10", "🎯 10+"), ("x30", "🔥 30+"),
    ("x100", "🎰 100+"), ("overs", "⚽ Over"), ("corners", "🚩 Κόρνερ"), ("cards", "🟨 Κάρτες"),
    ("throw_ins", "↔️ Πλάγια"), ("players", "👤 Παίκτες"), ("combo", "🔀 Συνδυαστικό"),
    ("moves", "📉 Κινήσεις"), ("history", "📊 Ιστορικό"), ("sources", "⚙️ Πηγές"),
]
LIST_NAMES = dict(TABS) | {"single": "⭐ Μονό της ημέρας", "safe1": "🛡️ Safe (μονά)",
                           "fair_corners": "🚩 Κόρνερ (δίκαιη)", "fair_cards": "🟨 Κάρτες (δίκαιη)",
                           "fair_throw_ins": "↔️ Πλάγια (δίκαιη)", "fair_players": "👤 Παίκτες (δίκαιη)"}


def _local(iso_s, tz):
    return parse_iso(iso_s).astimezone(ZoneInfo(tz))


def _pct(x):
    return "—" if x is None else f"{x * 100:.0f}%"


GR_DAYS = ["Δευ", "Τρι", "Τετ", "Πεμ", "Παρ", "Σαβ", "Κυρ"]


def _when(iso_s, tz):
    d = _local(iso_s, tz)
    return f"{GR_DAYS[d.weekday()]} {d:%H:%M}"


def _badges(form):
    cls = {"Ν": "w", "Ι": "d", "Η": "l"}
    return "".join(f'<span class="fb {cls[f["r"]]}" title="{E(f["date"])} {f["venue"]} vs {E(f["opp"])} '
                   f'{f["gf"]}-{f["ga"]}">{f["r"]}</span>' for f in reversed(form[:6])) or "—"


class Page:
    def __init__(self, cfg):
        self.cfg = cfg
        self.tz = cfg["timezone"]
        self.charts = []
        self.n = 0

    def chart(self, cfg, small=False):
        self.n += 1
        cid = f"c{self.n}"
        self.charts.append((cid, cfg))
        return f'<div class="chart{" sm" if small else ""}"><canvas id="{cid}" role="img"></canvas></div>'

    # ---------------- μία επιλογή ----------------
    def pick_row(self, c, show_fair=True):
        odds_cell = f"<b>{c['odds']:.2f}</b>" if c.get("odds") else \
            (f"<span class='muted'>δίκαιη {c['fair_odds']:.2f}</span><br><b>παίξ' το αν ≥ {c['play_if']:.2f}</b>"
             if c.get("play_if") else "—")
        edge = c.get("edge")
        edge_cell = f"<span class='{'pos' if edge > 0 else 'neg'}'>{edge * 100:+.1f}%</span>" if edge is not None else "—"
        mv = c.get("move")
        mv_cell = ""
        if mv and abs(mv["pct"]) >= 0.04:
            arrow = "▼" if mv["pct"] < 0 else "▲"
            mv_cell = f"<span class='mv {'dn' if mv['pct'] < 0 else 'up'}' title='{mv['open']:.2f} → {mv['now']:.2f}'>" \
                      f"{arrow}{abs(mv['pct']) * 100:.0f}%</span>"
        warn = "".join(f"<div class='wr'>⚠️ {E(w)}</div>" for w in c.get("warnings", []))
        why = "".join(f"<li>{E(w)}</li>" for w in c.get("why", []))
        form = ""
        if c.get("form_home") or c.get("form_away"):
            form = f"<p class='muted'>{E(c['home'])}: {_badges(c.get('form_home', []))} &nbsp; " \
                   f"{E(c['away'])}: {_badges(c.get('form_away', []))}</p>"
        return f"""<tr>
<td class="t">{_when(c['kickoff'], self.tz)}</td>
<td><b>{E(c['home'])}</b> – <b>{E(c['away'])}</b><br><span class="muted">{E(c['league_name'])}</span></td>
<td>{E(c['label'])} {mv_cell}{warn}
<details><summary>Γιατί;</summary><ul class="why">{why}</ul>{form}</details></td>
<td class="n" data-l="Απόδ.">{odds_cell}</td><td class="n" data-l="Πιθαν."><b>{_pct(c['p'])}</b></td><td class="n" data-l="Value">{edge_cell}</td></tr>"""

    def pick_table(self, picks, empty="Καμία επιλογή σήμερα."):
        if not picks:
            return f"<p class='muted'>{empty}</p>"
        rows = "".join(self.pick_row(c) for c in picks)
        return ("<div class='tbl'><table class='picks'><thead><tr><th>Ώρα</th><th>Αγώνας</th><th>Επιλογή</th><th>Απόδ.</th>"
                f"<th>Πιθαν.</th><th>Value</th></tr></thead><tbody>{rows}</tbody></table></div>")

    # ---------------- δελτίο ----------------
    def slip_block(self, sl, title, stake=None, note=""):
        if not sl:
            return (f"<div class='card'><h3>{E(title)}</h3><p class='muted'>Δεν βγήκε δελτίο σήμερα: δεν υπήρχαν αρκετές "
                    "επιλογές που να περνούν τους κανόνες για αυτό το εύρος απόδοσης. Αυτό είναι καλό σημάδι – "
                    "το bot δεν «γεμίζει» δελτία με αδύναμες επιλογές.</p></div>")
        stake_txt = f"<div class='tile'><div class='k'>Ποντάρισμα</div><div class='v'>{stake:.2f}€</div></div>" if stake else ""
        ret = f"<div class='tile'><div class='k'>Αν κερδίσει</div><div class='v pos'>{stake * sl['total_odds']:.2f}€</div></div>" if stake else ""
        pm = f"{sl['p_market'] * 100:.1f}%" if sl.get("p_market") else "—"
        lbl = [f"{l['home'][:12]}–{l['away'][:12]}" for l in sl["legs"]]
        ch = self.chart({
            "type": "bar",
            "data": {"labels": lbl, "datasets": [
                {"label": "Μοντέλο", "data": [round(l["p_model"] * 100, 1) for l in sl["legs"]], "backgroundColor": "var(--s1)"},
                {"label": "Αγορά (χωρίς γκανιότα)", "data": [round((l["p_market"] or 0) * 100, 1) for l in sl["legs"]],
                 "backgroundColor": "var(--s2)"}]},
            "options": {"indexAxis": "y", "scales": {"x": {"min": 0, "max": 100, "title": {"display": True, "text": "Πιθανότητα %"}}}},
        }, small=len(sl["legs"]) <= 3)
        return f"""<div class="card"><h3>{E(title)}</h3>{note}
<div class="tiles">
<div class="tile"><div class="k">Συνολική απόδοση</div><div class="v">{sl['total_odds']:.2f}</div></div>
<div class="tile"><div class="k">Επιλογές</div><div class="v">{len(sl['legs'])}</div></div>
<div class="tile"><div class="k">Πιθανότητα (εκτίμηση)</div><div class="v">{sl['p_win'] * 100:.1f}%</div></div>
<div class="tile"><div class="k">Κατά την αγορά</div><div class="v">{pm}</div></div>
<div class="tile"><div class="k">Αναμενόμενο ανά 1€</div><div class="v {'pos' if sl['p_win'] * sl['total_odds'] >= 1 else ''}">{(sl['p_win'] * sl['total_odds'] - 1) * 100:+.0f}%</div></div>{stake_txt}{ret}
</div>{self.pick_table(sl['legs'])}
<details><summary>Διάγραμμα: μοντέλο vs αγορά ανά επιλογή</summary>{ch}</details></div>"""


CSS = """
:root{--surface:#fcfcfb;--plane:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;
--border:rgba(11,11,11,.10);--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--s6:#008300;--s7:#6250d6;--s8:#e34948;
--good:#0ca30c;--goodtxt:#006300;--bad:#d03b3b;--warn:#fab219;--chip:#efeee9}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--surface:#1a1a19;--plane:#0d0d0d;--ink:#f0efec;
--ink2:#c3c2b7;--grid:#2c2c2a;--border:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;
--s5:#d55181;--s6:#008300;--s7:#9085e9;--s8:#e66767;--goodtxt:#0ca30c;--chip:#262624}}
:root[data-theme=dark]{--surface:#1a1a19;--plane:#0d0d0d;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;
--border:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--goodtxt:#0ca30c;--chip:#262624}
*{box-sizing:border-box}body{margin:0;background:var(--plane);color:var(--ink);
font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1150px;margin:0 auto;padding:18px 16px 60px}
h1{font-size:23px;margin:0 0 4px}h2{font-size:19px;margin:22px 0 8px}h3{font-size:16px;margin:0 0 8px}
.sub{color:var(--ink2);margin:0 0 12px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px;margin:12px 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:10px 0}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:8px 10px}
.tile .k{color:var(--ink2);font-size:12px}.tile .v{font-size:20px;font-weight:650;font-variant-numeric:tabular-nums}
.warn{border-left:4px solid var(--warn);background:var(--surface);padding:10px 14px;border-radius:8px;color:var(--ink2);font-size:14px}
.tabs{display:flex;gap:6px;overflow-x:auto;padding:4px 0 8px;margin:10px 0;position:sticky;top:0;background:var(--plane);z-index:5}
.tabs button{flex:0 0 auto;border:1px solid var(--border);background:var(--surface);color:var(--ink);border-radius:999px;
padding:7px 12px;font:inherit;font-size:14px;cursor:pointer;white-space:nowrap}
.tabs button[aria-selected=true]{background:var(--ink);color:var(--plane);border-color:var(--ink)}
.tab{display:none}.tab.on{display:block}
.tbl{width:100%;overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:7px 8px;border-bottom:1px solid var(--grid);text-align:left;vertical-align:top}
th{color:var(--ink2);font-weight:600;font-size:12px;white-space:nowrap}
td.n{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.fb{display:inline-block;width:18px;height:18px;line-height:18px;text-align:center;border-radius:4px;
font-size:11px;font-weight:700;margin-right:2px;color:#fff}.fb.w{background:var(--good)}.fb.d{background:var(--muted)}.fb.l{background:var(--bad)}
.pos{color:var(--goodtxt)}.neg{color:var(--bad)}.muted{color:var(--muted);font-size:13px}
.wr{font-size:12px;color:var(--ink2);margin-top:3px}
.mv{font-size:12px;font-weight:650;padding:1px 6px;border-radius:999px;background:var(--chip);white-space:nowrap}
.mv.dn{color:var(--s1)}.mv.up{color:var(--s2)}
ul.why{margin:6px 0 4px 18px;padding:0;font-size:13px;color:var(--ink2)}
details{margin-top:4px}summary{cursor:pointer;color:var(--ink2);font-size:13px}
.chart{position:relative;height:260px;margin-top:8px}.chart.sm{height:170px}
.rules li{margin:3px 0;font-size:14px;color:var(--ink2)}
td.t{white-space:nowrap;color:var(--ink2);font-variant-numeric:tabular-nums}
@media (max-width:640px){
 table.picks thead{display:none}
 table.picks tr{display:grid;grid-template-columns:repeat(3,auto);justify-content:start;gap:2px 18px;
   padding:10px 0;border-bottom:1px solid var(--grid)}
 table.picks td{border:0;padding:1px 0;text-align:left}
 table.picks td.t,table.picks td:nth-child(2),table.picks td:nth-child(3){grid-column:1/-1}
 table.picks td[data-l]::before{content:attr(data-l) " ";color:var(--muted);font-size:11px;font-weight:400}
 .chart{height:220px}
}
"""


def _plan_html(plan, cfg, tz) -> str:
    if not plan:
        return "<div class='card'><p class='muted'>Το πλάνο δεν είναι διαθέσιμο.</p></div>"
    from .plan import SRC
    ws = plan["week"]
    head = (f"<div class='card'><h3>🎯 Τι να παίξεις σήμερα</h3><div class='tiles'>"
            f"<div class='tile'><div class='k'>Σύνολο σήμερα</div><div class='v'>{plan['total']:.2f}€</div></div>"
            f"<div class='tile'><div class='k'>Διαθέσιμο εβδομάδας</div><div class='v'>{ws['remaining']:.2f}€</div></div>"
            f"<div class='tile'><div class='k'>Ζημιά εβδομάδας</div><div class='v'>{ws['settled_loss']:.2f}€ / {ws['loss_limit']:.0f}€</div></div>"
            f"<div class='tile'><div class='k'>Ανοιχτά</div><div class='v'>{ws['open_stake']:.2f}€</div></div></div>"
            + "".join(f"<p>{E(n)}</p>" for n in plan["notes"])
            + "<p class='muted'>Τα ποσά είναι ΑΝΩΤΑΤΑ όρια, όχι υποχρέωση. Το αναμενόμενο μακροπρόθεσμο αποτέλεσμα είναι μικρή ζημιά "
              "(περίπου −3% του ποσού, βλ. backtest)· παίζεις μόνο ό,τι μπορείς να χάσεις. Η εβδομαδιαία λογιστική υποθέτει ότι έπαιξες το πλάνο κάθε μέρα.</p></div>")
    cards = []
    for it in plan["items"]:
        rows = []
        for l in it["legs"]:
            ko = _when(l["kickoff"], cfg["timezone"]) if l.get("kickoff") else "—"
            src = SRC.get(l.get("best_source") or "", l.get("best_source") or "")
            rows.append(f"<tr><td>{E(ko)}</td><td><b>{E(l['home'])} – {E(l['away'])}</b><div class='muted'>{E(l.get('league_name') or '')}</div></td>"
                        f"<td>{E(str(l['label']))}</td><td><b>{l['odds']:.2f}</b></td><td class='muted'>{E(src)}</td></tr>")
        ev = it["ev"] * 100
        cards.append(
            f"<div class='card'><h3>{E(it['title'])}: <b>{it['stake']:.2f}€</b></h3><div class='tiles'>"
            f"<div class='tile'><div class='k'>Ποντάρισμα</div><div class='v'>{it['stake']:.2f}€</div></div>"
            f"<div class='tile'><div class='k'>Συνολική απόδοση</div><div class='v'>{it['total_odds']:.2f}</div></div>"
            f"<div class='tile'><div class='k'>Πιθανότητα</div><div class='v'>{it['p_win'] * 100:.0f}%</div></div>"
            f"<div class='tile'><div class='k'>Αν κερδίσει</div><div class='v pos'>{it['ret']:.2f}€</div></div>"
            f"<div class='tile'><div class='k'>Αναμενόμενο ανά 1€</div><div class='v'>{ev:+.0f}%</div></div></div>"
            "<div class='tbl'><table><thead><tr><th>Ώρα</th><th>Αγώνας</th><th>Επιλογή</th><th>Απόδοση</th><th>Τιμή από</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table></div>"
            "<p class='muted'>Ψάξε την ίδια επιλογή στο πρακτορείο σου. Αν η απόδοση εκεί είναι αισθητά χαμηλότερη από αυτή που φαίνεται, "
            "προτίμησε να μην παίξεις.</p></div>")
    return head + "".join(cards)


def _goals_card(g) -> str:
    if not g:
        return ""
    t = g["targets"]
    ws = g["week"]
    ok = lambda b: "✅" if b else "⏳"
    clv_n = g["n_clv"]
    clv_txt = "—" if g["clv_mean"] is None else f"{g['clv_mean'] * 100:+.1f}%"
    pos_txt = "—" if g["clv_pos"] is None else f"{g['clv_pos'] * 100:.0f}%"
    done = clv_n >= t["clv_n"] and g["weeks"] >= t["weeks"]
    if done:
        good = (g["clv_mean"] or 0) >= t["clv_mean"] and (g["clv_pos"] or 0) > 0.5
        verdict = ("✅ Το CLV ξεπερνά το +1% και η πλειοψηφία των επιλογών έχει καλύτερη τιμή από το κλείσιμο: συνεχίζουμε· αύξηση ποσού το πολύ ×2."
                   if good else "⚠️ Το CLV δεν δείχνει πλεονέκτημα: κράτα το ποσό σταθερό ως διασκέδαση ή σταμάτα. ΔΕΝ αυξάνουμε ποσό.")
    else:
        verdict = f"Χρειάζονται ≥{t['clv_n']} διακριτές επιλογές και ≥{t['weeks']} εβδομάδες για απόφαση."
    rec = "—" if g["rec_hit"] is None else f"{g['rec_hit'] * 100:.0f}% ({g['rec_n']} δελτία)"
    rows = [
        ("1. Προστασία", f"ζημιά εβδομάδας {ws['settled_loss']:.2f}€ από όριο {ws['loss_limit']:.0f}€", ok(not ws["stop"])),
        ("2. Μάθηση (CLV)", f"{clv_n}/{t['clv_n']} διακριτές επιλογές · μέσο CLV {clv_txt} (στόχος ≥ +1%) · θετικές {pos_txt} · "
                            f"{g['weeks']:.1f}/{t['weeks']} εβδομάδες", ok(done)),
        ("3. Προτεινόμενο δελτίο", f"βγήκε στο {rec} (στόχος ~{t['rec_hit'][0] * 100:.0f}–{t['rec_hit'][1] * 100:.0f}% μετά από {t['rec_days']}+ δελτία)",
         ok(g["rec_n"] >= t["rec_days"])),
        ("4. Αύξηση ποσού", "μόνο αν επιτευχθεί ο στόχος 2 με θετικό αποτέλεσμα", "⏳"),
    ]
    return ("<div class='card'><h3>🎯 Στόχοι</h3><div class='tbl'><table><tbody>"
            + "".join(f"<tr><td>{c}</td><td><b>{E(a)}</b></td><td>{E(b)}</td></tr>" for a, b, c in rows)
            + f"</tbody></table></div><p>{E(verdict)}</p></div>")


def _clv_card(clv) -> str:
    if not clv or not clv.get("n"):
        return ("<div class='card'><h3>🎯 CLV – παίρνουμε καλύτερη τιμή από την αγορά;</h3><p class='muted'>Δεν υπάρχουν ακόμα αρκετά "
                "δεδομένα. Μετά τους πρώτους αγώνες θα φαίνεται αν οι τιμές που προτείνουμε είναι υψηλότερες από τις τελευταίες πριν το ματς.</p></div>")
    good = clv["mean"] > 0
    return (f"<div class='card'><h3>🎯 CLV – παίρνουμε καλύτερη τιμή από την αγορά;</h3><p class='muted'>Σύγκριση της τιμής που "
            "προτείναμε με την τελευταία τιμή που είδαμε πριν τον αγώνα. Θετικό CLV σε βάθος χρόνου = πραγματική αξία· "
            "χρειάζονται 200+ επιλογές για σοβαρό συμπέρασμα.</p><div class='tiles'>"
            f"<div class='tile'><div class='k'>Επιλογές</div><div class='v'>{clv['n']}</div></div>"
            f"<div class='tile'><div class='k'>Μέσο CLV</div><div class='v {'pos' if good else ''}'>{clv['mean'] * 100:+.1f}%</div></div>"
            f"<div class='tile'><div class='k'>Με καλύτερη τιμή</div><div class='v'>{clv['pos'] * 100:.0f}%</div></div></div></div>")


def render_html(cfg, now, lists, cands, moves, hist_by_list, notes, clv=None, plan=None, goals=None) -> str:
    P = Page(cfg)
    tz = cfg["timezone"]
    loc = now.astimezone(ZoneInfo(tz))
    L = cfg["lists"]
    br = cfg["bankroll"]
    n_with = len(cands["with_odds"])
    n_fair = len(cands["fair"])
    n_matches = len(cands["contexts"])
    sec = {}

    # ⭐ Προτεινόμενο
    rec = lists["recommended"]
    single = rec["single"]
    sec["recommended"] = f"""
<div class="card"><h3>Τι να περιμένεις (backtest 13 μηνών, 6.100 αγώνες)</h3><ul class="rules">
<li>Δεν βρήκαμε τρόπο να <b>νικήσουμε την αγορά</b>: το στατιστικό μοντέλο γκολ ήταν χειρότερο από τις αποδόσεις των πρακτορείων, γι' αυτό οι πιθανότητες βγαίνουν πλέον από την αγορά.</li>
<li>Με τους σημερινούς κανόνες (φαβορί, χωρίς Under 2.5, απόδοση έως 3.0) το ιστορικό ROI ήταν <b>≈ −0.2%</b> στην καλύτερη τιμή και <b>≈ −3%</b> στη μέση τιμή: δηλαδή περίπου «στο μηδέν» μείον την προμήθεια.</li>
<li>Άρα ό,τι παίζεις είναι <b>ψυχαγωγία με ελεγχόμενο κόστος</b>, όχι εισόδημα. Κράτα το ταμείο και τα όριά σου. Η «Αναμενόμενη» τιμή σε κάθε δελτίο είναι η εκτίμηση κέρδους/ζημιάς ανά 1€.</li>
<li>Ψάξε <b>την καλύτερη τιμή</b> ανάμεσα στα πρακτορεία: αξίζει ~3 μονάδες ROI. Οι τιμές εδώ είναι της αγοράς, όχι απαραίτητα του δικού σου πρακτορείου.</li></ul></div>
<div class="card"><h3>Πλάνο εβδομάδας</h3><ul class="rules">
<li>Ταμείο εβδομάδας: <b>{br['weekly']:.0f}€</b> · μονάδα <b>{br['unit']:.2f}€</b> · έως <b>{br['max_bets_per_day']}</b> στοιχήματα τη μέρα</li>
<li>Stop: αν το ταμείο πέσει στα <b>{br['stop_at']:.0f}€</b>, σταματάμε για την εβδομάδα</li>
<li>Λαχεία (30+ / 100+): <b>{br['lottery_stake']:.2f}€</b>, μία φορά τη βδομάδα</li>
<li>Ποτέ διπλασιασμός για να «πάρουμε πίσω» τη χθεσινή μέρα</li></ul></div>
{P.slip_block(rec['slip'], '⭐ Το δελτίο που προτείνω να παίξεις', br['unit'],
              "<p class='muted'>2–3 επιλογές, μόνο όσες περνούν όλους τους κανόνες (φόρμα, απουσίες, κινήσεις αποδόσεων, το πολύ 1 μπάσκετ).</p>")}
<div class="card"><h3>⭐ Μονό της ημέρας ({br['unit']:.2f}€)</h3>{P.pick_table([single] if single else [])}</div>"""

    sec["safe"] = ("<div class='card'><h3>🛡️ Οι πιο σίγουρες επιλογές της ημέρας (μονά)</h3>"
                   "<p class='muted'>Ταξινομημένες κατά πιθανότητα. Χαμηλές αποδόσεις – καλές για «δέσιμο».</p>"
                   + P.pick_table(lists["safe"]["picks"]) + "</div>")
    sec["x10"] = P.slip_block(lists["x10"]["slip"], f"🎯 Δελτίο {L['x10']['min_total']:.0f}+", br["unit"])
    sec["x30"] = P.slip_block(lists["x30"]["slip"], f"🔥 Δελτίο {L['x30']['min_total']:.0f}+", br["lottery_stake"],
                              "<p class='muted'>Λαχείο: μικρό ποσό.</p>")
    sec["x100"] = P.slip_block(lists["x100"]["slip"], f"🎰 Λαχείο {L['x100']['min_total']:.0f}+", br["lottery_stake"],
                               "<p class='muted'>Πιθανότητα κάτω από 1%. Μόνο για πλάκα.</p>")
    ov = lists["overs"]
    sec["overs"] = (P.slip_block(ov["slip"], "⚽ Δελτίο μόνο με γκολ", br["unit"])
                    + "<div class='card'><h3>Όλες οι επιλογές γκολ</h3>" + P.pick_table(ov["picks"]) + "</div>")
    for lid, title, what in (("corners", "🚩 Κόρνερ", "κόρνερ"), ("cards", "🟨 Κάρτες", "κάρτες"),
                             ("throw_ins", "↔️ Πλάγια", "πλάγια"), ("players", "👤 Παίκτες", "παίκτες")):
        x = lists[lid]
        note = ("<p class='muted'>Όπου γράφει «παίξ' το αν ≥», δεν βρήκαμε απόδοση: είναι η ελάχιστη απόδοση που "
                "κάνει την επιλογή να αξίζει. Αν το πρακτορείο σου δίνει λιγότερα, την αφήνεις.</p>")
        if lid == "players":
            note += "<p class='muted'>⚠️ Παίκτες: παίζεις ΜΟΝΟ αφού βγει η ενδεκάδα (~1 ώρα πριν).</p>"
        if lid == "throw_ins":
            note += "<p class='muted'>Τα πλάγια έρχονται μόνο από το Sofascore. Αν σήμερα δεν απάντησε, η λίστα μένει άδεια (δες ⚙️ Πηγές).</p>"
        body = (P.slip_block(x["slip"], f"{title}: δελτίο", br["unit"]) if x.get("slip") else "") + \
            f"<div class='card'><h3>{title}: επιλογές</h3>{note}{P.pick_table(x['picks'], f'Δεν υπάρχουν αρκετά δεδομένα για {what} στα σημερινά ματς.')}</div>"
        sec[lid] = body
    sec["combo"] = P.slip_block(lists["combo"]["slip"], "🔀 Συνδυαστικό (διαφορετικές αγορές)", br["unit"])

    # 📉 Κινήσεις
    drops, rises = moves

    def mv_rows(rows):
        if not rows:
            return "<p class='muted'>Καμία σημαντική κίνηση ακόμα. Χρειάζονται τουλάχιστον 2 λήψεις αποδόσεων (το bot τρέχει πρωί και απόγευμα).</p>"
        from .selector import label as lab
        trs = "".join(
            f"<tr><td class='n'>{_when(r['match']['kickoff'], tz)}</td><td>{E(r['match']['home'])} – {E(r['match']['away'])}"
            f"<br><span class='muted'>{E(r['league_name'])}</span></td>"
            f"<td>{E(lab(r['market'], r['selection'], r['line'], r['match']['home'], r['match']['away']))}</td>"
            f"<td class='n'>{r['open']:.2f} → <b>{r['now']:.2f}</b></td>"
            f"<td class='n'><span class='mv {'dn' if r['pct'] < 0 else 'up'}'>{'▼' if r['pct'] < 0 else '▲'}{abs(r['pct']) * 100:.0f}%</span></td></tr>"
            for r in rows)
        return ("<div class='tbl'><table><thead><tr><th>Ώρα</th><th>Αγώνας</th><th>Επιλογή</th><th>Απόδοση</th><th>Κίνηση</th>"
                f"</tr></thead><tbody>{trs}</tbody></table></div>")
    top = (drops[:8] + rises[:8])
    mv_chart = P.chart({
        "type": "bar",
        "data": {"labels": [f"{r['match']['home'][:10]}–{r['match']['away'][:10]} {r['selection']}" for r in top],
                 "datasets": [{"label": "Μεταβολή απόδοσης %", "data": [round(r["pct"] * 100, 1) for r in top],
                               "backgroundColor": ["var(--s1)" if r["pct"] < 0 else "var(--s2)" for r in top]}]},
        "options": {"indexAxis": "y", "plugins": {"legend": {"display": False}},
                    "scales": {"x": {"title": {"display": True, "text": "% από την αρχική απόδοση (αρνητικό = πέφτει)"}}}},
    }) if top else ""
    sec["moves"] = f"""<div class="card"><h3>📉 Τι σημαίνουν οι κινήσεις</h3>
<p class="muted">Απόδοση που <b>πέφτει</b> = μπαίνουν λεφτά ή η αγορά έμαθε κάτι (ενδεκάδα, τραυματισμός). Συχνά είναι «έξυπνα» λεφτά.
Απόδοση που <b>ανεβαίνει</b> = η αγορά πάει κόντρα. Το bot βγάζει αυτόματα από το Προτεινόμενο ό,τι ανεβαίνει πάνω από
{cfg['rules']['max_drift_against'] * 100:.0f}%.</p>{mv_chart}</div>
<div class="card"><h3>▼ Πέφτουν (μπαίνουν λεφτά)</h3>{mv_rows(drops)}</div>
<div class="card"><h3>▲ Ανεβαίνουν (η αγορά πάει κόντρα)</h3>{mv_rows(rises)}</div>"""

    # 📊 Ιστορικό ανά λίστα
    rows, curves = [], []
    for lid, h in sorted(hist_by_list.items(), key=lambda kv: list(LIST_NAMES).index(kv[0]) if kv[0] in LIST_NAMES else 99):
        if not h["n"] and not h["open"]:
            continue
        rows.append(f"<tr><td>{E(LIST_NAMES.get(lid, lid))}</td><td class='n'>{h['n']}</td><td class='n'>{h['won']}</td>"
                    f"<td class='n'>{_pct(h['won'] / h['n']) if h['n'] else '—'}</td>"
                    f"<td class='n'>{_pct(h['leg_hit']) if h['leg_hit'] is not None else '—'}</td>"
                    f"<td class='n {'pos' if h['pl'] >= 0 else 'neg'}'>{h['pl']:+.2f}</td>"
                    f"<td class='n {'pos' if h['roi'] >= 0 else 'neg'}'>{h['roi'] * 100:+.0f}%</td><td class='n'>{h['open']}</td></tr>")
        if h["curve"] and lid in ("recommended", "single", "x10", "x30", "x100", "overs", "combo", "safe1"):
            curves.append((lid, h["curve"]))
    hist_chart = ""
    if curves:
        labels = sorted({p["x"] for _, c in curves for p in c})
        ds = []
        for i, (lid, c) in enumerate(curves[:8]):
            m = {p["x"]: p["y"] for p in c}
            last, data = 0.0, []
            for x in labels:
                last = m.get(x, last)
                data.append(last)
            ds.append({"label": LIST_NAMES.get(lid, lid), "data": data, "borderColor": SERIES[i], "backgroundColor": SERIES[i],
                       "borderWidth": 2, "pointRadius": 0, "tension": 0})
        hist_chart = "<div class='card'><h3>Σωρευτικό κέρδος/ζημιά ανά λίστα (μονάδες)</h3>" + P.chart(
            {"type": "line", "data": {"labels": labels, "datasets": ds},
             "options": {"scales": {"y": {"title": {"display": True, "text": "μονάδες"}}}}}) + "</div>"
    sec["today"] = _plan_html(plan, cfg, tz)
    sec["history"] = (_goals_card(goals) + "<div class='card'><h3>📊 Πώς πάει κάθε λίστα</h3><p class='muted'>Όλες οι λίστες καταγράφονται «στα χαρτιά» "
                      "με 1 μονάδα, για να βλέπουμε ποια δουλεύει. Χρειάζονται 4–6 εβδομάδες για σοβαρό συμπέρασμα. "
                      "«Επιτυχία επιλογών» = πόσες μεμονωμένες επιλογές βγήκαν.</p>"
                      + ("<div class='tbl'><table><thead><tr><th>Λίστα</th><th>Κλεισμένα</th><th>Κέρδισαν</th><th>%</th>"
                         "<th>Επιτυχία επιλογών</th><th>Κ/Ζ</th><th>ROI</th><th>Ανοιχτά</th></tr></thead><tbody>"
                         + "".join(rows) + "</tbody></table></div>" if rows else "<p class='muted'>Δεν υπάρχει ακόμα ιστορικό.</p>")
                      + "</div>" + hist_chart + _clv_card(clv))

    # ⚙️ Πηγές + κανόνες
    rr = cfg["rules"]
    sec["sources"] = ("<div class='card'><h3>Κατάσταση πηγών (σημερινή εκτέλεση)</h3><div class='tbl'><table><tbody>"
                      + "".join(f"<tr><td>{'✅' if ok else '⚠️'} {E(n)}</td><td class='muted'>{E(msg)}</td></tr>" for n, ok, msg in notes)
                      + "</tbody></table></div></div>"
                      + f"""<div class="card"><h3>Κανόνες που εφαρμόζονται (από τα λάθη μας)</h3><ul class="rules">
<li>Όχι «νίκη» σε ομάδα με λιγότερους από {rr['min_ppg_for_win']} β/ματς στα 5 τελευταία (Atalanta, 05/11)</li>
<li>Όχι Over/GG όταν μια ομάδα έχει ≥{rr['max_absences']} απουσίες ή ≥{rr['max_attack_absences']} στην επίθεση (Leverkusen, 05/11)</li>
<li>Μπάσκετ: το πολύ 1 σκέλος στο Προτεινόμενο· όχι γηπεδούχος κάτω από {rr['basket_min_ml_odds_safe']} ως «safe» (Efes/Hapoel/ASVEL, 05/11)</li>
<li>Παίκτες μόνο με επίσημη ενδεκάδα (Pavlidis πάγκος, 05/11)</li>
<li>Έξω από Προτεινόμενο/Safe ό,τι η απόδοσή του ανεβαίνει ≥{rr['max_drift_against'] * 100:.0f}%</li>
<li>Κάθε αγώνας το πολύ μία φορά σε κάθε δελτίο · το πολύ {cfg['selection']['max_legs_per_league']} επιλογές από την ίδια διοργάνωση</li>
</ul></div>""")

    tabs_html = "".join(f"<button role='tab' data-t='{tid}' aria-selected='{str(i == 0).lower()}'>{E(name)}</button>"
                        for i, (tid, name) in enumerate(TABS))
    body = "".join(f"<section class='tab{' on' if i == 0 else ''}' id='t-{tid}' role='tabpanel'>{sec.get(tid, '')}</section>"
                   for i, (tid, _) in enumerate(TABS))
    js = json.dumps([[cid, c] for cid, c in P.charts], ensure_ascii=False)
    return f"""<!doctype html><html lang="el"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>BetBot Δελτίο</title>
<style>{CSS}</style></head><body><main>
<header><h1>BetBot · {GR_DAYS[loc.weekday()]} {loc:%d/%m/%Y}</h1>
<p class="sub">Ενημέρωση {loc:%H:%M} · {n_matches} αγώνες · {n_with} επιλογές με απόδοση · {n_fair} με «δίκαιη απόδοση»</p></header>
{"<div class='warn' style='border-left-color:var(--bad);margin-bottom:8px'><b>DEMO</b> – φανταστικές ομάδες και παίκτες, μόνο για να δεις πώς δουλεύει η σελίδα. Δεν είναι πραγματικό δελτίο.</div>" if cfg.get("_demo") else ""}
<div class="warn">Στατιστική εκτίμηση, όχι εγγύηση. Ακόμα και οι «σίγουρες» επιλογές χάνουν περίπου 1 στις 3–4 φορές.
Παίζε μόνο το ποσό της εβδομάδας.</div>
<nav class="tabs" role="tablist">{tabs_html}</nav>{body}</main>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>
(function(){{
 const CH = {js};
 const cs = getComputedStyle(document.documentElement);
 const v = s => (typeof s==='string' && s.startsWith('var(')) ? cs.getPropertyValue(s.slice(4,-1)).trim() : s;
 const fix = o => {{ if(Array.isArray(o)) return o.map(fix); if(o && typeof o==='object'){{ for(const k in o) o[k]=fix(o[k]); return o; }} return v(o); }};
 const drawn = {{}};
 function drawIn(root){{
   if(!window.Chart){{ document.querySelectorAll('.chart').forEach(e => e.style.display='none'); return; }}
   Chart.defaults.color = v('var(--ink2)'); Chart.defaults.borderColor = v('var(--grid)');
   Chart.defaults.font.family = 'system-ui,-apple-system,"Segoe UI",sans-serif';
   Chart.defaults.maintainAspectRatio = false;
   Chart.defaults.elements.bar.borderRadius = 4; Chart.defaults.elements.bar.borderSkipped = 'start';
   for (const [id, cfg] of CH) {{
     const el = document.getElementById(id);
     if(!el || drawn[id] || !root.contains(el)) continue;
     const det = el.closest('details');
     if (det && !det.open) {{ det.addEventListener('toggle', () => {{ if(det.open && !drawn[id]){{ drawn[id]=new Chart(el, fix(cfg)); }} }}, {{once:false}}); continue; }}
     drawn[id] = new Chart(el, fix(cfg));
   }}
 }}
 const btns = document.querySelectorAll('.tabs button');
 function show(t){{
   btns.forEach(b => b.setAttribute('aria-selected', String(b.dataset.t===t)));
   document.querySelectorAll('.tab').forEach(s => s.classList.toggle('on', s.id==='t-'+t));
   const s = document.getElementById('t-'+t); if(s) drawIn(s);
   try {{ localStorage.setItem('betbot_tab', new Date().toDateString() + '|' + t); }} catch(e) {{}}
 }}
 btns.forEach(b => b.addEventListener('click', () => show(b.dataset.t)));
 let start = 'today';      // κάθε νέα μέρα ανοίγει στο πλάνο· η μνήμη καρτέλας ισχύει μόνο μέσα στην ίδια μέρα
 try {{ const v = (localStorage.getItem('betbot_tab') || '').split('|'); if (v[0] === new Date().toDateString() && document.getElementById('t-'+v[1])) start = v[1]; }} catch(e) {{}}
 show(start);
}})();
</script></body></html>"""


# ---------------------------------------------------------------- ΙΣΤΟΡΙΚΟ
def history_by_list(slips):
    by = defaultdict(list)
    for s in slips:
        by[s.get("list_name") or "recommended"].append(s)
    out = {}
    for lid, ss in by.items():
        settled = [s for s in ss if s["status"] in ("won", "lost")]
        staked = sum(s["stake"] for s in settled)
        ret = sum(s["payout"] for s in settled)
        cum, curve = 0.0, []
        for s in settled:
            cum += s["payout"] - s["stake"]
            curve.append({"x": s["created_at"][:10], "y": round(cum, 2)})
        legs = [l for s in ss for l in s["legs"] if l.get("result") in ("won", "lost")]
        out[lid] = {"n": len(settled), "won": sum(1 for s in settled if s["status"] == "won"),
                    "pl": ret - staked, "roi": (ret - staked) / staked if staked else 0.0,
                    "leg_hit": sum(1 for l in legs if l["result"] == "won") / len(legs) if legs else None,
                    "curve": curve, "open": sum(1 for s in ss if s["status"] == "open")}
    return out


# ---------------------------------------------------------------- EMAIL
def slip_png(sl) -> bytes:
    labels = [f"{l['home'][:12]}–{l['away'][:12]}\n{l['label'][:30]}" for l in sl["legs"]]
    fig, ax = plt.subplots(figsize=(7.5, 0.75 * len(labels) + 1.2), dpi=130)
    y = range(len(labels))
    ax.barh([i - 0.2 for i in y], [l["p_model"] * 100 for l in sl["legs"]], height=0.36, color=BLUE, label="Μοντέλο")
    ax.barh([i + 0.2 for i in y], [(l["p_market"] or 0) * 100 for l in sl["legs"]], height=0.36, color=ORANGE, label="Αγορά")
    ax.set_yticks(list(y)); ax.set_yticklabels(labels, fontsize=8); ax.invert_yaxis()
    ax.set_xlim(0, 100); ax.set_xlabel("Πιθανότητα %", color="#52514e")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(axis="x", color="#e1e0d9", lw=0.8); ax.set_axisbelow(True)
    ax.legend(loc="lower right", frameon=False, fontsize=8)
    fig.tight_layout()
    buf = io.BytesIO(); fig.savefig(buf, format="png"); plt.close(fig)
    return buf.getvalue()


def render_email(cfg, now, lists, page_url=None):
    tz = cfg["timezone"]
    imgs, blocks = {}, []

    def table(legs):
        return ("<table cellpadding='6' style='border-collapse:collapse;font-size:14px'>"
                "<tr style='color:#52514e'><th align='left'>Ώρα</th><th align='left'>Αγώνας</th><th align='left'>Επιλογή</th>"
                "<th>Απόδ.</th><th>p</th></tr>" + "".join(
                    f"<tr><td>{_when(l['kickoff'], tz)}</td><td>{E(l['home'])} – {E(l['away'])}</td>"
                    f"<td>{E(l['label'])}</td><td align='right'><b>{l['odds']:.2f}</b></td><td align='right'>{_pct(l['p'])}</td></tr>"
                    for l in legs) + "</table>")
    for lid, title in (("recommended", "⭐ Προτεινόμενο"), ("x10", "🎯 10+"), ("x30", "🔥 30+"), ("x100", "🎰 100+")):
        sl = lists[lid]["slip"]
        if not sl:
            continue
        cid = f"img_{lid}"
        if lid == "recommended":
            imgs[cid] = slip_png(sl)
        blocks.append(f"<h3 style='margin:18px 0 6px'>{title} · απόδοση {sl['total_odds']:.2f} · "
                      f"εκτ. πιθανότητα {sl['p_win'] * 100:.1f}%</h3>" + table(sl["legs"])
                      + (f"<img src='cid:{cid}' style='max-width:100%'>" if cid in imgs else ""))
    single = lists["recommended"]["single"]
    if single:
        blocks.insert(1, "<h3 style='margin:18px 0 6px'>⭐ Μονό της ημέρας</h3>" + table([single]))
    link = f"<p><a href='{E(page_url)}'>Όλες οι λίστες (κόρνερ, κάρτες, πλάγια, παίκτες, κινήσεις αποδόσεων)</a></p>" if page_url else ""
    body = (f"<div style='font-family:system-ui,Segoe UI,sans-serif;color:#0b0b0b'>"
            f"<h2>BetBot · {now.astimezone(ZoneInfo(tz)):%d/%m/%Y}</h2>"
            + ("".join(blocks) if blocks else "<p>Σήμερα δεν βγήκε δελτίο που να περνάει τους κανόνες.</p>")
            + link + "<p style='color:#898781;font-size:12px'>Στατιστική εκτίμηση, όχι εγγύηση. Παίζε μόνο το ποσό της εβδομάδας.</p></div>")
    return body, imgs


def write_page(reports_dir, now, html_text):
    os.makedirs(os.path.join(reports_dir, "archive"), exist_ok=True)
    with open(os.path.join(reports_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html_text)
    path = os.path.join(reports_dir, "archive", f"{now:%Y-%m-%d}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_text)
    return path
