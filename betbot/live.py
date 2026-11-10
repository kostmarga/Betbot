"""Live σελίδα δελτίων (docs/live.html): ✅/❌ σε ΚΑΘΕ αγώνα, ανά πάσα στιγμή, πριν τελειώσει ολόκληρο το δελτίο.

Πώς δουλεύει:
  - Το bot (σε κάθε εκτέλεση) γράφει στη σελίδα τα δελτία της ημέρας (και όσων ακόμα παίζονται) από τη βάση, μαζί με το
    αποτέλεσμα που ήδη ξέρει (✅/❌ από την τελευταία εκτέλεση).
  - Ο BROWSER σου ρωτά το ESPN (δημόσιο API, επιτρέπει σελίδες) ΜΟΝΟ για αγώνες που παίζονται τώρα, κάθε 2 λεπτά
    και ενημερώνει τα ✅/❌/🟢 χωρίς να περιμένει το GitHub (που καθυστερεί τα προγραμματισμένα τρεξίματα).
  - Σε κάθε δελτίο: πόσες επιλογές κέρδισαν, πόσες έχασαν, πόσες παίζονται, πόσες δεν ξεκίνησαν. Στην κορυφή: σύνολο για όλα.

Σημάδια: ✅ βγήκε (ή είναι ήδη σίγουρη) · ❌ έχασε (ή έχει ήδη χαθεί) · 🟢 πάει καλά τώρα · 🔴 πάει άσχημα τώρα ·
⏳ δεν ξεκίνησε · ➖ δεν παρακολουθείται live (παίκτες, πλάγια, Euroleague).

Περιορισμοί: οι αποδόσεις δεν ανανεώνονται live· η Euroleague δεν υπάρχει στο ESPN (δείχνει ό,τι ξέρει το bot).
"""
from __future__ import annotations

import html
import json
import os
from datetime import timedelta
from zoneinfo import ZoneInfo

from .collectors.espn_stats import TEAM_ALT, _pick
from .stats import LISTS, NAMES, real_slips
from .theme import calm
from .util import http_get, iso, parse_iso

E = html.escape
URL = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/summary"
SPORT = {"football": "soccer", "basketball": "basketball"}
MAX_FETCH = 40


def fetch_state(sport: str, league_espn: str, event_id: str) -> dict:
    """Σκορ, λεπτό και (ποδόσφαιρο) κόρνερ/κίτρινες από το ESPN summary (ρωτάει ο server του bot)."""
    data, _ = http_get(URL.format(sport=SPORT[sport], league=league_espn), params={"event": event_id}, timeout=15, retries=2)
    comp = data["header"]["competitions"][0]
    st = (comp.get("status") or {}).get("type") or {}
    by = {c["homeAway"]: c for c in comp["competitors"]}

    def sc(side):
        try:
            return int(float(by[side].get("score")))
        except (TypeError, ValueError, KeyError):
            return 0

    stats = {}
    for t in (data.get("boxscore") or {}).get("teams", []):
        side = t.get("homeAway")
        if side in ("home", "away"):
            s = {x.get("name"): x.get("displayValue", x.get("value")) for x in t.get("statistics", [])}
            stats[side] = {"corners": _pick(s, TEAM_ALT["corners"]), "yellow": _pick(s, TEAM_ALT["yellow"])}
    return {"state": st.get("state", "pre"), "clock": st.get("detail") or st.get("shortDetail") or "",
            "hs": sc("home"), "as": sc("away"), "stats": stats}


def add_live_states(data: list[dict], now, fetch=fetch_state) -> int:
    """Βάζει στα σκέλη την τρέχουσα κατάσταση (`st`) για αγώνες που παίζονται ή μόλις τελείωσαν. Επιστρέφει πόσες κλήσεις έγιναν."""
    cache, calls = {}, 0
    for s in data:
        for l in s["legs"]:
            if not (l["eid"] and l["lg"] and SPORT.get(l["sport"]) and l.get("ko")):
                continue
            ko = parse_iso(l["ko"])
            if not (ko <= now <= ko + timedelta(hours=4)):
                continue
            k = (l["sport"], l["lg"], l["eid"])
            if k not in cache:
                if calls >= MAX_FETCH:
                    continue
                calls += 1
                try:
                    cache[k] = fetch(l["sport"], l["lg"], l["eid"])
                except Exception:
                    cache[k] = None
            if cache[k]:
                l["st"] = cache[k]
    return calls


