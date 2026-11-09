"""Έρευνα: Over/Under 2.5 (βαθμονόμηση, ROI) και προσομοίωση «πράσινων» ημερών/εβδομάδων.
Πρώτα τρέξε tools/signals.py (φτιάχνει την cache). python tools/ou_sim.py > docs/signals_ou.txt"""
import sys,csv,io,os,math,pickle,numpy as np
sys.path.insert(0,os.path.join(os.path.dirname(os.path.abspath(__file__)),'..'))
import yaml
from datetime import datetime, timezone
from betbot.collectors.fdco_history import URL,_date,_i,season_codes
from betbot.util import http_get
cfg=yaml.safe_load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','config.yaml'),encoding='utf-8')); now=datetime.now(timezone.utc)
def f(r,k):
    try:
        v=float(r.get(k) or ''); return v if v>1 else None
    except ValueError: return None
cache='/tmp/betbot_ou_rows.pkl'
if os.path.exists(cache): rows=pickle.load(open(cache,'rb'))
else:
    rows=[]
    for lg in cfg['leagues']:
        if not lg.get('fdco') or lg['sport']!='football': continue
        for s in season_codes(now,3):
            try: text,_=http_get(URL.format(season=s,div=lg['fdco']),expect='text')
            except Exception: continue
            for r in csv.DictReader(io.StringIO(text.lstrip('﻿'))):
                ko=_date(r); hg,ag=_i(r.get('FTHG')),_i(r.get('FTAG'))
                if ko is None or hg is None or ag is None: continue
                av=[f(r,'AvgC>2.5'),f(r,'AvgC<2.5')]; mx=[f(r,'MaxC>2.5'),f(r,'MaxC<2.5')]
                if not all(av): continue
                rows.append(dict(lg=lg['id'],ko=ko,tot=hg+ag,av=av,mx=mx if all(mx) else None,
                    ca=_i(r.get('HC')) is not None and (_i(r.get('HC'))+_i(r.get('AC') or 0)),
                    cards=(_i(r.get('HY')) or 0)+(_i(r.get('AY')) or 0)))
    pickle.dump(rows,open(cache,'wb'))
print(len(rows),'matches with O/U 2.5 closing prices')
def prop(o):
    i=[1/x for x in o]; t=sum(i); return [x/t for x in i]
print('\nO/U 2.5 calibration (average closing, proportional devig): side, bucket, n, predicted, actual, ROI@avg, ROI@max')
for side,idx in (('OVER',0),('UNDER',1)):
    for lo,hi in ((0,.4),(.4,.5),(.5,.55),(.55,.6),(.6,.7),(.7,1.01)):
        xs=[]
        for r in rows:
            p=prop(r['av'])[idx]
            if lo<=p<hi:
                win=int(r['tot']>2.5) if idx==0 else int(r['tot']<=2.5)
                xs.append((p,win,r['av'][idx],(r['mx'][idx] if r['mx'] else None)))
        if len(xs)<100: continue
        ra=[(x[2] if x[1] else 0)-1 for x in xs]; rm=[(x[3] if x[1] else 0)-1 for x in xs if x[3]]
        print(f'{side:5s} {lo:.2f}-{hi:.2f} {len(xs):6d}  {np.mean([x[0] for x in xs]):.3f}  {np.mean([x[1] for x in xs]):.3f}  {np.mean(ra):+.1%}  {np.mean(rm):+.1%}')
# Simulation of green days/weeks using 1X2 favourites picks (2-leg slips)
rows1=pickle.load(open('/tmp/betbot_sig_rows.pkl','rb'))
def prop3(o):
    i=[1/x for x in o]; t=sum(i); return [x/t for x in i]
def out(r): return 0 if r['hg']>r['ag'] else 1 if r['hg']==r['ag'] else 2
pool={}
for r in rows1:
    if not r['avc'] or not r['mx']: continue
    p=prop3(r['avc'])
    for i in range(3):
        if p[i]>=.70: pool.setdefault('hi',[]).append((r['avc'][i],r['mx'][i],int(out(r)==i)))
        if .60<=p[i]<.70: pool.setdefault('mid',[]).append((r['avc'][i],r['mx'][i],int(out(r)==i)))
rng=np.random.default_rng(5)
def sim(name,legs,price_idx,nlegs=2,stake=2.0,weeks=20000,days=7):
    legs=np.array(legs,dtype=float); res=[]; daily=[]
    for _ in range(weeks):
        pl=0.0
        for d in range(days):
            idx=rng.integers(0,len(legs),nlegs); o=np.prod(legs[idx,price_idx]); w=np.all(legs[idx,2]==1)
            g=stake*(o-1) if w else -stake; pl+=g; daily.append(g>0)
        res.append(pl)
    res=np.array(res)
    print(f'{name:34s} green days {np.mean(daily):.0%} | green weeks {np.mean(res>0):.0%} | mean week {res.mean():+.2f}€ | worst 5% week {np.percentile(res,5):+.1f}€ | 4-week green {np.mean([sum(rng.choice(res,4))>0 for _ in range(4000)]):.0%}')
print('\nΠροσομοίωση: 1 δελτίο/ημέρα × 7 ημέρες, 2€ ανά δελτίο, επιλογές από ιστορικά φαβορί')
sim('2 σκέλη, p≥70%, μέση τιμή',pool['hi'],0)
sim('2 σκέλη, p≥70%, καλύτερη τιμή',pool['hi'],1)
sim('2 σκέλη, p 60-70%, μέση τιμή',pool['mid'],0)
sim('1 σκέλος (μονό), p≥70%, μέση τιμή',pool['hi'],0,nlegs=1)
sim('3 σκέλη, p≥70%, μέση τιμή',pool['hi'],0,nlegs=3)
