import sys,os,pickle; sys.path.insert(0,'..')
from common import DEMERGERS, MANUAL, wayback_sets
from ident import *
import pandas as pd
pd.set_option('display.width',250); pd.set_option('display.max_rows',800); pd.set_option('display.max_colwidth',200)
M=pd.read_parquet('monthly_parsed.parquet'); R=pd.read_csv('monthly_report.csv')
R['asof_d']=[pd.to_datetime(a,dayfirst=True) for a in R['asof']]
SNAP={r.asof_d:set(M[M.month==r.tag].symbol) for r in R.itertuples()}
START=min(SNAP); CUT=pd.Timestamp('2022-03-31')
# ---------- Period A events (dated from month-end diffs) ----------
EA=pd.read_csv('events_A.csv',parse_dates=['date'])
OVR={('FUTUREVENT','OUT','2013-05-31..2013-06-28'):('2013-06-11','IndexInclExcl.xls: Future Consumer Enterprise Ltd. (renamed)'),
     ('INEOSSTYRO','IN','2016-03-31..2016-04-29'):('2016-04-01','IndexInclExcl.xls: Styrolution ABS (India) Ltd. (renamed)'),
     ('POLARIS','IN','2016-03-31..2016-04-29'):('2016-04-01','IndexInclExcl.xls: Polaris Consulting & Services Ltd.'),
     ('POLARIS','OUT','2018-01-31..2018-02-28'):('2018-02-05','IndexInclExcl.xls: Polaris Consulting & Services Ltd.'),
     ('STAR','OUT','2018-01-31..2018-02-28'):('2018-02-05','IndexInclExcl.xls: Strides Shasun Ltd.'),
     ('STAR','IN','2018-08-31..2018-09-28'):('2018-09-28','IndexInclExcl.xls: Strides Pharma Science Ltd.'),
     ('KPIT','OUT','2018-08-31..2018-09-28'):('2018-09-28','IndexInclExcl.xls: KPIT Technologies Ltd.'),
     ('IIFL','IN','2019-08-30..2019-09-30'):('2019-09-27','IndexInclExcl.xls: IIFL Finance Ltd.')}
rows=[]
for r in EA.itertuples():
    if r.symbol in ('IBSEC','IBVENTURES') and r.window=='2015-02-28..2015-03-31': continue   # rename IBSEC->IBVENTURES (symbolchange.csv, 2015-04-01), not a membership change
    d,src=r.date,r.src
    k=(r.symbol,r.action,r.window)
    if k in OVR: d,src=OVR[k]; d=pd.Timestamp(d)
    if r.action=='RENAME': continue
    rows.append(dict(date=d,action=r.action,symbol=r.symbol,source=src,kind='regular'))
# ---------- Period B events ----------
P=pd.read_csv('press_events.csv'); P['eff']=pd.to_datetime(P.eff); P=P[P.eff>CUT]
pb=[dict(date=r.eff,action=r.action,symbol=r.symbol,source=r.release,kind='regular') for r in P.itertuples()]
for eff,act,sym,note in MANUAL:
    eff=pd.Timestamp(eff)
    if act=='CANCEL_IN': pb=[e for e in pb if not (e['date']==eff and e['action']=='IN' and e['symbol']==sym)]
    elif act=='CANCEL_OUT': pb=[e for e in pb if not (e['date']==eff and e['action']=='OUT' and e['symbol']==sym)]
    else: pb.append(dict(date=eff,action=act,symbol=sym,source=note,kind='regular'))
for dmy,lst,din,lon,out,par in DEMERGERS:
    if dmy: pb.append(dict(date=pd.Timestamp(din),action='IN',symbol=dmy,source=f'demerger of {par}: placeholder at zero price',kind='demerger_placeholder'))
    if lst:
        if dmy: pb.append(dict(date=pd.Timestamp(lon),action='SWAP',symbol=lst,old=dmy,source=f'{lst} listed; replaces placeholder {dmy}',kind='demerger_temporary'))
        else: pb.append(dict(date=pd.Timestamp(din),action='IN',symbol=lst,source=f'demerger of {par} (spun-off entity)',kind='demerger_temporary'))
        pb.append(dict(date=pd.Timestamp(out),action='OUT',symbol=lst,source=f'demerged entity excluded after listing',kind='demerger_temporary'))
