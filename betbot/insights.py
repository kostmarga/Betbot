"""Ανάλυση «τι συμβαίνει»: μετρητής τύχης, εξερεύνηση σκελών με φίλτρα, αυτοψία χαμένων, έκθεση σήμερα (22/11/2026).
Όλα βγαίνουν από τα αποθηκευμένα δελτία/σκέλη· δεν αγγίζουν επιλογές ή πιθανότητες."""
from __future__ import annotations

import html
import json
import math
from collections import defaultdict
from zoneinfo import ZoneInfo

from .paper import CAT_NAME, TIER_NAME, drop_tier_dups, split_list_name
from .stats import _LEGACY
from .util import slip_day, sport_day

E = html.escape
CORE = ("recommended", "safe", "overs")
GRP = {("OU", "OVER"): "Over γκολ", ("OU", "UNDER"): "Under γκολ", ("BTTS", "YES"): "BTTS Ναι", ("BTTS", "NO"): "BTTS Όχι",
       ("TOTAL", "OVER"): "Over πόντων", ("TOTAL", "UNDER"): "Under πόντων", ("1X2", None): "Νικητής 1Χ2", ("ML", None): "Νικητής (μπάσκετ/NFL)",
       ("SPREAD", None): "Χάντικαπ", ("CORNERS", None): "Κόρνερ", ("CARDS", None): "Κάρτες", ("PLAYER", None): "Παίκτες", ("PTS", None): "Πόντοι παικτών"}


def grp(leg) -> str:
    m, s = leg.get("market"), str(leg.get("selection") or "")
    return GRP.get((m, s)) or GRP.get((m, None)) or GRP.get((m, s.split("|")[0])) or str(m)


def margin_text(leg, m) -> str:
    """Σύντομο «πόσο έλειψε» με βάση το σκορ (μόνο όπου το σκορ αρκεί)."""
    if not m or m.get("home_score") is None:
        return ""
    h, a, mk, L = m["home_score"], m["away_score"], leg.get("market"), leg.get("line")
    s = str(leg.get("selection") or "")
    if mk in ("OU", "TOTAL") and L is not None:
        return f"σκορ {h}-{a} · σύνολο {h + a} (γραμμή {L:g})"
    if mk == "SPREAD" and L is not None:
        v = (h - a) + L
        return f"σκορ {h}-{a} · έλειψαν {abs(v):g} από το χάντικαπ"
    if mk in ("1X2", "ML", "BTTS"):
        return f"σκορ {h}-{a}"
    return f"σκορ {h}-{a}"


def _pm_notes(l, kills, m) -> list:
    """Αυτόματη «αυτοψία» ενός χαμένου σκέλους: τι ξέραμε πριν και τι έγινε."""
    notes = []
    p = l.get("p") or 0
    if p:
        notes.append(f"Πιθανότητα {p * 100:.0f}%" + (" → κανονική απώλεια." if p >= 0.55 else " → σχεδόν 50/50 εξαρχής."))
    t = margin_text(l, m)
    if t:
        notes.append("Τελικό: " + t)
    w = [x for x in (l.get("warnings") or []) if x]
    if w:
        notes.append("⚠️ Υπήρχε προειδοποίηση πριν τον αγώνα: " + "; ".join(w[:2]))
    why = l.get("why") or []
    for x in why:
        if "ανέβηκε" in x or "ανεβαίνει" in x:
            notes.append("Η αγορά πήγε κόντρα: " + x[:90])
            break
    for x in why:
        if x.startswith("Συμπέρασμα:"):
            notes.append("Το bot το είχε κρίνει: " + x.replace("Συμπέρασμα: ", "")[:80])
            break
    if kills > 1:
        notes.append(f"Έριξε {kills} δελτία μαζί (επικάλυψη).")
    return notes


def _lesson(l, kills) -> str:
    p = l.get("p") or 0
    if [x for x in (l.get("warnings") or []) if x]:
        return "Το σημάδι υπήρχε πριν: αν επαναληφθεί σε πολλά σκέλη, προτείνεται αυστηρότερος κανόνας."
    if p >= 0.7:
        return "Απλή ατυχία: δυνατό σκέλος που έχασε· δεν υπάρχει κάτι να διορθωθεί."
    if p < 0.55:
        return "Αδύναμη επιλογή (≈50/50)· μόνο σε λαχεία/χάντικαπ — δεν ταιριάζει στον στόχο «πιο σίγουρα»."
    return "Μέσης πιθανότητας σκέλος: η απώλεια είναι μέσα στα αναμενόμενα."


