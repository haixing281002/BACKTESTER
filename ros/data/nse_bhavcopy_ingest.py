"""Turn locally-downloaded NSE bhavcopy into this fund's master-universe CSV.

WHERE THIS FITS

This repo never fetches live data itself -- there is no network tool here that
reaches nseindia.com, and there should not be: a backtest must be reproducible
from files on disk, not from whatever the archive answered today. The fetch
happens on your machine, with your own `download_history.py` (NSE CM bhavcopy,
old format before 2024-07-08 and UDiFF format from 2024-01-02, main-board
rows only: ISIN starting `INE`, SERIES in EQ/BE/BZ), which writes one pickle
per trading day into a `cache/` directory with columns
`DATE, SYMBOL, SERIES, ISIN, OPEN, HIGH, LOW, CLOSE, PREV, QTY, VAL, TRADES`.

This module starts from that cache and produces the one file
`ros/data/master.py` already knows how to read:

    date,security_id,symbol,adj_close,in_universe,adv,sector

keyed on a canonical entity ID derived from ISIN (never the NSE symbol --
symbols get reused and renamed across corporate actions), with `in_universe`
set by a point-in-time top-N traded-value ranking, held fixed within each
quarter, and delisted names left IN the file with `in_universe` flipping to 0.

WHY THREE SEPARATE STEPS

Bhavcopy alone cannot be pivoted into a price series: the same company can
carry more than one ISIN over its life (a split, bonus or face-value change
sometimes reissues the ISIN under the same SYMBOL), and `PREVCLOSE` is never
adjusted for the corporate action that caused it -- a 4:1 bonus shows up as a
fake -78% day, a 1:5 split as -80%. Collapsing to one row per day, linking
ISINs into one entity, and neutralising the resulting jump are three distinct,
independently checkable steps, so they stay three functions rather than one
opaque pass.

Caveats that must travel with any result built on this file (put them in
data/raw/MANIFEST.yaml -- see `manifest_stanza()` below):

  - Ranking is by traded VALUE, not market cap. Bhavcopy carries no market cap
    field, so "top 1000" here means top 1000 by trailing traded value, not an
    official NSE index. Say so wherever the ranking is used.
  - Corporate-action neutralisation is a heuristic threshold (a day's gross
    return outside [0.72, 1.4] is treated as an unadjusted corporate action,
    not a real move). It can both miss a genuine small action and misclassify
    a genuine large one-day move. `ca_events` records every day it touched so
    this is auditable, never silent.
  - ISIN linking (same SYMBOL, a gap of -5 to +20 calendar days between one
    ISIN's last row and the next one's first) is also a heuristic. It is
    checkable from `isin_links` but not guaranteed complete.
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

RAW_COLS = ["DATE", "SYMBOL", "SERIES", "ISIN", "OPEN", "HIGH", "LOW", "CLOSE",
            "PREV", "QTY", "VAL", "TRADES"]

# A day's gross return outside this band is treated as an unadjusted
# corporate action (bonus, split, face-value change) rather than a real move.
CA_LOW, CA_HIGH = 0.72, 1.40

# ISIN re-link window: the new ISIN's first row must start within this many
# calendar days of the old ISIN's last row, under the same SYMBOL.
LINK_MIN_GAP_DAYS, LINK_MAX_GAP_DAYS = -5, 20


def combine_cache(cache_dir: str = "cache") -> pd.DataFrame:
    """Concatenate every `download_history.py` daily pickle into one frame."""
    files = sorted(glob.glob(os.path.join(cache_dir, "*.pkl")))
    if not files:
        raise FileNotFoundError(
            f"no .pkl files under {cache_dir}/. Run download_history.py on "
            f"your own machine first -- this repo has no network access to "
            f"NSE from inside a backtest run.")
    frames = [pd.read_pickle(f) for f in files]
    df = pd.concat(frames, ignore_index=True)
    missing = [c for c in RAW_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"cache files are missing expected column(s) {missing}; "
                          f"this does not look like download_history.py output")
    df["DATE"] = pd.to_datetime(df["DATE"])
    return df[RAW_COLS]


def dedupe_rows(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (DATE, ISIN): prefer SERIES == 'EQ', then highest VAL.

    A corporate action can briefly list a name under more than one series on
    the same day; silently keeping "whichever pandas happens to keep" would
    make the file non-reproducible across machines, the same failure
    `ros/data/master.py` refuses outright for duplicate (date, security) rows.
    """
    df = df.copy()
    df["_eq_first"] = (df["SERIES"] != "EQ").astype(int)
    df = df.sort_values(["DATE", "ISIN", "_eq_first", "VAL"],
                        ascending=[True, True, True, False])
    df = df.drop_duplicates(["DATE", "ISIN"], keep="first")
    return df.drop(columns="_eq_first").reset_index(drop=True)


