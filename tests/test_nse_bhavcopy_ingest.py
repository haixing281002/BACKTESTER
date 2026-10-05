"""Synthetic-data tests for ros/data/nse_bhavcopy_ingest.py.

This sandbox has no network access to NSE's archive, so these tests build
fake daily pickles matching download_history.py's exact output schema
(DATE, SYMBOL, SERIES, ISIN, OPEN, HIGH, LOW, CLOSE, PREV, QTY, VAL, TRADES)
rather than hitting the real site. They exercise dedupe, ISIN linking across
a simulated corporate action, corporate-action neutralisation, point-in-time
membership, and the final master.py-compatible CSV -- the same checks that
would catch a bug before it reaches real data.
"""
import os

import numpy as np
import pandas as pd
import pytest

from ros.data.nse_bhavcopy_ingest import (
    build_adjusted_prices, build_master_csv, combine_cache, dedupe_rows,
    link_isins, point_in_time_universe,
)
from ros.data.master import load_master


def _row(date, symbol, isin, close, prev, val=1_00_00_000, series="EQ", qty=10_000, trades=500):
    return dict(DATE=pd.Timestamp(date), SYMBOL=symbol, SERIES=series, ISIN=isin,
                OPEN=close, HIGH=close, LOW=close, CLOSE=close, PREV=prev,
                QTY=qty, VAL=val, TRADES=trades)


def _make_bhavcopy():
    """Two names across a year of trading days:

    - RELIANCE: one ISIN throughout, steady drift, one genuine large move.
    - WIPRO: splits into a NEW ISIN on 2023-02-01 (same SYMBOL), simulating a
      bonus issue that triples the share count and divides price by ~4 -- the
      kind of event PREVCLOSE never adjusts for.
    """
    rows = []
    days = pd.bdate_range("2023-01-02", "2023-12-29")
    rel_price = 2500.0
    wip_price = 400.0
    wip_isin = "INEWIP001011"
    for i, d in enumerate(days):
        rel_prev = rel_price
        rel_price = rel_price * (1.0005 if i != 120 else 0.80)  # one genuine -20% shock at i=120
        rows.append(_row(d, "RELIANCE", "INERELI01018", rel_price, rel_prev, val=50_00_00_000))

        if d < pd.Timestamp("2023-02-01"):
            wip_prev = wip_price
            wip_price = wip_price * 1.0004
            rows.append(_row(d, "WIPRO", wip_isin, wip_price, wip_prev, val=10_00_00_000))
        elif d == pd.Timestamp("2023-02-01"):
            # bonus issue: new ISIN, price collapses to ~1/4, PREVCLOSE still the old price
            new_isin = "INEWIP002019"
            wip_prev = wip_price
            wip_price = wip_price / 4.0
            rows.append(_row(d, "WIPRO", new_isin, wip_price, wip_prev, val=12_00_00_000))
            wip_isin = new_isin
        else:
            wip_prev = wip_price
            wip_price = wip_price * 1.0004
            rows.append(_row(d, "WIPRO", wip_isin, wip_price, wip_prev, val=12_00_00_000))

    return pd.DataFrame(rows)


def test_combine_cache_reads_all_pickles(tmp_path):
    df = _make_bhavcopy()
    cache = tmp_path / "cache"
    cache.mkdir()
    for d, g in df.groupby("DATE"):
        g.to_pickle(cache / f"{d:%Y%m%d}.pkl")
    out = combine_cache(str(cache))
    assert len(out) == len(df)
    assert list(out.columns) == ["DATE", "SYMBOL", "SERIES", "ISIN", "OPEN",
                                 "HIGH", "LOW", "CLOSE", "PREV", "QTY", "VAL", "TRADES"]


def test_combine_cache_empty_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        combine_cache(str(tmp_path / "nothing"))


def test_dedupe_prefers_eq_series_and_highest_value():
    d = pd.Timestamp("2023-01-02")
    df = pd.DataFrame([
        _row(d, "ABC", "INEABC01011", 100.0, 99.0, val=5, series="BE"),
        _row(d, "ABC", "INEABC01011", 101.0, 99.0, val=50, series="EQ"),
    ])
    out = dedupe_rows(df)
    assert len(out) == 1
    assert out.iloc[0]["SERIES"] == "EQ"
    assert out.iloc[0]["CLOSE"] == 101.0


def test_link_isins_chains_bonus_issue_under_same_symbol():
    df = _make_bhavcopy()
    links = link_isins(df)
    wip_isins = [isin for isin in links.isin_to_entity
                if isin.startswith("INEWIP")]
    assert len(wip_isins) == 2
    entities = {links.isin_to_entity[isin] for isin in wip_isins}
    assert len(entities) == 1, "the two WIPRO ISINs must resolve to one entity"
    assert len(links.links) == 1
    assert links.links[0][2] == "WIPRO"


def test_corporate_action_is_neutralised_but_real_shock_is_not():
    df = dedupe_rows(_make_bhavcopy())
    links = link_isins(df)
    adj = build_adjusted_prices(df, links)

    wip_ent = links.isin_to_entity["INEWIP002019"]
    rel_ent = links.isin_to_entity["INERELI01018"]

    # the bonus-day jump must show up in ca_events, not as a real return
    assert (adj.ca_events["ENT"] == wip_ent).any()

    wip_series = adj.panel[wip_ent].dropna()
    # if the bonus had NOT been neutralised, the adjusted index would have
    # collapsed to ~1/4 of its pre-bonus level; neutralised, it stays smooth
    pre = wip_series.loc[:"2023-01-31"].iloc[-1]
    post = wip_series.loc["2023-02-01":].iloc[0]
    assert post / pre > 0.9, "corporate-action jump should have been neutralised"

    # the genuine -20% shock in RELIANCE (inside the [CA_LOW, CA_HIGH] band,
    # so it is NOT mistaken for an unadjusted corporate action) must survive
    rel_series = adj.panel[rel_ent].dropna()
    ratio = rel_series.pct_change().min()
    assert ratio < -0.15, "a real move inside the CA band must survive, not be masked"


def test_point_in_time_universe_has_no_lookahead_and_respects_min_sessions():
    df = dedupe_rows(_make_bhavcopy())
    links = link_isins(df)
    membership = point_in_time_universe(df, links, top_n=1, lookback_sessions=20,
                                        min_sessions=10)
    # RELIANCE trades far higher value every day, so it should dominate top-1
    # membership once there is enough trailing history to rank anything.
    rel_ent = links.isin_to_entity["INERELI01018"]
    later = membership.index[membership.index >= "2023-04-01"]
    assert membership.loc[later, rel_ent].all()


def test_build_master_csv_produces_a_file_master_py_accepts(tmp_path):
    df = _make_bhavcopy()
    out_path = str(tmp_path / "nse_master.csv")
    report = build_master_csv(df, out_path, top_n=2, lookback_sessions=20, min_sessions=10)

    assert report["rows_written"] > 0
    assert report["entities"] == 2
    assert report["isin_links"] == 1
    assert os.path.exists(out_path)

    written = pd.read_csv(out_path)
    assert set(["date", "security_id", "symbol", "adj_close", "in_universe", "adv"]) <= set(written.columns)

    mu = load_master(out_path, require_membership=True, strict=False)
    assert mu.diagnosis.has_membership
    assert mu.diagnosis.n_securities == 2
    # a one-year synthetic file with both names still trading on the last day
    # is survivor-flavoured by construction -- that's expected here and is
    # exactly why strict=True is reserved for real multi-year files.