def days_view(db, slips, tz, today, ndays=21) -> list:
    """Ανά ημέρα στοιχημάτων: τι παίξαμε, τι κέρδισε/έχασε, και αυτοψία κάθε χαμένου σκέλους."""
    from datetime import timedelta
    from .util import parse_iso
    byday = defaultdict(list)
    for s in slips:
        d = slip_day(s, tz)
        if (today - d).days <= ndays:
            byday[d].append(s)
    out = []
    for d in sorted(byday, reverse=True):
        ss = sorted(byday[d], key=lambda x: (split_list_name(x["list_name"])[1] not in CORE, x["created_at"]))
        kills = defaultdict(int)
        legs_u = {}
        for s in ss:
            for l in s["legs"]:
                k = (l["match_id"], l["market"], l["selection"], l.get("line"))
                legs_u[k] = l
                if l.get("result") == "lost":
                    kills[k] += 1
        slips_out, pl = [], 0.0
        for s in ss:
            tier, cat = split_list_name(s["list_name"])
            nm = CAT_NAME.get(cat, cat) + ("" if tier == "balanced" else " · " + TIER_NAME[tier]) + (" · επιπλέον" if "+" in str(s["slip_id"]).split("#")[-1] else "")
            stk = 1.0 if cat in ("x10", "x30", "x100") else 2.0
            if not cat.startswith("fair_"):
                if s["status"] == "won":
                    pl += stk * s["total_odds"] - stk
                elif s["status"] == "lost":
                    pl -= stk
            lg = []
            for l in s["legs"]:
                m = db.get_match(l["match_id"])
                sc = f"{m['home_score']}-{m['away_score']}" if m and m.get("home_score") is not None else ""
                lg.append({"r": l.get("result") or "open", "lb": str(l.get("label") or "")[:44], "m": f"{l.get('home', '')} – {l.get('away', '')}"[:40],
                           "sc": sc, "p": round(l.get("p") or 0, 2), "o": round(l.get("odds") or 0, 2)})
            slips_out.append({"n": nm, "s": s["status"], "o": round(s["total_odds"], 2), "p": round(s["model_prob"] or 0, 3), "f": cat.startswith("fair_"), "L": lg})
        pm = []
        for k, n in sorted(kills.items(), key=lambda kv: -kv[1]):
            l = legs_u[k]
            m = db.get_match(l["match_id"])
            pm.append({"lb": str(l.get("label") or "")[:44], "m": f"{l.get('home', '')} – {l.get('away', '')}"[:40], "n": n, "notes": _pm_notes(l, n, m), "lesson": _lesson(l, n)})
        won = sum(1 for l in legs_u.values() if l.get("result") == "won")
        lost = sum(1 for l in legs_u.values() if l.get("result") == "lost")
        opn = sum(1 for l in legs_u.values() if l.get("result") in (None, "open"))
        exp_w = sum((l.get("p") or 0) for l in legs_u.values() if l.get("result") in ("won", "lost"))
        out.append({"d": d.isoformat(), "wd": ["Δευ", "Τρι", "Τετ", "Πεμ", "Παρ", "Σαβ", "Κυρ"][d.weekday()], "slips": slips_out,
                    "n": len(ss), "sw": sum(1 for s in ss if s["status"] == "won"), "sl": sum(1 for s in ss if s["status"] == "lost"), "so": sum(1 for s in ss if s["status"] == "open"),
                    "lw": won, "ll": lost, "lo": opn, "exp": round(exp_w, 1), "pl": round(pl, 2), "pm": pm})
    return out


