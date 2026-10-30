import pypdf, re, glob, pandas as pd, os, io
rows=[]; rep=[]
pat=re.compile(r'^([A-Z0-9&\-\.]+)\s+(.+?)\s+(-?[\d,]+\.\d+)\s+([\d\.Ee\-]+)\s*$')
for f in sorted(glob.glob('monthly/*.pdf'), key=lambda x: pd.to_datetime(os.path.basename(x)[:-4],format='%b%Y')):
    tag=os.path.basename(f)[:-4]; raw=open(f,'rb').read()
    if not raw.startswith(b'%PDF'):
        c=pd.read_csv(io.BytesIO(raw)); asof=c['Date'].iloc[0]
        for _,x in c.iterrows(): rows.append(dict(month=tag,asof=str(asof),symbol=x['Symbol'].strip(),name_ind=f"{x['Security Name']} | {x['Industry']}",close=str(x['Close Price']),weight=float(x['Weightage(%)'])))
        rep.append((tag,asof,len(c),'csv')); continue
    txt='\n'.join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(raw)).pages)
    m=re.search(r'Constituents of [^\n]*?500\s*\n?\s*([A-Z][a-z]+ \d{1,2}, ?\d{4})',txt)
    asof=m.group(1) if m else None
    n=0
    for ln in txt.splitlines():
        mm=pat.match(ln.strip())
        if mm: rows.append(dict(month=tag,asof=asof,symbol=mm.group(1),name_ind=mm.group(2),close=mm.group(3),weight=float(mm.group(4)))); n+=1
    rep.append((tag,asof,n,'pdf'))
df=pd.DataFrame(rows); df.to_parquet('monthly_parsed.parquet')
r=pd.DataFrame(rep,columns=['tag','asof','n','fmt']); r.to_csv('monthly_report.csv',index=False)
print(r.n.describe()); print(r[(r.n<499)|(r.n>501)|r.asof.isna()].to_string()); print(r.fmt.value_counts())