def build_data(db, cfg: dict, now) -> list[dict]:
    """Τα δελτία που φαίνονται στη live σελίδα: σημερινά + όσα έχουν ακόμα σκέλη σε εξέλιξη."""
    tz = ZoneInfo(cfg["timezone"])
    today = now.astimezone(tz).date()
    lg_espn = {lg["id"]: lg.get("espn") for lg in cfg["leagues"]}
    out = []
    for sl in real_slips(db.slips()):
        day = parse_iso(sl["created_at"]).astimezone(tz).date()
        any_open = any(l.get("result") in (None, "open") for l in sl["legs"])
        if not (day == today or sl["status"] == "open" or (any_open and day >= today - timedelta(days=1))):
            continue
        legs = []
        for l in sl["legs"]:
            m = db.get_match(l["match_id"])
            mid = l["match_id"]
            score = [m["home_score"], m["away_score"]] if m and m["home_score"] is not None else None
            legs.append({"eid": mid[5:] if mid.startswith("espn:") else None, "lg": lg_espn.get(l.get("league")),
                         "sport": l.get("sport"), "market": l["market"], "sel": l["selection"], "line": l.get("line"),
                         "home": l["home"], "away": l["away"], "label": l.get("label") or "", "odds": l.get("odds"),
                         "ko": l.get("kickoff"), "res": l.get("result"), "sc": score,
                         "dbst": m["status"] if m else None})
        out.append({"id": sl["slip_id"], "list": sl["list_name"], "name": NAMES.get(sl["list_name"], sl["list_name"]),
                    "odds": sl["total_odds"], "p": sl["model_prob"], "fair": sl["list_name"].startswith("fair_"),
                    "day": day.isoformat(), "status": sl["status"], "legs": legs})
    order = {k: i for i, k in enumerate(LISTS)}
    out.sort(key=lambda s: (s["day"] != today.isoformat(), s["day"], order.get(s["list"], 99)))
    return out


CSS = """
:root{--bg:#f9f9f7;--card:#fcfcfb;--ink:#0b0b0b;--muted:#6b6a66;--line:#e1e0d9;--ok:#0a7a0a;--bad:#c62f2f;--live:#1a6fd4}
@media(prefers-color-scheme:dark){:root{--bg:#0d0d0d;--card:#1a1a19;--ink:#f0efec;--muted:#a8a79f;--line:#2c2c2a;--ok:#35c035;--bad:#ef6a6a;--live:#5aa0f0}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:860px;margin:0 auto;padding:14px}h1{font-size:22px;margin:0 0 2px}.sub{color:var(--muted);margin:0 0 10px}
h2{font-size:16px;margin:20px 0 6px;color:var(--muted);font-weight:600}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin:8px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 10px}.tile .k{font-size:12px;color:var(--muted)}.tile .v{font-size:20px;font-weight:700}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 12px;margin:10px 0}
.card h3{margin:0;font-size:16px;display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap}.tot{color:var(--muted);font-weight:400;font-size:13px}
.cnt{font-size:14px;margin:4px 0 2px}.cnt b{font-variant-numeric:tabular-nums}
.leg{display:grid;grid-template-columns:30px 1fr auto;gap:8px;padding:8px 0;border-top:1px solid var(--line);align-items:start}
.leg:first-of-type{border-top:0}.ic{font-size:21px;line-height:1.1}.m{font-size:13px;color:var(--muted)}.p{text-align:right;font-variant-numeric:tabular-nums;font-size:14px}
.sc{font-variant-numeric:tabular-nums;font-weight:600}.won,.sure,.ok{color:var(--ok)}.lost,.dead,.bad{color:var(--bad)}.live{color:var(--live)}.n{color:var(--muted)}
.badge{font-size:13px;padding:2px 8px;border-radius:999px;border:1px solid var(--line)}
.b-won{color:var(--ok);border-color:var(--ok)}.b-lost{color:var(--bad);border-color:var(--bad)}.b-live{color:var(--live);border-color:var(--live)}
#status{font-size:13px;color:var(--muted)}a{color:inherit}
"""

