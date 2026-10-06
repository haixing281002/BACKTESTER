"""A 5-year stock panel built from exactly two sources: NSE bhavcopy and Screener.in.

SOURCE LIMIT. `ALLOWED_SOURCES` below is the whole list. Every public function that
reads data takes its inputs from the bhavcopy cache (`ros/data/nse_bhavcopy_download.py`)
and the Screener folder (`ros/data/screener_fetch.py`), and `assert_sources()` refuses
anything else. No Accord file, no index workbook, no third source.

WHAT EACH SOURCE SUPPLIES

  NSE bhavcopy   daily raw OHLC, quantity, traded value (rupees) and ISIN for every
                 main-board stock. Raw, unadjusted prices.
  Screener.in    current market cap and price (so current shares = market cap / price),
                 face value, FY equity capital, and the latest promoter holding. Restated
                 latest values; headline numbers are as of the day of the fetch.

WHAT THIS BUILDS

  rupee turnover   daily traded value over market cap, summed over a trailing window.
                   Market cap on date t is  adjusted_close_t x shares_now,  where the
                   adjusted close is rescaled to today's share basis (bhavcopy prices are
                   raw, and a split or bonus shows up as a fake large daily move; the
                   ingest module neutralises those). Rupee turnover does not depend on
                   split or bonus basis because both numerator and denominator are rupees.
  point-in-time    top-N membership by trailing traded value, quarterly, no look-ahead,
  universe         from `nse_bhavcopy_ingest.point_in_time_universe`. NOT an index and not
                   by market cap: bhavcopy has no market-cap field.

LIMITS THAT TRAVEL WITH EVERY NUMBER (they are written into the manifest stanza)

  * Screener is not point-in-time. Shares are TODAY's shares carried back, so real share
    issuance (QIPs, rights, ESOPs) over the window is not captured; turnover is slightly
    understated before an issuance.
  * Screener lists only companies that exist today. A stock that delisted inside the
    window has no shares, so its turnover is NaN and it cannot be ranked. That is a
    survivorship bias in the turnover rank, and `coverage_report()` states how large it is.
  * The corporate-action neutralisation is a heuristic threshold on daily gross return.
  * The free-float fraction (1 - latest promoter %) is a current snapshot and is a
    sensitivity input only.
"""
from __future__ import annotations

import os
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from ros.data.nse_bhavcopy_ingest import (
    build_adjusted_prices, dedupe_rows, link_isins, point_in_time_universe,
)
from ros.data.screener_parse import load, row

ALLOWED_SOURCES = ("nse_bhavcopy", "screener")
CRORE = 1e7


def assert_sources(sources: Iterable[str]) -> None:
    """Refuse any data source outside the two this panel is allowed to use."""
    bad = sorted(set(sources) - set(ALLOWED_SOURCES))
    if bad:
        raise ValueError(f"data source(s) {bad} are not allowed here; only {list(ALLOWED_SOURCES)}")


def screener_shares(scr_dir: str, symbols: Iterable[str]) -> pd.DataFrame:
    """One row per symbol that has a Screener folder.

    shares_cr           current market cap (Rs cr) / current price (Rs) -> shares in crore
    promoter_pct        latest quarter's promoter holding, percent
    free_float_frac     1 - promoter_pct/100 (a current snapshot, not point-in-time)
    shares_ec_cr        latest FY equity capital (Rs cr) / face value (Rs), a second estimate
    shares_ratio        shares_ec_cr / shares_cr; far from 1 flags a bonus, split or issuance
                        that the two estimates see differently
    """
    rows = []
    for sym in symbols:
        sym = str(sym).upper()
        if not os.path.exists(os.path.join(scr_dir, sym, "meta.json")):
            continue
        try:
            secs, meta = load(scr_dir, sym)
        except Exception:
            continue
        mcap, px = meta.get("mcap_cr"), meta.get("price")
        shares = mcap / px if (mcap and px and px > 0) else np.nan
        face = None
        raw_face = meta.get("headline_raw", {}).get("Face Value")
        if raw_face:
            from ros.data.screener_fetch import to_float
            face = to_float(raw_face)
        ec = np.nan
        try:
            eq = row(secs["balance-sheet"][0], ["Equity Capital"])
            vals = [v for v in eq.values() if v is not None]
            ec = vals[-1] if vals else np.nan
        except Exception:
            pass
        shares_ec = ec / face if (face and not np.isnan(ec) and face > 0) else np.nan
        promo = np.nan
        try:
            sh = secs["shareholding"][0]
            r = row(sh, ["Promoters"])
            vals = [v for v in r.values() if v is not None]
            promo = vals[-1] if vals else np.nan
        except Exception:
            pass
        rows.append({"symbol": sym, "shares_cr": shares, "promoter_pct": promo,
                     "free_float_frac": (1 - promo / 100) if not np.isnan(promo) else np.nan,
                     "shares_ec_cr": shares_ec,
                     "shares_ratio": (shares_ec / shares) if (shares and not np.isnan(shares_ec)) else np.nan,
                     "view": meta.get("view")})
    cols = ["symbol", "shares_cr", "promoter_pct", "free_float_frac", "shares_ec_cr", "shares_ratio", "view"]
    return pd.DataFrame(rows, columns=cols)