def patterns(slips, tz) -> dict:
    """Μοτίβα σε ΟΛΑ τα κριθέντα μοναδικά σκέλη: σε ποια χαρακτηριστικά πηγαίνουμε χειρότερα/καλύτερα από το αναμενόμενο (με σ)."""
    from .util import parse_iso
    legs = {}
    for s in slips:
        for l in s["legs"]:
            if l.get("result") in ("won", "lost") and l.get("p"):
                legs[(l["match_id"], l["market"], l["selection"], l.get("line"))] = l
    feats = defaultdict(lambda: [0, 0.0, 0.0, 0])      # (χαρακτηριστικό, τιμή) -> n, Σp, Σp(1-p), νίκες
    for l in legs.values():
        p = l["p"]
        v = str(l.get("verdict") or "")
        vb = ("ΑΞΙΖΕΙ ΜΕ ΕΠΙΦΥΛΑΞΕΙΣ" if "ΕΠΙΦΥΛΑΞΕΙΣ" in v else "ΟΡΙΑΚΟ" if "ΟΡΙΑΚΟ" in v else "ΑΞΙΖΕΙ" if "ΑΞΙΖΕΙ" in v else "άλλο")
        for key in (("Αγορά", grp(l)), ("Λίγκα", l.get("league_name") or l.get("league") or ""), ("Άθλημα", l.get("sport") or ""),
                    ("Πιθανότητα", "<60%" if p < .6 else "60–70%" if p < .7 else "70–80%" if p < .8 else "80%+"),
                    ("Προειδοποίηση πριν", "είχε" if [x for x in (l.get("warnings") or []) if x] else "δεν είχε"), ("Κρίση bot", vb)):
            f = feats[key]
            f[0] += 1; f[1] += p; f[2] += p * (1 - p); f[3] += l["result"] == "won"
    rows = []
    for (name, val), (n, e, var, w) in feats.items():
        if n >= 12 and val:
            sd = math.sqrt(var)
            rows.append({"f": name, "v": val, "n": n, "w": int(w), "e": round(e, 1), "sd": round(sd, 1), "z": round((w - e) / sd, 1) if sd else 0.0})
    tested = len(rows)
    rows.sort(key=lambda r: r["z"])
    return {"worst": [r for r in rows if r["z"] <= -1.5][:6], "best": [r for r in rows[::-1] if r["z"] >= 1.5][:4], "tested": tested,
            "chance": round(tested * 0.134, 1), "n_legs": len(legs)}


def build(db, cfg, now) -> dict:
    tz = ZoneInfo(cfg["timezone"])
    today = sport_day(now, tz)
    slips = [s for s in db.slips() if not _LEGACY.search(str(s["slip_id"])) and not str(s.get("list_name") or "").startswith("shadow_")]
    slips = drop_tier_dups(slips)
    # ---------- μοναδικά κριθέντα σκέλη (για την εξερεύνηση)
    legs, cats = {}, defaultdict(set)
    for s in slips:
        cat = split_list_name(s["list_name"])[1]
        for l in s["legs"]:
            k = (l["match_id"], l["market"], l["selection"], l.get("line"))
            cats[k].add(cat)
            if l.get("result") in ("won", "lost") and l.get("p"):
                legs[k] = {"d": sport_day(__import__("betbot.util", fromlist=["parse_iso"]).parse_iso(l["kickoff"]), tz).isoformat(), "sp": l.get("sport") or "",
                           "lg": l.get("league_name") or l.get("league") or "", "g": grp(l), "lb": str(l.get("label") or "")[:48],
                           "p": round(l["p"], 3), "o": round(l.get("odds") or 0, 2), "w": 1 if l["result"] == "won" else 0}
    for k, v in legs.items():
        v["c"] = sorted(CAT_NAME.get(c, c) for c in cats[k])
    legs_out = sorted(legs.values(), key=lambda x: x["d"], reverse=True)
    # ---------- μετρητής τύχης (νίκες δελτίων vs αναμενόμενες) ανά κατηγορία και για τον «πυρήνα»
    done = sorted([s for s in slips if s["status"] in ("won", "lost") and not str(s["list_name"]).startswith("fair_")],
                  key=lambda s: (slip_day(s, tz), s["created_at"]))

    def series(sel):
        cw = ce = cv = 0.0
        pts = []
        for s in sel:
            p = s["model_prob"] or 0.0
            cw += s["status"] == "won"; ce += p; cv += p * (1 - p)
            pts.append({"d": slip_day(s, tz).strftime("%d/%m"), "diff": round(cw - ce, 2), "sd": round(math.sqrt(cv), 2)})
        return pts, cw, ce, math.sqrt(cv)

    core_sel = [s for s in done if split_list_name(s["list_name"])[1] in CORE]
    core_pts, cw, ce, csd = series(core_sel)
    cat_rows = []
    for c in sorted({split_list_name(s["list_name"])[1] for s in done}, key=lambda c: -len([s for s in done if split_list_name(s["list_name"])[1] == c])):
        sel = [s for s in done if split_list_name(s["list_name"])[1] == c]
        _, w, e, sd = series(sel)
        cat_rows.append({"c": CAT_NAME.get(c, c), "n": len(sel), "w": int(w), "e": round(e, 1), "sd": round(sd, 1), "z": round((w - e) / sd, 1) if sd else 0.0})
    # ---------- αυτοψία χαμένων (τελευταίες 7 ημέρες στοιχημάτων): ποια σκέλη έριξαν πόσα δελτία
    from datetime import timedelta
    cut = today - timedelta(days=6)
    kill = {}
    lost_slips = 0
    for s in slips:
        if s["status"] != "lost" or slip_day(s, tz) < cut or str(s["list_name"]).startswith("fair_"):
            continue
        lost_slips += 1
        for l in s["legs"]:
            if l.get("result") == "lost":
                k = (l["match_id"], l["market"], l["selection"], l.get("line"))
                e = kill.setdefault(k, {"leg": l, "n": 0, "cats": set()})
                e["n"] += 1; e["cats"].add(CAT_NAME.get(split_list_name(s["list_name"])[1], ""))
    kill_out = []
    for k, e in sorted(kill.items(), key=lambda kv: (-kv[1]["n"], -(kv[1]["leg"].get("p") or 0)))[:12]:
        l = e["leg"]
        kill_out.append({"lb": str(l.get("label") or "")[:44], "m": f"{l.get('home', '')} – {l.get('away', '')}"[:44], "p": round(l.get("p") or 0, 2), "n": e["n"],
                         "t": margin_text(l, db.get_match(l["match_id"])), "d": sport_day(__import__("betbot.util", fromlist=["parse_iso"]).parse_iso(l["kickoff"]), tz).strftime("%d/%m"),
                         "c": ", ".join(sorted(x for x in e["cats"] if x))})
    # ---------- έκθεση σήμερα
    exp = {}
    for s in slips:
        if slip_day(s, tz) != today:
            continue
        cat = CAT_NAME.get(split_list_name(s["list_name"])[1], split_list_name(s["list_name"])[1])
        for l in s["legs"]:
            e = exp.setdefault(l["match_id"], {"m": f"{l.get('home', '')} – {l.get('away', '')}"[:44], "n": 0, "cats": set(), "done": l.get("result") in ("won", "lost")})
            e["n"] += 1; e["cats"].add(cat)
    exp_out = sorted(({"m": e["m"], "n": e["n"], "c": sorted(e["cats"])} for e in exp.values()), key=lambda x: (-x["n"], x["m"]))[:20]
    return {"legs": legs_out, "core": {"pts": core_pts, "w": int(cw), "e": round(ce, 1), "sd": round(csd, 1), "n": len(core_sel)}, "cats": cat_rows,
            "kill": kill_out, "lost_slips": lost_slips, "exposure": exp_out, "days": days_view(db, slips, tz, today), "patterns": patterns(slips, tz)}


