import sys,os,re,difflib,pickle; sys.path.insert(0,'..')
from common import DEMERGERS, MANUAL, wayback_sets
from ident import *
import pandas as pd
pd.set_option('display.width',250); pd.set_option('display.max_rows',500); pd.set_option('display.max_colwidth',60)
M=pd.read_parquet('monthly_parsed.parquet'); R=pd.read_csv('monthly_report.csv')
R['asof_d']=[pd.to_datetime(a,dayfirst=True) for a in R['asof']]
snap={r.asof_d:sorted(M[M.month==r.tag].symbol) for r in R.itertuples()}
names={}
for r in M.itertuples(): names.setdefault(r.symbol,r.name_ind)
X=pd.read_csv('inclexcl_n500.csv',parse_dates=['date'])
P=pd.read_csv('press_events.csv'); P=P[P.kind=='review/replacement'].copy(); P['eff']=pd.to_datetime(P.eff)
def norm(s):
    s=s.lower().replace('&',' and ')
    s=re.sub(r'\|.*','',s)
    s=re.sub(r'\b(ltd|limited|the|co|company|corporation|corpn|india|of|and)\b','',s)
    return re.sub(r'[^a-z0-9]','',s)
# ---------- Period A: month-end snapshots ----------
dates=sorted(snap)
events=[]; unmatched=[]
for p,c in zip(dates[:-1],dates[1:]):
    Sp=set(snap[p]); Sc=set(snap[c])
    # roll prev symbols to current date for renames
    roll={s:roll_symbol(s,p,c) for s in Sp}
    Sp_r={roll[s] for s in Sp}
    # ISIN-level identity for safety
    ins=sorted(Sc-Sp_r); outs=sorted(s for s in Sp if roll[s] not in Sc)
    # ISIN check: a symbol pair that maps to same ISIN is a rename not in symbolchange
    ip={isin_of(s,p):s for s in outs}; ic={isin_of(s,c):s for s in ins}
    same=[k for k in ip if k and k in ic]
    for k in same: events.append(dict(date=c,action='RENAME',symbol=ic[k],old=ip[k],src='isin-match')); 
    outs=[s for s in outs if isin_of(s,p) not in same or isin_of(s,p) is None]; ins=[s for s in ins if isin_of(s,c) not in same or isin_of(s,c) is None]
    winX=X[(X.date>p)&(X.date<=c)]; winP=P[(P.eff>p)&(P.eff<=c)]
    for act,lst,desc in [('IN',ins,'Inclusion'),('OUT',outs,'Exclusion')]:
        for s in lst:
            d=None; src=None
            hp=winP[(winP.symbol==s)&(winP.action==act)]
            if len(hp): d=hp.eff.iloc[0]; src=hp.release.iloc[0]
            else:
                cand=winX[winX.desc.str.startswith(desc)]
                nm=norm(names.get(s,s))
                best=None;bs=0
                for r in cand.itertuples():
                    sc=difflib.SequenceMatcher(None,nm,norm(r.name)).ratio()
                    if nm and (nm in norm(r.name) or norm(r.name) in nm): sc=max(sc,0.95)
                    if sc>bs: bs=sc;best=r
                if best is not None and bs>=0.8: d=best.date; src=f'IndexInclExcl.xls: {best.name}'
            if d is None: unmatched.append((p.date(),c.date(),act,s,names.get(s)))
            events.append(dict(date=d if d is not None else c,action=act,symbol=s,src=src or 'UNDATED: month-end diff',window=f'{p.date()}..{c.date()}'))
EA=pd.DataFrame(events)
print('Period A events',len(EA), EA.action.value_counts().to_dict()); print('undated:',len(unmatched))
for u in unmatched: print('  ',u)
EA.to_csv('events_A.csv',index=False)