@dataclass
class IsinLinks:
    isin_to_entity: Dict[str, str] = field(default_factory=dict)
    links: List[Tuple[str, str, str, int]] = field(default_factory=list)
    # each link: (old_isin, new_isin, symbol, gap_days)


def link_isins(df: pd.DataFrame) -> IsinLinks:
    """Union-find: chain consecutive ISINs under the same SYMBOL into one entity.

    A split/bonus/face-value change sometimes reissues the ISIN for the same
    company under the same SYMBOL. If one ISIN's last trading day is followed,
    within `LINK_MIN_GAP_DAYS..LINK_MAX_GAP_DAYS` calendar days, by a different
    ISIN's first trading day under the identical SYMBOL, treat them as the same
    entity -- otherwise a corporate action would look like a delisting followed
    by an unrelated IPO.
    """
    spans = (df.groupby("ISIN")
               .agg(symbol=("SYMBOL", "last"), first=("DATE", "min"),
                    last=("DATE", "max"))
               .reset_index())

    parent: Dict[str, str] = {isin: isin for isin in spans["ISIN"]}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    links: List[Tuple[str, str, str, int]] = []
    for symbol, g in spans.groupby("symbol"):
        g = g.sort_values("first")
        rows = list(g.itertuples(index=False))
        for prev, nxt in zip(rows, rows[1:]):
            gap = (nxt.first - prev.last).days
            if LINK_MIN_GAP_DAYS <= gap <= LINK_MAX_GAP_DAYS:
                union(prev.ISIN, nxt.ISIN)
                links.append((prev.ISIN, nxt.ISIN, symbol, gap))

    isin_to_entity = {isin: find(isin) for isin in spans["ISIN"]}
    return IsinLinks(isin_to_entity=isin_to_entity, links=links)


@dataclass
class AdjustedPrices:
    panel: pd.DataFrame            # DATE x ENT -> adjusted close
    raw_close: pd.DataFrame        # DATE x ENT -> unadjusted close (for reference)
    ca_events: pd.DataFrame        # one row per neutralised jump