EXPLORER_JS = """
(function(){
  var root=document.getElementById('legx'); if(!root) return;
  var data=JSON.parse(document.getElementById('legx-data').textContent);
  var F=['sp','lg','g','pb','ob','c','res','days'];
  function uniq(f){var s={};data.forEach(function(x){(f(x)||[]).forEach?0:0;var v=f(x);(Array.isArray(v)?v:[v]).forEach(function(y){if(y!=='')s[y]=1;});});return Object.keys(s).sort();}
  function opt(id,vals,all){var el=document.getElementById(id);el.innerHTML='<option value="">'+all+'</option>'+vals.map(function(v){return '<option>'+v+'</option>';}).join('');}
  opt('lx-sp',uniq(function(x){return x.sp;}),'Όλα τα αθλήματα');
  opt('lx-lg',uniq(function(x){return x.lg;}),'Όλες οι λίγκες');
  opt('lx-g',uniq(function(x){return x.g;}),'Όλες οι αγορές');
  opt('lx-c',uniq(function(x){return x.c;}),'Όλες οι κατηγορίες');
  function pb(p){return p<0.6?'<60%':p<0.7?'60–70%':p<0.8?'70–80%':'80%+';}
  function ob(o){return o<1.3?'<1.30':o<1.6?'1.30–1.59':o<2?'1.60–1.99':'2.00+';}
  opt('lx-pb',['<60%','60–70%','70–80%','80%+'],'Κάθε πιθανότητα');
  opt('lx-ob',['<1.30','1.30–1.59','1.60–1.99','2.00+'],'Κάθε απόδοση');
  function today(){return new Date();}
  function render(){
    var v=function(id){return document.getElementById(id).value;};
    var days=parseInt(v('lx-days')||'0',10), now=new Date(), rows=data.filter(function(x){
      if(v('lx-sp')&&x.sp!==v('lx-sp'))return false; if(v('lx-lg')&&x.lg!==v('lx-lg'))return false; if(v('lx-g')&&x.g!==v('lx-g'))return false;
      if(v('lx-pb')&&pb(x.p)!==v('lx-pb'))return false; if(v('lx-ob')&&ob(x.o)!==v('lx-ob'))return false;
      if(v('lx-c')&&x.c.indexOf(v('lx-c'))<0)return false; if(v('lx-res')==='won'&&!x.w)return false; if(v('lx-res')==='lost'&&x.w)return false;
      if(days){var d=new Date(x.d+'T12:00:00');if((now-d)/86400000>days)return false;} return true;});
    var n=rows.length, w=rows.reduce(function(a,x){return a+x.w;},0), e=rows.reduce(function(a,x){return a+x.p;},0), sd=Math.sqrt(rows.reduce(function(a,x){return a+x.p*(1-x.p);},0));
    var z=sd?((w-e)/sd):0;
    var s=document.getElementById('lx-sum');
    s.innerHTML=n?('<b>'+n+'</b> σκέλη · πέρασαν <b>'+w+'</b> ('+Math.round(w/n*100)+'%) · το μοντέλο περίμενε <b>'+e.toFixed(1)+' ± '+sd.toFixed(1)+'</b> · διαφορά <b class="'+(z<-1.5?'neg':z>1.5?'pos':'')+'">'+(z>=0?'+':'')+z.toFixed(1)+'σ</b>'+(n<30?' <span class="muted">(λίγα σκέλη — ένδειξη, όχι απόδειξη)</span>':'')):'Κανένα σκέλος με αυτά τα φίλτρα.';
    document.getElementById('lx-list').innerHTML=rows.slice(0,40).map(function(x){return '<tr><td>'+(x.w?'✅':'❌')+'</td><td>'+x.d.slice(8)+'/'+x.d.slice(5,7)+'</td><td>'+x.lb+'<div class="muted">'+x.lg+' · '+x.g+'</div></td><td>'+Math.round(x.p*100)+'%</td><td>'+(x.o?x.o.toFixed(2):'—')+'</td></tr>';}).join('');
  }
  ['lx-sp','lx-lg','lx-g','lx-pb','lx-ob','lx-c','lx-res','lx-days'].forEach(function(id){document.getElementById(id).addEventListener('change',render);});
  render();
})();
"""


