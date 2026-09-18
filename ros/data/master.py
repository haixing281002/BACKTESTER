"""The master universe: one long CSV you build, parsed into what the engine needs.

THE SHAPE

One row per (date, security). Columns for whatever you have:

    date,security_id,symbol,adj_close,in_universe,free_float_mcap,adv,sector
    2015-01-01,INE001A01036,HDFCBANK,912.4,1,412000,1840,financials
    2015-01-01,INE002A01018,RELIANCE,881.0,1,905000,3110,energy

That is the format a human can actually assemble from several sources, and it
is the one that survives a stock listing, delisting, being renamed or dropping
out of the index -- all of which are just rows that stop, or an `in_universe`
that flips to 0.

Wide panels (dates x securities, one file per field) are what the engine wants
and what this module produces. They are not what you should MAINTAIN: adding a
security to a wide file means editing every row.

WHAT THIS MODULE IS REALLY FOR

Parsing is the easy half. The hard half is refusing a file that would produce a
confident wrong answer, and there are exactly three ways that happens:

  1. The file contains only names that are still listed. Every result is then
     survivorship-inflated and nothing downstream can tell. `diagnose()` checks
     the signature and says so loudly.
  2. `in_universe` is missing, so the code assumes everyone was always a member.
     That is the same bias wearing different clothes.
  3. Duplicate (date, security) rows. A pivot silently keeps one of them, and
     which one depends on row order.

All three are refused or flagged here rather than discovered in a report.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


class MasterUniverseError(ValueError):
    """A master file that cannot be trusted. Never downgraded to a warning."""


# Spelling variants, because you will assemble this from several sources and
# nobody agrees on a name. Matching is case-insensitive and ignores separators.
ALIASES: Dict[str, List[str]] = {
    "date": ["date", "tradedate", "trade_date", "timestamp", "dt", "asof", "as_of"],
    "security_id": ["security_id", "securityid", "secid", "id", "isin",
                    "permno", "entity_id"],
    "symbol": ["symbol", "ticker", "scrip", "nsesymbol", "nse_symbol", "code"],
    "adj_close": ["adj_close", "adjclose", "adjusted_close", "close_adj",
                  "px_adj", "adjusted_price", "adj_price"],
    "close": ["close", "close_price", "px_close", "closing_price", "price"],
    "in_universe": ["in_universe", "in_index", "member", "membership",
                    "is_member", "index_member", "active", "is_active"],
    "free_float_mcap": ["free_float_mcap", "ff_mcap", "free_float_market_cap",
                        "ffmc", "freefloat_mcap", "float_mcap"],
    "market_cap": ["market_cap", "mcap", "total_mcap", "full_mcap"],
    "adv": ["adv", "traded_value", "turnover_value", "value_traded",
            "traded_val", "turnover"],
    "volume": ["volume", "qty", "shares_traded", "traded_qty"],
    "sector": ["sector", "industry", "gics_sector", "macro_sector"],
}
REQUIRED = ("date", "security_id")
PRICE_FIELDS = ("adj_close", "close")


def _norm(name: str) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def _resolve_columns(cols) -> Dict[str, str]:
    """Map canonical field -> the actual column name in the file."""
    lookup = {_norm(c): c for c in cols}
    found = {}
    for canon, spellings in ALIASES.items():
        for sp in spellings:
            if _norm(sp) in lookup:
                found[canon] = lookup[_norm(sp)]
                break
    return found


def _to_bool(s: pd.Series) -> pd.Series:
    """Coerce a membership column without guessing.

    A membership flag arrives as 1/0, True/False, Y/N or TRUE/FALSE depending on
    who exported it. Anything outside those is an error rather than a guess:
    silently reading an unrecognised value as False would drop a stock from the
    universe and look exactly like a delisting.
    """
    if s.dtype == bool:
        return s
    TRUE = {"1", "1.0", "true", "t", "y", "yes", "in", "active", "member"}
    FALSE = {"0", "0.0", "false", "f", "n", "no", "out", "inactive", "", "nan", "none"}
    txt = s.astype(str).str.strip().str.lower()
    bad = sorted(set(txt) - TRUE - FALSE)
    if bad:
        raise MasterUniverseError(
            f"membership column has values that are neither true nor false: "
            f"{bad[:8]}. Use 1/0, TRUE/FALSE or Y/N. Guessing here would drop "
            f"securities from the universe and look identical to a delisting.")
    return txt.isin(TRUE)


@dataclass
class MasterDiagnosis:
    n_securities: int
    n_dates: int
    date_min: str
    date_max: str
    alive_at_end: int
    never_left: int
    has_membership: bool
    fields: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)

    @property
    def survivor_ratio(self) -> float:
        """Share of all securities that still have data on the final date.

        A real 20-year Indian panel is well under 1.0: companies delist, merge
        and fall out of the index. Close to 1.0 means the file was built from a
        current constituent list and back-filled, which inflates every result.
        """
        return self.alive_at_end / self.n_securities if self.n_securities else 0.0

    @property
    def usable(self) -> bool:
        return not self.blockers

    def render(self) -> str:
        L = ["  MASTER UNIVERSE",
             f"    securities      : {self.n_securities:,}",
             f"    trading days    : {self.n_dates:,}   {self.date_min} -> {self.date_max}",
             f"    fields present  : {', '.join(self.fields)}",
             f"    membership col  : {'yes' if self.has_membership else 'NO'}",
             f"    alive on last day: {self.alive_at_end:,} of {self.n_securities:,}"
             f"  ({self.survivor_ratio:.0%})"]
        for b in self.blockers:
            L.append(f"    BLOCKING: {b}")
        for w in self.warnings:
            L.append(f"    warning : {w}")
        return "\n".join(L)


@dataclass
class MasterUniverse:
    """Wide panels the engine consumes, plus the diagnosis of where they came from."""
    prices: pd.DataFrame
    membership: pd.DataFrame
    adv: Optional[pd.DataFrame] = None
    free_float_mcap: Optional[pd.DataFrame] = None
    market_cap: Optional[pd.DataFrame] = None
    sector: Optional[pd.DataFrame] = None
    symbols: Optional[pd.DataFrame] = None
    diagnosis: Optional[MasterDiagnosis] = None
    source: str = ""

    @property
    def securities(self) -> List[str]:
        return list(self.prices.columns)

    def restrict(self, start: Optional[str] = None,
                 end: Optional[str] = None) -> "MasterUniverse":
        """Trim to a date window, dropping securities with no history left."""
        def cut(df):
            if df is None:
                return None
            out = df.loc[start:end] if (start or end) else df
            return out
        px = cut(self.prices)
        keep = [c for c in px.columns if px[c].notna().any()]
        return MasterUniverse(
            prices=px[keep], membership=cut(self.membership)[keep],
            adv=cut(self.adv)[keep] if self.adv is not None else None,
            free_float_mcap=(cut(self.free_float_mcap)[keep]
                             if self.free_float_mcap is not None else None),
            market_cap=(cut(self.market_cap)[keep]
                        if self.market_cap is not None else None),
            sector=cut(self.sector)[keep] if self.sector is not None else None,
            symbols=cut(self.symbols)[keep] if self.symbols is not None else None,
            diagnosis=self.diagnosis, source=self.source)


def load_master(path: str, require_membership: bool = True,
                strict: bool = True) -> MasterUniverse:
    """Parse a long master-universe CSV into engine-ready panels.

    `strict` refuses a file whose diagnosis has blockers. Turn it off only to
    inspect a file you already know is broken -- never to run a backtest.
    """
    if not os.path.exists(path):
        raise MasterUniverseError(f"no such master file: {path}")
    df = (pd.read_csv(path) if path.lower().endswith((".csv", ".txt", ".gz"))
          else pd.read_parquet(path) if path.lower().endswith(".parquet")
          else pd.read_excel(path))
    if df.empty:
        raise MasterUniverseError(f"{path} has no rows")

    cols = _resolve_columns(df.columns)
    missing = [r for r in REQUIRED if r not in cols]
    if missing:
        raise MasterUniverseError(
            f"{path}: cannot find column(s) for {missing}.\n"
            f"  columns present: {list(df.columns)[:15]}\n"
            f"  accepted spellings: "
            + "; ".join(f"{m} = {'/'.join(ALIASES[m][:5])}" for m in missing))
    price_col = next((cols[f] for f in PRICE_FIELDS if f in cols), None)
    if price_col is None:
        raise MasterUniverseError(
            f"{path}: no price column. One of {ALIASES['adj_close'][:4]} or "
            f"{ALIASES['close'][:3]} is required.")

    df["_date"] = pd.to_datetime(df[cols["date"]], errors="coerce")
    unparsed = int(df["_date"].isna().sum())
    if unparsed:
        raise MasterUniverseError(
            f"{path}: {unparsed:,} rows have an unparseable date. Dropping them "
            f"would silently shorten the sample, so fix the file instead.")
    df["_sec"] = df[cols["security_id"]].astype(str).str.strip()

    dup = df.duplicated(["_date", "_sec"]).sum()
    if dup:
        raise MasterUniverseError(
            f"{path}: {dup:,} duplicate (date, security) rows. A pivot keeps one "
            f"of them and which one depends on row order, so the backtest would "
            f"not be reproducible. De-duplicate before loading.")

    def panel(field_name, coerce=None):
        c = cols.get(field_name)
        if c is None:
            return None
        vals = df[c]
        if coerce is not None:
            vals = coerce(vals)
        out = df.assign(_v=vals).pivot(index="_date", columns="_sec", values="_v")
        return out.sort_index()

    prices = df.assign(_v=pd.to_numeric(df[price_col], errors="coerce")) \
               .pivot(index="_date", columns="_sec", values="_v").sort_index()

    has_membership = "in_universe" in cols
    if has_membership:
        membership = panel("in_universe", _to_bool).fillna(False).astype(bool)
    else:
        # Present in the file on a date = in the universe on that date. This is
        # the best available reading, and it is only correct if the file really
        # does omit a security on dates it was not a member. Flagged loudly.
        membership = prices.notna()

    diag = diagnose(prices, membership, has_membership,
                    fields=sorted(cols), require_membership=require_membership)
    if strict and not diag.usable:
        raise MasterUniverseError(
            f"{path} cannot be used as it stands:\n" + diag.render())

    mu = MasterUniverse(
        prices=prices, membership=membership,
        adv=panel("adv", lambda s: pd.to_numeric(s, errors="coerce")),
        free_float_mcap=panel("free_float_mcap",
                              lambda s: pd.to_numeric(s, errors="coerce")),
        market_cap=panel("market_cap", lambda s: pd.to_numeric(s, errors="coerce")),
        sector=panel("sector"), symbols=panel("symbol"),
        diagnosis=diag, source=path)
    return mu


def diagnose(prices: pd.DataFrame, membership: pd.DataFrame,
             has_membership: bool, fields: List[str],
             require_membership: bool = True) -> MasterDiagnosis:
    """Everything that decides whether this file can support an honest backtest."""
    n_sec = prices.shape[1]
    alive_end = int(prices.iloc[-1].notna().sum()) if len(prices) else 0
    never_left = int((membership.sum(axis=0) == len(membership)).sum())

    d = MasterDiagnosis(
        n_securities=n_sec, n_dates=len(prices),
        date_min=str(prices.index.min().date()) if len(prices) else "",
        date_max=str(prices.index.max().date()) if len(prices) else "",
        alive_at_end=alive_end, never_left=never_left,
        has_membership=has_membership, fields=fields)

    if not has_membership:
        msg = ("no membership column. Presence in the file is being read as "
               "membership, which is correct ONLY if the file genuinely omits a "
               "security on dates it was not in the index. If it instead carries "
               "every security on every date, every backtest built on it will "
               "select from names that were not investable at the time.")
        (d.blockers if require_membership else d.warnings).append(msg)

    # The survivorship signature. A real long Indian panel loses names.
    if n_sec and d.survivor_ratio > 0.98 and len(prices) > 500:
        d.blockers.append(
            f"{d.survivor_ratio:.0%} of securities still have data on the final "
            f"date. Over {len(prices):,} trading days that is not what a real "
            f"universe looks like -- companies delist, merge and fall out. This "
            f"file was almost certainly built from a CURRENT constituent list and "
            f"back-filled, which inflates every result and cannot be corrected "
            f"downstream. Rebuild it from point-in-time membership.")
    elif n_sec and d.survivor_ratio > 0.9 and len(prices) > 500:
        d.warnings.append(
            f"{d.survivor_ratio:.0%} of securities are alive at the end. High for "
            f"a long sample; confirm the dead names really are in the file.")

    if n_sec and never_left == n_sec and len(prices) > 500:
        d.warnings.append(
            "no security ever leaves the universe. Index reconstitution alone "
            "should produce exits over this span.")

    if "adv" not in fields:
        d.warnings.append("no traded-value column: capacity cannot be assessed, "
                          "and turnover_capacity will have to be given ADV by hand.")
    if "free_float_mcap" not in fields and "market_cap" in fields:
        d.warnings.append("market cap present but not FREE FLOAT. Indian promoter "
                          "holdings are large, so total cap overstates investable "
                          "size and flatters capacity.")

    all_na = [c for c in prices.columns if prices[c].notna().sum() == 0]
    if all_na:
        d.warnings.append(f"{len(all_na)} securities have no price at all: "
                          f"{all_na[:5]}")
    return d


def engine_inputs(mu: MasterUniverse, assets: Optional[List[str]] = None):
    """(prices, membership) ready for Backtester(..., membership=...).

    Securities with no price at all are dropped: the engine cannot hold what it
    cannot mark, and carrying an all-NaN column only makes the eligible count
    look larger than it is.
    """
    px = mu.prices if assets is None else mu.prices[assets]
    keep = [c for c in px.columns if px[c].notna().any()]
    return px[keep], mu.membership[keep].reindex(px.index).fillna(False).astype(bool)


# ---------------------------------------------------------------------------
# CLI: inspect a master file before you build anything on it.
#
#     python -m ros.data.master data/raw/master/universe.csv
#
# Run this the moment a file lands. A master universe is the foundation of every
# number that follows, and the failures that matter are invisible once a
# backtest has run on it -- the report looks the same either way.
# ---------------------------------------------------------------------------
def _cli(argv=None) -> int:
    import argparse
    import sys

    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(
        description="Inspect a master universe file. Reads no other data.")
    ap.add_argument("path", help="the master CSV/parquet to inspect")
    ap.add_argument("--allow-no-membership", action="store_true",
                    help="treat a missing membership column as a warning")
    args = ap.parse_args(argv)

    print("=" * 92)
    print(f"  MASTER UNIVERSE CHECK   {args.path}")
    print("=" * 92)
    try:
        mu = load_master(args.path, require_membership=not args.allow_no_membership,
                         strict=False)
    except MasterUniverseError as e:
        print()
        print("  THIS FILE CANNOT BE PARSED")
        print()
        for line in str(e).splitlines():
            print(f"    {line}")
        print()
        print("=" * 92)
        return 1

    d = mu.diagnosis
    print()
    print(d.render())
    print()
    for name, panel in (("prices", mu.prices), ("membership", mu.membership),
                        ("adv", mu.adv), ("free float", mu.free_float_mcap),
                        ("market cap", mu.market_cap), ("sector", mu.sector)):
        if panel is None:
            print(f"    {name:<12} -- absent")
        else:
            filled = float(panel.notna().mean().mean()) if panel.size else 0.0
            print(f"    {name:<12} {panel.shape[0]:,} x {panel.shape[1]:,}"
                  f"   {filled:.0%} populated")

    print()
    print("=" * 92)
    if not d.usable:
        print("  NOT USABLE AS IT STANDS")
        print()
        print("  The blockers above are not style points. Each one produces a")
        print("  backtest that looks completely normal and is wrong in a")
        print("  direction that flatters the strategy.")
        print("=" * 92)
        return 1

    print("  USABLE")
    print()
    print("  Declare it in data/raw/MANIFEST.yaml so its provenance travels with")
    print("  every result computed from it:")
    print()
    print("    master:")
    print(f"      file: {os.path.relpath(args.path, 'data/raw') if args.path.startswith('data/raw') else args.path}")
    print("      pit_status: point_in_time     # <- the field that decides whether")
    print("                                    #    a LIVE claim may rest on this")
    print('      licence: "<who owns this, and what may we do with it>"')
    print("      caveats:")
    print('        - "<what would mislead someone reading a result built on this>"')
    print("=" * 92)
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
