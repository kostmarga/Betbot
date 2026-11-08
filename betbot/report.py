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

from .live import CORE_JS
from .util import iso, parse_iso

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
        tk, scr, attr = "", "", ""
        if "res" in c:        # σκέλος καταγεγραμμένου δελτίου: ✅/❌/⏳ + σκορ (ενημερώνεται και ζωντανά από τον browser)
            ic = {"won": "✅", "lost": "❌", "void": "↩️"}.get(c.get("res"), "⏳")
            sc = c.get("sc")
            tk = f"<span class='tk'>{ic}</span> "
            scr = f"<div class='scr'>{(str(sc[0]) + '-' + str(sc[1]) + ' ΤΕΛΟΣ') if sc else ''}</div>"
            if c.get("eid") and c.get("lg"):
                leg = {k: c.get(k) for k in ("eid", "lg", "sport", "market", "ko", "res", "sc", "fair")}
                leg["sel"] = c.get("selection")
                leg["line"] = c.get("line")
                attr = f' data-leg="{E(json.dumps(leg, ensure_ascii=False))}"'
        return f"""<tr{attr}>
<td class="t">{tk}{_when(c['kickoff'], self.tz)}{scr}</td>
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
        # Δελτίο χωρίς απόδοση πρακτορείου («δίκαιη» ελάχιστη απόδοση): το αναμενόμενο κέρδος δεν έχει νόημα
        ev_tile = "" if sl.get("fair") else (f"<div class=\"tile\"><div class=\"k\">Αναμενόμενο ανά 1€</div><div class=\"v "
                                            f"{'pos' if sl['p_win'] * sl['total_odds'] >= 1 else ''}\">{(sl['p_win'] * sl['total_odds'] - 1) * 100:+.0f}%</div></div>")
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
{ev_tile}{stake_txt}{ret}
</div>{_cnt_html(sl['legs'])}{self.pick_table(sl['legs'])}
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


ENRICH = ("why", "form_home", "form_away", "warnings", "move")
RESIC = {"won": "✅", "lost": "❌", "void": "↩️", "open": "⏳"}
EXTRA_CSS = """
.tk{display:flex;gap:10px;padding:7px 0;border-top:1px solid var(--grid);align-items:flex-start}.tk:first-of-type{border-top:0}
.tk .ic{width:26px;font-size:19px;line-height:1.2}.tk .sc{font-variant-numeric:tabular-nums}
.grid td,.grid th{text-align:center;padding:6px 4px}.grid td.d{text-align:left;white-space:nowrap}
.ok{color:var(--goodtxt)}.ko{color:var(--bad)}h4{margin:14px 0 6px;font-size:15px}
.tk{font-size:18px}.scr{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}.cnt{font-size:14px;margin:6px 0}
.banner{background:#fff1c2;color:#5c4400;border:1px solid #e6c34d;border-radius:10px;padding:10px 12px;margin:8px 0;font-size:14px}
.banner a{color:inherit;font-weight:700}
@media(prefers-color-scheme:dark){.banner{background:#3a3000;color:#ffe9a0;border-color:#7a6500}}
"""

INDEX_JS = r"""
(function(){
const B = window.BetbotLive;
// 1) ✅/❌ + σκορ σε κάθε αγώνα των δελτίων (ζωντανά, μόνο όσο παίζεται αγώνας)
const rows = [];
document.querySelectorAll('tr[data-leg]').forEach(tr => { try { rows.push({tr, leg: JSON.parse(tr.dataset.leg)}); } catch (e) {} });
function update() {
  rows.forEach(r => {
    const l = r.leg, st = B.trackable(l) ? B.cache[B.key(l)] : null, c = B.judge(l, st)[0];
    const tk = r.tr.querySelector('.tk'); if (tk) tk.textContent = B.IC[c];
    const scr = r.tr.querySelector('.scr');
    if (scr) { let t = ''; if (st && st.state !== 'pre') t = st.hs + '-' + st.as + (st.state === 'in' ? ' ' + st.clock : ' ΤΕΛΟΣ'); else if (l.sc) t = l.sc[0] + '-' + l.sc[1] + ' ΤΕΛΟΣ'; scr.textContent = t; }
  });
  document.querySelectorAll('.slipcnt').forEach(el => {
    const card = el.closest('.card'); if (!card) return;
    const ic = Array.from(card.querySelectorAll('.tk')).map(x => x.textContent);
    const w = ic.filter(x => x === '✅').length, k = ic.filter(x => x === '❌').length, p = ic.filter(x => x === '🟢' || x === '🔴').length;
    el.innerHTML = '✅ <b>' + w + '</b> · ❌ <b>' + k + '</b> · 🟢 <b>' + p + '</b> σε εξέλιξη · ⏳ <b>' + (ic.length - w - k - p) + '</b>';
  });
}
const legs = rows.map(r => r.leg);
if (legs.length) B.start(legs, update);

// 2) Προειδοποίηση όταν η σελίδα είναι ξεπερασμένη (το GitHub καθυστερεί τα προγραμματισμένα τρεξίματα)
const GEN = new Date(document.querySelector('meta[name=generated]').content), NOW = new Date();
const day = d => d.toLocaleDateString('el-GR', {timeZone: 'Europe/Athens'});
const ageH = (NOW - GEN) / 3600000;
const ban = document.getElementById('stale');
if (ban && (day(GEN) !== day(NOW) || ageH > 10)) {
  const when = GEN.toLocaleString('el-GR', {timeZone: 'Europe/Athens', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false});
  ban.hidden = false;
  ban.innerHTML = '⚠️ <b>Η σελίδα είναι ξεπερασμένη</b>: ενημερώθηκε ' + when + ' (πριν ' + Math.round(ageH) + ' ώρες). Το GitHub καθυστερεί τα προγραμματισμένα τρεξίματα. ' +
    '<a href="https://github.com/kostmarga/Betbot/actions/workflows/daily.yml">▶️ Πάτα εδώ → Run workflow για να τρέξει τώρα</a>';
}
// 3) Κάθε 5' ελέγχουμε αν υπάρχει νεότερη έκδοση και ΜΟΝΟ τότε ανανεώνουμε
async function checkNew() {
  try {
    const t = await (await fetch(location.pathname + '?t=' + Date.now())).text();
    const m = t.match(/<meta name="generated" content="([^"]+)"/);
    if (m && m[1] !== document.querySelector('meta[name=generated]').content) location.reload();
  } catch (e) { /* χωρίς δίκτυο: αγνοείται */ }
}
setInterval(checkNew, 5 * 60 * 1000);
})();
"""


def _pkey(c):
    return (c.get("match_id"), c.get("market"), c.get("selection"), c.get("line"))


def _cnt_html(legs) -> str:
    """Μέτρηση ✅/❌/⏳ ενός δελτίου (όταν τα σκέλη έχουν αποτέλεσμα). Ενημερώνεται και ζωντανά από τον browser."""
    if not any("res" in l for l in legs):
        return ""
    w = sum(1 for l in legs if l.get("res") == "won")
    k = sum(1 for l in legs if l.get("res") == "lost")
    n = len(legs) - w - k
    return f"<div class='cnt slipcnt'>✅ <b>{w}</b> · ❌ <b>{k}</b> · 🟢 <b>0</b> σε εξέλιξη · ⏳ <b>{n}</b></div>"


def _enrich(legs, cidx, fair=False, tctx=None):
    """Προσθέτει «Γιατί;», φόρμα, κινήσεις από τις τωρινές επιλογές (όπου υπάρχουν) στα κλειδωμένα σκέλη της βάσης.
    Με tctx = {"scores":…, "lgmap":…}: προσθέτει και τα πεδία παρακολούθησης (αποτέλεσμα, σκορ, id αγώνα ESPN) για ✅/❌."""
    out = []
    for l in legs:
        d = dict(l)
        if tctx is not None:
            mid = l.get("match_id")
            sc = (tctx["scores"] or {}).get(mid)
            d["res"] = l.get("result")
            d["sc"] = [sc[0], sc[1]] if sc and sc[0] is not None else None
            d["eid"] = mid[5:] if isinstance(mid, str) and mid.startswith("espn:") else None
            d["lg"] = tctx["lgmap"].get(l.get("league"))
            d["ko"] = l.get("kickoff")
            d["fair"] = fair
        c = (cidx or {}).get(_pkey(l)) or {}
        for k in ENRICH:
            if c.get(k) is not None and not d.get(k):
                d[k] = c[k]
        d.setdefault("league_name", l.get("league"))
        if fair and d.get("odds"):                 # σκέλος χωρίς απόδοση: «παίξ' το αν ≥»
            d["play_if"] = d["odds"]
            d["fair_odds"] = (1 / d["p"]) if d.get("p") else d["odds"]
            d["odds"] = None
        out.append(d)
    return out


def _lot_note(sl) -> str:
    """Ειλικρινής σημείωση για δελτία μεγάλης απόδοσης: πιθανότητα και αναμενόμενο αποτέλεσμα."""
    if not sl or not sl.get("p_win"):
        return ""
    p = sl["p_win"]
    ev = (p * sl["total_odds"] - 1) * 100
    return (f"<p class='muted'><b>Λαχείο, όχι στρατηγική.</b> Πιθανότητα να βγει: <b>{p * 100:.1f}%</b> (1 στις {round(1 / p)}). "
            f"Αναμενόμενο ανά 1€: <b>{ev:+.0f}%</b>. Παίζεται μόνο για πλάκα, με το ποσό του λαχείου.</p>")


def _tiles(items) -> str:
    return "<div class='tiles'>" + "".join(f"<div class='tile'><div class='k'>{k}</div><div class='v {c}'>{v}</div></div>"
                                           for k, v, c in items) + "</div>"


def _plan_html(P, plan, cfg, tz, cidx, tctx=None) -> str:
    if not plan:
        return "<div class='card'><p class='muted'>Το πλάνο δεν είναι διαθέσιμο.</p></div>"
    ws = plan["week"]
    head = ("<div class='card'><h3>🎯 Τι να παίξεις σήμερα</h3>"
            + _tiles([("Σύνολο σήμερα", f"{plan['total']:.2f}€", ""), ("Διαθέσιμο εβδομάδας", f"{ws['remaining']:.2f}€", ""),
                      ("Ζημιά εβδομάδας", f"{ws['settled_loss']:.2f}€ / {ws['loss_limit']:.0f}€", ""),
                      ("Ανοιχτά", f"{ws['open_stake']:.2f}€", "")])
            + "".join(f"<p>{E(n)}</p>" for n in plan["notes"])
            + "<p class='muted'>Παίζεις ΜΟΝΟ δελτία (όχι μονά). Τα ποσά είναι ΑΝΩΤΑΤΑ όρια, όχι υποχρέωση. Το αναμενόμενο μακροπρόθεσμο "
              "αποτέλεσμα είναι μικρή ζημιά (περίπου −3% του ποσού, βλ. backtest)· παίζεις μόνο ό,τι μπορείς να χάσεις. "
              "Η εβδομαδιαία λογιστική υποθέτει ότι έπαιξες το πλάνο κάθε μέρα.</p></div>")
    cards = []
    for it in plan["items"]:
        legs = _enrich(it["legs"], cidx, tctx=tctx)
        ev = it["ev"] * 100
        srcs = sorted({SRC_NAME.get(l.get("best_source") or "", "") for l in it["legs"]} - {""})
        cards.append(
            f"<div class='card'><h3>{E(it['title'])}: <b>{it['stake']:.2f}€</b></h3>"
            + _tiles([("Ποντάρισμα", f"{it['stake']:.2f}€", ""), ("Συνολική απόδοση", f"{it['total_odds']:.2f}", ""),
                      ("Πιθανότητα", f"{it['p_win'] * 100:.0f}%", ""), ("Αν κερδίσει", f"{it['ret']:.2f}€", "pos"),
                      ("Αναμενόμενο ανά 1€", f"{ev:+.0f}%", "")])
            + _cnt_html(legs) + P.pick_table(legs)
            + f"<p class='muted'>Τιμές: {E(', '.join(srcs) or 'αγοράς')}. Πάτα «Γιατί;» σε κάθε επιλογή για τους λόγους. "
              "Ψάξε την ίδια επιλογή στο πρακτορείο σου· αν η απόδοση εκεί είναι αισθητά χαμηλότερη, προτίμησε να μην παίξεις.</p></div>")
    return head + "".join(cards)


SRC_NAME = {"espn": "ESPN", "espn_max": "ESPN", "fdco": "μέσος όρος πρακτορείων", "fdco_max": "καλύτερη τιμή πρακτορείων",
            "oddsapi": "μέσος όρος πρακτορείων", "oddsapi_max": "καλύτερη τιμή πρακτορείων"}


def _slip_compact(P, title, sl, cidx, fair=False, tctx=None) -> str:
    legs = _enrich(sl["legs"], cidx, fair=fair, tctx=tctx)
    if fair:
        stats = _tiles([("Ελάχιστη απόδοση", f"{sl['total_odds']:.2f}", ""), ("Πιθανότητα", f"{sl['p_win'] * 100:.0f}%", "")])
        note = "<p class='muted'>Δεν βρέθηκε απόδοση πρακτορείου: παίζεις μόνο αν σου δίνει τουλάχιστον την «ελάχιστη απόδοση».</p>"
    else:
        ev = (sl["p_win"] * sl["total_odds"] - 1) * 100
        stats = _tiles([("Απόδοση", f"{sl['total_odds']:.2f}", ""), ("Πιθανότητα", f"{sl['p_win'] * 100:.0f}%", ""),
                        ("Αναμενόμενο ανά 1€", f"{ev:+.0f}%", "")])
        note = ""
    return f"<h4>{E(title)}</h4>{stats}{note}{P.pick_table(legs)}"


def _alternatives_html(P, lists, plan, cfg, cidx, tctx=None, view=None) -> str:
    """Άλλα δελτία (από όλες τις κατηγορίες) που θα μπορούσες να παίξεις σήμερα αντί/εκτός των προτεινόμενων."""
    if plan and plan.get("week", {}).get("stop"):
        return ""
    in_plan = {it.get("list") for it in (plan or {}).get("items", [])}
    unit = cfg["bankroll"]["unit"]
    blocks = []
    for lid, key, title in (("safe", "safe", "🛡️ Safe δελτίο"), ("overs", "overs", "⚽ Over δελτίο"),
                            ("combo", "combo", "🔀 Συνδυαστικό"), ("fair_corners", "corners", "🚩 Δελτίο κόρνερ"),
                            ("fair_cards", "cards", "🟨 Δελτίο καρτών"), ("fair_throw_ins", "throw_ins", "↔️ Δελτίο πλάγιων"),
                            ("fair_players", "players", "👤 Δελτίο παικτών")):
        if lid in in_plan or (lid == "safe" and "safe" in in_plan):
            continue
        sl = view(lid, lists[key].get("slip"), fair=lid.startswith("fair_")) if view else lists[key].get("slip")
        if sl and (sl["total_odds"] <= 8):
            blocks.append(_slip_compact(P, title, sl, cidx, fair=bool(sl.get("fair")), tctx=tctx))
    if not blocks:
        return ""
    return ("<div class='card'><h3>➕ Δελτία που επίσης θα μπορούσες να παίξεις σήμερα</h3>"
            "<p class='muted'>Ένα δελτίο ανά κατηγορία. Δεν προστίθενται στο πλάνο ποσών: αν προτιμάς κάποιο "
            f"<b>αντί</b> για τα προτεινόμενα, κράτα το ίδιο ποσό ({unit:.2f}€) και το όριο των στοιχημάτων της ημέρας.</p>"
            + "".join(blocks) + "</div>")


def _lottery_html(P, lists, cfg, cidx, tctx=None, view=None) -> str:
    """Δελτία μεγάλης απόδοσης (10+/30+/100+): ΜΟΝΟ ως λαχεία, στο τέλος, με ειλικρινή πιθανότητα."""
    parts = []
    for lid, title in (("x10", "🎯 Δελτίο 10+"), ("x30", "🔥 Δελτίο 30+"), ("x100", "🎰 Δελτίο 100+")):
        sl = view(lid, lists[lid]["slip"]) if view else lists[lid]["slip"]
        if sl:
            parts.append(f"<h4>{title}: απόδοση {sl['total_odds']:.1f}</h4>{_lot_note(sl)}{P.pick_table(_enrich(sl['legs'], cidx, tctx=tctx))}")
    if not parts:
        return ""
    return ("<details class='card'><summary><b>🎰 Λαχεία</b> <span class='muted'>· μόνο για πλάκα · πιθανότητα κάτω από ~10%</span></summary>"
            "<p class='muted'>Δελτία με μεγάλη απόδοση βγαίνουν σπάνια και έχουν τη μεγαλύτερη αναμενόμενη ζημιά. "
            f"Αν θες ένα, παίζεις το πολύ {cfg['bankroll']['lottery_stake']:.2f}€ τη βδομάδα.</p>" + "".join(parts) + "</details>")


def _picks_details(P, picks, title="Όλες οι επιλογές της κατηγορίας (για αναφορά)") -> str:
    if not picks:
        return ""
    return f"<details class='card'><summary>{E(title)}</summary>{P.pick_table(picks)}</details>"


def _leg_ticks(legs, scores, fair=False) -> str:
    rows = []
    for l in legs:
        ic = RESIC.get(l.get("result") or "open", "⏳")
        sc = scores.get(l["match_id"])
        stxt = f"{sc[0]}-{sc[1]}" if sc and sc[0] is not None else ""
        price = (f"≥ {l['odds']:.2f}" if fair else f"@ {l['odds']:.2f}") if l.get("odds") else ""
        rows.append(f"<div class='tk'><span class='ic'>{ic}</span><div><b>{E(l['home'])} – {E(l['away'])}</b> "
                    f"<span class='sc'>{stxt}</span><div class='muted'>{E(str(l.get('label') or ''))} {price}</div></div></div>")
    return "".join(rows)


def _yesterday_card(st, lid) -> str:
    """📅 Το δελτίο της προηγούμενης ημέρας αυτής της κατηγορίας, με ✅/❌ ανά αγώνα."""
    if not st:
        return ""
    sl = st["yesterday"].get(lid)
    name = NAMES_HIST.get(lid, lid)
    if not sl:
        return f"<div class='card'><h3>📅 Χθες · {E(name)}</h3><p class='muted'>Δεν υπήρχε δελτίο σε αυτή την κατηγορία.</p></div>"
    res = [l.get("result") or "open" for l in sl["legs"]]
    done = sum(1 for r in res if r in ("won", "lost", "void"))
    verdict = {"won": "<span class='ok'>✅ ΠΕΡΑΣΕ</span>", "lost": "<span class='ko'>❌ ΔΕΝ ΠΕΡΑΣΕ</span>",
               "void": "↩️ Άκυρο"}.get(sl["status"], f"⏳ Σε εξέλιξη ({done}/{len(res)} κρίθηκαν)")
    fair = lid.startswith("fair_")
    price = f"ελάχιστη απόδοση {sl['total_odds']:.2f}" if fair else f"απόδοση {sl['total_odds']:.2f}"
    return (f"<div class='card'><h3>📅 Χθες ({sl['day']:%d/%m}) · {E(name)}: {verdict}</h3>"
            f"<p class='muted'>{price} · πιθανότητα που είχαμε εκτιμήσει {sl['model_prob'] * 100:.0f}% · "
            f"{sum(1 for r in res if r == 'won')}/{len(res)} επιλογές βγήκαν</p>" + _leg_ticks(sl["legs"], st["scores"], fair) + "</div>")


NAMES_HIST = {"recommended": "⭐ Προτεινόμενο", "safe": "🛡️ Safe", "x10": "🎯 10+", "x30": "🔥 30+", "x100": "🎰 100+",
              "overs": "⚽ Over", "combo": "🔀 Συνδυαστικό", "fair_corners": "🚩 Κόρνερ", "fair_cards": "🟨 Κάρτες",
              "fair_throw_ins": "↔️ Πλάγια", "fair_players": "👤 Παίκτες"}


def _pct1(x):
    return "—" if x is None else f"{x * 100:.0f}%"


def _history_stats_html(st) -> str:
    """Στατιστικά ιστορικού: ποια δελτία πέρασαν, ημερολόγιο, ανάλυση επιλογών."""
    if not st or not st["n_slips"]:
        return ("<div class='card'><h3>📊 Στατιστικά δελτίων</h3><p class='muted'>Δεν υπάρχει ακόμα ιστορικό. Από αύριο κάθε πρωί "
                "καταγράφεται ΕΝΑ δελτίο ανά κατηγορία και την επόμενη μέρα φαίνεται αν πέρασε.</p></div>")
    rows, rows2 = [], []
    for lid, h in st["summary"].items():
        if not h["n"]:
            continue
        pl = "—" if h["pl"] is None else f"{h['pl']:+.2f}"
        nm = E(NAMES_HIST[lid])
        rows.append(f"<tr><td>{nm}</td><td class='n'>{h['n']}</td><td class='n ok'>{h['won']}</td>"
                    f"<td class='n ko'>{h['lost']}</td><td class='n'>{h['open']}</td><td class='n'><b>{_pct1(h['pass'])}</b></td></tr>")
        rows2.append(f"<tr><td>{nm}</td><td class='n'>{_pct1(h['avg_p'])}</td><td class='n'>{_pct1(h['leg_hit'])}</td>"
                     f"<td class='n'>{h['avg_odds']:.2f}</td><td class='n'>{pl}</td></tr>")
    summ = ("<div class='card'><h3>📊 Πόσα δελτία πέρασαν ανά κατηγορία</h3><p class='muted'>«Πέρασε» = βγήκαν ΟΛΕΣ οι επιλογές.</p>"
            "<div class='tbl'><table><thead><tr><th>Κατηγορία</th><th>Δελτία</th><th>✅</th><th>❌</th><th>⏳</th><th>Επιτυχία</th></tr></thead>"
            "<tbody>" + "".join(rows) + "</tbody></table></div>"
            "<h4>Ακρίβεια και απόδοση</h4><p class='muted'>«Αναμενόταν» = η πιθανότητα που είχαμε εκτιμήσει για τα δελτία που κρίθηκαν· αν η πραγματική "
            "επιτυχία είναι σταθερά πιο χαμηλή, το bot είναι υπερβολικά αισιόδοξο. Κ/Ζ σε μονάδες του 1 (όχι για κατηγορίες χωρίς απόδοση).</p>"
            "<div class='tbl'><table><thead><tr><th>Κατηγορία</th><th>Αναμενόταν</th><th>Επιτ. επιλογών</th><th>Μέση απόδ.</th><th>Κ/Ζ</th></tr></thead>"
            "<tbody>" + "".join(rows2) + "</tbody></table></div></div>")
    # ημερολόγιο
    cols = [l for l in st["summary"] if st["summary"][l]["n"]]
    grid_rows = []
    for d, cells in st["grid"].items():
        tds = "".join(f"<td>{RESIC.get(cells.get(l), '·')}</td>" for l in cols)
        n_ok = sum(1 for c in cells.values() if c == "won")
        n_ko = sum(1 for c in cells.values() if c == "lost")
        grid_rows.append(f"<tr><td class='d'>{d:%d/%m}</td>{tds}<td><b class='ok'>{n_ok}</b> / <b class='ko'>{n_ko}</b></td></tr>")
    grid = ("<div class='card'><h3>🗓️ Ημερολόγιο: ποια δελτία πέρασαν κάθε μέρα</h3><p class='muted'>✅ πέρασε · ❌ δεν πέρασε · ⏳ σε εξέλιξη · "
            "· δεν υπήρχε. Τελευταία στήλη: πόσα πέρασαν / πόσα όχι εκείνη τη μέρα.</p><div class='tbl'><table class='grid'><thead><tr><th></th>"
            + "".join(f"<th>{E(NAMES_HIST[l].split(' ')[0])}</th>" for l in cols) + "<th>✅/❌</th></tr></thead><tbody>"
            + "".join(grid_rows) + "</tbody></table></div></div>") if grid_rows else ""

    def table(title, rows_, keyname, note=""):
        if not rows_:
            return ""
        tr = "".join(f"<tr><td>{E(str(r['key']))}</td><td class='n'>{r['n']}</td><td class='n'>{r['won']}</td>"
                     f"<td class='n'><b>{r['hit'] * 100:.0f}%</b></td><td class='n'>{_pct1(r['p'])}</td></tr>" for r in rows_)
        return (f"<h4>{title}</h4>{note}<div class='tbl'><table><thead><tr><th>{keyname}</th><th>Επιλογές</th><th>Βγήκαν</th>"
                f"<th>Επιτυχία</th><th>Αναμενόταν</th></tr></thead><tbody>{tr}</tbody></table></div>")

    lg = st["legs"]
    legs = ""
    if lg["n"]:
        legs = ("<div class='card'><h3>🔬 Ανάλυση επιλογών (για να βελτιώνουμε το bot)</h3>"
                f"<p class='muted'>{lg['n']} διακριτές επιλογές που έχουν κριθεί (η ίδια επιλογή σε πολλά δελτία μετράει μία φορά). "
                "Με λίγες επιλογές τα ποσοστά είναι ασταθή· χρειάζονται δεκάδες για συμπέρασμα.</p>"
                + table("Ανά πιθανότητα (βαθμονόμηση)", lg["by_p"], "Πιθανότητα")
                + table("Ανά άθλημα", lg["by_sport"], "Άθλημα") + table("Ανά αγορά", lg["by_market"], "Αγορά")
                + table("Ανά διοργάνωση", lg["by_league"], "Διοργάνωση", "<p class='muted'>Μόνο διοργανώσεις με ≥5 επιλογές.</p>") + "</div>")
    # αναλυτικά τελευταίων ημερών
    byday = {}
    for sl in st["recent"]:
        byday.setdefault(sl["created_at"][:10], []).append(sl)
    det = []
    for day, ss in list(byday.items())[:7]:
        inner = "".join(f"<h4>{E(NAMES_HIST[s['list_name']])}: {RESIC.get(s['status'], '⏳')}</h4>"
                        f"{_leg_ticks(s['legs'], st['scores'], s['list_name'].startswith('fair_'))}" for s in ss)
        det.append(f"<details><summary><b>{day[8:10]}/{day[5:7]}</b> · "
                   f"✅ {sum(1 for s in ss if s['status'] == 'won')} · ❌ {sum(1 for s in ss if s['status'] == 'lost')}</summary>{inner}</details>")
    detail = ("<div class='card'><h3>📅 Αναλυτικά οι τελευταίες μέρες (✅/❌ σε κάθε αγώνα)</h3>" + "".join(det) + "</div>") if det else ""
    return summ + grid + legs + detail


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


def render_html(cfg, now, lists, cands, moves, hist_by_list, notes, clv=None, plan=None, goals=None, st=None, cidx=None) -> str:
    P = Page(cfg)
    tctx = {"scores": (st or {}).get("scores") or {}, "lgmap": {lg["id"]: lg.get("espn") for lg in cfg["leagues"]}}
    today_slips = (st or {}).get("today_slips") or {}

    def view(listname, current, fair=False):
        """Το δελτίο που ΚΑΤΑΓΡΑΦΕΤΑΙ στο ιστορικό σήμερα (κλειδωμένο), με ✅/❌ ανά αγώνα· αλλιώς το τωρινό (μη καταγεγραμμένο)."""
        fz = today_slips.get(listname)
        if fz:
            return {"legs": _enrich(fz["legs"], cidx, fair=fair, tctx=tctx), "total_odds": fz["total_odds"], "p_win": fz["model_prob"],
                    "p_market": None, "fair": fair, "locked": fz["created_at"]}
        if current:
            return dict(current, legs=_enrich(current["legs"], cidx, fair=fair, tctx=tctx), fair=fair)
        return None

    def lock_note(sl):
        if sl and sl.get("locked"):
            hh = parse_iso(sl["locked"]).astimezone(ZoneInfo(cfg["timezone"])).strftime("%H:%M")
            return f"<p class='muted'>🔒 Κλειδώθηκε στις {hh} και καταγράφεται στο ιστορικό. Τα ✅/❌ ενημερώνονται καθώς τελειώνουν οι αγώνες.</p>"
        return "<p class='muted'>Δεν καταγράφεται στο ιστορικό (δεν υπήρχε κλειδωμένο δελτίο σήμερα).</p>" if sl else ""
    hist_by_list = {k: v for k, v in hist_by_list.items() if k not in ("single", "safe1")}   # παλιά μονά: δεν παίζονται πια
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
    _rec_view = view("recommended", rec["slip"])
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
{P.slip_block(_rec_view, '⭐ Το δελτίο που προτείνω να παίξεις', br['unit'],
              "<p class='muted'>2–3 επιλογές, μόνο όσες περνούν όλους τους κανόνες (φόρμα, απουσίες, κινήσεις αποδόσεων, το πολύ 1 μπάσκετ).</p>" + lock_note(_rec_view))}
"""

    sl_safe = view("safe", lists["safe"].get("slip"))
    sec["safe"] = (P.slip_block(sl_safe, "🛡️ Safe δελτίο", br["unit"],
                                "<p class='muted'>Οι πιο πιθανές επιλογές της ημέρας σε ΕΝΑ δελτίο (χαμηλές αποδόσεις, υψηλή πιθανότητα ανά επιλογή).</p>" + lock_note(sl_safe))
                   + _picks_details(P, lists["safe"]["picks"], "Όλες οι σίγουρες επιλογές (αναφορά)"))
    _v = view("x10", lists["x10"]["slip"])
    sec["x10"] = P.slip_block(_v, f"🎯 Δελτίο {L['x10']['min_total']:.0f}+", br["lottery_stake"], _lot_note(lists["x10"]["slip"]) + lock_note(_v))
    _v = view("x30", lists["x30"]["slip"])
    sec["x30"] = P.slip_block(_v, f"🔥 Δελτίο {L['x30']['min_total']:.0f}+", br["lottery_stake"], _lot_note(lists["x30"]["slip"]) + lock_note(_v))
    _v = view("x100", lists["x100"]["slip"])
    sec["x100"] = P.slip_block(_v, f"🎰 Λαχείο {L['x100']['min_total']:.0f}+", br["lottery_stake"], _lot_note(lists["x100"]["slip"]) + lock_note(_v))
    ov = lists["overs"]
    _ov = view("overs", ov["slip"])
    sec["overs"] = (P.slip_block(_ov, "⚽ Over δελτίο (γκολ)", br["unit"], lock_note(_ov))
                    + _picks_details(P, ov["picks"], "Όλες οι επιλογές γκολ (αναφορά)"))
    for lid, title, what in (("corners", "🚩 Κόρνερ", "κόρνερ"), ("cards", "🟨 Κάρτες", "κάρτες"),
                             ("throw_ins", "↔️ Πλάγια", "πλάγια"), ("players", "👤 Παίκτες", "παίκτες")):
        x = lists[lid]
        note = ("<p class='muted'>Όπου γράφει «παίξ' το αν ≥», δεν βρήκαμε απόδοση: είναι η ελάχιστη απόδοση που "
                "κάνει την επιλογή να αξίζει. Αν το πρακτορείο σου δίνει λιγότερα, την αφήνεις.</p>")
        if lid == "players":
            note += "<p class='muted'>⚠️ Παίκτες: παίζεις ΜΟΝΟ αφού βγει η ενδεκάδα (~1 ώρα πριν).</p>"
        if lid == "throw_ins":
            note += "<p class='muted'>Τα πλάγια έρχονται μόνο από το Sofascore. Αν σήμερα δεν απάντησε, η λίστα μένει άδεια (δες ⚙️ Πηγές).</p>"
        cur = x.get("slip")
        fz_name = ("fair_" + lid) if (today_slips.get("fair_" + lid) or (cur and cur.get("fair"))) else lid
        sl = view(fz_name, cur, fair=fz_name.startswith("fair_"))
        if sl and sl.get("fair"):
            slip_html = P.slip_block(sl, f"{title}: δελτίο", None,
                                     "<p class='muted'>Δεν βρέθηκε απόδοση πρακτορείου: η «Συνολική απόδοση» είναι η ΕΛΑΧΙΣΤΗ για να αξίζει. "
                                     "Παίζεις μόνο αν το πρακτορείο σου δίνει τουλάχιστον τόση.</p>" + lock_note(sl))
        elif sl:
            slip_html = P.slip_block(sl, f"{title}: δελτίο", br["unit"], lock_note(sl))
        else:
            slip_html = ("<div class='card'><h3>" + E(title) + ": δελτίο</h3><p class='muted'>Σήμερα δεν υπάρχουν αρκετές "
                         "επιλογές για δελτίο σε αυτή την κατηγορία.</p></div>")
        body = slip_html + f"<div class='card'><h3>{title}: οδηγίες</h3>{note}</div>" + _picks_details(P, x["picks"], f"Όλες οι επιλογές {what} (αναφορά)")
        sec[lid] = body
    _cb = view("combo", lists["combo"]["slip"])
    sec["combo"] = P.slip_block(_cb, "🔀 Συνδυαστικό (διαφορετικές αγορές)", br["unit"], lock_note(_cb))

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
    sec["today"] = (_plan_html(P, plan, cfg, tz, cidx, tctx) + _alternatives_html(P, lists, plan, cfg, cidx, tctx, view)
                    + _lottery_html(P, lists, cfg, cidx, tctx, view))
    from .stats import TAB_LIST
    for tid, lname in TAB_LIST.items():
        if tid in sec:
            sec[tid] = _yesterday_card(st, lname) + sec[tid]
    sec["history"] = (_goals_card(goals) + _history_stats_html(st) + "<div class='card'><h3>📊 Κ/Ζ ανά λίστα (σε μονάδες)</h3><p class='muted'>Όλες οι λίστες καταγράφονται «στα χαρτιά» "
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
<meta name="generated" content="{iso(now)}"><style>{CSS}{EXTRA_CSS}</style></head><body><main>
<div id="stale" class="banner" hidden></div>
<header><h1>BetBot · {GR_DAYS[loc.weekday()]} {loc:%d/%m/%Y}</h1>
<p class="sub">Ενημέρωση {loc:%H:%M} · {n_matches} αγώνες · {n_with} επιλογές με απόδοση · {n_fair} με «δίκαιη απόδοση» · <a href="live.html"><b>🔴 Live: ✅/❌ σε κάθε αγώνα τώρα</b></a></p></header>
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
</script>
<script>{CORE_JS}</script>
<script>{INDEX_JS}</script></body></html>"""


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