DAY_JS = """
(function(){
  var el=document.getElementById('dayv'); if(!el) return;
  var days=JSON.parse(document.getElementById('dayv-data').textContent); if(!days.length) return;
  var i=0, IC={won:'✅',lost:'❌',void:'↩️',open:'⏳'}, SC={won:'ΠΕΡΑΣΕ',lost:'ΔΕΝ ΠΕΡΑΣΕ',void:'ΑΚΥΡΟ',open:'ΣΕ ΕΞΕΛΙΞΗ'};
  function esc(t){return String(t).replace(/[&<>]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c];});}
  var sel=document.getElementById('day-sel');
  sel.innerHTML=days.map(function(d,k){return '<option value="'+k+'">'+d.wd+' '+d.d.slice(8)+'/'+d.d.slice(5,7)+(k===0?' (πιο πρόσφατη)':'')+'</option>';}).join('');
  function show(){
    var d=days[i], h='';
    var pl=d.pl; 
    h+='<div class="tiles"><div class="tile"><div class="k">Δελτία</div><div class="v">'+d.n+'</div></div>'
      +'<div class="tile"><div class="k">Πέρασαν</div><div class="v pos">'+d.sw+'</div></div>'
      +'<div class="tile"><div class="k">Δεν πέρασαν</div><div class="v neg">'+d.sl+'</div></div>'
      +'<div class="tile"><div class="k">Σε εξέλιξη</div><div class="v">'+d.so+'</div></div>'
      +'<div class="tile"><div class="k">Σκέλη ✅/❌</div><div class="v">'+d.lw+'/'+d.ll+'</div></div>'
      +'<div class="tile"><div class="k">Αναμενόταν ✅</div><div class="v">'+d.exp.toFixed(1)+'</div></div>'
      +'<div class="tile"><div class="k">Κ/Ζ ημέρας (εικον.)</div><div class="v '+(pl>0?'pos':pl<0?'neg':'')+'">'+(pl>=0?'+':'')+pl.toFixed(2)+'€</div></div></div>';
    h+='<p class="muted" style="margin:6px 0">Μοναδικά σκέλη: '+(d.lw+d.ll+d.lo)+' ('+d.lw+' ✅, '+d.ll+' ❌'+(d.lo?', '+d.lo+' ⏳':'')+'). Αν η διαφορά ✅ από «αναμενόταν» είναι μικρή, η μέρα ήταν κανονική· η επικάλυψη είναι αυτή που μεγαλώνει τις ήττες δελτίων.</p>';
    h+=d.slips.map(function(s){
      return '<details class="dslip"><summary><b>'+IC[s.s]+' '+esc(s.n)+'</b> · '+s.o.toFixed(2)+' · '+Math.round(s.p*100)+'%'+(s.f?' · χωρίς απόδοση':'')+'</summary>'
        +s.L.map(function(l){return '<div class="lgl">'+IC[l.r]+' '+esc(l.m)+': <b>'+esc(l.lb)+'</b> @'+(l.o?l.o.toFixed(2):'—')+(l.sc?' <span class="muted">('+l.sc+')</span>':'')+'</div>';}).join('')+'</details>';}).join('');
    if(d.pm.length){
      h+='<h4 style="margin:14px 0 6px">🩺 Γιατί χάσαμε — αυτοψία κάθε χαμένου σκέλους</h4>';
      h+=d.pm.map(function(x){return '<div class="card" style="margin:6px 0"><b>❌ '+esc(x.lb)+'</b> <span class="muted">· '+esc(x.m)+(x.n>1?' · έριξε '+x.n+' δελτία':'')+'</span><ul style="margin:6px 0 4px 18px">'+x.notes.slice(0,3).map(function(n){return '<li>'+esc(n)+'</li>';}).join('')+'</ul><div><b>Μάθημα:</b> '+esc(x.lesson)+'</div></div>';}).join('');
    } else if(d.ll===0 && d.lw+d.lo>0){ h+='<p class="muted">Κανένα χαμένο σκέλος ακόμα.</p>'; }
    document.getElementById('day-body').innerHTML=h;
    document.getElementById('day-prev').disabled=(i>=days.length-1); document.getElementById('day-next').disabled=(i<=0); sel.value=String(i);
  }
  document.getElementById('day-prev').onclick=function(){if(i<days.length-1){i++;show();}};
  document.getElementById('day-next').onclick=function(){if(i>0){i--;show();}};
  sel.onchange=function(){i=parseInt(sel.value,10);show();};
  show();
})();
"""