def universe_symbols(df: pd.DataFrame, top_n: int = 500, **kw) -> List[str]:
    """Latest symbol of every entity that was in the point-in-time top-N at any date.
    This is the list to hand to the Screener fetch."""
    df = dedupe_rows(df)
    links = link_isins(df)
    mem = point_in_time_universe(df, links, top_n=top_n, **kw)
    ever = mem.columns[mem.any(axis=0)]
    last_sym = (df.assign(ENT=df["ISIN"].map(links.isin_to_entity))
                  .sort_values("DATE").groupby("ENT")["SYMBOL"].last())
    return sorted(set(last_sym.reindex(ever).dropna().astype(str)))


def build_turnover_panel(df: pd.DataFrame, shares: pd.DataFrame, top_n: int = 500,
                         window: int = 21, **kw) -> pd.DataFrame:
    """Long panel: date, security_id, symbol, adj_close_now_basis, traded_value_cr,
    mcap_cr_est, turnover_window, in_universe, free_float_frac.

    `turnover_window` is the sum over the trailing `window` sessions of daily
    traded value / market cap, known only AFTER the close of `date`. A backtest must
    shift it by at least one session.
    """
    df = dedupe_rows(df)
    links = link_isins(df)
    prices = build_adjusted_prices(df, links)
    mem = point_in_time_universe(df, links, top_n=top_n, **kw)

    d = df.assign(ENT=df["ISIN"].map(links.isin_to_entity))
    val = d.pivot_table(index="DATE", columns="ENT", values="VAL", aggfunc="sum").sort_index()
    last_sym = d.sort_values("DATE").groupby("ENT")["SYMBOL"].last()
    sh = shares.set_index("symbol")

    adj = prices.panel
    raw = prices.raw_close
    frames = []
    for ent in adj.columns:
        a = adj[ent].dropna()
        if a.empty:
            continue
        r = raw[ent].dropna()
        # rescale the adjusted index to today's share basis: last adjusted == last raw close
        a_now = a * (r.iloc[-1] / a.iloc[-1])
        sym = str(last_sym.get(ent, ent))
        shares_cr = sh["shares_cr"].get(sym, np.nan)
        ff = sh["free_float_frac"].get(sym, np.nan)
        v_cr = val[ent].reindex(a.index) / CRORE if ent in val.columns else pd.Series(np.nan, index=a.index)
        mcap = a_now * shares_cr                      # Rs cr (price Rs x shares cr)
        daily = v_cr / mcap
        turnover = daily.rolling(window, min_periods=window).sum()
        m = mem[ent].reindex(a.index).fillna(False) if ent in mem.columns else pd.Series(False, index=a.index)
        frames.append(pd.DataFrame({
            "date": a.index, "security_id": ent, "symbol": sym,
            "adj_close_now_basis": a_now.to_numpy(), "traded_value_cr": v_cr.to_numpy(),
            "mcap_cr_est": mcap.to_numpy(), "turnover_window": turnover.to_numpy(),
            "in_universe": m.astype(int).to_numpy(), "free_float_frac": ff}))
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return out.sort_values(["date", "security_id"]).reset_index(drop=True)


def coverage_report(panel: pd.DataFrame) -> Dict[str, float]:
    """How much of the point-in-time universe has a usable turnover value.
    The gap is the survivorship bias: names Screener does not list have no shares."""
    u = panel[panel["in_universe"] == 1]
    if u.empty:
        return {"universe_stock_days": 0}
    have = u["turnover_window"].notna()
    ents_all = u["security_id"].nunique()
    ents_have = u.loc[have, "security_id"].nunique()
    return {
        "universe_stock_days": int(len(u)),
        "stock_days_with_turnover": int(have.sum()),
        "share_of_universe_stock_days_with_turnover": float(have.mean()),
        "entities_ever_in_universe": int(ents_all),
        "entities_with_any_turnover": int(ents_have),
        "entities_without_screener_shares": int(ents_all - ents_have),
    }


def manifest_stanza(out_path: str, top_n: int = 500) -> str:
    rel = os.path.relpath(out_path, "data/raw")
    return f"""bhavcopy_screener_panel:
  file: {rel}
  pit_status: not_point_in_time   # the universe and traded value are point in time; the share counts are NOT
  licence: "NSE bhavcopy public archive and Screener.in public pages; personal research use; not redistributed"
  caveats:
    - "Only two sources: NSE bhavcopy and Screener.in. Nothing else enters this panel."
    - "Shares are today's shares (Screener market cap / price) carried back. Share issuance inside the window is not captured."
    - "Screener lists only companies that exist today; delisted names have no shares and no turnover (survivorship bias). See coverage_report()."
    - "Universe is top-{top_n} by trailing traded value, not by market cap and not an official index."
    - "Corporate-action neutralisation is a heuristic threshold on daily gross return; see ca_events."
    - "Prices are raw bhavcopy, price return only, no dividends."
    - "Free-float fraction is a current promoter-holding snapshot."
"""
