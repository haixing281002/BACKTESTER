# Quant AI Researcher
"""Market-cap and sector allocation and returns by financial year, from a run's holdings (Wave 6, Step 2 l).

What is read: the run's holdings.csv (weights at each rebalance), Ace adjusted closes (each holding's return from one
execution date to the next), the NIFTY 500 holdings workbook's quarterly Nifty 100 / Midcap 150 / Smallcap 250 flags
(the market-cap bucket, from the latest snapshot on or before the rebalance), and Ace's sector per company grouped by
config/sector_groups.yaml (used only once the operator has approved the grouping).

Definitions, which are this module's own and are stated wherever the tables are shown:
  - allocation in a financial year = the average, over the rebalances executed in that year, of the bucket's weight;
  - market-cap return of a holding period = the bucket's holdings' returns weighted by their weights; sector return of a
    holding period = the plain average of the bucket's holdings' returns ("average stock return of the sector");
  - a financial year's return = those holding-period returns compounded over the periods the bucket was held.
Nothing here is read by a backtest or by Gate B.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ros import config
from universal_backtester.xlsx_style import BOX, DATE, F_BASE, F_BOLD, F_INPUT, F_NOTE, F_TITLE, PCT2, header, put, widths

CAP = ["Large cap (Nifty 100)", "Mid cap (Midcap 150)", "Small cap (Smallcap 250)", "Not in the quarterly list"]
SHEET = "Allocation"


def _fy(d: pd.Timestamp) -> str:
    return f"FY{(d.year + (d.month >= 4)) % 100:02d}"


def build(df: pd.DataFrame, holdings: pd.DataFrame | None, se_block: dict[str, Any]) -> dict[str, Any]:
    if holdings is None or not len(holdings) or not {"isin", "weight", "execution_date"} <= set(holdings.columns):
        return {"status": "left out", "why": "the run wrote no holdings with an ISIN, a weight and an execution date"}
    from ros.data import ace, nifty500
    h = holdings[["isin", "weight", "execution_date"]].copy()
    h["exec"] = pd.to_datetime(h["execution_date"])
    h = h[h["weight"] > 0]
    execs = pd.DatetimeIndex(sorted(h["exec"].unique()))
    end = pd.Timestamp(df["date"].max())
    px = ace.wide("close", start=execs[0] - pd.Timedelta(days=10), end=end)
    px = px.reindex(columns=[c for c in h["isin"].unique() if c in px.columns]).ffill()
    snaps = nifty500.load_snapshots()
    snaps = snaps[snaps["isin"].notna()]
    snap_dates = pd.DatetimeIndex(sorted(pd.to_datetime(snaps["snapshot_date"]).unique()))
    by_snap = {d: g.drop_duplicates("isin").set_index("isin") for d, g in snaps.assign(d=pd.to_datetime(snaps["snapshot_date"])).groupby("d")}
    sg = config._load("sector_groups.yaml")
    sector_ok = bool(sg.get("approved"))
    group_of = {lab: grp for grp, labs in (sg.get("groups") or {}).items() for lab in labs}
    sectors = list((sg.get("groups") or {}).keys())
    sm = ace.security_master()
    sec_of = dict(zip(sm["isin"], sm["sector"])) if "sector" in sm.columns else {}
    no_price = set()
    rows = []
    for k, e in enumerate(execs):
        nxt = execs[k + 1] if k + 1 < len(execs) else end
        if nxt <= e:
            continue
        p0, p1 = px.loc[:e].iloc[-1], px.loc[:nxt].iloc[-1]
        g = h[h["exec"] == e]
        before = snap_dates[snap_dates <= e]
        flags = by_snap[before[-1]] if len(before) else None
        rec = {"date": e, "fy": _fy(e)}
        cap_w, cap_wr = dict.fromkeys(CAP, 0.0), dict.fromkeys(CAP, 0.0)
        sec_w, sec_r = dict.fromkeys(sectors, 0.0), {s: [] for s in sectors}
        for isin, w in zip(g["isin"], g["weight"]):
            r = (p1.get(isin, np.nan) / p0.get(isin, np.nan) - 1.0) if isin in px.columns else np.nan
            if r != r:
                no_price.add(isin)
                r = 0.0
            b = CAP[3]
            if flags is not None and isin in flags.index:
                f = flags.loc[isin]
                b = CAP[0] if f["in_nifty100"] else CAP[1] if f["in_midcap150"] else CAP[2] if f["in_smallcap250"] else CAP[3]
            cap_w[b] += w
            cap_wr[b] += w * r
            s = group_of.get(sec_of.get(isin), "Others")
            if s in sec_w:
                sec_w[s] += w
                sec_r[s].append(r)
        for b in CAP:
            rec[f"w|{b}"], rec[f"r|{b}"] = cap_w[b], (cap_wr[b] / cap_w[b] if cap_w[b] > 0 else None)
        for s in sectors:
            rec[f"w|{s}"], rec[f"r|{s}"] = sec_w[s], (float(np.mean(sec_r[s])) if sec_r[s] else None)
        rec["w|Cash"] = 1.0 - sum(cap_w.values())
        rows.append(rec)
    per = pd.DataFrame(rows)
    fys = list(dict.fromkeys(per["fy"]))

    def tab(title, cols, kind, note):
        out = []
        for fy in fys:
            p = per[per["fy"] == fy]
            vals = []
            for c in cols:
                x = p[f"{kind}|{c}"]
                vals.append(float(x.mean()) if kind == "w" else (float(np.prod(1.0 + x.dropna().to_numpy(dtype=float)) - 1.0) if x.notna().any() else None))
            out.append({"label": fy, "values": vals})
        return {"title": title, "columns": cols, "kind": kind, "rows": out, "note": note}

    tables = [tab("Market-cap allocation: average weight", CAP + ["Cash"], "w", "Bucket = the name's place in the latest quarterly NIFTY 500 list on or before the rebalance."),
              tab("Market-cap weighted average returns", CAP, "r", "Holdings' returns weighted by their weights, compounded over the year's holding periods.")]
    if sector_ok:
        tables += [tab("Sector allocation: average weight", sectors, "w", "Ace's present-day sector for each company, grouped by config/sector_groups.yaml. Not dated."),
                   tab("Sector returns: average stock return", sectors, "r", "The plain average of the sector's holdings' returns, compounded over the year's holding periods.")]
    first, last = execs[0], end
    return {"status": "built", "tables": tables, "per": per, "cap": CAP, "sectors": sectors if sector_ok else [],
            "sector_status": "shown" if sector_ok else "left out: the 45-to-11 sector grouping in config/sector_groups.yaml is a draft awaiting the operator's approval",
            "no_price": sorted(no_price),
            "note": (f"Financial years April to March, by execution date, {first.date()} to {last.date()}; the first and last years are part years. "
                     f"{len(per)} holding periods. Prices are Ace adjusted closes; {len(no_price)} holding(s) with no price in a period are counted at a zero return. "
                     + ("" if sector_ok else "Sector tables are left out until the sector grouping is approved."))}


def for_page(alloc: dict[str, Any] | None) -> dict[str, Any] | None:
    """The JSON the page draws: the tables without the per-rebalance frame."""
    if alloc is None:
        return None
    if alloc.get("status") != "built":
        return {"status": alloc.get("status"), "why": alloc.get("why")}
    return {"status": "built", "note": alloc["note"], "sector_status": alloc["sector_status"],
            "tables": [{k: t[k] for k in ("title", "columns", "rows", "note")} for t in alloc["tables"]]}


def write_sheet(wb, alloc: dict[str, Any]) -> list[tuple[str, str, Any, str]]:
    """The Allocation sheet: the financial-year tables as formulas over the per-rebalance figures, which sit to the right
    in blue (Python values from the holdings and the price file). Returns the Python vs Excel items."""
    from openpyxl.utils import get_column_letter as L
    from openpyxl.worksheet.formula import ArrayFormula
    ws = wb.create_sheet(SHEET)
    put(ws, "A1", "Market-cap and sector allocation and returns, by financial year", F_TITLE)
    put(ws, "A2", alloc["note"] + " The yearly tables are formulas over the per-rebalance figures to the right. Quant AI Researcher", F_NOTE)
    if alloc.get("status") != "built":
        put(ws, "A4", "Left out: " + str(alloc.get("why")), F_BOLD)
        return []
    per = alloc["per"]
    cols = [c for c in per.columns if c not in ("date", "fy")]
    c0 = 22                                             # the per-rebalance block starts at column V
    d0, d1 = 6, 5 + len(per)
    header(ws, 5, ["Execution date", "Financial year"] + [("Weight: " if c[0] == "w" else "Return to the next rebalance: ") + c[2:] for c in cols], col=c0, height=58)
    where = {}
    for j, c in enumerate(cols):
        where[c] = L(c0 + 2 + j)
    for i, row in enumerate(per.itertuples(index=False), start=d0):
        ws.cell(row=i, column=c0, value=row[0].to_pydatetime()).number_format = DATE
        ws.cell(row=i, column=c0 + 1, value=row[1])
        for j, c in enumerate(cols):
            v = row[2 + j]
            cell = ws.cell(row=i, column=c0 + 2 + j, value=None if v is None or v != v else float(v))
            cell.font, cell.number_format = F_INPUT, PCT2
    fy_rng = f"${L(c0 + 1)}${d0}:${L(c0 + 1)}${d1}"
    items, r = [], 4
    for t in alloc["tables"]:
        put(ws, f"A{r}", t["title"], F_BOLD)
        header(ws, r + 1, ["Financial year"] + t["columns"], height=44)
        r += 2
        for row in t["rows"]:
            put(ws, f"A{r}", row["label"], F_BASE, border=True)
            for j, (c, v) in enumerate(zip(t["columns"], row["values"])):
                ref = f"{L(2 + j)}{r}"
                rng = f"${where[t['kind'] + '|' + c]}${d0}:${where[t['kind'] + '|' + c]}${d1}"
                if t["kind"] == "w":
                    ws[ref] = f'=AVERAGEIFS({rng},{fy_rng},$A{r})'
                else:
                    ws[ref] = ArrayFormula(ref, f'=IF(SUM(({fy_rng}=$A{r})*ISNUMBER({rng}))=0,"n/a",PRODUCT(IF(({fy_rng}=$A{r})*ISNUMBER({rng}),1+{rng},1))-1)')
                ws[ref].font, ws[ref].number_format, ws[ref].border = F_BASE, PCT2, BOX
                items.append((f"Allocation: {t['title']}", f"{row['label']}, {c}", v, f"'{SHEET}'!{ref}"))
            r += 1
        put(ws, f"A{r}", t["note"], F_NOTE)
        r += 2
    widths(ws, [16] + [15] * 13)
    return items
