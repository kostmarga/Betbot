"""Αναφορά: μία HTML σελίδα με καρτέλες (dashboards) + email.

Καρτέλες: ⭐ Προτεινόμενο · 🛡️ Safe · 🎯 10+ · 🔥 30+ · 🎰 100+ · ⚽ Over · 🚩 Κόρνερ ·
          🟨 Κάρτες · ↔️ Πλάγια · 👤 Παίκτες · 🔀 Συνδυαστικό · 📉 Κινήσεις · 📊 Ιστορικό · ⚙️ Πηγές

Η σελίδα γράφεται στο docs/index.html (GitHub Pages) + docs/archive/ΗΗΗΗ-ΜΜ-ΗΗ.html.
Διαγράμματα: Chart.js (CDN). Χρώματα: validated παλέτα (μπλε = μοντέλο, πορτοκαλί = αγορά).
"""
from __future__ import annotations

import html
import re
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
    ("today", "🎯 Σήμερα"), ("recommended", "⭐ Προτεινόμενο"), ("safe", "Safe"), ("x10", "🎯 10+"), ("x30", "🔥 30+"),
    ("x100", "🎰 100+"), ("overs", "Over"), ("corners", "🚩 Κόρνερ"), ("cards", "🟨 Κάρτες"),
    ("throw_ins", "↔️ Πλάγια"), ("players", "👤 Παίκτες"), ("combo", "🔀 Συνδυαστικό"),
    ("live", "Live αξία"), ("moves", "📉 Κινήσεις"), ("analysis", "📊 Ανάλυση"), ("calendar", "📆 Ημερολόγιο"), ("sources", "⚙️ Πηγές"),
]
SLIP_TABS = ("recommended", "safe", "x10", "x30", "x100", "overs", "corners", "cards", "throw_ins", "players", "combo")
GROUPS = [   # κάτω μπάρα: (id, ετικέτα, εικονίδιο SVG path, καρτέλες)
    ("today", "Σήμερα", "M3 11l9-8 9 8M5 10v10h14V10", ("today",)),
    ("slips", "Δελτία", "M7 4h10a2 2 0 012 2v14l-3-2-2 2-2-2-2 2-2-2-3 2V6a2 2 0 012-2zM9 9h6M9 13h6", SLIP_TABS),
    ("analysis", "Ανάλυση", "M4 20V10M10 20V4M16 20v-8M22 20H2", ("analysis",)),
    ("calendar", "Ημερολόγιο", "M5 5h14a1 1 0 011 1v13a1 1 0 01-1 1H5a1 1 0 01-1-1V6a1 1 0 011-1zM4 10h16M8 3v4M16 3v4", ("calendar",)),
    ("more", "Άλλα", "M5 12h.01M12 12h.01M19 12h.01", ("live", "moves", "sources")),
]
LIST_NAMES = dict(TABS) | {"single": "⭐ Μονό της ημέρας", "safe1": "Safe (μονά)",
                           "fair_corners": "🚩 Κόρνερ (δίκαιη)", "fair_cards": "🟨 Κάρτες (δίκαιη)",
                           "fair_throw_ins": "↔️ Πλάγια (δίκαιη)", "fair_players": "👤 Παίκτες (δίκαιη)"}


def plain(name) -> str:
    """Το όνομα χωρίς το αρχικό emoji (π.χ. «🛡️ Safe» -> «Safe»)."""
    return re.sub(r"^[^0-9A-Za-zΑ-Ωα-ωά-ώ]+", "", name or "")


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
        odds_cell = (f"<b>{c['odds']:.2f}</b>" + (f"<div class='minp {'ok' if c['odds'] >= c['min_play'] else 'ko'}'>αξίζει από {c['min_play']:.2f}</div>" if c.get("min_play") else "")) if c.get("odds") else \
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
        whyline = f"<div class='whyline'>{E(c['why'][0])}</div>" if c.get("why") else ""
        if c.get("verdict"):
            vt = c["verdict"]
            vcls = "ok" if "ΑΞΙΖΕΙ —" in vt else "mid" if ("ΕΠΙΦΥΛΑΞΕΙΣ" in vt or "ΟΡΙΑΚΟ" in vt) else "ko" if "ΔΕΝ ΑΞΙΖΕΙ" in vt else ""
            whyline += f"<div class='verdict {vcls}'>{E(vt)}</div>"
        form = ""
        if c.get("form_home") or c.get("form_away"):
            form = f"<p class='muted'>{E(c['home'])}: {_badges(c.get('form_home', []))} &nbsp; " \
                   f"{E(c['away'])}: {_badges(c.get('form_away', []))}</p>"
        tk, scr, attr = "", "", ""
        if "res" in c:        # σκέλος καταγεγραμμένου δελτίου: ✅/❌/⚽/🏁/⏳ + σκορ (ενημερώνεται και ζωντανά από τον browser)
            _code, ic, txt = leg_state(c, getattr(self, "now", None))
            tk = f"<span class='tk' data-c='{_code}'>{ic}</span> "
            scr = f"<div class='scr'>{E(txt)}</div>"
            if c.get("eid") and c.get("lg"):
                leg = {k: c.get(k) for k in ("eid", "lg", "sport", "market", "ko", "res", "sc", "fair")}
                leg["sel"] = c.get("selection")
                leg["line"] = c.get("line")
                attr = f' data-leg="{E(json.dumps(leg, ensure_ascii=False))}"'
        return f"""<tr{attr}>
<td class="t">{tk}{_when(c['kickoff'], self.tz)}{scr}</td>
<td class="m"><b>{E(c['home'])}</b> – <b>{E(c['away'])}</b><br><span class="muted">{E(c['league_name'])}</span></td>
<td class="p"><b>{E(c['label'])}</b> {mv_cell}{warn}{whyline}
<details><summary>Όλοι οι λόγοι</summary><ul class="why">{why}</ul>{form}</details></td>
<td class="n o" data-l="Απόδ.">{odds_cell}</td><td class="n q" data-l="Πιθαν."><b>{_pct(c['p'])}</b></td><td class="n v" data-l="Value">{edge_cell}</td></tr>"""

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
        vd, dslip = "", ""
        if any("res" in l for l in sl["legs"]):
            vcode, vtxt = verdict([leg_state(l, getattr(self, "now", None))[0] for l in sl["legs"]])
            vd = f" <span class='vd b-{vcode}'>{vtxt}</span>"
            if sl.get("list"):
                dslip = f' data-slip="{E(sl["list"])}"'
        ttl = plain(title)
        mps = [l.get("min_play") for l in sl["legs"]]
        minp_total = (f"<div class='minp {'ok' if sl['total_odds'] >= math.prod(mps) else 'ko'}'>αξίζει από {math.prod(mps):.2f}</div>" if (mps and all(mps) and not sl.get("fair")) else "")
        lines = [f"{ttl} · απόδοση {sl['total_odds']:.2f} · πιθανότητα {sl['p_win'] * 100:.0f}%"]
        lines += [f"{_when(l['kickoff'], self.tz)} {l['home']} – {l['away']}: {plain(l['label'])} @ {l['odds']:.2f}" if l.get("odds")
                  else f"{_when(l['kickoff'], self.tz)} {l['home']} – {l['away']}: {plain(l['label'])}" for l in sl["legs"]]
        copy_btn = f'<button type="button" class="copybtn" data-copy="{E(chr(10).join(lines))}">Αντιγραφή δελτίου</button>'
        stake_v = f"{stake:.2f}€" if stake else "—"
        ret_v = f"{stake * sl['total_odds']:.2f}€" if stake else "—"
        return f"""<div class="card slip"{dslip}><div class="slip-top"><div><div class="eyebrow">{E(ttl)}</div>{vd}</div>
<div class="slip-odds"><small>Συνολική απόδοση</small><b>{sl['total_odds']:.2f}</b>{minp_total}</div></div>
<div class="slip-body">{_cnt_html(sl['legs'], getattr(self, 'now', None))}{self.pick_table(sl['legs'])}</div>
<div class="slip-stub"><div><small>Ποντάρισμα</small><b>{stake_v}</b></div><div><small>Αν κερδίσει</small><b class="pos">{ret_v}</b></div>
<div><small>Πιθανότητα</small><b>{sl['p_win'] * 100:.0f}%</b></div></div>
<div class="slip-copy">{copy_btn}</div>
<details class="slip-more"><summary>Λεπτομέρειες, σημειώσεις και διάγραμμα</summary>{note}<div class="tiles">
<div class="tile"><div class="k">Επιλογές</div><div class="v">{len(sl['legs'])}</div></div>
<div class="tile"><div class="k">Κατά την αγορά</div><div class="v">{pm}</div></div>{ev_tile}</div>{ch}</details></div>"""


from .theme import CSS, calm  # noqa: E402