CORE_JS = r"""
// Κοινός κώδικας live (live σελίδα + κύρια σελίδα): κρίση επιλογής, ρώτημα ESPN ΜΟΝΟ όσο παίζεται αγώνας, χρονοδιάγραμμα.
window.BetbotLive = (function(){
const ESPN = 'https://site.api.espn.com/apis/site/v2/sports/';
const SPORT = {football: 'soccer', basketball: 'basketball'};
const cache = {};                       // κλειδί αγώνα -> κατάσταση από ESPN
let legs = [], onUpdate = function(){}, timer = null, lastOk = null, lastErr = null, browserOk = false;
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const key = l => l.sport + '|' + l.lg + '|' + l.eid;
const trackable = l => !!(l.eid && l.lg && SPORT[l.sport]);
const hhmm = iso => { try { return new Date(iso).toLocaleTimeString('el-GR', {timeZone:'Europe/Athens', hour:'2-digit', minute:'2-digit', hour12:false}); } catch(e) { return ''; } };
const pick = (o, names) => { for (const n of names) { if (o[n] != null && o[n] !== '') { const v = parseFloat(String(o[n]).replace('%','')); if (!isNaN(v)) return v; } } return null; };

function parseSummary(d) {
  const comp = d.header.competitions[0], t = (comp.status || {}).type || {}, by = {};
  comp.competitors.forEach(c => by[c.homeAway] = c);
  const num = x => { const v = parseInt(x, 10); return isNaN(v) ? 0 : v; };
  const st = {state: t.state || 'pre', clock: t.detail || t.shortDetail || '', hs: num(by.home && by.home.score),
              as: num(by.away && by.away.score), stats: {}, ts: Date.now()};
  ((d.boxscore && d.boxscore.teams) || []).forEach(tm => {
    const s = {}; (tm.statistics || []).forEach(x => s[x.name] = (x.displayValue !== undefined ? x.displayValue : x.value));
    st.stats[tm.homeAway] = {corners: pick(s, ['wonCorners','cornerKicks','corners']), yellow: pick(s, ['yellowCards']), red: pick(s, ['redCards'])};
  });
  return st;
}

// Κρίση επιλογής: [κωδικός, κείμενο προόδου]. Ίδια λογική με το selector.settle_leg + live (sure/dead/ok/bad).
// Χωρίς ζωντανά δεδομένα: εκτίμηση από την ώρα. ⏳ ΜΟΝΟ πριν την έναρξη· μετά ⚽ (παίζεται) ή 🏁 (τελείωσε, περιμένω αποτέλεσμα).
const END_MIN = {football: 150, basketball: 180};
function byTime(l) {
  const ko = l.ko ? Date.parse(l.ko) : NaN;
  if (isNaN(ko) || Date.now() < ko) return ['pending', ''];
  const end = ko + (END_MIN[l.sport] || 150) * 60000;
  return Date.now() < end ? ['play', 'παίζεται'] : ['wait', 'τελείωσε · περιμένω αποτέλεσμα'];
}
function judge(l, st) {
  const m = l.market, s = l.sel, L = l.line;
  if (m === 'THROWINS' || m === 'PLAYER') return (l.res === 'won' || l.res === 'lost' || l.res === 'void') ? [l.res, ''] : (byTime(l)[0] === 'pending' ? ['pending', ''] : ['na', 'δεν παρακολουθείται live']);
  if (!st) {
    if (l.res === 'won' || l.res === 'lost' || l.res === 'void') return [l.res, l.sc ? l.sc[0] + '-' + l.sc[1] : ''];
    return byTime(l);
  }
  if (st.state === 'pre') return byTime(l);
  const h = st.hs, a = st.as, fin = st.state === 'post', sc = h + '-' + a;
  const res = h > a ? '1' : (h === a ? 'X' : '2');
  const tot = col => { const x = st.stats.home && st.stats.home[col], y = st.stats.away && st.stats.away[col]; return (x == null || y == null) ? null : x + y; };
  const ou = (cur, what) => {
    if (cur == null) return ['na', what + ': χωρίς στοιχεία'];
    if (fin) { if (cur === L) return ['void', what + ' ' + cur]; return [((cur > L) === (s === 'OVER')) ? 'won' : 'lost', what + ' ' + cur]; }
    if (s === 'OVER') return [cur > L ? 'sure' : 'ok', what + ' ' + cur + ' / ' + L];
    return [cur > L ? 'dead' : 'ok', what + ' ' + cur + ' / κάτω από ' + L];
  };
  const now = (good) => fin ? [good ? 'won' : 'lost', sc] : [good ? 'ok' : 'bad', sc];
  if (m === 'OU') return ou(h + a, 'γκολ');
  if (m === 'TOTAL') return ou(h + a, 'πόντοι');
  if (m === 'CORNERS') return ou(tot('corners'), 'κόρνερ');
  if (m === 'CARDS') return ou(tot('yellow'), 'κίτρινες');
  if (m === 'CORNERS_MORE') {
    const x = st.stats.home && st.stats.home.corners, y = st.stats.away && st.stats.away.corners;
    if (x == null || y == null) return ['na', 'κόρνερ: χωρίς στοιχεία'];
    const good = x !== y && ((x > y) === (s === 'HOME'));
    return [fin ? (good ? 'won' : 'lost') : (good ? 'ok' : 'bad'), 'κόρνερ ' + x + '-' + y];
  }
  if (m === 'BTTS') {
    const both = h > 0 && a > 0;
    if (fin) return [(both === (s === 'YES')) ? 'won' : 'lost', sc];
    if (s === 'YES') return [both ? 'sure' : 'ok', sc];
    return [both ? 'dead' : 'ok', sc];
  }
  if (m === '1X2') return now(res === s);
  if (m === 'DC') return now(s.indexOf(res) >= 0);
  if (m === 'ML') return fin ? [((h > a) === (s === 'HOME')) ? 'won' : 'lost', sc] : now(h !== a && ((h > a) === (s === 'HOME')));
  if (m === 'SPREAD') { const v = (h - a) + L; if (fin && v === 0) return ['void', sc]; return now(v !== 0 && ((v > 0) === (s === 'HOME'))); }
  return ['na', sc];
}
const grp = c => (c === 'won' || c === 'sure') ? 'w' : (c === 'lost' || c === 'dead') ? 'l' : (c === 'ok' || c === 'bad' || c === 'play') ? 'p' : (c === 'wait') ? 'q' : 'n';
const IC = {won:'✅', lost:'❌', void:'↩️', sure:'✅', dead:'❌', ok:'🟢', bad:'🔴', play:'⚽', wait:'🏁', pending:'⏳', na:'➖'};

// Ποιοι αγώνες χρειάζονται ερώτηση: ΜΟΝΟ όσοι έχουν ήδη ξεκινήσει και δεν έχουν τελειώσει (όχι πριν την έναρξη, όχι μετά το τέλος).
function neededEvents() {
  const now = Date.now(), need = {};
  legs.forEach(l => {
    if (!trackable(l) || !l.ko) return;
    const k = key(l), st = cache[k], ko = Date.parse(l.ko);
    if (st && st.state === 'post') return;
    if (now < ko) return;
    if (now > ko + 4 * 3600 * 1000 && st) return;
    if (!st && (l.res === 'won' || l.res === 'lost' || l.res === 'void')) return;                // ήδη κριμένο στη βάση: δεν ρωτάμε
    need[k] = l;
  });
  return need;
}
function nextKickoff() {
  const now = Date.now(); let best = null;
  legs.forEach(l => { if (trackable(l) && l.ko) { const ko = Date.parse(l.ko), st = cache[key(l)]; if (ko > now && !(st && st.state === 'post') && (best === null || ko < best)) best = ko; } });
  return best;
}
async function tick() {
  if (document.visibilityState === 'hidden') return schedule();
  const need = neededEvents(), keys = Object.keys(need);
  if (keys.length) {
    const results = await Promise.allSettled(keys.map(k => {
      const l = need[k];
      // ΧΩΡΙΣ επιπλέον επικεφαλίδες/επιλογές (π.χ. cache:'no-store'): αλλιώς ο browser στέλνει preflight και το ESPN το απορρίπτει
      return fetch(ESPN + SPORT[l.sport] + '/' + l.lg + '/summary?event=' + l.eid)
        .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); }).then(d => { cache[k] = parseSummary(d); });
    }));
    const bad = results.filter(r => r.status === 'rejected').length;
    if (bad < keys.length) { browserOk = true; lastOk = new Date(); lastErr = bad ? bad + ' αγώνες δεν απάντησαν' : null; } else { lastErr = 'το ESPN δεν απαντά'; }
  } else { lastOk = new Date(); lastErr = null; browserOk = true; }
  onUpdate();
  schedule();
}
function schedule() {
  clearTimeout(timer);
  let delay;
  if (Object.keys(neededEvents()).length) delay = 120000;            // παίζεται αγώνας: κάθε 2 λεπτά
  else { const nk = nextKickoff(); delay = nk ? Math.min(Math.max(nk - Date.now() + 5000, 5000), 600000) : 600000; }   // αλλιώς ξύπνημα στην επόμενη έναρξη
  timer = setTimeout(tick, delay);
}
// Έλεγχος σύνδεσης: ρωτά ΜΙΑ φορά ένα ελαφρύ endpoint του ESPN, ώστε να ξέρουμε αν η συσκευή φτάνει εκεί (ποτέ cache:'no-store')
function probe() {
  return fetch(ESPN + 'basketball/nba/scoreboard').then(r => r.ok ? 'ok' : 'http ' + r.status).catch(e => 'δίκτυο/CORS');
}
function status() { return {lastOk, lastErr, browserOk, playing: Object.keys(neededEvents()).length, nk: nextKickoff()}; }
function start(ls, cb) {
  legs = ls; onUpdate = cb;
  // Σπόρος: η κατάσταση που έγραψε ο server του bot στην τελευταία εκτέλεση (αν ο browser δεν φτάσει στο ESPN, δείχνουμε αυτή)
  legs.forEach(l => { if (l.st && trackable(l)) cache[key(l)] = Object.assign({srv: true}, l.st); });
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') tick(); });
  onUpdate(); tick();
}
function slipVerdict(codes) {
  if (codes.some(c => c === 'lost' || c === 'dead')) return ['lost', '❌ ΔΕΝ ΠΕΡΑΣΕ'];
  if (codes.every(c => c === 'won' || c === 'void')) return ['won', '✅ ΠΕΡΑΣΕ'];
  if (codes.every(c => c === 'won' || c === 'void' || c === 'sure')) return ['won', '✅ Σχεδόν σίγουρο'];
  if (codes.some(c => c === 'ok' || c === 'bad' || c === 'play')) return ['live', '⚽ Παίζεται'];
  if (codes.some(c => c === 'wait')) return ['wait', '🏁 Περιμένω αποτελέσματα'];
  if (codes.some(c => c === 'won' || c === 'sure')) return ['live', '🟢 Σε εξέλιξη'];
  return ['pending', '⏳ Δεν ξεκίνησε'];
}
return {start, probe, judge, parseSummary, cache, key, trackable, hhmm, esc, grp, IC, status, slipVerdict, byTime};
})();
"""