import glob as _g
_chk=list(pd.date_range(START,'2026-10-31',freq='ME'))+list(SNAP)+[pd.Timestamp(os.path.basename(f).replace('LIVE_','')[:8]) for f in _g.glob('wayback/*.csv')]
rolls=[dict(date=d+pd.Timedelta(days=1),action='ROLL',symbol='',source='',kind='') for d in sorted(set(_chk)) if d>=START]
EV=pd.DataFrame(rows+pb+rolls).sort_values(['date','action'],key=lambda c: c.map({'ROLL':-1,'OUT':0,'SWAP':1,'IN':2}) if c.name=='action' else c).reset_index(drop=True)
# ---------- chain into intervals, rolling symbols through NSE renames ----------
ISIN=ISIN if "ISIN" in dir() else {}
open_={}  # symbol -> dict(start, kind, first_symbol, company_key)
iv=[]; problems=[]
cur=sorted(SNAP[START])
for s in cur: open_[s]=dict(start=START,kind='regular',src='NSE month-end file Apr2013')
_,m0=bmap(START); ISIN.update({s:m0[s] for s in cur if s in m0})
last=START
ISIN=ISIN if "ISIN" in dir() else {}
def isin_rolls(d):
    t,m=bmap(d)
    if not m: return
    inv={}
    for s,i in m.items(): inv.setdefault(i,s)
    for s in list(open_):
        if s.startswith('DUMMY'): continue
        if s in m: ISIN[s]=m[s]; continue
        i=ISIN.get(s)
        if i and i in inv and inv[i]!=s and inv[i] not in open_:
            n=inv[i]; o=open_.pop(s); iv.append(dict(symbol=s,start=o['start'],end=t,kind=o['kind'],end_reason=f'renamed to {n} (same ISIN {i}; first seen in bhavcopy {t.date()})'))
            open_[n]=dict(start=t,kind=o['kind'],src=f'renamed from {s}'); ISIN[n]=i
def roll_to(d):
    global last
    for r in SC[(SC.d>last)&(SC.d<=d)].itertuples():
        if r.old in open_ and r.old!=r.new:
            o=open_.pop(r.old); iv.append(dict(symbol=r.old,start=o['start'],end=r.d,kind=o['kind'],end_reason=f'renamed to {r.new}'))
            open_[r.new]=dict(start=r.d,kind=o['kind'],src=f'renamed from {r.old}')
    last=d
for e in EV.itertuples():
    roll_to(e.date); isin_rolls(e.date-pd.Timedelta(days=1))
    s=e.symbol
    if e.action=='ROLL': continue
    if e.action=='IN':
        if s in open_: problems.append(('already member',e.date.date(),s,e.source)); continue
        open_[s]=dict(start=e.date,kind=e.kind,src=e.source)
        i=isin_of(s,e.date) or isin_of(s,e.date-pd.Timedelta(days=1))
        if i: ISIN[s]=i
    elif e.action=='SWAP':
        o=open_.pop(e.old); iv.append(dict(symbol=e.old,start=o['start'],end=e.date,kind=o['kind'],end_reason=f'listed as {s}'))
        open_[s]=dict(start=e.date,kind=e.kind,src=e.source)
    else:
        if s not in open_:
            # maybe symbol changed before NSE's symbolchange date
            problems.append(('not member at exclusion',e.date.date(),s,e.source)); continue
        o=open_.pop(s); iv.append(dict(symbol=s,start=o['start'],end=e.date,kind=o['kind'],end_reason=e.source))
roll_to(pd.Timestamp('2026-10-21'))
for s,o in open_.items(): iv.append(dict(symbol=s,start=o['start'],end=pd.NaT,kind=o['kind'],end_reason=''))
IV=pd.DataFrame(iv).sort_values(['start','symbol']).reset_index(drop=True)
print('events',len(EV),'intervals',len(IV),'open now',IV.end.isna().sum())
print('problems:'); [print('  ',p) for p in problems]
EV=EV[EV.action!='ROLL'].reset_index(drop=True)
pickle.dump((EV,IV),open('final.pkl','wb'))
