import sys,pickle; sys.path.insert(0,'..')
from common import wayback_sets
from ident import *
import pandas as pd
EV,IV=pickle.load(open('final.pkl','rb'))
def members(d):
    d=pd.Timestamp(d); x=IV[(IV.start<=d)&((IV.end.isna())|(IV.end>d))]; return set(x.symbol)
def cmp(d,truth,label):
    mine=members(d); t,m=bmap(d)
    def iso(S): return {m.get(s,'SYM:'+s) for s in S}
    a=set(truth)-mine; b=mine-set(truth)
    # tolerate pure symbol-name timing (same ISIN)
    ia={m.get(s) for s in a}; ib={m.get(s) for s in b}
    a2=sorted(s for s in a if m.get(s) is None or m.get(s) not in ib); b2=sorted(s for s in b if m.get(s) is None or m.get(s) not in ia)
    return dict(source=label,date=d.date(),nse=len(truth),rebuilt=len(mine),sym_diff=len(a)+len(b),only_nse=' '.join(a2),only_rebuilt=' '.join(b2),renamed_same_isin=' '.join(sorted(a-set(a2))))
M=pd.read_parquet('monthly_parsed.parquet'); R=pd.read_csv('monthly_report.csv')
out=[]
for r in R.itertuples():
    out.append(cmp(pd.to_datetime(r.asof,dayfirst=True),set(M[M.month==r.tag].symbol),'NSE monthly file '+r.tag))
for d,c in wayback_sets().items():
    if d<pd.Timestamp('2013-04-18'): continue
    out.append(cmp(d,set(c.Symbol.str.strip()),'NSE CSV (archive.org)' if d.year<2026 or d.month<10 or d.day!=21 else 'NSE CSV live today'))
V=pd.DataFrame(out).sort_values('date'); V.to_csv('validation.csv',index=False)
pd.set_option('display.width',250); pd.set_option('display.max_colwidth',80); pd.set_option('display.max_rows',300)
bad=V[(V.only_nse!='')|(V.only_rebuilt!='')]
print('checks',len(V),'exact (by ISIN)',len(V)-len(bad),'mismatching',len(bad))
print(bad[['source','date','nse','rebuilt','only_nse','only_rebuilt']].to_string())
