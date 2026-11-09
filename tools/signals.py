"""Έρευνα σημάτων (python tools/signals.py > docs/signals.txt): βαθμονόμηση πιθανοτήτων αγοράς, devig, κίνηση τιμής, ανά λίγκα.
Χρησιμοποιεί τα CSV του football-data.co.uk (κλείσιμο Pinnacle), 3 σεζόν, κύριες λίγκες."""
import sys, csv, io, math, pickle, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import yaml, numpy as np
from datetime import datetime, timezone
from betbot.collectors.fdco_history import URL, _date, _i, season_codes
from betbot.util import http_get
cfg=yaml.safe_load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','config.yaml'),encoding='utf-8'))
now=datetime.now(timezone.utc)
cache=os.path.join('/tmp','betbot_sig_rows.pkl')
def f(r,k):
    try:
        v=float(r.get(k) or ''); return v if v>1 else None
    except ValueError: return None
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
                op=[f(r,c) for c in ('PSH','PSD','PSA')]; cl=[f(r,c) for c in ('PSCH','PSCD','PSCA')]
                avc=[f(r,c) for c in ('AvgCH','AvgCD','AvgCA')]; mx=[f(r,c) for c in ('MaxCH','MaxCD','MaxCA')]
                b3=[f(r,c) for c in ('B365H','B365D','B365A')]
                if not all(cl): continue
                rows.append(dict(lg=lg['id'],ko=ko,hg=hg,ag=ag,op=op if all(op) else None,cl=cl,avc=avc if all(avc) else None,mx=mx if all(mx) else None,b3=b3 if all(b3) else None))
    pickle.dump(rows,open(cache,'wb'))
print(len(rows),'matches')
def prop(o):
    i=[1/x for x in o]; t=sum(i); return [x/t for x in i]
def shin(o,it=100):
    inv=[1/x for x in o]; B=sum(inv); n=len(o); z=0.0
    for _ in range(it):
        p=[(math.sqrt(z*z+4*(1-z)*(x*x)/B)-z)/(2*(1-z)) for x in inv]
        z_new=(sum(p)-1)*0+ (B-1)/ (1 - 1/1) if False else z
        break
    # simple: power method
    lo,hi=0.5,3.0
    for _ in range(60):
        k=(lo+hi)/2
        s=sum(x**k for x in inv)
        if s>1: lo=k
        else: hi=k
    p=[x**k for x in inv]; t=sum(p); return [x/t for x in p]
def ll(p): return -math.log(max(p,1e-9))
def out(r): return 0 if r['hg']>r['ag'] else 1 if r['hg']==r['ag'] else 2
# A) devig method log-loss (closing Pinnacle)
for name,fn in (('proportional',prop),('power',shin)):
    print('devig',name, round(np.mean([ll(fn(r['cl'])[out(r)]) for r in rows]),5))
# B) calibration of closing Pinnacle proportional by bucket
bk=[(0,.3),(.3,.4),(.4,.5),(.5,.6),(.6,.7),(.7,.8),(.8,1.01)]
print('\nBucket  n  predicted  actual   ROI@PSC  ROI@max')
for lo,hi in bk:
    xs=[]
    for r in rows:
        p=prop(r['cl'])
        for i in range(3):
            if lo<=p[i]<hi: xs.append((p[i],int(out(r)==i),r['cl'][i],(r['mx'][i] if r['mx'] else None)))
    if not xs: continue
    pr=np.mean([x[0] for x in xs]); ac=np.mean([x[1] for x in xs])
    roi=np.mean([(x[2] if x[1] else 0)-1 for x in xs]); mxs=[(x[3] if x[1] else 0)-1 for x in xs if x[3]]
    print(f'{lo:.1f}-{hi:.1f} {len(xs):6d}  {pr:.3f}  {ac:.3f}  {roi:+.1%}  {np.mean(mxs):+.1%}')
# C) movement: pick favourites p_open in [.6,.85]; split by closing prob up/down vs opening
print('\nMovement test (Pinnacle open -> close), picks with open prob 0.6-0.85, bet at OPEN price')
res={'up':[], 'down':[], 'flat':[]}
for r in rows:
    if not r['op']: continue
    po,pc=prop(r['op']),prop(r['cl'])
    for i in range(3):
        if .6<=po[i]<.85:
            d=pc[i]-po[i]; k='up' if d>0.01 else 'down' if d<-0.01 else 'flat'
            res[k].append((int(out(r)==i), r['op'][i], po[i]))
for k,v in res.items():
    if v:
        pr=[(x[1] if x[0] else 0)-1 for x in v]; m=np.mean(pr)
        rng=np.random.default_rng(1); b=[np.mean(rng.choice(pr,len(pr))) for _ in range(500)]
        print(k,len(v),'actual',f'{np.mean([x[0] for x in v]):.3f}','implied',f'{np.mean([x[2] for x in v]):.3f}','ROI@open',f'{m:+.1%}',f'[{np.percentile(b,2.5):+.1%},{np.percentile(b,97.5):+.1%}]')
# D) league-level calibration for favourites p>=.65
print('\nPer league (closing Pinnacle, picks p>=0.65): n, predicted, actual')
byl={}
for r in rows:
    p=prop(r['cl'])
    for i in range(3):
        if p[i]>=.65: byl.setdefault(r['lg'],[]).append((p[i],int(out(r)==i)))
for l,v in sorted(byl.items(), key=lambda kv:-len(kv[1])):
    if len(v)>=60: print(l,len(v),f'{np.mean([x[0] for x in v]):.3f}',f'{np.mean([x[1] for x in v]):.3f}')