PAGE_JS = r"""
(function(){
const B = window.BetbotLive, esc = B.esc, IC = B.IC, grp = B.grp;
const DATA = JSON.parse(document.getElementById('data').textContent);
const GEN = new Date(document.getElementById('data').dataset.gen);
const genTxt = GEN.toLocaleTimeString('el-GR', {timeZone:'Europe/Athens', hour:'2-digit', minute:'2-digit', hour12:false});

const slipVerdict = B.slipVerdict;
function legRow(l, st, code, txt) {
  const live = st && st.state === 'in', fin = st && st.state === 'post';
  const score = st && st.state !== 'pre' ? '<span class="sc">' + st.hs + '-' + st.as + '</span> ' + (live ? '<span class="live">' + esc(st.clock) + '</span>' : (fin ? 'ΤΕΛΟΣ' : '')) : (l.sc ? '<span class="sc">' + l.sc[0] + '-' + l.sc[1] + '</span> ΤΕΛΟΣ' : '');
  const when = code === 'pending' && l.ko ? B.hhmm(l.ko) + ' · ' : '';
  const price = l.odds ? (l.fair ? '≥ ' : '@ ') + Number(l.odds).toFixed(2) : '';
  return '<div class="leg"><div class="ic">' + IC[code] + '</div><div><b>' + esc(l.home) + ' – ' + esc(l.away) + '</b> ' + score +
         '<div class="m">' + when + esc(l.label) + ' ' + price + '</div></div><div class="p ' + code + '">' + esc(txt) + '</div></div>';
}
function render() {
  const app = document.getElementById('app');
  const seen = {}, tot = {w: 0, l: 0, p: 0, q: 0, n: 0}, sl = {won: 0, lost: 0, live: 0, wait: 0, pending: 0}, byDay = {};
  const TODAY = DATA.reduce((m, s) => s.day > m ? s.day : m, '');      // οι μετρητές πάνω-πάνω αφορούν ΜΟΝΟ τη σημερινή ημέρα
  DATA.forEach(s => {
    const codes = [], rows = [];
    s.legs.forEach(l => {
      l.fair = s.fair;
      const st = B.trackable(l) ? B.cache[B.key(l)] : null;
      const [code, txt] = B.judge(l, st);
      codes.push(code); rows.push(legRow(l, st, code, txt));
      const k = [l.eid || l.home, l.market, l.sel, l.line].join('|');
      if (s.day === TODAY && !seen[k]) { seen[k] = 1; tot[grp(code)]++; }
    });
    const [v, vt] = slipVerdict(codes);
    if (s.day === TODAY) sl[v]++;
    const c = {w: 0, l: 0, p: 0, q: 0, n: 0}; codes.forEach(x => c[grp(x)]++);
    const card = '<div class="card"><h3><span>' + esc(s.name) + ' <span class="tot">· ' + (s.fair ? 'ελάχιστη απόδοση ' : 'απόδοση ') + Number(s.odds).toFixed(2) + ' · εκτίμηση ' + Math.round((s.p || 0) * 100) + '%</span></span><span class="badge b-' + v + '">' + vt + '</span></h3>' +
      '<div class="cnt">✅ <b>' + c.w + '</b> · ❌ <b>' + c.l + '</b> · ⚽ <b>' + c.p + '</b> παίζονται · 🏁 <b>' + c.q + '</b> περιμένω αποτέλεσμα · ⏳ <b>' + c.n + '</b> δεν ξεκίνησαν</div>' + rows.join('') + '</div>';
    (byDay[s.day] = byDay[s.day] || []).push(card);
  });
  const days = Object.keys(byDay).sort().reverse(), today = days.length ? days[0] : '';
  let out = '<div class="tiles">' +
    '<div class="tile"><div class="k">Σήμερα: δελτία που πέρασαν</div><div class="v ok">✅ ' + sl.won + '</div></div>' +
    '<div class="tile"><div class="k">Δελτία που ΔΕΝ πέρασαν</div><div class="v lost">❌ ' + sl.lost + '</div></div>' +
    '<div class="tile"><div class="k">Παίζονται</div><div class="v live">⚽ ' + sl.live + '</div></div>' +
    '<div class="tile"><div class="k">Περιμένω αποτέλεσμα</div><div class="v n">🏁 ' + sl.wait + '</div></div>' +
    '<div class="tile"><div class="k">Δεν ξεκίνησαν</div><div class="v n">⏳ ' + sl.pending + '</div></div></div>' +
    '<div class="tiles"><div class="tile"><div class="k">Επιλογές που βγήκαν</div><div class="v ok">✅ ' + tot.w + '</div></div>' +
    '<div class="tile"><div class="k">Επιλογές που έχασαν</div><div class="v lost">❌ ' + tot.l + '</div></div>' +
    '<div class="tile"><div class="k">Παίζονται τώρα</div><div class="v live">⚽ ' + tot.p + '</div></div>' +
    '<div class="tile"><div class="k">Περιμένω αποτέλεσμα</div><div class="v n">🏁 ' + tot.q + '</div></div>' +
    '<div class="tile"><div class="k">Δεν ξεκίνησαν</div><div class="v n">⏳ ' + tot.n + '</div></div></div>';
  if (!DATA.length) out += '<div class="card n">Δεν υπάρχουν δελτία ακόμα. Δημιουργούνται στην πρωινή εκτέλεση.</div>';
  days.forEach(d => { out += '<h2>' + (d === today ? 'Σήμερα' : 'Προηγούμενη μέρα (ακόμα σε εξέλιξη)') + ' · ' + d.slice(8, 10) + '/' + d.slice(5, 7) + '</h2>' + byDay[d].join(''); });
  app.innerHTML = out;
  const S = B.status(), stEl = document.getElementById('status');
  const info = S.playing ? (S.playing + ' αγώνες παίζονται· ενημερώνεται κάθε 2 λεπτά') : (S.nk ? ('Δεν παίζεται κάτι τώρα· επόμενη έναρξη ' + B.hhmm(new Date(S.nk).toISOString())) : 'Δεν παίζεται κάτι τώρα');
  stEl.textContent = S.browserOk ? ('🔴 ' + info + (S.lastOk ? ' · τελευταία ενημέρωση ' + S.lastOk.toLocaleTimeString('el-GR') : '') + (S.lastErr ? ' · ⚠️ ' + S.lastErr : '')) :
    (S.lastErr ? ('⚠️ Ο browser δεν μπόρεσε να ρωτήσει το ESPN (' + S.lastErr + ') — δείχνω ό,τι ήξερε το bot στην εκτέλεση των ' + genTxt + '. Ανανέωσε σε λίγο.') : 'Φόρτωση…');
}
// Νέα δελτία/δεδομένα από την τελευταία εκτέλεση του bot: κάθε 5' ελέγχουμε αν υπάρχει νεότερη έκδοση της σελίδας και ΜΟΝΟ τότε ανανεώνουμε
async function checkNew() {
  try {
    const t = await (await fetch(location.pathname + '?t=' + Date.now())).text();
    const m = t.match(/data-gen="([^"]+)"/);
    if (m && m[1] !== document.getElementById('data').dataset.gen) location.reload();
  } catch (e) { /* τοπικό αρχείο ή χωρίς δίκτυο: αγνοείται */ }
}
setInterval(checkNew, 5 * 60 * 1000);
const all = []; DATA.forEach(s => s.legs.forEach(l => all.push(l)));
B.start(all, render);
B.probe().then(function(r){ var c = document.getElementById('espnchk'); if (c) c.innerHTML = r === 'ok' ? '📡 Σύνδεση με ESPN από τη συσκευή σου: ✅ λειτουργεί' :
  '📡 Σύνδεση με ESPN από τη συσκευή σου: ⚠️ δεν απαντά (' + r + ')'; });
window.__betbot = {judge: B.judge, parseSummary: B.parseSummary, cache: B.cache, DATA};
})();
"""


