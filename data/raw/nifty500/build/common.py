import pandas as pd, glob, os, sys
sys.path.insert(0,os.path.dirname(__file__)); from bhav import fetch, last_trading
BD='.'
def bhav_on_or_before(d):
    t,x=last_trading(pd.Timestamp(d)); return t,x
_cache={}
def sym2isin(sym,d,back=10):
    """ISIN for symbol as traded on the last trading day on/before d (EQ/BE/BZ/RR series)."""
    d=pd.Timestamp(d)
    for i in range(back):
        dd=d-pd.Timedelta(days=i)
        if dd not in _cache:
            _cache[dd]=fetch(dd)
        x=_cache[dd]
        if x is None: continue
        m=x[(x.SYMBOL==sym)&(x.SERIES.isin(['EQ','BE','BZ','RR','ST','SM']))]
        if len(m): return m.ISIN.iloc[0]
        m=x[x.SYMBOL==sym]
        if len(m): return m.ISIN.iloc[0]
    return None
def wayback_sets():
    out={}
    for f in sorted(glob.glob('wayback/*.csv')):
        c=pd.read_csv(f); c.columns=[x.strip() for x in c.columns]
        tag=os.path.basename(f)[:-4]; d=pd.Timestamp(tag.replace('LIVE_','')[:8])
        out[d]=c
    return out
# demergers since 2022: (dummy, listed_symbol, dummy_in_eff, listed_on, out_eff, parent)
DEMERGERS=[
 (None,'JIOFIN','2023-07-20','2023-08-21','2023-09-07','RELIANCE'),
 ('DUMMYSANOF','SANOFICONR','2024-06-13','2024-09-13','2024-09-23','SANOFI'),
 ('DUMMYRAYMD','RAYMONDLSL','2024-07-11','2024-09-05','2024-09-17','RAYMOND'),
 ('DUMMYITC','ITCHOTELS','2025-01-06','2025-01-29','2025-02-10','ITC'),
 ('DUMMYSIEMS','ENRIN','2025-04-07','2025-06-19','2025-06-27','SIEMENS'),
 ('DUMMYRAYMN','RAYMONDREL','2025-05-14','2025-07-01','2025-07-10','RAYMOND'),
 ('DUMMYABFRL','ABLBL','2025-05-22','2025-06-23','2025-06-27','ABFRL'),
 ('DUMMYDBRLT','ADVENTHTL','2025-07-18','2025-11-13','2025-11-28','DBREALTY'),
 ('DUMMYTATAM','TMCV','2025-10-14','2025-11-12','2025-11-17','TATAMOTORS'),
 ('DUMMYSKFIN','SKFINDUS','2025-10-15','2025-12-05','2025-12-15','SKFINDIA'),
 ('DUMMYHDLVR','KWIL','2025-12-05','2026-02-16','2026-02-24','HINDUNILVR'),
 ('DUMMYVEDL1','VAML','2026-04-30','2026-06-15','2026-06-23','VEDL'),
 ('DUMMYVEDL2','VEDPOWER','2026-04-30','2026-06-15','2026-06-19','VEDL'),
 ('DUMMYVEDL3','VOGL','2026-04-30','2026-06-15','2026-06-24','VEDL'),
 ('DUMMYVEDL4','VISL','2026-04-30','2026-06-15','2026-06-19','VEDL'),
 ('DUMMYHEG',None,'2026-09-07',None,None,'HEG'),
]
# manual corrections to parsed review tables (revocations)
MANUAL=[ # (eff, action, symbol, note)
 ('2024-03-28','CANCEL_IN','IREDA','inclusion revoked: ind_prs19032024'),
 ('2024-03-28','CANCEL_OUT','VGUARD','exclusion revoked: ind_prs19032024'),
 ('2024-08-30','OUT','TATAMTRDVR','DVR shares cancelled: ind_prs23082024_1'),
 ('2024-09-30','CANCEL_OUT','IDEA','exclusion revoked: ind_prs25092024'),
 ('2024-09-30','OUT','PRSMJOHNSN','excluded instead of IDEA: ind_prs25092024'),
]
