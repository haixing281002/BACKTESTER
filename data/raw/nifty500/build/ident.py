import pandas as pd, os, sys
sys.path.insert(0,os.path.dirname(__file__)); from bhav import fetch
SC=pd.read_csv(os.path.join(os.path.dirname(__file__),'nse','symbolchange.csv'),encoding='latin1'); SC.columns=[c.strip() for c in SC.columns]
SC['old']=SC['OLD SYMBOL'].str.strip(); SC['new']=SC['NEW SYMBOL'].str.strip()
SC['d']=pd.to_datetime(SC['EFFECTIVE DATE'].str.strip(),format='%d-%b-%Y',errors='coerce'); SC=SC.sort_values('d')
_bd={}
def bmap(d,back=10):
    """(trading_date, {symbol: isin}) for last trading day on/before d"""
    d=pd.Timestamp(d).normalize()
    for i in range(back):
        dd=d-pd.Timedelta(days=i)
        if dd not in _bd:
            x=fetch(dd)
            if x is None: _bd[dd]=None
            else:
                x=x.copy(); x['pri']=(~x.SERIES.isin(['EQ','BE','BZ','RR'])).astype(int)
                x=x.sort_values('pri').drop_duplicates('SYMBOL'); _bd[dd]=dict(zip(x.SYMBOL,x.ISIN))
        if _bd[dd] is not None: return dd,_bd[dd]
    return None,{}
def roll_symbol(sym,since,until):
    """follow NSE symbol changes with since < date <= until"""
    s=sym
    for r in SC[(SC.d>pd.Timestamp(since))&(SC.d<=pd.Timestamp(until))].itertuples():
        if r.old==s: s=r.new
    return s
def isin_of(sym,d):
    t,m=bmap(d); return m.get(sym)