def render(cfg, now, data: list[dict]) -> str:
    loc = now.astimezone(ZoneInfo(cfg["timezone"]))
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return calm(f"""<!doctype html><html lang="el"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BetBot Live</title><style>{CSS}</style></head><body><main>
<h1>BetBot Live</h1>
<p class="sub">✅ βγήκε · ❌ έχασε · 🟢 πάει καλά · 🔴 πάει άσχημα · ⏳ δεν ξεκίνησε · ➖ χωρίς live ·
<a href="index.html">← Κύρια σελίδα</a></p>
<p id="status">Φόρτωση…</p><p id="espnchk" class="muted"></p>
<div id="app"><noscript>Η live σελίδα χρειάζεται JavaScript.</noscript></div>
<p class="sub">Δεδομένα δελτίων από την εκτέλεση των {loc:%H:%M} ({loc:%d/%m}). Πηγή αποτελεσμάτων: ESPN (ρωτάει μόνο όσο παίζεται αγώνας, κάθε 2 λεπτά).
Οι αποδόσεις δεν ανανεώνονται live. Παίκτες, πλάγια και Euroleague δεν παρακολουθούνται live.</p>
</main>
<script id="data" type="application/json" data-gen="{iso(now)}">{payload}</script>
<script>{CORE_JS}</script>
<script>{PAGE_JS}</script></body></html>""")