END_MIN = {"football": 150, "basketball": 180}      # εκτίμηση διάρκειας αγώνα (λεπτά) – ίδιο με το BetbotLive.byTime στο JS
ENRICH = ("why", "form_home", "form_away", "warnings", "move", "verdict")


def leg_state(c, now):
    """(κωδικός, εικονίδιο, κείμενο) ενός σκέλους καταγεγραμμένου δελτίου. ⏳ ΜΟΝΟ πριν την έναρξη· μετά ⚽ ή 🏁 ή το αποτέλεσμα."""
    res = c.get("res")
    sc = c.get("sc")
    score = f"{sc[0]}-{sc[1]} ΤΕΛΟΣ" if sc else ""
    if res in ("won", "lost", "void"):
        return res, {"won": "✅", "lost": "❌", "void": "↩️"}[res], score
    ko = parse_iso(c.get("ko") or c.get("kickoff")) if (c.get("ko") or c.get("kickoff")) else None
    if ko is None or now is None or now < ko:
        return "pending", "⏳", ""
    if (now - ko).total_seconds() < END_MIN.get(c.get("sport"), 150) * 60:
        return "play", "⚽", "παίζεται"
    return "wait", "🏁", "τελείωσε · περιμένω αποτέλεσμα"


def verdict(codes):
    """(κωδικός, κείμενο) δελτίου από τους κωδικούς των σκελών (ίδια λογική με το BetbotLive.slipVerdict)."""
    if any(c == "lost" for c in codes):
        return "lost", "❌ ΔΕΝ ΠΕΡΑΣΕ"
    if codes and all(c in ("won", "void") for c in codes):
        return "won", "✅ ΠΕΡΑΣΕ"
    if any(c == "play" for c in codes):
        return "live", "⚽ Παίζεται"
    if any(c == "wait" for c in codes):
        return "wait", "🏁 Περιμένω αποτελέσματα"
    if any(c == "won" for c in codes):
        return "live", "🟢 Σε εξέλιξη"
    return "pending", "⏳ Δεν ξεκίνησε"
RESIC = {"won": "✅", "lost": "❌", "void": "↩️", "open": "⏳"}
EXTRA_CSS = ""      # όλο το CSS είναι στο betbot/theme.py

