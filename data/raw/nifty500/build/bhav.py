import urllib.request as u, pandas as pd, io, zipfile, os, time
H={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36','Referer':'https://www.nseindia.com/'}
def fetch(d):
    """Return DataFrame SYMBOL,SERIES,ISIN for trading date d, or None if holiday."""
    d=pd.Timestamp(d); fn=f'bhav/{d:%Y%m%d}.csv'
    if os.path.exists(fn):
        x=pd.read_csv(fn); return x if len(x) else None
    urls=[]
    if d>=pd.Timestamp('2024-07-08'): urls=[f'https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip']
    else: urls=[f'https://nsearchives.nseindia.com/content/historical/EQUITIES/{d:%Y}/{d:%b}'.upper().replace('HTTPS://NSEARCHIVES.NSEINDIA.COM/CONTENT/HISTORICAL/EQUITIES','https://nsearchives.nseindia.com/content/historical/EQUITIES')+f'/cm{d:%d}{d:%b}'.upper()[:0]+f'/cm{d:%d}{d.strftime("%b").upper()}{d:%Y}bhav.csv.zip']
    for url in urls:
        for k in range(3):
            try:
                b=u.urlopen(u.Request(url,headers=H),timeout=60).read()
                z=zipfile.ZipFile(io.BytesIO(b)); x=pd.read_csv(z.open(z.namelist()[0]))
                x.columns=[c.strip() for c in x.columns]
                if 'TckrSymb' in x.columns: x=x.rename(columns={'TckrSymb':'SYMBOL','SctySrs':'SERIES','ISIN':'ISIN'})
                x=x[['SYMBOL','SERIES','ISIN']]; x.to_csv(fn,index=False); return x
            except Exception as e:
                if '404' in str(e): break
                time.sleep(2)
    pd.DataFrame(columns=['SYMBOL','SERIES','ISIN']).to_csv(fn,index=False); return None
def last_trading(d,back=7):
    d=pd.Timestamp(d)
    for i in range(back):
        x=fetch(d-pd.Timedelta(days=i))
        if x is not None: return d-pd.Timedelta(days=i), x
    return None,None