def run(cfg: dict, now, out_path: str | None = None) -> str:
    from .db import DB
    db = DB(cfg["database"])
    data = build_data(db, cfg, now)
    try:
        add_live_states(data, now)
    except Exception:       # η σελίδα βγαίνει και χωρίς τρέχουσες καταστάσεις
        pass
    path = out_path or os.path.join(cfg["reports_dir"], "live.html")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    text = render(cfg, now, data)
    # Να μην ξαναγράφεται (και άρα να μην γίνεται commit κάθε 10 λεπτά) όταν άλλαξε ΜΟΝΟ η ώρα εκτέλεσης στο κείμενο της σελίδας.
    try:
        with open(path, encoding="utf-8") as f:
            old = f.read()
        if _stable(old) == _stable(text):
            return path
    except OSError:
        pass
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _stable(html_text: str) -> str:
    """Η σελίδα χωρίς την ώρα εκτέλεσης («Δεδομένα δελτίων από την εκτέλεση των ΩΩ:ΛΛ (ηη/μμ)») και χωρίς τον χρόνο παραγωγής."""
    import re
    t = re.sub(r"εκτέλεση των \d\d:\d\d \(\d\d/\d\d\)", "εκτέλεση των --", html_text)
    return re.sub(r'data-gen="[^"]*"', 'data-gen=""', t)