INDEX_JS = r"""
(function(){
const B = window.BetbotLive;
document.addEventListener('click', e => {
  const b = e.target.closest('.copybtn'); if (!b) return;
  const t = b.dataset.copy, done = () => { const o = b.dataset.o || b.textContent; b.dataset.o = o; b.textContent = 'Αντιγράφηκε ✓'; setTimeout(() => b.textContent = o, 1800); };
  const fb = () => { const a = document.createElement('textarea'); a.value = t; a.style.position = 'fixed'; a.style.opacity = '0'; document.body.appendChild(a); a.select(); try { document.execCommand('copy'); done(); } catch (x) {} a.remove(); };
  if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(t).then(done, fb); else fb();
});
// 1) ✅/❌/⚽/🏁 + σκορ σε κάθε αγώνα των δελτίων (ζωντανά, μόνο όσο παίζεται αγώνας)
const rows = [];
document.querySelectorAll('tr[data-leg]').forEach(tr => { try { rows.push({tr, leg: JSON.parse(tr.dataset.leg)}); } catch (e) {} });
const CODE = {'✅': 'won', '❌': 'lost', '↩️': 'void', '⚽': 'play', '🟢': 'ok', '🔴': 'ok', '🏁': 'wait', '⏳': 'pending', '➖': 'pending'};
const VIC = {won: '✅', lost: '❌', live: '⚽', wait: '🏁', pending: '⏳'};
function update() {
  rows.forEach(r => {
    const l = r.leg, st = B.trackable(l) ? B.cache[B.key(l)] : null, j = B.judge(l, st), c = j[0];
    const tk = r.tr.querySelector('.tk'); if (tk) { tk.textContent = B.IC[c]; tk.dataset.c = c; }
    const scr = r.tr.querySelector('.scr');
    if (scr) {
      let t = '';
      if (st && st.state !== 'pre') t = st.hs + '-' + st.as + (st.state === 'in' ? ' ' + st.clock : ' ΤΕΛΟΣ');
      else if (l.sc) t = l.sc[0] + '-' + l.sc[1] + ' ΤΕΛΟΣ';
      else if (c === 'play' || c === 'wait') t = j[1];
      scr.textContent = t;
    }
  });
  // ανά δελτίο: μετρητής + ετικέτα ΠΕΡΑΣΕ / ΔΕΝ ΠΕΡΑΣΕ
  const lists = {};
  document.querySelectorAll('.card[data-slip]').forEach(card => {
    const codes = Array.from(card.querySelectorAll('.tk')).map(x => CODE[x.textContent] || 'pending');
    const v = B.slipVerdict(codes);
    const vd = card.querySelector('.vd'); if (vd) { vd.className = 'vd b-' + v[0]; vd.textContent = v[1]; }
    const cnt = card.querySelector('.slipcnt');
    if (cnt) { const n = k => codes.filter(x => k.indexOf(x) >= 0).length; cnt.innerHTML = '✅ <b>' + n(['won']) + '</b> · ❌ <b>' + n(['lost']) + '</b> · ⚽ <b>' + n(['play', 'ok']) + '</b> παίζονται · 🏁 <b>' + n(['wait']) + '</b> περιμένω αποτέλεσμα · ⏳ <b>' + n(['pending']) + '</b> δεν ξεκίνησαν'; }
    const name = card.dataset.slip; if (!(name in lists)) lists[name] = v[0];
  });
  const tally = {won: 0, lost: 0, live: 0, wait: 0, pending: 0};
  document.querySelectorAll('.chip[data-chip]').forEach(ch => {
    const v = lists[ch.dataset.chip]; if (!v) return;
    const nm = ch.textContent.replace(/^\S+\s/, ''); ch.textContent = VIC[v] + ' ' + nm; ch.className = 'chip b-' + v; tally[v]++;
  });
  const line = document.querySelector('#daysum .line');
  if (line && document.querySelector('.chip[data-chip]')) line.innerHTML = 'Σήμερα: <b class="ok">✅ ' + tally.won + '</b> πέρασαν · <b class="ko">❌ ' + tally.lost + '</b> δεν πέρασαν · ⚽ <b>' + tally.live + '</b> παίζονται · 🏁 <b>' + tally.wait + '</b> περιμένω αποτέλεσμα · ⏳ <b>' + tally.pending + '</b> δεν ξεκίνησαν';
  // γραμμή κατάστασης (μόνο όταν έχει νόημα): τι συμβαίνει αυτή τη στιγμή και αν ο browser φτάνει στο ESPN
  const S = B.status(), ls = document.getElementById('livestat'); if (!ls) return;
  const link = ' <a href="https://github.com/kostmarga/Betbot/actions/workflows/daily.yml"><b>Ανανέωση αποτελεσμάτων →</b></a>';
  const blocked = !S.browserOk && S.lastErr;
  if (tally.live) ls.innerHTML = '🔴 ' + tally.live + ' δελτία με αγώνες που παίζονται· ενημερώνεται κάθε 2 λεπτά' + (blocked ? ' · ⚠️ δεν φτάνω στο ESPN από τη συσκευή σου, δείχνω εκτίμηση από την ώρα.' + link : '');
  else if (tally.wait) ls.innerHTML = blocked ? ('⚠️ Δεν μπόρεσα να φέρω τα τελικά αποτελέσματα από τη συσκευή σου. Δείχνω ό,τι ήξερε το bot στην τελευταία εκτέλεση.' + link) : '🏁 Περιμένω τα τελικά αποτελέσματα· ελέγχω κάθε 2 λεπτά.';
  else ls.textContent = '';
}
const legs = rows.map(r => r.leg);
if (legs.length) B.start(legs, update); else update();
// Αυτοέλεγχος: φτάνει η συσκευή σου στο ESPN; (μία ερώτηση κατά το άνοιγμα)
(function(){ var c = document.getElementById('espnchk'); if (!c) return;
  B.probe().then(function(r){ c.innerHTML = r === 'ok' ? '📡 Σύνδεση με ESPN από τη συσκευή σου: ✅ λειτουργεί' :
    '📡 Σύνδεση με ESPN από τη συσκευή σου: ⚠️ δεν απαντά (' + r + '). Τα αποτελέσματα θα φανούν μετά το επόμενο τρέξιμο του bot.'; }); })();

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


def _cnt_html(legs, now=None) -> str:
    """Μέτρηση ✅/❌/⚽/🏁/⏳ ενός δελτίου (όταν τα σκέλη έχουν αποτέλεσμα). Ενημερώνεται και ζωντανά από τον browser."""
    if not any("res" in l for l in legs):
        return ""
    codes = [leg_state(l, now)[0] for l in legs]
    c = lambda *k: sum(1 for x in codes if x in k)
    return (f"<div class='cnt slipcnt'>✅ <b>{c('won')}</b> · ❌ <b>{c('lost')}</b> · ⚽ <b>{c('play')}</b> παίζονται · "
            f"🏁 <b>{c('wait')}</b> περιμένω αποτέλεσμα · ⏳ <b>{c('pending')}</b> δεν ξεκίνησαν</div>")


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
            d["eid"] = mid[5:] if isinstance(mid, str) and mid.startswith("espn:") else (mid[11:] if isinstance(mid, str) and mid.startswith("euroleague:") else None)
            d["lg"] = "EL" if isinstance(mid, str) and mid.startswith("euroleague:") else tctx["lgmap"].get(l.get("league"))
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
    head = ("<details class='card'><summary><b>ℹ️ Πώς υπολογίζεται το πλάνο</b> <span class='muted'>· ποσά, όρια, λογιστική</span></summary>"
            + _tiles([("Σύνολο σήμερα", f"{plan['total']:.2f}€", ""), ("Διαθέσιμο εβδομάδας", f"{ws['remaining']:.2f}€", ""),
                      ("Ζημιά εβδομάδας", f"{ws['settled_loss']:.2f}€ / {ws['loss_limit']:.0f}€", ""),
                      ("Ανοιχτά", f"{ws['open_stake']:.2f}€", "")])
            + "".join(f"<p>{E(n)}</p>" for n in plan["notes"])
            + "<p class='muted'>Παίζεις ΜΟΝΟ δελτία (όχι μονά). Τα ποσά είναι ΑΝΩΤΑΤΑ όρια, όχι υποχρέωση. Το αναμενόμενο μακροπρόθεσμο "
              "αποτέλεσμα είναι μικρή ζημιά (περίπου −3% του ποσού, βλ. backtest)· παίζεις μόνο ό,τι μπορείς να χάσεις. "
              "Η εβδομαδιαία λογιστική υποθέτει ότι έπαιξες το πλάνο κάθε μέρα.</p></details>")
    cards = []
    for it in plan["items"]:
        legs = _enrich(it["legs"], cidx, tctx=tctx)
        ev = it["ev"] * 100
        srcs = sorted({SRC_NAME.get(l.get("best_source") or "", "") for l in it["legs"]} - {""})
        _vc, _vt = verdict([leg_state(l, tctx["now"] if tctx else None)[0] for l in legs]) if tctx else ("pending", "")
        sl_ = {"legs": legs, "total_odds": it["total_odds"], "p_win": it["p_win"], "p_market": None, "fair": False, "list": it["list"]}
        cards.append(P.slip_block(sl_, it["title"], it["stake"],
                                  f"<p class='muted'>Τιμές: {E(', '.join(srcs) or 'αγοράς')}. Πάτα «Γιατί;» σε κάθε επιλογή. "
                                  "Ψάξε την ίδια επιλογή στο πρακτορείο σου· αν η απόδοση εκεί είναι αισθητά χαμηλότερη, προτίμησε να μην παίξεις.</p>"))
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
    for lid, key, title in (("safe", "safe", "Safe δελτίο"), ("overs", "overs", "Over δελτίο"),
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


def _slip_history_body(sl, st, lid) -> tuple[str, str]:
    """(επικεφαλίδα-ετικέτα, σώμα) ενός κλεισμένου δελτίου με ✅/❌ ανά αγώνα."""
    res = [l.get("result") or "open" for l in sl["legs"]]
    done = sum(1 for r in res if r in ("won", "lost", "void"))
    verdict = {"won": "<span class='ok'>✅ ΠΕΡΑΣΕ</span>", "lost": "<span class='ko'>❌ ΔΕΝ ΠΕΡΑΣΕ</span>",
               "void": "↩️ Άκυρο"}.get(sl["status"], f"⏳ Σε εξέλιξη ({done}/{len(res)} κρίθηκαν)")
    fair = lid.startswith("fair_")
    price = f"ελάχιστη απόδοση {sl['total_odds']:.2f}" if fair else f"απόδοση {sl['total_odds']:.2f}"
    body = (f"<p class='muted'>{price} · πιθανότητα που είχαμε εκτιμήσει {sl['model_prob'] * 100:.0f}% · "
            f"{sum(1 for r in res if r == 'won')}/{len(res)} επιλογές βγήκαν</p>" + _leg_ticks(sl["legs"], st["scores"], fair))
    return verdict, body


def _yesterday_card(st, lid) -> str:
    """📅 Το δελτίο ΤΗΣ ΧΘΕΣΙΝΗΣ ημέρας αυτής της κατηγορίας, με ✅/❌ ανά αγώνα. Αν χθες δεν υπήρχε δελτίο, το λέει καθαρά
    και δείχνει (αναδιπλωμένο) το τελευταίο δελτίο που υπήρξε."""
    if not st:
        return ""
    from datetime import timedelta
    yday = st["today"] - timedelta(days=1)
    sl = st["yesterday"].get(lid)
    name = NAMES_HIST.get(lid, lid)
    if sl and sl["day"] == yday:
        verdict, body = _slip_history_body(sl, st, lid)
        return f"<div class='card'><h3>📅 Χθες ({yday:%d/%m}) · {E(name)}: {verdict}</h3>{body}</div>"
    head = f"<div class='card'><h3>📅 Χθες ({yday:%d/%m}) · {E(name)}</h3><p class='muted'>Χθες δεν υπήρχε δελτίο σε αυτή την κατηγορία.</p>"
    if not sl:
        return head + "</div>"
    verdict, body = _slip_history_body(sl, st, lid)
    return head + f"<details><summary>Τελευταίο δελτίο ({sl['day']:%d/%m}): {verdict}</summary>{body}</details></div>"


NAMES_HIST = {"recommended": "⭐ Προτεινόμενο", "safe": "Safe", "x10": "🎯 10+", "x30": "🔥 30+", "x100": "🎰 100+",
              "overs": "Over", "combo": "🔀 Συνδυαστικό", "fair_corners": "🚩 Κόρνερ", "fair_cards": "🟨 Κάρτες",
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


VERDICT_IC = {"won": "✅", "lost": "❌", "live": "⚽", "wait": "🏁", "pending": "⏳"}


def _day_summary_html(today_slips, cidx, tctx) -> str:
    """Γραμμή πάνω-πάνω: ποια δελτία της ημέρας πέρασαν / δεν πέρασαν / παίζονται, ένα «chip» ανά κατηγορία."""
    from .stats import LISTS, NAMES
    if not today_slips:
        return "<div class='daysum' id='daysum'><div class='line muted'>Σήμερα δεν έχει καταγραφεί ακόμα δελτίο.</div></div>"
    chips, cnt = [], {"won": 0, "lost": 0, "live": 0, "wait": 0, "pending": 0}
    for lid in LISTS:
        fz = today_slips.get(lid)
        if not fz:
            continue
        legs = _enrich(fz["legs"], cidx, fair=lid.startswith("fair_"), tctx=tctx)
        code, _ = verdict([leg_state(l, tctx["now"])[0] for l in legs])
        cnt[code] += 1
        chips.append(f"<span class='chip b-{code}' data-chip=\"{lid}\">{VERDICT_IC[code]} {E(NAMES[lid])}</span>")
    line = (f"Σήμερα: <b class='ok'>✅ {cnt['won']}</b> πέρασαν · <b class='ko'>❌ {cnt['lost']}</b> δεν πέρασαν · ⚽ <b>{cnt['live']}</b> παίζονται · "
            f"🏁 <b>{cnt['wait']}</b> περιμένω αποτέλεσμα · ⏳ <b>{cnt['pending']}</b> δεν ξεκίνησαν")
    return f"<div class='daysum' id='daysum'><div class='line'>{line}</div><div class='chips'>{''.join(chips)}</div></div>"


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


CAL_JS = """
(function(){
  var el=document.getElementById('caldata'); if(!el) return;
  var D=JSON.parse(el.textContent), box=document.getElementById('cal'), out=document.getElementById('calday');
  var MN=['Ιανουάριος','Φεβρουάριος','Μάρτιος','Απρίλιος','Μάιος','Ιούνιος','Ιούλιος','Αύγουστος','Σεπτέμβριος','Οκτώβριος','Νοέμβριος','Δεκέμβριος'];
  var IC={won:'✅',lost:'❌',void:'↩️',open:'⏳'};
  var keys=Object.keys(D).sort(), last=keys.length?keys[keys.length-1]:null;
  var cur=last?new Date(last+'T12:00:00'):new Date(); cur.setDate(1);
  function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]});}
  function pad(n){return (n<10?'0':'')+n;}
  function iso(y,m,d){return y+'-'+pad(m+1)+'-'+pad(d);}
  function dayBadge(k){var a=D[k]||[],w=0,l=0;a.forEach(function(s){if(s.f)return;if(s.s==='won')w++;else if(s.s==='lost')l++;});
    return a.length?('<span class="cw">'+(w?w+'✅':'')+'</span><span class="cl">'+(l?l+'❌':'')+'</span>'+((w+l)<a.length?'<span>⏳</span>':'')):'';}
  function cls(k){var w=0,l=0,a=D[k]||[];a.forEach(function(s){if(s.f)return;if(s.s==='won')w++;else if(s.s==='lost')l++;});return w&&!l?' w':l&&!w?' l':(w&&l)?' m':'';}
  function draw(){
    var y=cur.getFullYear(),m=cur.getMonth(),n=new Date(y,m+1,0).getDate(),off=(new Date(y,m,1).getDay()+6)%7;
    var h='<div class="calh"><button id="cprev">‹</button><b>'+MN[m]+' '+y+'</b><button id="cnext">›</button></div><div class="calg">';
    ['Δ','Τ','Τ','Π','Π','Σ','Κ'].forEach(function(x){h+='<div class="cdw">'+x+'</div>';});
    for(var i=0;i<off;i++)h+='<div></div>';
    for(var d=1;d<=n;d++){var k=iso(y,m,d),has=D[k]?' has'+cls(k):'';h+='<button class="cd'+has+'" data-d="'+k+'"'+(D[k]?'':' disabled')+'><i>'+d+'</i>'+dayBadge(k)+'</button>';}
    box.innerHTML=h+'</div>';
    document.getElementById('cprev').onclick=function(){cur.setMonth(cur.getMonth()-1);draw();};
    document.getElementById('cnext').onclick=function(){cur.setMonth(cur.getMonth()+1);draw();};
    Array.prototype.forEach.call(box.querySelectorAll('.cd.has'),function(b){b.onclick=function(){show(b.getAttribute('data-d'));};});
  }
  function show(k){
    var a=D[k]||[],h='<h4>'+k.split('-').reverse().join('/')+'</h4>';
    a.forEach(function(s){
      var v={won:'<span class="ok">✅ ΠΕΡΑΣΕ</span>',lost:'<span class="ko">❌ ΔΕΝ ΠΕΡΑΣΕ</span>',void:'↩️ Άκυρο'}[s.s]||'⏳ Σε εξέλιξη';
      h+='<div class="card"><b>'+esc(s.n)+'</b> · '+v+'<div class="muted">'+(s.f?'ελάχιστη απόδοση ':'απόδοση ')+s.o.toFixed(2)+' · εκτιμώμενη πιθανότητα '+Math.round(s.p*100)+'%</div>';
      s.L.forEach(function(l){h+='<div class="tk"><span class="ic">'+(IC[l.r]||'⏳')+'</span><div><b>'+esc(l.h)+' – '+esc(l.a)+'</b> <span class="sc">'+esc(l.sc)+'</span><div class="muted">'+esc(l.lb)+(l.o?' @ '+Number(l.o).toFixed(2):'')+'</div></div></div>';});
      h+='</div>';});
    out.innerHTML=h||'<p class="muted">Δεν υπάρχουν δελτία αυτή τη μέρα.</p>';
    out.scrollIntoView({behavior:'smooth',block:'nearest'});
  }
  draw(); if(last) show(last);
})();
"""


def _calendar_html(st) -> str:
    """📆 Ημερολόγιο: πατάς μια μέρα και βλέπεις όλα τα δελτία της με ✅/❌ ανά αγώνα."""
    if not st or not st.get("calendar"):
        return ""
    import json
    data = json.dumps(st["calendar"], ensure_ascii=False).replace("</", "<\\/")
    return ("<div class='card'><h3>📆 Ημερολόγιο: δες οποιαδήποτε μέρα</h3><p class='muted'>Πάτα μια μέρα για να δεις τι είχαμε προτείνει και "
            "τι πέρασε. ✅ = δελτία που πέρασαν, ❌ = που δεν πέρασαν, ⏳ = σε εξέλιξη. Περιλαμβάνει και τα επίπεδα ρίσκου.</p>"
            "<div id='cal'></div></div><div id='calday'></div>"
            f"<script type='application/json' id='caldata'>{data}</script><script>{CAL_JS}</script>")


def _ledger_html(pp) -> str:
    """Paper trading: ταμείο ανά κατηγορία × επίπεδο ρίσκου (βλ. betbot/paper.py)."""
    if not pp:
        return ""
    from .paper import CAT_NAME, CATS, TIER_NAME, TIERS
    R = {(r["cat"], r["tier"]): r for r in pp["rows"]}
    if not any(r["n"] for r in pp["rows"]):
        return ("<div class='card'><h3>📒 Ταμεία (paper trading)</h3><p class='muted'>Κάθε κατηγορία × επίπεδο ρίσκου έχει δικό της "
                f"εικονικό ταμείο {pp['weekly']:.0f}€ την εβδομάδα. Θα γεμίσει από την πρώτη εκτέλεση.</p></div>")
    money = lambda v: f"{v:+.2f}€"
    wk, tot = [], []
    for cat in CATS:
        for tier in TIERS:
            r = R[(cat, tier)]
            if not r["n"]:
                continue
            nm = f"{CAT_NAME[cat]} · {TIER_NAME[tier]}"
            cls = "ok" if r["wk_pl"] > 0 else "ko" if r["wk_pl"] < 0 else ""
            wk.append(f"<tr><td>{E(nm)}</td><td class='n'>{r['wk_bets']}</td><td class='n'>{r['wk_spent']:.0f}€</td>"
                      f"<td class='n {cls}'><b>{money(r['wk_pl'])}</b></td><td class='n'>{r['wk_open']:.0f}€</td>"
                      f"<td class='n'>{r['wk_left']:.0f}€</td>"
                      f"<td class='n'>{r['wk_pass']}✅ {r['wk_fail']}❌ <span class='muted'>(στόχος 5/7)</span></td></tr>")
            roi = "—" if r["roi"] is None else f"{r['roi']:+.0%}"
            ci = "" if not r["ci"] else f" <span class='muted'>({r['ci'][0]:+.0%}…{r['ci'][1]:+.0%})</span>"
            hit = "—" if r["hit"] is None else f"{r['hit']:.0%}"
            c2 = "ok" if r["profit"] > 0 else "ko" if r["profit"] < 0 else ""
            tot.append(f"<tr><td>{E(nm)}</td><td class='n'>{r['n']}</td><td class='n'>{r['won']}/{r['lost']}</td>"
                       f"<td class='n'>{hit}</td><td class='n {c2}'><b>{money(r['profit'])}</b></td><td class='n'>{roi}{ci}</td>"
                       f"<td class='n'>{'—' if r['avg_days'] is None else format(r['avg_days'], '.1f') + '/7'}</td><td>{r['verdict_text']}</td></tr>")
    return ("<div class='card'><h3>📒 Ταμεία: " f"{pp['weekly']:.0f}€ την εβδομάδα ανά κατηγορία και ρίσκο</h3>"
            "<p class='muted'>Εικονικά στοιχήματα (paper trading), δεν παίζεται πραγματικό χρήμα. Κάθε συνδυασμός έχει δικό του ταμείο· "
            "δείχνει πόσα θα είχαμε χάσει ή κερδίσει. Στόχος: να κρατήσουμε μόνο ό,τι αποδεδειγμένα αξίζει.</p>"
            f"<h4>Αυτή την εβδομάδα (από {pp['monday']:%d/%m})</h4><div class='tbl'><table><thead><tr><th>Ταμείο</th><th>Δελτία</th>"
            "<th>Στοιχηματίστηκαν</th><th>Κ/Ζ έως τώρα</th><th>Εκκρεμή</th><th>Υπόλοιπο</th><th>Μέρες που πέρασε</th></tr></thead><tbody>" + "".join(wk) + "</tbody></table></div>"
            "<h4>Συνολικά και κρίση</h4><p class='muted'>Κρίση μόνο μετά από " f"{pp['need']} δελτία που κρίθηκαν. «Αξίζει» = το κάτω όριο του 95% διαστήματος του ROI είναι "
            "πάνω από 0· «να αφαιρεθεί» = το πάνω όριο είναι κάτω από 0.</p>"
            "<div class='tbl'><table><thead><tr><th>Ταμείο</th><th>Δελτία</th><th>✅/❌</th><th>Επιτυχία</th><th>Κ/Ζ</th><th>ROI (95%)</th><th>Μέρες/εβδ.</th><th>Κρίση</th></tr></thead><tbody>"
            + "".join(tot) + "</tbody></table></div></div>")


LIVE_JS = r"""
document.addEventListener('DOMContentLoaded', function(){
const el = document.getElementById('priors'); if (!el) return;
const P = JSON.parse(el.textContent), box = document.getElementById('livebox'), B = window.BetbotLive;
const fact = n => { let r = 1; for (let i = 2; i <= n; i++) r *= i; return r; };
const pois = (k, l) => Math.exp(-l) * Math.pow(l, k) / fact(k);
const S = {};                       // eid -> {state, hs, as, min}
const redOf = st => st && st.stats ? ((st.stats.home && +st.stats.home.red) || 0) + ((st.stats.away && +st.stats.away.red) || 0) : 0;
function minute(st) {
  if (!st || st.state === 'pre') return 0;
  if (st.state === 'post') return 90;
  const d = String(st.clock || ''); if (/half/i.test(d) || /^HT/i.test(d)) return 45;
  const m = d.match(/(\d+)(?:\+(\d+))?/); return m ? Math.min(95, parseInt(m[1], 10) + (m[2] ? parseInt(m[2], 10) : 0)) : 0;
}
function markets(p, st) {
  // Χρόνος: το 44,4% των γκολ πέφτει στο 1ο ημίχρονο (tools/inplay_test.py)· όποιος προηγείται παίζει πιο συντηρητικά (δ=12%, βέλτιστο στο backtest)
  const mn = Math.min(95, minute(st)), g = mn <= 45 ? mn * 0.444 / 45 : 0.444 + (Math.min(mn, 90) - 45) * 0.556 / 45, f = Math.max(0.02, 1 - g);
  const h = st ? st.hs : 0, a = st ? st.as : 0, D = 0.12, N = 9; let lh = p.lh * f, la = p.la * f;
  if (h > a) { lh *= 1 - D; la *= 1 + D; } else if (a > h) { lh *= 1 + D; la *= 1 - D; } let p1 = 0, px = 0, p2 = 0, ov15 = 0, ov25 = 0, ov35 = 0, bt = 0;
  for (let i = 0; i < N; i++) for (let j = 0; j < N; j++) {
    const q = pois(i, lh) * pois(j, la), H = h + i, A = a + j, T = H + A;
    if (H > A) p1 += q; else if (H === A) px += q; else p2 += q;
    if (T >= 2) ov15 += q; if (T >= 3) ov25 += q; if (T >= 4) ov35 += q; if (H > 0 && A > 0) bt += q;
  }
  const t = p1 + px + p2;
  return [['Νίκη ' + p.home, p1 / t], ['Ισοπαλία', px / t], ['Νίκη ' + p.away, p2 / t], ['Over 1.5 γκολ', ov15 / t], ['Over 2.5 γκολ', ov25 / t],
          ['Over 3.5 γκολ', ov35 / t], ['Under 2.5 γκολ', 1 - ov25 / t], ['Και οι δύο σκοράρουν', bt / t]];
}
function render() {
  const now = Date.now(); let n = 0, html = '';
  P.forEach((p, idx) => {
    const ko = Date.parse(p.ko), st = S[p.eid], pre = now < ko, fin = st && st.state === 'post';
    if (fin) return; n++;
    const red = redOf(st), score = st && st.state !== 'pre' ? st.hs + '-' + st.as : '–', when = pre ? 'ξεκινά ' + B.hhmm(p.ko) : (st && st.state === 'in' ? (st.clock || 'παίζεται') : 'παίζεται');
    const rows = markets(p, st).map((m, k) => {
      const pr = m[1], fair = pr > 0.001 ? 1 / pr : 999;
      return '<tr data-i="' + idx + '" data-k="' + k + '"><td>' + B.esc(m[0]) + '</td><td class="n">' + (pr * 100).toFixed(0) + '%</td><td class="n"><b>' + fair.toFixed(2) +
        '</b></td><td class="n"><input class="od" inputmode="decimal" placeholder="απόδοση" value="' + (window.__odds && window.__odds[p.eid + '|' + k] || '') + '"></td><td class="vv"></td></tr>';
    }).join('');
    html += '<div class="card"><div class="slip-top"><div><div class="eyebrow">' + B.esc(p.league) + '</div><b>' + B.esc(p.home) + ' – ' + B.esc(p.away) + '</b>' +
      '<div class="muted">' + B.esc(when) + '</div>' + (red ? '<div class="wr">! Κόκκινη κάρτα: το μοντέλο δεν ισχύει, οι τιμές δεν υπολογίζονται</div>' : '') + '</div><div class="slip-odds"><small>Σκορ</small><b>' + score + '</b></div></div>' +
      '<div class="tbl"><table><thead><tr><th>Αγορά</th><th>Πιθ.</th><th>Δίκαιη απόδ.</th><th>Η απόδοσή σου</th><th></th></tr></thead><tbody>' + rows + '</tbody></table></div></div>';
  });
  if (!n) html = '<div class="card"><p class="muted">Δεν υπάρχουν ποδοσφαιρικοί αγώνες σήμερα με αρκετά δεδομένα αγοράς.</p></div>';
  const keep = {}; box.querySelectorAll('input.od').forEach(i => { const tr = i.closest('tr'); keep[P[tr.dataset.i].eid + '|' + tr.dataset.k] = i.value; });
  window.__odds = Object.assign(window.__odds || {}, keep);
  box.innerHTML = html; box.querySelectorAll('input.od').forEach(i => { i.addEventListener('input', verdicts); }); verdicts();
}
function verdicts() {
  box.querySelectorAll('tr[data-i]').forEach(tr => {
    const p = P[tr.dataset.i], m = markets(p, S[p.eid])[tr.dataset.k], inp = tr.querySelector('input.od'), v = parseFloat(String(inp.value).replace(',', '.')), c = tr.querySelector('.vv');
    window.__odds = window.__odds || {}; window.__odds[p.eid + '|' + tr.dataset.k] = inp.value;
    if (redOf(S[p.eid]) > 0) { c.textContent = '—'; return; }
    if (!(v > 1)) { c.textContent = ''; return; }
    const ev = m[1] * v - 1;
    c.innerHTML = ev >= 0.03 ? '<span class="badge good">αξίζει +' + (ev * 100).toFixed(0) + '%</span>' : '<span class="badge bad">όχι (' + (ev * 100).toFixed(0) + '%)</span>';
  });
}
async function poll() {
  const now = Date.now(); let any = false;
  for (const p of P) {
    const ko = Date.parse(p.ko); if (now < ko - 5 * 60000 || now > ko + 4 * 3600000) continue;
    const old = S[p.eid]; if (old && old.state === 'post') continue; any = true;
    try { const r = await fetch('https://site.api.espn.com/apis/site/v2/sports/soccer/' + p.lg + '/summary?event=' + p.eid); if (r.ok) S[p.eid] = B.parseSummary(await r.json()); } catch (e) {}
  }
  render(); setTimeout(poll, any ? 120000 : 300000);
}
render(); poll();
});
"""


def _live_html(pri) -> str:
    if not pri:
        return "<div class='card'><h3>Live αξία</h3><p class='muted'>Δεν υπάρχουν ποδοσφαιρικοί αγώνες με αρκετά δεδομένα αγοράς αυτή τη στιγμή.</p></div>"
    import json as _j
    data = _j.dumps(pri, ensure_ascii=False).replace('</', '<\\/')
    return ("<div class='card'><h3>Live αξία: τι αξίζει να παίξεις τώρα</h3><p class='muted'>Δίνουμε τη <b>δίκαιη απόδοση</b> κάθε αγοράς για το σκορ και το λεπτό που βλέπεις. "
            "Γράψε την απόδοση που βλέπεις στο πρακτορείο σου και η σελίδα λέει αν αξίζει (πάνω από +3% αξία). Δεν υπάρχουν δωρεάν ζωντανές αποδόσεις, γι' αυτό τις γράφεις εσύ.</p>"
            "<p class='muted'>Προσοχή: υπολογισμός χωρίς δοκιμή στο παρελθόν· αγνοεί κόκκινες κάρτες και τραυματισμούς. Ενημερώνεται κάθε 2 λεπτά μόνο για αγώνες που παίζονται.</p></div>"
            "<div id='livebox'></div>" + f"<script type='application/json' id='priors'>{data}</script><script>{LIVE_JS}</script>")


def _hero_html(plan, cfg, loc, n_matches, n_with, paper) -> str:
    """Η αρχική κάρτα: τι αποφασίζει το bot για σήμερα, σε μία ματιά."""
    br = cfg["bankroll"]
    weekly = float(br["weekly"])
    if not plan:
        head, why, kp = "Σήμερα", "Το πλάνο δεν είναι διαθέσιμο.", []
        rem = settled = total = None
    else:
        ws = plan["week"]
        rem, settled, total = ws["remaining"], ws["settled_loss"], plan["total"]
        n = len(plan["items"])
        if ws["stop"]:
            head, why = "Σταματάμε για αυτή την εβδομάδα", plan["notes"][0] if plan["notes"] else "Έφτασες το όριο ζημιάς."
        elif n:
            head = f"Σήμερα προτείνουμε {n} δελτί{'ο' if n == 1 else 'α'}"
            why = f"{total:.2f}€ συνολικά. Μόνο δελτία, ποτέ μονά."
        else:
            head = "Σήμερα δεν παίζουμε τίποτα"
            why = "Καμία επιλογή δεν πέρασε τους κανόνες. Είναι σωστή απόφαση, όχι σφάλμα."
    used = 0 if rem is None else max(0.0, min(1.0, 1 - rem / weekly))
    kp = ""
    if rem is not None:
        kp = (f"<div class='kpis'><div class='kpi'><div class='k'>Παίζω σήμερα</div><div class='v'>{total:.2f}€</div></div>"
              f"<div class='kpi'><div class='k'>Υπόλοιπο εβδομάδας</div><div class='v'>{rem:.2f}€</div></div>"
              f"<div class='kpi'><div class='k'>Ζημιά / όριο</div><div class='v'>{settled:.0f}/{weekly - float(br['stop_at']):.0f}€</div></div></div>"
              f"<div class='meter' title='Πόσο από το ταμείο της εβδομάδας έχει δεσμευτεί'><i style='width:{used * 100:.0f}%'></i></div>")
    wk = f"{GR_DAYS[loc.weekday()]} {loc:%d/%m/%Y}"
    return (f"<section class='hero'><div class='eyebrow'>{wk} · {n_matches} αγώνες · {n_with} επιλογές</div>"
            f"<div class='big'>{E(head)}</div><div class='why'>{E(why)}</div>{kp}</section>")


def _verdict_badge(v) -> str:
    return {"wait": "wait", "good": "good", "bad": "bad", "mid": "mid"}.get(v, "wait")


def _analysis_html(P, cfg, paper, st, goals, clv, extra_html="") -> str:
    """📊 Ανάλυση: συμπεράσματα, scorecards ανά κατηγορία/ρίσκο, γραφήματα, βαθμονόμηση."""
    from .paper import CAT_NAME, CATS, TIER_NAME, TIERS
    out = []
    rows = paper["rows"] if paper else []
    R = {(r["cat"], r["tier"]): r for r in rows}
    tot_settled = sum(r["settled"] for r in rows)
    need = paper["need"] if paper else 30
    # ---- συμπεράσματα
    ins = []
    if not tot_settled:
        ins.append(("i", "Μαζεύουμε στοιχεία", f"Δεν έχει κριθεί ακόμα δελτίο στα εικονικά ταμεία. Η κρίση θα γίνει μετά από {need} δελτία ανά ταμείο."))
    else:
        ins.append(("i", f"{tot_settled} δελτία έχουν κριθεί συνολικά",
                    f"Για αξιόπιστο συμπέρασμα χρειάζονται {need}+ ανά ταμείο· όσα ταμεία έχουν λιγότερα είναι ενδείξεις, όχι αποδείξεις."))
        cand = [r for r in rows if r["settled"] >= 5 and r["roi"] is not None]
        if cand:
            b = max(cand, key=lambda r: r["roi"])
            w = min(cand, key=lambda r: r["roi"])
            ins.append(("★", f"Καλύτερο ταμείο μέχρι τώρα: {CAT_NAME[b['cat']]} · {TIER_NAME[b['tier']]}",
                        f"ROI {b['roi']:+.0%} σε {b['settled']} δελτία, επιτυχία {b['hit']:.0%}. (πρώιμη ένδειξη)"))
            if w is not b:
                ins.append(("!", f"Πιο αδύναμο: {CAT_NAME[w['cat']]} · {TIER_NAME[w['tier']]}",
                            f"ROI {w['roi']:+.0%} σε {w['settled']} δελτία. Αν παραμείνει χαμηλό μετά τα {need} δελτία, αφαιρείται."))
        pe = [(r["avg_p"], r["hit"], r["settled"]) for r in rows if r["settled"] and r["avg_p"] and r["hit"] is not None]
        if pe:
            n_ = sum(x[2] for x in pe)
            exp_ = sum(x[0] * x[2] for x in pe) / n_
            act_ = sum(x[1] * x[2] for x in pe) / n_
            msg = ("το bot είναι υπερβολικά αισιόδοξο" if act_ < exp_ - 0.08 else
                   "το bot είναι συντηρητικό" if act_ > exp_ + 0.08 else "οι εκτιμήσεις του bot είναι ρεαλιστικές")
            ins.append(("◎", "Αναμενόμενη vs πραγματική επιτυχία", f"Αναμενόταν {exp_:.0%}, βγήκε {act_:.0%}: {msg}."))
        d5 = [r for r in rows if r["avg_days"] is not None]
        if d5:
            b5 = max(d5, key=lambda r: r["avg_days"])
            ins.append(("▦", "Στόχος 5 στις 7 ημέρες",
                        f"Το πιο κοντά: {CAT_NAME[b5['cat']]} · {TIER_NAME[b5['tier']]} με {b5['avg_days']:.1f}/7 ημέρες ανά εβδομάδα. Προσοχή: πολλές νίκες δεν σημαίνουν κέρδος."))
    out.append("<div class='card'><h3>💡 Τι μάθαμε μέχρι τώρα</h3>" + "".join(
        f"<div class='insight'><div class='ico'>{i}</div><div><b>{E(t)}</b><span>{E(d)}</span></div></div>" for i, t, d in ins) + "</div>")
    # ---- scorecards
    cards = []
    for cat in CATS:
        trs = []
        for tier in TIERS:
            r = R.get((cat, tier))
            if not r or not r["n"]:
                continue
            prog = min(1.0, r["settled"] / need)
            roi = "—" if (r["roi"] is None or r["settled"] < 5) else f"{r['roi']:+.0%}"
            hit = "—" if r["hit"] is None else f"{r['hit']:.0%}"
            pl = f"{r['profit']:+.2f}€"
            gd = "—" if r["green_days"] is None else f"{r['green_days']:.0%}"
            gw = "—" if r["green_weeks"] is None else f"{r['green_weeks']:.0%}"
            trs.append(f"<div class='trow'><div><div class='nm'>{TIER_NAME[tier]}</div><div class='st'>{r['won']}✅ {r['lost']}❌ · {r['open']}⏳</div><div class='st'>πράσινες μέρες {gd} · εβδ. {gw}</div></div>"
                       f"<div><div class='st'>επιτυχία <b>{hit}</b> · ROI <b>{roi}</b> · Κ/Ζ <b class='{'pos' if r['profit'] > 0 else 'neg' if r['profit'] < 0 else ''}'>{pl}</b></div>"
                       f"<div class='bar2' title='{r['settled']}/{need} δελτία για κρίση'><i style='width:{prog * 100:.0f}%'></i></div></div>"
                       f"<span class='badge {_verdict_badge(r['verdict'])}'>{E(r['verdict_text'])}</span></div>")
        if trs:
            cards.append(f"<div class='scorecard'><h4>{E(CAT_NAME[cat])}</h4>{''.join(trs)}</div>")
    if cards:
        out.append("<h4 style='margin:18px 2px 8px'>Ταμεία ανά κατηγορία και ρίσκο</h4><p class='muted' style='margin:0 2px 8px'>Εικονικά στοιχήματα· "
                   "η μπάρα δείχνει πόσο κοντά είμαστε στα δελτία που χρειάζονται για κρίση.</p><div class='sc-grid'>" + "".join(cards) + "</div>")
    # ---- γράφημα σωρευτικού Κ/Ζ
    top = sorted([r for r in rows if len(r["series"]) >= 2], key=lambda r: -len(r["series"]))[:6]
    if top:
        days = sorted({d for r in top for d, _ in r["series"]})
        ds = []
        for i, r in enumerate(top):
            m = dict(r["series"])
            last, data = None, []
            for d in days:
                last = m.get(d, last)
                data.append(last)
            ds.append({"label": f"{CAT_NAME[r['cat']]} · {TIER_NAME[r['tier']]}", "data": data, "borderColor": SERIES[i % len(SERIES)],
                       "backgroundColor": SERIES[i % len(SERIES)], "tension": .25, "pointRadius": 2, "spanGaps": True})
        out.append("<div class='card'><h3>💶 Σωρευτικό κέρδος/ζημιά (€, εικονικά)</h3>" + P.chart(
            {"type": "line", "data": {"labels": [f"{d[8:10]}/{d[5:7]}" for d in days], "datasets": ds},
             "options": {"scales": {"y": {"title": {"display": True, "text": "€"}}}, "plugins": {"legend": {"position": "bottom"}}}}) + "</div>")
    # ---- βαθμονόμηση
    lg = (st or {}).get("legs") or {}
    bp = [r for r in lg.get("by_p", []) if r["p"] is not None]
    if bp:
        out.append("<div class='card'><h3>🎯 Βαθμονόμηση: ό,τι λέμε, βγαίνει;</h3><p class='muted'>Αν οι μπάρες είναι ίδιες, το bot λέει "
                   "την αλήθεια. Αν το «πραγματικό» είναι χαμηλότερο, είναι υπερβολικά αισιόδοξο.</p>" + P.chart(
            {"type": "bar", "data": {"labels": [f"{r['key']} (n={r['n']})" for r in bp], "datasets": [
                {"label": "Αναμενόταν %", "data": [round(r["p"] * 100) for r in bp], "backgroundColor": "var(--s1)"},
                {"label": "Βγήκε %", "data": [round(r["hit"] * 100) for r in bp], "backgroundColor": "var(--s3)"}]},
             "options": {"scales": {"y": {"min": 0, "max": 100}}, "plugins": {"legend": {"position": "bottom"}}}}, small=True) + "</div>")
    out.append(_goals_card(goals))
    out.append(extra_html)
    return "".join(out)


def render_html(cfg, now, lists, cands, moves, hist_by_list, notes, clv=None, plan=None, goals=None, st=None, cidx=None, paper=None, tier_lists=None, inplay=None) -> str:
    P = Page(cfg)
    P.now = now
    tctx = {"scores": (st or {}).get("scores") or {}, "lgmap": {lg["id"]: lg.get("espn") for lg in cfg["leagues"]}, "now": now}
    today_slips = (st or {}).get("today_slips") or {}

    def view(listname, current, fair=False):
        """Το δελτίο που ΚΑΤΑΓΡΑΦΕΤΑΙ στο ιστορικό σήμερα (κλειδωμένο), με ✅/❌ ανά αγώνα· αλλιώς το τωρινό (μη καταγεγραμμένο)."""
        fz = today_slips.get(listname)
        if fz:
            return {"legs": _enrich(fz["legs"], cidx, fair=fair, tctx=tctx), "total_odds": fz["total_odds"], "p_win": fz["model_prob"],
                    "p_market": None, "fair": fair, "locked": fz["created_at"], "list": listname}
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

    def tab_sections(lists, sfx=""):
        sec = {}
        # ⭐ Προτεινόμενο
        rec = lists["recommended"]
        _rec_view = view("recommended" + sfx, rec["slip"])
        single = rec["single"]
        intro = f"""<div class="card"><h3>Τι να περιμένεις (backtest 13 μηνών, 6.100 αγώνες)</h3><ul class="rules">
    <li>Δεν βρήκαμε τρόπο να <b>νικήσουμε την αγορά</b>: το στατιστικό μοντέλο γκολ ήταν χειρότερο από τις αποδόσεις των πρακτορείων, γι' αυτό οι πιθανότητες βγαίνουν πλέον από την αγορά.</li>
    <li>Με τους σημερινούς κανόνες (φαβορί, χωρίς Under 2.5, απόδοση έως 3.0) το ιστορικό ROI ήταν <b>≈ −0.2%</b> στην καλύτερη τιμή και <b>≈ −3%</b> στη μέση τιμή: δηλαδή περίπου «στο μηδέν» μείον την προμήθεια.</li>
    <li>Άρα ό,τι παίζεις είναι <b>ψυχαγωγία με ελεγχόμενο κόστος</b>, όχι εισόδημα. Κράτα το ταμείο και τα όριά σου. Η «Αναμενόμενη» τιμή σε κάθε δελτίο είναι η εκτίμηση κέρδους/ζημιάς ανά 1€.</li>
    <li>Ψάξε <b>την καλύτερη τιμή</b> ανάμεσα στα πρακτορεία: αξίζει ~3 μονάδες ROI. Οι τιμές εδώ είναι της αγοράς, όχι απαραίτητα του δικού σου πρακτορείου.</li></ul></div>
    <div class="card"><h3>Πλάνο εβδομάδας</h3><ul class="rules">
    <li>Ταμείο εβδομάδας: <b>{br['weekly']:.0f}€</b> · μονάδα <b>{br['unit']:.2f}€</b> · έως <b>{br['max_bets_per_day']}</b> στοιχήματα τη μέρα</li>
    <li>Stop: αν το ταμείο πέσει στα <b>{br['stop_at']:.0f}€</b>, σταματάμε για την εβδομάδα</li>
    <li>Λαχεία (30+ / 100+): <b>{br['lottery_stake']:.2f}€</b>, μία φορά τη βδομάδα</li>
    <li>Ποτέ διπλασιασμός για να «πάρουμε πίσω» τη χθεσινή μέρα</li></ul></div>""" if not sfx else ""
        sec["recommended"] = f"""
    {P.slip_block(_rec_view, '⭐ Το δελτίο που προτείνω να παίξεις', br['unit'],
                  "<p class='muted'>2–3 επιλογές, μόνο όσες περνούν όλους τους κανόνες (φόρμα, απουσίες, κινήσεις αποδόσεων, το πολύ 1 μπάσκετ).</p>" + lock_note(_rec_view))}
    <details class="card"><summary><b>Τι να περιμένεις</b> <span class="muted">· backtest, πλάνο εβδομάδας</span></summary>{intro}</details>
    """ if not sfx else f"""
    {P.slip_block(_rec_view, '⭐ Το δελτίο που προτείνω να παίξεις', br['unit'], lock_note(_rec_view))}
    """

        sl_safe = view("safe" + sfx, lists["safe"].get("slip"))
        sec["safe"] = (P.slip_block(sl_safe, "Safe δελτίο", br["unit"],
                                    "<p class='muted'>Οι πιο πιθανές επιλογές της ημέρας σε ΕΝΑ δελτίο (χαμηλές αποδόσεις, υψηλή πιθανότητα ανά επιλογή).</p>" + lock_note(sl_safe))
                       + _picks_details(P, lists["safe"]["picks"], "Όλες οι σίγουρες επιλογές (αναφορά)"))
        _v = view("x10" + sfx, lists["x10"]["slip"])
        sec["x10"] = P.slip_block(_v, f"🎯 Δελτίο {L['x10']['min_total']:.0f}+", br["lottery_stake"], _lot_note(lists["x10"]["slip"]) + lock_note(_v))
        _v = view("x30" + sfx, lists["x30"]["slip"])
        sec["x30"] = P.slip_block(_v, f"🔥 Δελτίο {L['x30']['min_total']:.0f}+", br["lottery_stake"], _lot_note(lists["x30"]["slip"]) + lock_note(_v))
        _v = view("x100" + sfx, lists["x100"]["slip"])
        sec["x100"] = P.slip_block(_v, f"🎰 Λαχείο {L['x100']['min_total']:.0f}+", br["lottery_stake"], _lot_note(lists["x100"]["slip"]) + lock_note(_v))
        ov = lists["overs"]
        _ov = view("overs" + sfx, ov["slip"])
        sec["overs"] = (P.slip_block(_ov, "Over δελτίο (γκολ)", br["unit"], lock_note(_ov))
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
            fz_name = (("fair_" + lid) if (today_slips.get("fair_" + lid + sfx) or (cur and cur.get("fair"))) else lid) + sfx
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
        _cb = view("combo" + sfx, lists["combo"]["slip"])
        sec["combo"] = P.slip_block(_cb, "🔀 Συνδυαστικό (διαφορετικές αγορές)", br["unit"], lock_note(_cb))

        return sec

    sec = tab_sections(lists)
    sec_t = {t: tab_sections(tier_lists[t], suf) for t, suf in (('strong', '~s'), ('bold', '~b')) if tier_lists and t in tier_lists}

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
    daysum_html = _day_summary_html(today_slips, cidx, tctx)
    sec["today"] = (_hero_html(plan, cfg, loc, n_matches, n_with, paper) + daysum_html + '<div class="livestat" id="livestat"></div>' + _plan_html(P, plan, cfg, tz, cidx, tctx) + _alternatives_html(P, lists, plan, cfg, cidx, tctx, view)
                    + _lottery_html(P, lists, cfg, cidx, tctx, view))
    from .stats import TAB_LIST
    ydays = {tid: _yesterday_card(st, lname) for tid, lname in TAB_LIST.items() if tid in sec}
    _details = ("<details class='card'><summary><b>🔎 Αναλυτικοί πίνακες</b> <span class='muted'>· όλα τα νούμερα αναλυτικά</span></summary>"
                + _ledger_html(paper) + _history_stats_html(st) + "<div class='card'><h3>📊 Κ/Ζ ανά λίστα (σε μονάδες)</h3><p class='muted'>Όλες οι λίστες καταγράφονται «στα χαρτιά» "
                      "με 1 μονάδα, για να βλέπουμε ποια δουλεύει. Χρειάζονται 4–6 εβδομάδες για σοβαρό συμπέρασμα. "
                      "«Επιτυχία επιλογών» = πόσες μεμονωμένες επιλογές βγήκαν.</p>"
                      + ("<div class='tbl'><table><thead><tr><th>Λίστα</th><th>Κλεισμένα</th><th>Κέρδισαν</th><th>%</th>"
                         "<th>Επιτυχία επιλογών</th><th>Κ/Ζ</th><th>ROI</th><th>Ανοιχτά</th></tr></thead><tbody>"
                         + "".join(rows) + "</tbody></table></div>" if rows else "<p class='muted'>Δεν υπάρχει ακόμα ιστορικό.</p>")
                      + "</div>" + hist_chart + _clv_card(clv) + "</details>")
    sec["analysis"] = _analysis_html(P, cfg, paper, st, goals, clv, _details)
    sec["live"] = _live_html(inplay)
    sec["calendar"] = _calendar_html(st) or "<div class='card'><p class='muted'>Το ημερολόγιο θα γεμίσει με τα πρώτα δελτία.</p></div>"

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

    TIER_META = [("strong", "Δυνατό", "πιο σίγουρο, μικρότερη απόδοση"), ("balanced", "Ισορροπημένο", "η προεπιλογή"),
                 ("bold", "Τολμηρό", "λιγότερο σίγουρο, μεγαλύτερη απόδοση")]
    if sec_t:
        for tid in SLIP_TABS:
            if tid not in sec:
                continue
            panes = [("balanced", sec[tid])] + [(t, sec_t[t][tid]) for t in ("strong", "bold") if t in sec_t and tid in sec_t[t]]
            bar = ("<div class='tiersel' role='group' aria-label='Επίπεδο ρίσκου'>"
                   + "".join(f"<button data-tier='{t}' aria-pressed='{str(t == 'balanced').lower()}'><i class='dot d-{t}'></i><b>{n}</b><span>{d}</span></button>"
                             for t, n, d in TIER_META if t in dict(panes)) + "</div>")
            sec[tid] = bar + "".join(f"<div class='tierpane' data-tier='{t}'{'' if t == 'balanced' else ' hidden'}>{h}</div>" for t, h in panes)
    for tid, h in ydays.items():       # «Χθες» κάτω από το σημερινό δελτίο, εκτός των επιπέδων ρίσκου
        sec[tid] = sec[tid] + h
    body = "".join(f"<section class='tab{' on' if i == 0 else ''}' id='t-{tid}' role='tabpanel'>{sec.get(tid, '')}</section>"
                   for i, (tid, _) in enumerate(TABS))
    names = dict(TABS)
    bar_html = "".join(
        f"<button data-g='{gid}' aria-selected='{str(i == 0).lower()}'><svg viewBox='0 0 24 24'><path d='{ico}'/></svg>{lab}</button>"
        for i, (gid, lab, ico, _t) in enumerate(GROUPS))
    chips_html = "".join(
        f"<div class='chipnav' id='cn-{gid}' hidden>" + "".join(f"<button data-t='{t}' aria-selected='false'>{E(plain(names[t]))}</button>" for t in tabs) + "</div>"
        for gid, _l, _i, tabs in GROUPS if len(tabs) > 1)
    tabs_html = ""
    js = json.dumps([[cid, c] for cid, c in P.charts], ensure_ascii=False)
    return calm(f"""<!doctype html><html lang="el"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>BetBot Δελτίο</title>