def build_adjusted_prices(df: pd.DataFrame, links: IsinLinks) -> AdjustedPrices:
    """Chain daily gross returns into an adjusted index, neutralising corporate
    actions that `PREV` was never adjusted for.

    Bhavcopy's PREVCLOSE is the literal previous close, not a corporate-action-
    adjusted one. A day whose gross return `CLOSE/PREV` falls outside
    [CA_LOW, CA_HIGH] is treated as an artifact of an unadjusted bonus, split or
    face-value change rather than a real -28%/+40%+ move, and is neutralised to
    a flat day (gross return 1.0) in the adjusted series. The raw close is kept
    alongside, and every neutralised day is logged in `ca_events` so this is
    auditable rather than a silent rewrite.
    """
    df = df.copy()
    df["ENT"] = df["ISIN"].map(links.isin_to_entity)
    df = df.sort_values(["ENT", "DATE"])

    raw_close = df.pivot(index="DATE", columns="ENT", values="CLOSE").sort_index()

    events = []
    adj_cols = {}
    for ent, g in df.groupby("ENT"):
        g = g.sort_values("DATE")
        close = g["CLOSE"].to_numpy(dtype=float)
        prev = g["PREV"].to_numpy(dtype=float)
        dates = g["DATE"].to_numpy()
        with np.errstate(divide="ignore", invalid="ignore"):
            gross = np.where((prev > 0) & np.isfinite(prev), close / prev, 1.0)
        neutral_mask = (gross < CA_LOW) | (gross > CA_HIGH)
        gross_adj = np.where(neutral_mask, 1.0, gross)
        gross_adj[0] = 1.0  # first observed day has no prior day to chain from
        idx = np.cumprod(gross_adj) * close[0] / gross_adj[0] if len(close) else close
        # anchor the index level at the entity's first actual close
        idx = idx * (close[0] / idx[0]) if len(idx) else idx
        adj_cols[ent] = pd.Series(idx, index=dates)
        for i in np.where(neutral_mask)[0]:
            if i == 0:
                continue
            events.append({"ENT": ent, "DATE": dates[i], "raw_gross_return": gross[i],
                           "prev_close": prev[i], "close": close[i]})

    panel = pd.DataFrame(adj_cols).sort_index()
    ca_events = pd.DataFrame(events)
    return AdjustedPrices(panel=panel, raw_close=raw_close, ca_events=ca_events)


def point_in_time_universe(df: pd.DataFrame, links: IsinLinks, top_n: int = 1000,
                           lookback_sessions: int = 63,
                           min_sessions: int = 40) -> pd.DataFrame:
    """Quarterly top-`top_n`-by-trailing-traded-value membership, held fixed
    within each quarter.

    No look-ahead: membership at a quarter boundary is decided only from the
    `lookback_sessions` trading days strictly before it, and an entity needs at
    least `min_sessions` of those days with data to be eligible at all (a name
    that just listed, or that is thinly traded, should not rank by a handful of
    sessions). Membership does not get re-ranked mid-quarter.

    This is NOT an official NSE index: bhavcopy carries no market-cap field, so
    "top 1000" means top 1000 by trailing traded value. Say so wherever this is
    used -- it is a documented limitation, not official methodology.
    """
    df = df.copy()
    df["ENT"] = df["ISIN"].map(links.isin_to_entity)
    val = df.pivot_table(index="DATE", columns="ENT", values="VAL", aggfunc="sum").sort_index()

    quarter_starts = pd.date_range(val.index.min().to_period("Q").start_time,
                                   val.index.max().to_period("Q").start_time,
                                   freq="QS")

    membership = pd.DataFrame(False, index=val.index, columns=val.columns)
    for qstart in quarter_starts:
        qend = qstart + pd.offsets.QuarterEnd(0)
        trailing = val.loc[:qstart - pd.Timedelta(days=1)].tail(lookback_sessions)
        if trailing.empty:
            continue
        n_sessions = trailing.notna().sum()
        avg_val = trailing.mean()
        eligible = avg_val[n_sessions >= min_sessions].dropna()
        top = eligible.sort_values(ascending=False).head(top_n).index
        in_this_quarter = val.index[(val.index >= qstart) & (val.index <= qend)]
        membership.loc[in_this_quarter, top] = True

    return membership