def render(P, ins) -> dict:
    """HTML ανά ομάδα καρτελών της Ανάλυσης: day, luck, legs, lessons."""
    G = {"day": "", "luck": "", "legs": "", "lessons": ""}
    if not ins:
        return G
    # --- καρτέλα «Ημέρα»
    if ins.get("days"):
        G["day"] += ("<div class='card'><h3>📅 Ημέρα προς ημέρα</h3><p class='muted'>Τι παίξαμε, τι κερδίσαμε, τι χάσαμε — και αυτοψία γιατί χάθηκε κάθε σκέλος. "
                     "Η «ημέρα στοιχημάτων» πάει από τις 06:00 ως τις 05:59.</p>"
                     "<div style='display:flex;gap:6px;align-items:center;margin:8px 0'><button id='day-prev' type='button'>◀ Παλαιότερη</button><select id='day-sel' style='flex:1'></select>"
                     "<button id='day-next' type='button'>Νεότερη ▶</button></div><div id='dayv'><div id='day-body'></div></div>"
                     "<script type='application/json' id='dayv-data'>" + json.dumps(ins["days"], ensure_ascii=False).replace("</", "<\\/") + "</script><script>" + DAY_JS + "</script></div>")
    # --- μετρητής τύχης
    core = ins["core"]
    if core["n"] >= 3:
        pts = core["pts"]
        cfgc = {"type": "line", "data": {"labels": [f"{i + 1}" for i in range(len(pts))], "datasets": [
            {"label": "Νίκες − αναμενόμενες", "data": [p["diff"] for p in pts], "borderColor": "var(--s1)", "borderWidth": 2.5, "pointRadius": 0, "fill": False},
            {"label": "+1σ", "data": [p["sd"] for p in pts], "borderColor": "var(--s4)", "borderDash": [5, 4], "borderWidth": 1.5, "pointRadius": 0, "fill": False},
            {"label": "−1σ", "data": [-p["sd"] for p in pts], "borderColor": "var(--s4)", "borderDash": [5, 4], "borderWidth": 1.5, "pointRadius": 0, "fill": False},
            {"label": "+2σ", "data": [2 * p["sd"] for p in pts], "borderColor": "var(--s5)", "borderDash": [2, 4], "borderWidth": 1, "pointRadius": 0, "fill": False},
            {"label": "−2σ", "data": [-2 * p["sd"] for p in pts], "borderColor": "var(--s5)", "borderDash": [2, 4], "borderWidth": 1, "pointRadius": 0, "fill": False}]},
            "options": {"scales": {"x": {"title": {"display": True, "text": "Κριθέντα δελτία (με σειρά)"}}, "y": {"title": {"display": True, "text": "νίκες − αναμενόμενες"}}}}}
        z = (core["w"] - core["e"]) / core["sd"] if core["sd"] else 0.0
        verdict = ("μέσα στην κανονική διακύμανση" if abs(z) <= 1.5 else "κάτω από το αναμενόμενο — να το προσέχουμε" if z < 0 else "πάνω από το αναμενόμενο (πιθανή τύχη)")
        rows = "".join(f"<tr><td>{E(r['c'])}</td><td>{r['n']}</td><td>{r['w']}</td><td>{r['e']:.1f} ± {r['sd']:.1f}</td>"
                       f"<td class='{'neg' if r['z'] < -1.5 else 'pos' if r['z'] > 1.5 else ''}'>{r['z']:+.1f}σ</td></tr>" for r in ins["cats"] if r["n"] >= 2)
        G["luck"] = ("<div class='card'><h3>🍀 Μετρητής τύχης</h3><p class='muted'>Πόσες νίκες έχουμε σε σχέση με όσες περίμενε το μοντέλο, για Προτεινόμενο · Safe · Over (όλα τα επίπεδα). "
                     "Η γραμμή μέσα στις διακεκομμένες = κανονική διακύμανση· εκτός ±2σ = αξίζει έλεγχο.</p>"
                     f"<p><b>{core['n']}</b> δελτία · νίκες <b>{core['w']}</b> · αναμενόταν <b>{core['e']:.1f} ± {core['sd']:.1f}</b> · <b>{z:+.1f}σ</b> — {verdict}.</p>"
                     + P.chart(cfgc) + "<div class='tbl'><table><thead><tr><th>Κατηγορία</th><th>Δελτία</th><th>Νίκες</th><th>Αναμενόταν</th><th>σ</th></tr></thead><tbody>"
                     + rows + "</tbody></table></div></div>")
    # --- εξερεύνηση σκελών
    if ins["legs"]:
        sel = lambda i, w="": f"<select id='{i}' {w}></select>"
        G["legs"] = ("<div class='card'><h3>🔎 Εξερεύνηση σκελών</h3><p class='muted'>Όλα τα μοναδικά σκέλη που κρίθηκαν (ένα σκέλος που μπήκε σε πολλά δελτία μετράει μία φορά). "
                     "Φίλτραρε για να δεις πού πάμε καλά ή άσχημα — με τη διαφορά από τις αναμενόμενες νίκες.</p>"
                     "<div id='legx' style='display:grid;grid-template-columns:repeat(2,1fr);gap:6px;margin:8px 0'>"
                     + sel("lx-sp") + sel("lx-lg") + sel("lx-g") + sel("lx-c") + sel("lx-pb") + sel("lx-ob")
                     + "<select id='lx-res'><option value=''>Όλα τα αποτελέσματα</option><option value='won'>Μόνο ✅ πέρασαν</option><option value='lost'>Μόνο ❌ έχασαν</option></select>"
                     + "<select id='lx-days'><option value=''>Όλες οι ημέρες</option><option value='7'>Τελευταίες 7</option><option value='14'>Τελευταίες 14</option><option value='30'>Τελευταίες 30</option></select></div>"
                     "<div id='lx-sum' style='margin:8px 0'></div><div class='tbl'><table><thead><tr><th></th><th>Ημ.</th><th>Σκέλος</th><th>p</th><th>Απόδ.</th></tr></thead><tbody id='lx-list'></tbody></table></div>"
                     "<p class='muted'>Δείχνονται τα 40 πιο πρόσφατα με τα φίλτρα· η σύνοψη πάνω μετράει ΟΛΑ.</p>"
                     "<script type='application/json' id='legx-data'>" + json.dumps(ins["legs"], ensure_ascii=False).replace("</", "<\\/") + "</script><script>" + EXPLORER_JS + "</script></div>")
    # --- Μαθήματα: μοτίβα + αυτοψία 7 ημερών
    pt = ins.get("patterns") or {}
    if pt.get("n_legs"):
        def trs(lst, cls):
            return "".join(f"<tr><td>{E(r['f'])}: <b>{E(r['v'])}</b></td><td>{r['n']}</td><td>{r['w']}</td><td>{r['e']:.1f} ± {r['sd']:.1f}</td><td class='{cls}'>{r['z']:+.1f}σ</td></tr>" for r in lst)
        head = "<thead><tr><th>Χαρακτηριστικό</th><th>Σκέλη</th><th>Νίκες</th><th>Αναμενόταν</th><th>σ</th></tr></thead>"
        body = ""
        if pt.get("worst"):
            body += "<h4 style='margin:10px 0 4px'>Πιθανές «παγίδες» (κάτω από το αναμενόμενο)</h4><div class='tbl'><table>" + head + "<tbody>" + trs(pt["worst"], "neg") + "</tbody></table></div>"
        else:
            body += "<p>✅ Κανένα χαρακτηριστικό (αγορά, λίγκα, άθλημα, πιθανότητα, προειδοποίηση, κρίση του bot) δεν είναι σημαντικά κάτω από το αναμενόμενο.</p>"
        if pt.get("best"):
            body += "<h4 style='margin:10px 0 4px'>Δυνατά σημεία (πάνω από το αναμενόμενο)</h4><div class='tbl'><table>" + head + "<tbody>" + trs(pt["best"], "pos") + "</tbody></table></div>"
        G["lessons"] += ("<div class='card'><h3>🧠 Μοτίβα: πού χάνουμε περισσότερο από το αναμενόμενο</h3>"
                         f"<p class='muted'>Έλεγχος σε {pt['n_legs']} κριθέντα σκέλη, {pt['tested']} χαρακτηριστικά (με ≥12 σκέλη). Από τύχη μόνο, περίπου {pt['chance']:.0f} από αυτά θα βγουν "
                         "«ύποπτα» (|διαφορά| > 1,5σ). Γι' αυτό ΔΕΝ αλλάζουμε κανόνα για ένα μοτίβο μόνο του· χρειάζεται να μείνει κάτω από −2σ με 30+ σκέλη για 2 εβδομάδες. "
                         "Τότε σου προτείνω ρητά τον κανόνα και τον εφαρμόζουμε μαζί.</p>" + body + "</div>")
    if ins["kill"]:
        trs_ = "".join(f"<tr><td><b>{k['n']}</b></td><td>{E(k['lb'])}<div class='muted'>{E(k['m'])} · {k['d']} · {E(k['t'])}</div></td><td>{int(k['p'] * 100)}%</td><td class='muted'>{E(k['c'])}</td></tr>"
                       for k in ins["kill"])
        G["lessons"] += ("<div class='card'><h3>🩺 Τι έριξε τα δελτία (τελευταίες 7 ημέρες)</h3>"
                         f"<p class='muted'>{ins['lost_slips']} δελτία έχασαν. Εδώ τα σκέλη που τα έριξαν και πόσα δελτία έριξε το καθένα (αριστερά). "
                         "Αν ένα σκέλος έριξε πολλά δελτία, είχαμε υπερβολική επικάλυψη.</p><div class='tbl'><table><thead><tr><th>Δελτία</th><th>Σκέλος</th><th>p</th><th>Κατηγορίες</th></tr></thead><tbody>"
                         + trs_ + "</tbody></table></div></div>")
    # --- έκθεση σήμερα (στην καρτέλα Ημέρα)
    if ins["exposure"]:
        trs_ = "".join(f"<tr><td>{'⚠️' if x['n'] > 2 else '🔁' if len(x['c']) > 1 else ''}</td><td>{E(x['m'])}</td><td><b>{x['n']}</b></td><td class='muted'>{E(', '.join(x['c']))}</td></tr>"
                       for x in ins["exposure"])
        G["day"] += ("<div class='card'><h3>⚖️ Έκθεση σήμερα</h3><p class='muted'>Κάθε αγώνας σε πόσα δελτία της ημέρας υπάρχει. ⚠️ = πάνω από 2 δελτία, 🔁 = σε περισσότερες από μία κατηγορίες "
                     "(επιτρέπεται μόνο όταν δεν υπήρχαν άλλοι αγώνες).</p><div class='tbl'><table><thead><tr><th></th><th>Αγώνας</th><th>Δελτία</th><th>Κατηγορίες</th></tr></thead><tbody>"
                     + trs_ + "</tbody></table></div></div>")
    return G