<link rel="manifest" href="manifest.webmanifest"><link rel="apple-touch-icon" href="icon-192.png"><meta name="theme-color" content="#0f172a">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-title" content="BetBot">
<meta name="generated" content="{iso(now)}"><style>{CSS}{EXTRA_CSS}</style></head><body><main>
<header class="appbar"><div class="logo">B</div><div class="t"><b>BetBot</b><span>{GR_DAYS[loc.weekday()]} {loc:%d/%m} · ενημέρωση {loc:%H:%M}</span></div>
<a class="pill live" href="live.html"><i></i>Live</a></header>
<div id="stale" class="banner" hidden></div>
{"<div class='warn' style='border-left-color:var(--bad);margin-bottom:8px'><b>DEMO</b> – φανταστικές ομάδες και παίκτες, μόνο για να δεις πώς δουλεύει η σελίδα. Δεν είναι πραγματικό δελτίο.</div>" if cfg.get("_demo") else ""}
{chips_html}{body}
<div class="livestat" id="espnchk"></div>
<p class="disclaimer">Στατιστική εκτίμηση, όχι εγγύηση. Ακόμα και οι «σίγουρες» επιλογές χάνουν περίπου 1 στις 3–4 φορές. Εικονικά στοιχήματα (paper trading) μέχρι να αποδειχθεί ότι υπάρχει πλεονέκτημα.</p></main>
<nav class="bar" role="tablist">{bar_html}</nav>
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
   Chart.defaults.elements.line.borderWidth = 2; Chart.defaults.elements.point.radius = 3; Chart.defaults.elements.point.borderColor = v('var(--surface)');
   Chart.defaults.elements.bar.borderColor = v('var(--surface)'); Chart.defaults.elements.bar.borderWidth = 2;
   Chart.defaults.plugins.legend.labels.usePointStyle = true; Chart.defaults.plugins.legend.labels.boxWidth = 8;
   Chart.defaults.interaction = {{mode: 'index', intersect: false}};
   Chart.defaults.plugins.tooltip.backgroundColor = v('var(--ink)'); Chart.defaults.plugins.tooltip.titleColor = v('var(--plane)'); Chart.defaults.plugins.tooltip.bodyColor = v('var(--plane)');
   Chart.defaults.scale.grid.drawTicks = false;
   for (const [id, cfg] of CH) {{
     const el = document.getElementById(id);
     if(!el || drawn[id] || !root.contains(el)) continue;
     const det = el.closest('details');
     if (det && !det.open) {{ det.addEventListener('toggle', () => {{ if(det.open && !drawn[id]){{ drawn[id]=new Chart(el, fix(cfg)); }} }}, {{once:false}}); continue; }}
     drawn[id] = new Chart(el, fix(cfg));
   }}
 }}
 const GR = {json.dumps({gid: list(tabs) for gid, _l, _i, tabs in GROUPS})};
 const grpOf = t => Object.keys(GR).find(g => GR[g].indexOf(t) >= 0);
 const barBtns = document.querySelectorAll('.bar button'), chipBtns = document.querySelectorAll('.chipnav button');
 let lastIn = {{}};
 function show(t){{
   const g = grpOf(t); lastIn[g] = t;
   barBtns.forEach(b => b.setAttribute('aria-selected', String(b.dataset.g===g)));
   document.querySelectorAll('.chipnav').forEach(c => c.hidden = (c.id !== 'cn-'+g));
   chipBtns.forEach(b => b.setAttribute('aria-selected', String(b.dataset.t===t)));
   document.querySelectorAll('.tab').forEach(s => s.classList.toggle('on', s.id==='t-'+t));
   const s = document.getElementById('t-'+t); if(s) drawIn(s);
   window.scrollTo({{top:0}});
   try {{ localStorage.setItem('betbot_tab', new Date().toDateString() + '|' + t); }} catch(e) {{}}
 }}
 function setTier(t){{
   document.querySelectorAll('.tierpane').forEach(p => p.hidden = (p.dataset.tier !== t));
   document.querySelectorAll('.tiersel button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.tier === t)));
   try {{ localStorage.setItem('betbot_tier', t); }} catch(e) {{}}
 }}
 document.querySelectorAll('.tiersel button').forEach(b => b.addEventListener('click', () => setTier(b.dataset.tier)));
 try {{ const t = localStorage.getItem('betbot_tier'); if (t && document.querySelector('.tierpane[data-tier="'+t+'"]')) setTier(t); }} catch(e) {{}}
 barBtns.forEach(b => b.addEventListener('click', () => show(lastIn[b.dataset.g] || GR[b.dataset.g][0])));
 chipBtns.forEach(b => b.addEventListener('click', () => show(b.dataset.t)));
 let start = 'today';      // κάθε νέα μέρα ανοίγει στο πλάνο· η μνήμη καρτέλας ισχύει μόνο μέσα στην ίδια μέρα
 try {{ const v = (localStorage.getItem('betbot_tab') || '').split('|'); if (v[0] === new Date().toDateString() && document.getElementById('t-'+v[1])) start = v[1]; }} catch(e) {{}}
 show(start);
}})();
</script>
<script>{CORE_JS}</script>
<script>{INDEX_JS}</script></body></html>""")


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
