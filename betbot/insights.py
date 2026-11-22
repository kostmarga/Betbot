"""Ανάλυση «τι συμβαίνει»: μετρητής τύχης, εξερεύνηση σκελών με φίλτρα, αυτοψία χαμένων, έκθεση σήμερα (22/11/2026).
Όλα βγαίνουν από τα αποθηκευμένα δελτία/σκέλη· δεν αγγίζουν επιλογές ή πιθανότητες."""
from __future__ import annotations

import html
import json
import math
from collections import defaultdict
from zoneinfo import ZoneInfo

from .paper import CAT_NAME, drop_tier_dups, split_list_name
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
            "kill": kill_out, "lost_slips": lost_slips, "exposure": exp_out}


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


def render(P, ins) -> str:
    """HTML κάρτες: μετρητής τύχης, εξερεύνηση σκελών, αυτοψία χαμένων, έκθεση σήμερα."""
    if not ins:
        return ""
    out = []
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
        out.append("<div class='card'><h3>🍀 Μετρητής τύχης</h3><p class='muted'>Πόσες νίκες έχουμε σε σχέση με όσες περίμενε το μοντέλο, για Προτεινόμενο · Safe · Over (όλα τα επίπεδα). "
                   "Η γραμμή μέσα στις διακεκομμένες = κανονική διακύμανση· εκτός ±2σ = αξίζει έλεγχο.</p>"
                   f"<p><b>{core['n']}</b> δελτία · νίκες <b>{core['w']}</b> · αναμενόταν <b>{core['e']:.1f} ± {core['sd']:.1f}</b> · <b>{z:+.1f}σ</b> — {verdict}.</p>"
                   + P.chart(cfgc) + "<div class='tbl'><table><thead><tr><th>Κατηγορία</th><th>Δελτία</th><th>Νίκες</th><th>Αναμενόταν</th><th>Διαφορά</th></tr></thead><tbody>"
                   + rows + "</tbody></table></div></div>")
    # --- εξερεύνηση σκελών
    if ins["legs"]:
        sel = lambda i, w="": f"<select id='{i}' {w}></select>"
        out.append("<div class='card'><h3>🔎 Εξερεύνηση σκελών</h3><p class='muted'>Όλα τα μοναδικά σκέλη που κρίθηκαν (ένα σκέλος που μπήκε σε πολλά δελτία μετράει μία φορά). "
                   "Φίλτραρε για να δεις πού πάμε καλά ή άσχημα — με τη διαφορά από τις αναμενόμενες νίκες.</p>"
                   "<div id='legx' style='display:grid;grid-template-columns:repeat(2,1fr);gap:6px;margin:8px 0'>"
                   + sel("lx-sp") + sel("lx-lg") + sel("lx-g") + sel("lx-c") + sel("lx-pb") + sel("lx-ob")
                   + "<select id='lx-res'><option value=''>Όλα τα αποτελέσματα</option><option value='won'>Μόνο ✅ πέρασαν</option><option value='lost'>Μόνο ❌ έχασαν</option></select>"
                   + "<select id='lx-days'><option value=''>Όλες οι ημέρες</option><option value='7'>Τελευταίες 7</option><option value='14'>Τελευταίες 14</option><option value='30'>Τελευταίες 30</option></select></div>"
                   "<div id='lx-sum' style='margin:8px 0'></div><div class='tbl'><table><thead><tr><th></th><th>Ημ.</th><th>Σκέλος</th><th>p</th><th>Απόδ.</th></tr></thead><tbody id='lx-list'></tbody></table></div><p class='muted'>Δείχνονται τα 40 πιο πρόσφατα με τα φίλτρα· η σύνοψη πάνω μετράει ΟΛΑ.</p>"
                   "<script type='application/json' id='legx-data'>" + json.dumps(ins["legs"], ensure_ascii=False).replace("</", "<\\/") + "</script><script>" + EXPLORER_JS + "</script></div>")
    # --- αυτοψία χαμένων
    if ins["kill"]:
        trs = "".join(f"<tr><td><b>{k['n']}</b></td><td>{E(k['lb'])}<div class='muted'>{E(k['m'])} · {k['d']} · {E(k['t'])}</div></td><td>{int(k['p'] * 100)}%</td><td class='muted'>{E(k['c'])}</td></tr>"
                      for k in ins["kill"])
        out.append("<div class='card'><h3>🩺 Αυτοψία: τι έριξε τα δελτία (τελευταίες 7 ημέρες)</h3>"
                   f"<p class='muted'>{ins['lost_slips']} δελτία έχασαν. Εδώ τα σκέλη που τα έριξαν και πόσα δελτία έριξε το καθένα (αριστερά). "
                   "Αν ένα σκέλος έριξε πολλά δελτία, είχαμε υπερβολική επικάλυψη.</p><div class='tbl'><table><thead><tr><th>Δελτία</th><th>Σκέλος</th><th>p</th><th>Κατηγορίες</th></tr></thead><tbody>"
                   + trs + "</tbody></table></div></div>")
    # --- έκθεση σήμερα
    if ins["exposure"]:
        trs = "".join(f"<tr><td>{'⚠️' if x['n'] > 2 else '🔁' if len(x['c']) > 1 else ''}</td><td>{E(x['m'])}</td><td><b>{x['n']}</b></td><td class='muted'>{E(', '.join(x['c']))}</td></tr>"
                      for x in ins["exposure"])
        out.append("<div class='card'><h3>⚖️ Έκθεση σήμερα</h3><p class='muted'>Κάθε αγώνας σε πόσα δελτία της ημέρας υπάρχει. ⚠️ = πάνω από 2 δελτία, 🔁 = σε περισσότερες από μία κατηγορίες "
                   "(επιτρέπεται μόνο όταν δεν υπήρχαν άλλοι αγώνες).</p><div class='tbl'><table><thead><tr><th></th><th>Αγώνας</th><th>Δελτία</th><th>Κατηγορίες</th></tr></thead><tbody>"
                   + trs + "</tbody></table></div></div>")
    return "".join(out)
