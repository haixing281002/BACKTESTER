import sys,pickle,re,os; sys.path.insert(0,'..')
from common import wayback_sets, DEMERGERS
from ident import *
import pandas as pd
OUT=sys.argv[1]; os.makedirs(OUT,exist_ok=True)
EV,IV=pickle.load(open('final.pkl','rb'))
TODAY=pd.Timestamp('2026-10-21')
# ---- names / industry by ISIN and by symbol ----
name_isin={}; ind_isin={}
for d,c in sorted(wayback_sets().items()):
    for r in c.itertuples(): name_isin[r[5]]=r[1]; ind_isin[r[5]]=r[2]
P=pd.read_csv('press_events.csv'); name_sym={r.symbol:re.sub(r'[\*#]+$','',r.name).strip() for r in P.itertuples()}
M=pd.read_parquet('monthly_parsed.parquet')
apr=pd.read_csv('monthly/Apr2013.pdf'); name_sym.update({r.Symbol.strip():r._4 for r in apr.itertuples()}) if False else None
for r in M.itertuples():
    if r.symbol in name_sym: continue
    n=r.name_ind.split(' | ')[0] if ' | ' in r.name_ind else re.sub(r'(\s+[A-Z][A-Z0-9&/\-,\.\(\)]*)+$','',r.name_ind)
    name_sym[r.symbol]=n.strip()
DUMISIN={}
for d,c in wayback_sets().items():
    for r in c[c.Symbol.str.startswith('DUMMY')].itertuples(): DUMISIN[r.Symbol]=(r[5],r[1])
def isin_at(sym,d):
    if sym.startswith('DUMMY'): return DUMISIN.get(sym,('',''))[0]
    for k in (0,1,3,7):
        i=isin_of(sym,pd.Timestamp(d)+pd.Timedelta(days=k)) if k else isin_of(sym,d)
        if i: return i
    return isin_of(sym,pd.Timestamp(d)-pd.Timedelta(days=1)) or ''
rows=[]
for r in IV.itertuples():
    end_ref=(r.end-pd.Timedelta(days=1)) if pd.notna(r.end) else TODAY
    i0=isin_at(r.symbol,r.start); i1=isin_of(r.symbol,end_ref) or i0
    if r.symbol.startswith('DUMMY'): nm=DUMISIN.get(r.symbol,('', 'Placeholder for demerged entity'))[1]
    else: nm=name_isin.get(i1) or name_isin.get(i0) or name_sym.get(r.symbol,'')
    t,_=bmap(end_ref) if pd.notna(r.end) else (None,None)
    rows.append(dict(symbol=r.symbol,isin=i1,isin_at_start=i0 if i0!=i1 else '',company_name=nm,industry=ind_isin.get(i1,ind_isin.get(i0,'')),
                     start_date=r.start.date(),end_date=r.end.date() if pd.notna(r.end) else '',
                     last_day_in_index=t.date() if t is not None else '',entry_type=r.kind,end_reason=r.end_reason))
MB=pd.DataFrame(rows)
# start reason from events
src=EV[EV.action.isin(['IN','SWAP'])].set_index(['symbol','date']).source.to_dict()
MB['start_source']=[src.get((s,pd.Timestamp(d)),'in NIFTY 500 on 2013-04-18 (first NSE file)' if str(d)=='2013-04-18' else 'renamed (same company)') for s,d in zip(MB.symbol,MB.start_date)]
MB=MB[['symbol','isin','company_name','industry','start_date','end_date','last_day_in_index','entry_type','start_source','end_reason','isin_at_start']]
MB.sort_values(['start_date','symbol']).to_csv(f'{OUT}/nifty500_membership.csv',index=False)
# ---- change log ----
ch=[]
for r in EV.itertuples():
    if r.action not in ('IN','OUT','SWAP'): continue
    d=r.date; s=r.symbol
    if r.action=='SWAP':
        ch.append(dict(effective_date=d.date(),action='OUT',symbol=r.old,isin=DUMISIN.get(r.old,('',''))[0],source=r.source,entry_type='demerger_placeholder'))
        ch.append(dict(effective_date=d.date(),action='IN',symbol=s,isin=isin_at(s,d),source=r.source,entry_type=r.kind)); continue
    ch.append(dict(effective_date=d.date(),action=r.action,symbol=s,isin=isin_at(s,d if r.action=='IN' else d-pd.Timedelta(days=1)),source=r.source,entry_type=r.kind))
for r in IV.itertuples():
    if isinstance(r.end_reason,str) and r.end_reason.startswith('renamed to'):
        new=r.end_reason.split()[2]
        ch.append(dict(effective_date=r.end.date(),action='RENAME',symbol=new,isin=isin_at(new,r.end),source=f'{r.symbol} -> {new}: '+('NSE symbolchange.csv' if 'ISIN' not in r.end_reason else 'same ISIN in bhavcopy'),entry_type=r.kind))
CH=pd.DataFrame(ch)
nm=dict(zip(MB.symbol,MB.company_name)); CH['company_name']=CH.symbol.map(nm).fillna('')
CH=CH[['effective_date','action','symbol','isin','company_name','entry_type','source']].sort_values(['effective_date','action','symbol'])
CH.to_csv(f'{OUT}/nifty500_changes.csv',index=False)
# ---- month-end snapshots ----
me=[]
dates=sorted(set(pd.date_range('2013-04-30','2026-09-30',freq='ME'))|{TODAY})
for d in dates:
    t,m=bmap(d); t=t or d
    x=MB[(pd.to_datetime(MB.start_date)<=t)&((MB.end_date=='')|(pd.to_datetime(MB.end_date.replace('',None))>t))]
    for r in x.itertuples(): me.append(dict(date=t.date(),symbol=r.symbol,isin=m.get(r.symbol,r.isin) if not r.symbol.startswith('DUMMY') else r.isin,company_name=r.company_name,entry_type=r.entry_type))
ME=pd.DataFrame(me); ME.to_csv(f'{OUT}/nifty500_month_end.csv',index=False)
print(MB.shape, CH.shape, ME.shape); print(ME.groupby('date').size().describe())
print('blank isin', (MB.isin=='').sum(), MB[MB.isin==''].symbol.tolist()[:20]); print('blank name',(MB.company_name=='').sum(), MB[MB.company_name==''].symbol.tolist()[:20])
