"""Εμφάνιση της σελίδας (CSS) + «ηρεμία» των emoji.

Στυλ: πίνακας συναλλαγών (trading desk) — επίπεδο, καθαρές γραμμές, μονοσπαστοί αριθμοί, ένα βασικό χρώμα.
Τα ονόματα κλάσεων/μεταβλητών είναι τα ίδια με πριν, ώστε το περιεχόμενο του report.py να μην αλλάξει.
"""
import re

# Σημάδια κατάστασης: κρατάμε ΜΟΝΟ τα ✅ ❌ (σαφή και ζητήθηκαν). Τα υπόλοιπα γίνονται απλά γράμματα/σχήματα.
_STATUS = {"⚽": "●", "🏁": "◆", "⏳": "○", "🟢": "▲", "🔴": "▼", "↩️": "↺", "↩": "↺", "➖": "–", "⚠️": "!", "⚠": "!"}
# Διακοσμητικά emoji που αφαιρούνται (μαζί με το κενό που ακολουθεί)
_DECOR = "⭐🛡🎯🔥🎰🔀🚩🟨👤↔📊📅📆🗓💡🏆📈🔒📡ℹ🔎💶📉⚙🛑🟡🟠🌱🔬✔"
_DECOR_RE = re.compile("[" + _DECOR + "]️?‍?\\s?")


def calm(text: str) -> str:
    """Λιγότερα emoji: ✅/❌ μένουν, τα σημάδια κατάστασης γίνονται σχήματα, τα διακοσμητικά φεύγουν. Εφαρμόζεται σε όλη τη σελίδα
    (HTML και JS μαζί), ώστε οι πίνακες αντιστοίχισης του JS να μένουν συνεπείς."""
    for k, v in _STATUS.items():
        text = text.replace(k, v)
    text = _DECOR_RE.sub("", text)
    return text.replace("️", "")