def build_master_csv(df: pd.DataFrame, out_path: str, top_n: int = 1000,
                     lookback_sessions: int = 63, min_sessions: int = 40
                     ) -> Dict[str, object]:
    """Run the full pipeline (dedupe -> link -> adjust -> membership) and write
    `ros/data/master.py`'s long CSV shape. Returns a small report dict for the
    caller to print (row counts, number of ISIN links, number of CA events).
    """
    df = dedupe_rows(df)
    links = link_isins(df)
    prices = build_adjusted_prices(df, links)
    membership = point_in_time_universe(df, links, top_n=top_n,
                                        lookback_sessions=lookback_sessions,
                                        min_sessions=min_sessions)

    symbol_last = (df.assign(ENT=df["ISIN"].map(links.isin_to_entity))
                     .sort_values("DATE").groupby("ENT")["SYMBOL"].last())
    avg_val = (df.assign(ENT=df["ISIN"].map(links.isin_to_entity))
                 .pivot_table(index="DATE", columns="ENT", values="VAL", aggfunc="sum")
                 .sort_index())

    adj = prices.panel
    rows = []
    for ent in adj.columns:
        px = adj[ent].dropna()
        if px.empty:
            continue
        sym = symbol_last.get(ent, ent)
        mem = membership[ent] if ent in membership.columns else pd.Series(False, index=px.index)
        adv = avg_val[ent] if ent in avg_val.columns else pd.Series(np.nan, index=px.index)
        for dt, price in px.items():
            rows.append({
                "date": dt.date().isoformat(),
                "security_id": ent,
                "symbol": sym,
                "adj_close": price,
                "in_universe": int(bool(mem.get(dt, False))),
                "adv": adv.get(dt, np.nan),
            })

    out = pd.DataFrame(rows).sort_values(["date", "security_id"])
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    out.to_csv(out_path, index=False)

    return {
        "rows_written": len(out),
        "entities": out["security_id"].nunique(),
        "date_min": out["date"].min() if len(out) else None,
        "date_max": out["date"].max() if len(out) else None,
        "isin_links": len(links.links),
        "ca_events_neutralised": len(prices.ca_events),
        "out_path": out_path,
    }


def manifest_stanza(out_path: str) -> str:
    """The `master:` block to paste into data/raw/MANIFEST.yaml for this file."""
    rel = os.path.relpath(out_path, "data/raw")
    return f"""master:
  file: {rel}
  pit_status: point_in_time   # membership and ADV are computed with no
                               # look-ahead (see point_in_time_universe()); if
                               # you re-ran this against a cache you edited by
                               # hand, downgrade this honestly.
  licence: "NSE bhavcopy, public archive (nsearchives.nseindia.com); personal research use"
  caveats:
    - "in_universe ranks by trailing traded VALUE, not market cap -- bhavcopy has no market-cap field. This is top-{{top_n}}-by-turnover, not an official NSE index."
    - "Corporate-action neutralisation is a heuristic threshold (daily gross return outside [{CA_LOW}, {CA_HIGH}] is treated as an unadjusted bonus/split/face-value change). See ca_events in the ingest report for every day it touched."
    - "ISIN linking across corporate actions is a heuristic (same SYMBOL, {LINK_MIN_GAP_DAYS}..{LINK_MAX_GAP_DAYS} day gap). Check isin_links in the ingest report before trusting a long single-entity history through a known corporate action."
    - "No dividends. adj_close is a price-return series, not a total-return series."
"""


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", default="cache",
                    help="directory of download_history.py daily .pkl files")
    ap.add_argument("--out", default="data/raw/master/nse_master.csv")
    ap.add_argument("--top-n", type=int, default=1000)
    ap.add_argument("--lookback-sessions", type=int, default=63)
    ap.add_argument("--min-sessions", type=int, default=40)
    args = ap.parse_args()

    df = combine_cache(args.cache)
    report = build_master_csv(df, args.out, top_n=args.top_n,
                              lookback_sessions=args.lookback_sessions,
                              min_sessions=args.min_sessions)

    print("NSE bhavcopy -> master universe")
    for k, v in report.items():
        print(f"  {k}: {v}")
    print()
    print("Next:")
    print(f"  1. python -m ros.data.master {args.out}")
    print(f"     (refuses the file if it looks survivor-only or membership is off)")
    print(f"  2. Paste this into data/raw/MANIFEST.yaml:")
    print()
    print(manifest_stanza(args.out).replace("{top_n}", str(args.top_n)))


if __name__ == "__main__":
    main()
