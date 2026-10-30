import pypdf, re, pandas as pd, os
y=pd.read_csv('press_selected.csv',parse_dates=['d'])
extra=pd.DataFrame([dict(date='Jul 15, 2025',href='/Press_Release/ind_prs15072025.pdf',title='Corporate Action Adjustment for Valor Estate Ltd. in Nifty indices and Replacement in Nifty IPO w.e.f. July 18, 2025',d=pd.Timestamp('2025-07-15'))])
y=pd.concat([y,extra],ignore_index=True).sort_values('d')
def path(h):
    b=os.path.basename(h)
    for d in ('press','press_other'):
        if os.path.exists(f'{d}/{b}'): return f'{d}/{b}'
def text(f):
    s='\n'.join(p.extract_text() or '' for p in pypdf.PdfReader(f).pages)
    return s.replace('\ufffd',"'").replace('\u2019',"'")
MON='January|February|March|April|May|June|July|August|September|October|November|December'
DATE_RX=re.compile(r'effective (?:from )?(?:on )?\(?(' + MON + r') ?(\d{1,2}) ?, ?(\d) ?(\d) ?(\d) ?(\d)',re.I)
def dates_in(s):
    s2=re.sub(r'\s+',' ',s); return [(m.start(),pd.Timestamp(f'{m.group(1)} {m.group(2)} {m.group(3)}{m.group(4)}{m.group(5)}{m.group(6)}')) for m in DATE_RX.finditer(s2)], s2
HDR=re.compile(r'\n\s*(?:[A-Z]\.\s*)?(?:\d+|[a-zA-Z])\s*[\)\.]\s*(?:NIFTY|Nifty)\s*500\s*(?:index)?\s*\n')
END=re.compile(r'\n\s*(?:[A-Z]\.\s*)?(?:\d+|[a-zA-Z])\s*[\)\.]\s*(?:NIFTY|Nifty)\s|\n\s*[B-Z]\.\s+[A-Z]|About NSE Indices')
ROW=re.compile(r'^\s*\d+\s+(.+?)\s+([A-Z0-9][A-Z0-9&\-]*)[\*#]*\s*$')
def sections(s):
    out=[]
    for mm in HDR.finditer(s):
        if not re.search(r'being (?:excluded|included)',s[mm.end():mm.end()+400]): continue
        rest=s[mm.end():]; n=END.search(rest)
        out.append((mm.start(), rest[:n.start()] if n else rest))
    return out
def tables(sec):
    out={'excl':[],'incl':[]}; cur=None
    for ln in sec.splitlines():
        l=ln.strip()
        if re.search(r'being excluded|to be excluded|shall be excluded',l,re.I): cur='excl'; continue
        if re.search(r'being included|to be included|shall be included',l,re.I): cur='incl'; continue
        if re.match(r'^(Note|Notes)\b',l,re.I): cur=None
        mm=ROW.match(l)
        if cur and mm and mm.group(2)!='SYMBOL': out[cur].append((mm.group(2),mm.group(1)))
    return out
events=[]; log=[]
for _,r in y.iterrows():
    f=path(r.href); s=text(f); rel=os.path.basename(r.href)
    secs=sections(s)
    for pos,sec in secs:
        # effective date: last 'effective from' stated before this section; else first in release
        pre_dates,_=dates_in(s[:pos]); all_dates,_=dates_in(s)
        e=(pre_dates[-1][1] if pre_dates else (all_dates[0][1] if all_dates else None))
        tb=tables(sec)
        log.append(dict(release=rel,rdate=r.d.date(),title=r.title,eff=e.date() if e is not None else None,n_ex=len(tb['excl']),n_in=len(tb['incl']),kind='table'))
        for k in ('excl','incl'):
            for sym,nm in tb[k]: events.append(dict(eff=e.date(),action='OUT' if k=='excl' else 'IN',symbol=sym,name=nm,release=rel,kind='review/replacement'))
    if not secs:
        log.append(dict(release=rel,rdate=r.d.date(),title=r.title,kind='indexlist' if re.search(r'^\s*\d+\s+Nifty 500\s*$',s,re.M|re.I) else 'none'))
L=pd.DataFrame(log); E=pd.DataFrame(events)
L.to_csv('press_log.csv',index=False); E.to_csv('press_events.csv',index=False)
print(L[L.kind=='table'].groupby('release').agg(eff=('eff',lambda x: sorted(set(map(str,x)))),n_ex=('n_ex','sum'),n_in=('n_in','sum')).to_string())