CSS = """
:root{--plane:#f4f5f7;--surface:#ffffff;--ink:#101418;--ink2:#4a5361;--muted:#8a93a1;--grid:#e6e8ec;--border:#dfe3e8;
--accent:#0b7a5a;--accent-ink:#ffffff;--accent-soft:#e1f2ec;--s1:#2a78d6;--s2:#d9541f;--s3:#12a67a;--s4:#c98500;--s5:#d9548a;--s6:#0b8f4d;--s7:#6250d6;--s8:#e04848;
--good:#0b7a5a;--goodtxt:#0b7a5a;--bad:#c7372f;--warn:#d89a14;--chip:#eef0f3;--hero1:#101418;--hero2:#101418;--r:10px;
--mono:ui-monospace,"SF Mono","Cascadia Mono",Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--plane:#0c0f13;--surface:#141920;--ink:#e7eaef;--ink2:#a9b1be;--muted:#737c8a;
--grid:#222932;--border:#262d37;--accent:#2fb585;--accent-ink:#04281c;--accent-soft:#12342a;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;
--s6:#199e70;--s7:#9085e9;--s8:#e66767;--good:#2fb585;--goodtxt:#2fb585;--bad:#ef5b52;--chip:#1b212a;--hero1:#141920;--hero2:#141920}}
:root[data-theme=dark]{--plane:#0c0f13;--surface:#141920;--ink:#e7eaef;--ink2:#a9b1be;--muted:#737c8a;--grid:#222932;--border:#262d37;
--accent:#2fb585;--accent-ink:#04281c;--accent-soft:#12342a;--goodtxt:#2fb585;--good:#2fb585;--bad:#ef5b52;--chip:#1b212a;--hero1:#141920;--hero2:#141920}
[hidden]{display:none!important}*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--plane);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,system-ui,sans-serif;
-webkit-font-smoothing:antialiased;font-variant-numeric:tabular-nums}
main{max-width:860px;margin:0 auto;padding:0 14px 92px}
a{color:var(--s1)}
h1{font-size:21px;margin:0}h2{font-size:18px;margin:20px 0 8px}h3{font-size:15px;margin:0 0 10px;font-weight:700}
h4{margin:16px 0 8px;font-size:12px;color:var(--muted);font-weight:700;text-transform:uppercase;letter-spacing:.07em}
.sub{color:var(--ink2);margin:0 0 12px}
/* --- πάνω μπάρα --- */
.appbar{position:sticky;top:0;z-index:20;margin:0 -14px;padding:10px 14px;background:var(--plane);border-bottom:1px solid var(--border);display:flex;align-items:center;gap:10px}
.logo{width:28px;height:28px;border-radius:7px;background:var(--ink);color:var(--plane);display:grid;place-items:center;font-weight:800;font-size:15px;flex:0 0 auto}
.appbar .t{flex:1;min-width:0}.appbar .t b{display:block;font-size:15px;line-height:1.2}.appbar .t span{font-size:12px;color:var(--muted)}
.pill{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:700;padding:5px 10px;border-radius:7px;border:1px solid var(--border);background:var(--surface);color:var(--ink);text-decoration:none;white-space:nowrap}
.pill.live i{width:7px;height:7px;border-radius:50%;background:var(--bad);display:inline-block;animation:pulse 1.6s infinite}
@keyframes pulse{50%{opacity:.3}}
/* --- ένδειξη ημέρας (hero) --- */
.hero{background:var(--surface);color:var(--ink);border:1px solid var(--border);border-left:4px solid var(--accent);border-radius:var(--r);padding:16px 16px 14px;margin:14px 0 10px}
.hero:after{display:none}
.hero .eyebrow{font-size:11.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:700}
.hero .big{font-size:25px;line-height:1.2;font-weight:800;margin:6px 0 2px;letter-spacing:-.015em}
.hero .why{font-size:14px;color:var(--ink2)}
.hero .kpis{display:grid;grid-template-columns:repeat(3,1fr);margin-top:14px;border-top:1px solid var(--grid)}
.hero .kpi{padding:10px 12px 0 0;background:none;border-radius:0}.hero .kpi+.kpi{padding-left:12px;border-left:1px solid var(--grid)}
.hero .kpi .k{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;opacity:1}.hero .kpi .v{font-family:var(--mono);font-size:19px;font-weight:700}
.meter{height:4px;border-radius:2px;background:var(--grid);margin-top:12px;overflow:hidden}.meter i{display:block;height:100%;background:var(--accent)}
/* --- κάρτες --- */
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:14px;margin:10px 0}
details.card>summary{font-weight:650;color:var(--ink)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(112px,1fr));gap:0;margin:8px 0;border:1px solid var(--grid);border-radius:8px;overflow:hidden}
.tile{background:transparent;border:0;border-right:1px solid var(--grid);border-bottom:1px solid var(--grid);padding:8px 10px;margin:-1px -1px 0 0;border-radius:0}
.tile .k{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.05em}.tile .v{font-family:var(--mono);font-size:17px;font-weight:700}
.warn{border-left:3px solid var(--warn);background:var(--surface);padding:9px 12px;border-radius:8px;color:var(--ink2);font-size:13.5px;margin:10px 0}
.disclaimer{font-size:12px;color:var(--muted);margin:14px 2px}
/* --- πλοήγηση --- */
.chipnav{display:flex;gap:6px;overflow-x:auto;padding:12px 14px 6px;scrollbar-width:none;margin:0 -14px}
.chipnav::-webkit-scrollbar{display:none}
.chipnav button{flex:0 0 auto;border:1px solid var(--border);background:var(--surface);color:var(--ink2);border-radius:8px;padding:7px 12px;font:inherit;font-size:13.5px;font-weight:650;cursor:pointer;white-space:nowrap;box-shadow:none}
.chipnav button[aria-selected=true]{background:var(--ink);color:var(--plane);border-color:var(--ink)}
.bar{position:fixed;left:0;right:0;bottom:0;z-index:30;display:grid;grid-template-columns:repeat(5,1fr);background:var(--surface);border-top:1px solid var(--border);padding:5px 6px calc(5px + env(safe-area-inset-bottom))}
.bar button{border:0;background:none;color:var(--muted);font:inherit;font-size:11px;font-weight:650;display:flex;flex-direction:column;align-items:center;gap:3px;padding:5px 2px;border-radius:8px;cursor:pointer}
.bar button svg{width:21px;height:21px;stroke:currentColor;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.bar button[aria-selected=true]{color:var(--ink);background:var(--chip)}
.tab{display:none}.tab.on{display:block}
@media (min-width:900px){.bar{left:50%;right:auto;transform:translateX(-50%);width:520px;bottom:12px;border:1px solid var(--border);border-radius:12px}}
/* επιλογέας ρίσκου: ενιαίο segmented control */
.tiersel{display:grid;grid-template-columns:repeat(3,1fr);margin:12px 0 6px;border:1px solid var(--border);border-radius:var(--r);overflow:hidden;background:var(--surface)}
.tiersel button{display:flex;flex-direction:column;align-items:flex-start;gap:2px;padding:9px 11px;border:0;border-right:1px solid var(--border);border-radius:0;background:transparent;color:var(--ink);font:inherit;cursor:pointer;text-align:left;box-shadow:none}
.tiersel button:last-child{border-right:0}
.tiersel button b{font-size:13.5px;display:flex;align-items:center;gap:6px}.tiersel button span{font-size:11px;color:var(--muted);line-height:1.25}
.tiersel button[aria-pressed=true]{background:var(--ink);color:var(--plane);box-shadow:none}.tiersel button[aria-pressed=true] span{color:inherit;opacity:.75}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin:0}.d-strong{background:var(--s3)}.d-balanced{background:var(--s4)}.d-bold{background:var(--s2)}
/* --- πίνακες --- */
.tbl{width:100%;overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:8px 8px;border-bottom:1px solid var(--grid);text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:700;font-size:11px;white-space:nowrap;text-transform:uppercase;letter-spacing:.06em}
td.n{font-family:var(--mono);text-align:right;white-space:nowrap}
tr:last-child td{border-bottom:0}
.fb{display:inline-block;width:18px;height:18px;line-height:18px;text-align:center;border-radius:4px;font-size:11px;font-weight:700;margin-right:2px;color:#fff}
.fb.w{background:var(--good)}.fb.d{background:var(--muted)}.fb.l{background:var(--bad)}
.pos{color:var(--goodtxt)}.neg{color:var(--bad)}.muted{color:var(--muted);font-size:13px}
.wr{font-size:12px;color:var(--ink2);margin-top:3px}
.mv{font-size:11.5px;font-weight:700;padding:1px 6px;border-radius:4px;background:var(--chip);white-space:nowrap;font-family:var(--mono)}
.mv.dn{color:var(--s1)}.mv.up{color:var(--s2)}
ul.why{margin:6px 0 4px 18px;padding:0;font-size:13px;color:var(--ink2)}
details{margin-top:4px}summary{cursor:pointer;color:var(--ink2);font-size:13px}
.chart{position:relative;height:250px;margin-top:8px}.chart.sm{height:170px}
.rules li{margin:4px 0;font-size:14px;color:var(--ink2)}
td.t{white-space:nowrap;color:var(--ink2)}
/* --- ΕΠΙΛΟΓΗ: ευθυγραμμισμένη, με το «γιατί» ορατό --- */
.whyline{font-size:12.5px;color:var(--ink2);margin-top:3px;line-height:1.35}
table.picks td.o b,table.picks td.q b{font-family:var(--mono)}
@media (max-width:640px){
 table.picks thead{display:none}table.picks,table.picks tbody{display:block}
 table.picks tr{display:grid;grid-template-columns:auto auto 1fr auto;grid-template-areas:"t t t o" "m m m m" "p p p p" "q v . .";gap:2px 14px;padding:12px 0;border-bottom:1px solid var(--grid);align-items:baseline;background:none;border-radius:0;margin:0}
 table.picks td{border:0;padding:0;text-align:left}
 table.picks td.t{grid-area:t}table.picks td.m{grid-area:m;font-size:15.5px;margin-top:2px}table.picks td.p{grid-area:p}
 table.picks td.o{grid-area:o;text-align:right;align-self:start}table.picks td.o b{font-size:19px}
 table.picks td.q{grid-area:q;margin-top:5px}table.picks td.v{grid-area:v;margin-top:5px}
 table.picks td[data-l]::before{content:attr(data-l) " ";color:var(--muted);font-size:10.5px;font-weight:600;text-transform:uppercase;letter-spacing:.05em}
 .chart{height:220px}
}
/* --- σημάδια κατάστασης --- */
.tk{font-size:15px;font-weight:800;display:inline-block;min-width:18px;text-align:center}
.tk[data-c=won],.tk[data-c=sure]{color:var(--goodtxt)}.tk[data-c=lost],.tk[data-c=dead]{color:var(--bad)}
.tk[data-c=play],.tk[data-c=ok]{color:var(--s1)}.tk[data-c=bad]{color:var(--s2)}.tk[data-c=wait],.tk[data-c=pending],.tk[data-c=na],.tk[data-c=void]{color:var(--muted)}
.scr{font-size:12.5px;color:var(--muted)}.cnt{font-size:13px;margin:8px 0;color:var(--ink2)}
.banner{background:#fff4d6;color:#5c4400;border:1px solid #efd37a;border-radius:8px;padding:9px 12px;margin:10px 0;font-size:13.5px}.banner a{color:inherit;font-weight:700}
.vd{font-size:11.5px;padding:2px 8px;border-radius:5px;background:var(--chip);white-space:nowrap;font-weight:700;vertical-align:middle;letter-spacing:.02em}
.b-won{color:var(--goodtxt);background:var(--accent-soft)}.b-lost{color:var(--bad);background:color-mix(in srgb,var(--bad) 13%,transparent)}
.b-live{color:var(--s1);background:color-mix(in srgb,var(--s1) 13%,transparent)}.b-wait,.b-pending{color:var(--muted)}
.daysum{margin:8px 0 2px}.daysum .line{font-size:12.5px;color:var(--ink2)}.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.chip{font-size:12px;padding:3px 9px;border-radius:6px;background:var(--surface);border:1px solid var(--border);font-weight:600}
.livestat{font-size:12.5px;color:var(--muted);margin:6px 2px}
.ok{color:var(--goodtxt)}.ko{color:var(--bad)}
div.tk{display:flex;gap:10px;padding:8px 0;border-top:1px solid var(--grid);align-items:flex-start;font-size:15px;font-weight:400;min-width:0;text-align:left}div.tk:first-of-type{border-top:0}
div.tk .ic{width:22px;font-size:17px;line-height:1.3;font-weight:800;text-align:center}
div.tk .sc{font-family:var(--mono)}
.grid td,.grid th{text-align:center;padding:6px 4px}.grid td.d{text-align:left;white-space:nowrap}
/* --- δελτίο ως απόδειξη --- */
.slip{padding:0;overflow:hidden}
.slip-top{padding:14px 14px 4px;display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
.slip .eyebrow{font-size:11.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:700;margin-bottom:6px}
.slip-odds{text-align:right}.slip-odds small{display:block;font-size:10.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.07em}
.slip-odds b{font-family:var(--mono);font-size:34px;font-weight:800;letter-spacing:-.03em;line-height:1}
.slip-body{padding:0 14px}.slip-body .muted{margin:4px 0}
.slip-stub{border-top:1px dashed var(--border);margin-top:6px;padding:12px 14px;display:grid;grid-template-columns:repeat(3,1fr);gap:8px;background:var(--chip)}
.slip-stub:before,.slip-stub:after{display:none}
.slip-stub small{display:block;font-size:10.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}.slip-stub b{font-family:var(--mono);font-size:17px}
.find{margin-top:6px;display:flex;gap:6px;flex-wrap:wrap}.findbtn{font:inherit;font-size:11.5px;padding:3px 9px;border:1px solid var(--border);border-radius:6px;background:transparent;color:inherit;cursor:pointer}.findbtn:active{opacity:.7}
.slip-copy{padding:8px 14px;background:var(--chip);text-align:right}.copybtn{font:inherit;font-size:13px;padding:6px 12px;border:1px solid var(--border);border-radius:8px;background:var(--card,transparent);color:inherit;cursor:pointer}.copybtn:active{opacity:.7}
.slip-more{padding:0 14px 12px;background:var(--chip)}.slip-more summary{padding:2px 0 6px}
.slip table.picks tr:last-child{border-bottom:0}
/* --- ημερολόγιο --- */
.calh{display:flex;justify-content:space-between;align-items:center;margin:6px 0 10px}.calh b{font-size:15px}
.calh button{font-size:18px;width:38px;height:36px;border:1px solid var(--border);background:var(--surface);color:inherit;border-radius:8px;cursor:pointer}
.calg{display:grid;grid-template-columns:repeat(7,1fr);gap:4px}.cdw{text-align:center;font-size:11px;color:var(--muted);font-weight:700;text-transform:uppercase}
.cd{min-height:52px;border:1px solid transparent;background:transparent;color:var(--muted);border-radius:8px;padding:4px 2px;font-size:11px;display:flex;flex-direction:column;align-items:center;gap:2px;font-family:inherit}
.cd i{font-style:normal;font-size:13px;font-weight:600}.cd.has{background:var(--chip);color:var(--ink);cursor:pointer}.cd:disabled{opacity:.4}.cd span{line-height:1.1;font-weight:700}
.cd.w{background:var(--accent-soft);color:var(--goodtxt)}.cd.l{background:color-mix(in srgb,var(--bad) 13%,transparent);color:var(--bad)}.cd.m{background:color-mix(in srgb,var(--warn) 22%,transparent)}
.cd.sel{border-color:var(--ink)}
/* --- ανάλυση --- */
.insight{display:flex;gap:12px;align-items:flex-start;padding:10px 0;border-top:1px solid var(--grid)}.insight:first-of-type{border-top:0}
.insight .ico{width:24px;height:24px;border-radius:6px;background:var(--chip);color:var(--ink);display:grid;place-items:center;font-weight:800;font-size:13px;flex:0 0 auto;line-height:1}
.insight b{display:block;font-size:14.5px}.insight span{font-size:13.5px;color:var(--ink2)}
.sc-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:10px}
.scorecard{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:12px 14px}
.scorecard h4{margin:0 0 6px;color:var(--ink);font-size:14px;text-transform:none;letter-spacing:0}
.trow{display:grid;grid-template-columns:112px 1fr auto;gap:8px;align-items:center;padding:8px 0;border-top:1px solid var(--grid);font-size:13px}
.trow[data-k]{cursor:pointer}.trow.open{background:var(--chip);border-radius:8px}.lgpanel{padding:8px 4px 12px;border-top:1px dashed var(--border)}.lgchips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}.lgchip{font:inherit;font-size:12px;padding:4px 10px;border:1px solid var(--border);border-radius:999px;background:transparent;color:inherit;cursor:pointer}.lgchip.on{background:var(--accent);color:#fff;border-color:var(--accent)}.lgslip{padding:8px 0;border-top:1px solid var(--grid);font-size:13px}.lgh{margin-bottom:3px}.lgl{padding-left:2px;font-size:12.5px}
.trow:first-of-type{border-top:0}.trow .nm{font-weight:650;white-space:nowrap}.trow .st{color:var(--muted);font-size:12px}
.bar2{height:4px;background:var(--grid);border-radius:2px;overflow:hidden;margin-top:5px}.bar2 i{display:block;height:100%;background:var(--accent)}
.badge{font-size:11px;font-weight:700;padding:3px 7px;border-radius:5px;white-space:nowrap}
.badge.good{background:var(--accent-soft);color:var(--goodtxt)}.badge.bad{background:color-mix(in srgb,var(--bad) 13%,transparent);color:var(--bad)}
.badge.mid{background:color-mix(in srgb,var(--warn) 24%,transparent);color:#8a5a00}.badge.wait{background:var(--chip);color:var(--muted)}
.stat3{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0}

.minp{font-family:var(--mono);font-size:11px;font-weight:600;color:var(--muted);white-space:nowrap}
.slip-odds .minp{margin-top:3px}

.verdict{font-size:12.5px;margin-top:6px;padding:6px 9px;border-radius:8px;background:var(--chip);line-height:1.4}
.verdict.ok{background:var(--accent-soft)}.verdict.ko{background:color-mix(in srgb,var(--warn) 22%,transparent)}.verdict.mid{background:color-mix(in srgb,var(--warn) 14%,transparent)}
"""
