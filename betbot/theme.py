"""Εμφάνιση της σελίδας (CSS). Κρατά τα ίδια ονόματα μεταβλητών/κλάσεων που χρησιμοποιεί το report.py,
ώστε το περιεχόμενο να μην αλλάζει· αλλάζει μόνο ο τρόπος που φαίνεται. Mobile-first, φωτεινό/σκοτεινό θέμα."""

CSS = """
:root{--plane:#f3f5f9;--surface:#ffffff;--ink:#0f172a;--ink2:#475569;--muted:#8a94a6;--grid:#e6e9f0;--border:rgba(15,23,42,.08);
--accent:#0f9d6b;--accent-ink:#ffffff;--accent-soft:#e3f6ee;--s1:#2a78d6;--s2:#d9541f;--s3:#12a67a;--s4:#c98500;--s5:#d9548a;--s6:#0b8f4d;--s7:#6250d6;--s8:#e04848;
--good:#0f9d6b;--goodtxt:#0a7d54;--bad:#d64545;--warn:#f2b01e;--chip:#eef1f6;--hero1:#0f172a;--hero2:#1e3a5f;--shadow:0 1px 2px rgba(15,23,42,.06),0 6px 18px rgba(15,23,42,.06);--r:16px}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--plane:#0a0f1c;--surface:#131a2c;--ink:#e8edf7;--ink2:#b4bdd0;--muted:#7d889e;
--grid:#222b40;--border:rgba(255,255,255,.08);--accent:#25c28a;--accent-ink:#06281c;--accent-soft:#12372d;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;
--s6:#199e70;--s7:#9085e9;--s8:#e66767;--good:#25c28a;--goodtxt:#25c28a;--bad:#ff6b6b;--chip:#1c2540;--hero1:#16213b;--hero2:#1d4a63;--shadow:0 1px 2px rgba(0,0,0,.3),0 8px 22px rgba(0,0,0,.28)}}
:root[data-theme=dark]{--plane:#0a0f1c;--surface:#131a2c;--ink:#e8edf7;--ink2:#b4bdd0;--muted:#7d889e;--grid:#222b40;--border:rgba(255,255,255,.08);
--accent:#25c28a;--accent-ink:#06281c;--accent-soft:#12372d;--goodtxt:#25c28a;--good:#25c28a;--bad:#ff6b6b;--chip:#1c2540;--hero1:#16213b;--hero2:#1d4a63}
[hidden]{display:none!important}*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--plane);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,system-ui,sans-serif;
-webkit-font-smoothing:antialiased}
main{max-width:980px;margin:0 auto;padding:0 14px 96px}
a{color:var(--s1)}
h1{font-size:22px;margin:0;letter-spacing:-.01em}h2{font-size:19px;margin:22px 0 8px}h3{font-size:16px;margin:0 0 10px;letter-spacing:-.005em}
h4{margin:16px 0 8px;font-size:14px;color:var(--ink2);font-weight:650;text-transform:none}
.sub{color:var(--ink2);margin:0 0 12px}
/* --- πάνω μπάρα --- */
.appbar{position:sticky;top:0;z-index:20;margin:0 -14px;padding:10px 14px;background:color-mix(in srgb,var(--plane) 88%,transparent);
backdrop-filter:saturate(1.4) blur(10px);-webkit-backdrop-filter:saturate(1.4) blur(10px);border-bottom:1px solid var(--border);display:flex;align-items:center;gap:10px}
.logo{width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,var(--accent),var(--s1));display:grid;place-items:center;color:#fff;font-weight:800;font-size:17px;flex:0 0 auto}
.appbar .t{flex:1;min-width:0}.appbar .t b{display:block;font-size:16px;line-height:1.15}.appbar .t span{font-size:12px;color:var(--muted)}
.pill{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;font-weight:650;padding:6px 11px;border-radius:999px;background:var(--chip);color:var(--ink);text-decoration:none;white-space:nowrap}
.pill.live{background:#fde8e8;color:#b42318}.pill.live i{width:7px;height:7px;border-radius:50%;background:#e5484d;display:inline-block;animation:pulse 1.6s infinite}
@media (prefers-color-scheme:dark){.pill.live{background:#3a1a1d;color:#ff9aa0}}
@keyframes pulse{50%{opacity:.35}}
/* --- hero --- */
.hero{background:var(--hero1);color:#fff;border-radius:22px;padding:20px 18px 16px;margin:14px 0 12px;box-shadow:var(--shadow);position:relative;overflow:hidden}
.hero:after{content:"";position:absolute;left:18px;top:0;width:38px;height:4px;border-radius:0 0 4px 4px;background:var(--accent)}
.hero .eyebrow{font-size:12px;letter-spacing:.08em;text-transform:uppercase;opacity:.7;font-weight:650}
.hero .big{font-size:27px;line-height:1.15;font-weight:800;margin:6px 0 4px;letter-spacing:-.02em}
.hero .why{font-size:14px;opacity:.82;max-width:34em}
.hero .kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:16px}
.hero .kpi{background:rgba(255,255,255,.1);border-radius:12px;padding:9px 10px}.hero .kpi .k{font-size:11.5px;opacity:.75}.hero .kpi .v{font-size:18px;font-weight:750;font-variant-numeric:tabular-nums}
.meter{height:7px;border-radius:99px;background:rgba(255,255,255,.18);margin-top:6px;overflow:hidden}.meter i{display:block;height:100%;background:linear-gradient(90deg,#34d399,#fbbf24);border-radius:99px}
/* --- κάρτες --- */
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:16px;margin:12px 0;box-shadow:var(--shadow)}
details.card>summary{font-weight:650}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:8px;margin:10px 0}
.tile{background:var(--chip);border:0;border-radius:12px;padding:9px 11px}
.tile .k{color:var(--ink2);font-size:11.5px}.tile .v{font-size:19px;font-weight:750;font-variant-numeric:tabular-nums;letter-spacing:-.01em}
.warn{border-left:4px solid var(--warn);background:var(--surface);padding:10px 14px;border-radius:10px;color:var(--ink2);font-size:13.5px;margin:10px 0}
.disclaimer{font-size:12.5px;color:var(--muted);margin:14px 2px}
/* --- πλοήγηση --- */
.chipnav{display:flex;gap:8px;overflow-x:auto;padding:12px 0 6px;scrollbar-width:none;margin:0 -14px;padding-left:14px;padding-right:14px}
.chipnav::-webkit-scrollbar{display:none}
.chipnav button{flex:0 0 auto;border:1px solid var(--border);background:var(--surface);color:var(--ink);border-radius:999px;padding:8px 14px;font:inherit;font-size:14px;font-weight:600;cursor:pointer;white-space:nowrap;box-shadow:var(--shadow)}
.chipnav button[aria-selected=true]{background:var(--ink);color:var(--plane);border-color:var(--ink)}
.bar{position:fixed;left:0;right:0;bottom:0;z-index:30;display:grid;grid-template-columns:repeat(5,1fr);background:color-mix(in srgb,var(--surface) 92%,transparent);
backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border-top:1px solid var(--border);padding:6px 6px calc(6px + env(safe-area-inset-bottom))}
.bar button{border:0;background:none;color:var(--muted);font:inherit;font-size:11px;font-weight:650;display:flex;flex-direction:column;align-items:center;gap:3px;padding:5px 2px;border-radius:12px;cursor:pointer}
.bar button svg{width:22px;height:22px;stroke:currentColor;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.bar button[aria-selected=true]{color:var(--accent)}.bar button[aria-selected=true]{background:var(--accent-soft)}
.tab{display:none}.tab.on{display:block;animation:fade .25s ease}
@keyframes fade{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
@media (min-width:900px){.bar{left:50%;right:auto;transform:translateX(-50%);width:560px;bottom:14px;border:1px solid var(--border);border-radius:20px;box-shadow:var(--shadow)}}
/* --- πίνακες --- */
.tbl{width:100%;overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:8px 8px;border-bottom:1px solid var(--grid);text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:650;font-size:11.5px;white-space:nowrap;text-transform:uppercase;letter-spacing:.04em}
td.n{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
tr:last-child td{border-bottom:0}
.fb{display:inline-block;width:18px;height:18px;line-height:18px;text-align:center;border-radius:5px;font-size:11px;font-weight:700;margin-right:2px;color:#fff}
.fb.w{background:var(--good)}.fb.d{background:var(--muted)}.fb.l{background:var(--bad)}
.pos{color:var(--goodtxt)}.neg{color:var(--bad)}.muted{color:var(--muted);font-size:13px}
.wr{font-size:12px;color:var(--ink2);margin-top:3px}
.mv{font-size:12px;font-weight:650;padding:1px 7px;border-radius:999px;background:var(--chip);white-space:nowrap}
.mv.dn{color:var(--s1)}.mv.up{color:var(--s2)}
ul.why{margin:6px 0 4px 18px;padding:0;font-size:13px;color:var(--ink2)}
details{margin-top:4px}summary{cursor:pointer;color:var(--ink2);font-size:13px}
.chart{position:relative;height:250px;margin-top:8px}.chart.sm{height:170px}
.rules li{margin:4px 0;font-size:14px;color:var(--ink2)}
td.t{white-space:nowrap;color:var(--ink2);font-variant-numeric:tabular-nums}
/* επιλογές ως κάρτες στο κινητό */
@media (max-width:640px){
 table.picks thead{display:none}
 table.picks,table.picks tbody{display:block}
 table.picks tr{display:grid;grid-template-columns:repeat(3,auto);justify-content:start;gap:3px 16px;padding:12px;margin:8px 0;background:var(--chip);border-radius:14px;border:0}
 table.picks td{border:0;padding:1px 0;text-align:left}
 table.picks td.t,table.picks td:nth-child(2),table.picks td:nth-child(3){grid-column:1/-1}
 table.picks td:nth-child(2){font-size:15.5px}
 table.picks td[data-l]::before{content:attr(data-l) " ";color:var(--muted);font-size:11px;font-weight:400}
 .chart{height:220px}
}
/* --- ζωντανές καταστάσεις --- */
.tk{font-size:18px}.scr{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}.cnt{font-size:14px;margin:8px 0}
.banner{background:#fff4d6;color:#5c4400;border:1px solid #efd37a;border-radius:12px;padding:10px 12px;margin:10px 0;font-size:14px}.banner a{color:inherit;font-weight:700}
.vd{font-size:12.5px;padding:3px 9px;border-radius:999px;background:var(--chip);white-space:nowrap;font-weight:700;vertical-align:middle}
.b-won{color:var(--goodtxt);background:var(--accent-soft)}.b-lost{color:var(--bad);background:color-mix(in srgb,var(--bad) 14%,transparent)}
.b-live{color:#1d5fd3;background:color-mix(in srgb,#1d5fd3 13%,transparent)}.b-wait,.b-pending{color:var(--muted)}
.daysum{margin:8px 0 2px}.daysum .line{font-size:14px}.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.chip{font-size:13px;padding:4px 10px;border-radius:999px;background:var(--surface);border:1px solid var(--border)}
.livestat{font-size:12.5px;color:var(--muted);margin:6px 2px}
.ok{color:var(--goodtxt)}.ko{color:var(--bad)}
.tk{display:flex;gap:10px;padding:8px 0;border-top:1px solid var(--grid);align-items:flex-start}.tk:first-of-type{border-top:0}
.tk .ic{width:26px;font-size:19px;line-height:1.2}.tk .sc{font-variant-numeric:tabular-nums}
.grid td,.grid th{text-align:center;padding:6px 4px}.grid td.d{text-align:left;white-space:nowrap}
/* --- ημερολόγιο --- */
.calh{display:flex;justify-content:space-between;align-items:center;margin:6px 0 10px}.calh b{font-size:16px}
.calh button{font-size:20px;width:40px;height:40px;border:0;background:var(--chip);color:inherit;border-radius:12px;cursor:pointer}
.calg{display:grid;grid-template-columns:repeat(7,1fr);gap:5px}.cdw{text-align:center;font-size:11.5px;color:var(--muted);font-weight:650}
.cd{min-height:54px;border:0;background:transparent;color:var(--muted);border-radius:12px;padding:4px 2px;font-size:11px;display:flex;flex-direction:column;align-items:center;gap:2px;font-family:inherit}
.cd i{font-style:normal;font-size:13px;font-weight:600}.cd.has{background:var(--chip);color:var(--ink);cursor:pointer}.cd:disabled{opacity:.4}.cd span{line-height:1.1;font-weight:700}
.cd.w{background:var(--accent-soft);color:var(--goodtxt)}.cd.l{background:color-mix(in srgb,var(--bad) 14%,transparent);color:var(--bad)}.cd.m{background:color-mix(in srgb,var(--warn) 22%,transparent)}
.cd.sel{outline:2px solid var(--ink)}
/* --- ανάλυση --- */
.insight{display:flex;gap:12px;align-items:flex-start;padding:10px 0;border-top:1px solid var(--grid)}.insight:first-of-type{border-top:0}
.insight .ico{font-size:20px;line-height:1.2}.insight b{display:block;font-size:14.5px}.insight span{font-size:13.5px;color:var(--ink2)}
.sc-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}
.scorecard{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:14px;box-shadow:var(--shadow)}
.scorecard h4{margin:0 0 8px;color:var(--ink);font-size:15px}
.trow{display:grid;grid-template-columns:118px 1fr auto;gap:8px;align-items:center;padding:7px 0;border-top:1px solid var(--grid);font-size:13px}
.trow:first-of-type{border-top:0}.trow .nm{font-weight:650;white-space:nowrap}.trow .st{color:var(--muted);font-size:12px}
.bar2{height:6px;background:var(--chip);border-radius:99px;overflow:hidden;margin-top:4px}.bar2 i{display:block;height:100%;background:var(--accent);border-radius:99px}
.badge{font-size:11.5px;font-weight:700;padding:3px 8px;border-radius:999px;white-space:nowrap}
.badge.good{background:var(--accent-soft);color:var(--goodtxt)}.badge.bad{background:color-mix(in srgb,var(--bad) 14%,transparent);color:var(--bad)}
.badge.mid{background:color-mix(in srgb,var(--warn) 24%,transparent);color:#8a5a00}.badge.wait{background:var(--chip);color:var(--muted)}
.stat3{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0}
.stat3 .tile{text-align:center}

.tiersel{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin:12px 0 4px}
.tiersel button{display:flex;flex-direction:column;align-items:flex-start;gap:1px;padding:10px 11px;border:1px solid var(--border);background:var(--surface);color:var(--ink);border-radius:14px;font:inherit;cursor:pointer;text-align:left;position:relative}
.tiersel button b{font-size:13.5px}.tiersel button span{font-size:11px;color:var(--muted);line-height:1.25}
.tiersel button[aria-pressed=true]{border-color:var(--ink);box-shadow:inset 0 0 0 1px var(--ink)}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block;margin-bottom:4px}.d-strong{background:var(--s3)}.d-balanced{background:var(--s4)}.d-bold{background:var(--s2)}

/* --- δελτίο ως απόδειξη --- */
.slip{padding:0;overflow:hidden}
.slip-top{padding:16px 16px 4px;display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
.slip .eyebrow{font-size:12px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);font-weight:700;margin-bottom:6px}
.slip-odds{text-align:right}.slip-odds small{display:block;font-size:10.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.07em}
.slip-odds b{font-size:38px;font-weight:800;letter-spacing:-.035em;font-variant-numeric:tabular-nums;line-height:1}
.slip-body{padding:0 16px}.slip-body .muted{margin:4px 0}
.slip-stub{position:relative;border-top:2px dashed var(--grid);margin-top:10px;padding:14px 16px;display:grid;grid-template-columns:repeat(3,1fr);gap:8px;background:var(--chip)}
.slip-stub:before,.slip-stub:after{content:"";position:absolute;top:-9px;width:16px;height:16px;border-radius:50%;background:var(--plane);border:1px solid var(--border)}
.slip-stub:before{left:-9px}.slip-stub:after{right:-9px}
.slip-stub small{display:block;font-size:10.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}.slip-stub b{font-size:18px;font-variant-numeric:tabular-nums;letter-spacing:-.01em}
.slip-more{padding:0 16px 12px;background:var(--chip)}.slip-more summary{padding:2px 0 6px}
.slip table.picks tr{background:none;border-radius:0;margin:0;padding:12px 0;border-bottom:1px solid var(--grid)}
.slip table.picks tr:last-child{border-bottom:0}

.insight .ico{width:28px;height:28px;border-radius:50%;background:var(--chip);color:var(--ink);display:grid;place-items:center;font-weight:800;font-size:14px;flex:0 0 auto;line-height:1}

/* γραμμή επιλογής πιο συμπαγής */
table.picks td.t{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
table.picks td.t .tk{display:inline;padding:0;border:0;font-size:17px}table.picks td.t .scr{display:inline;font-weight:650;color:var(--ink2)}
.chip{font-size:12.5px}

.daysum .line{font-size:12.5px;color:var(--ink2)}
"""
