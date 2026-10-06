"""Offline tests for the bhavcopy downloader and the bhavcopy + Screener panel.

No network: the downloader is driven by a fake session, and the Screener folder is built by hand
in a temp directory using the same files screener_fetch.py writes (meta.json, secs.pkl).
"""
import io
import json
import os
import pickle
import zipfile
from datetime import date

import numpy as np
import pandas as pd
import pytest

from ros.data import nse_bhavcopy_download as dl
from ros.data.bhavcopy_screener_panel import (
    ALLOWED_SOURCES, assert_sources, build_turnover_panel, coverage_report, screener_shares,
    universe_symbols,
)

OLD_CSV = ("SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,\n"
           "AAA,EQ,10,11,9,10.5,10.4,10,1000,10500,06-OCT-2021,50,INE000A01011,\n"
           "BOND,GS,100,100,100,100,100,100,5,500,06-OCT-2021,1,IN0020010081,\n"
           "BBB,BE,20,21,19,20.5,20.4,20,2000,41000,06-OCT-2021,70,INE000B01012,\n"
           "ETF,EQ,5,5,5,5,5,5,9,45,06-OCT-2021,2,INF000C01013,\n")
UDIFF_CSV = ("TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,"
             "OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,"
             "ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4\n"
             "2024-07-08,2024-07-08,CM,NSE,STK,1,INE000A01011,AAA,EQ,,,,,A,10,11,9,10.5,10.4,10,,10.5,,,1000,10500,50,F1,1,,,,,\n"
             "2024-07-08,2024-07-08,CM,NSE,STK,2,IN0020200104,SGB,GB,,,,,G,100,100,100,100,100,100,,100,,,5,500,1,F1,1,,,,,\n")


def _zip(text):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("x.csv", text)
    return b.getvalue()


class _Resp:
    def __init__(self, status, content=b""):
        self.status_code, self.content = status, content


class _Session:
    """Maps a URL substring to a status/content; anything else is 404."""
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        for key, resp in self.routes.items():
            if key in url:
                return resp
        return _Resp(404)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(dl.time, "sleep", lambda s: None)


def test_parse_old_and_mainboard_filter():
    df = dl.keep_mainboard(dl.parse_old(OLD_CSV))
    assert list(df["SYMBOL"]) == ["AAA", "BBB"]          # GS bond and INF ETF dropped
    assert list(df.columns) == dl.RAW_COLS
    assert df["DATE"].iloc[0] == pd.Timestamp("2021-10-06")
    assert df.loc[0, "PREV"] == 10 and df.loc[0, "VAL"] == 10500


def test_parse_udiff_matches_schema():
    df = dl.keep_mainboard(dl.parse_udiff(UDIFF_CSV))
    assert list(df["SYMBOL"]) == ["AAA"]                  # the gold bond (series GB, ISIN IN00) is dropped
    assert list(df.columns) == dl.RAW_COLS
    assert df.loc[0, "QTY"] == 1000 and df.loc[0, "VAL"] == 10500


def test_urls():
    assert dl.url_old(date(2023, 1, 2)).endswith("/2023/JAN/cm02JAN2023bhav.csv.zip")
    assert dl.url_udiff(date(2024, 7, 8)).endswith("BhavCopy_NSE_CM_0_0_0_20240708_F_0000.csv.zip")


def test_fetch_day_picks_format_by_date_and_falls_back():
    s = _Session({"cm06OCT2021bhav": _Resp(200, _zip(OLD_CSV))})
    status, frame = dl.fetch_day(date(2021, 10, 6), s)
    assert status == "ok" and len(frame) == 2
    # a post cut-over date asks UDiFF first
    s2 = _Session({"BhavCopy_NSE_CM_0_0_0_20240708": _Resp(200, _zip(UDIFF_CSV))})
    status, frame = dl.fetch_day(date(2024, 7, 8), s2)
    assert status == "ok" and "20240708" in s2.calls[0]


def test_404_on_both_is_nontrading_but_403_is_an_error_not_a_holiday():
    assert dl.fetch_day(date(2021, 10, 2), _Session({}))[0] == "nontrading"
    blocked = _Session({"nsearchives": _Resp(403)})
    assert dl.fetch_day(date(2021, 10, 6), blocked)[0] == "error"


def test_download_range_is_resumable_and_records_holidays(tmp_path):
    s = _Session({"cm06OCT2021bhav": _Resp(200, _zip(OLD_CSV))})
    cache = str(tmp_path / "cache")
    out = dl.download_range(date(2021, 10, 4), date(2021, 10, 8), cache, delay=0, session=s)
    assert out["ok"] == 1 and out["nontrading"] == 4          # only 06 Oct is served in this fake
    assert sorted(os.listdir(cache)) == ["2021-10-06.pkl", "_nontrading.txt"]
    n_calls = len(s.calls)
    out2 = dl.download_range(date(2021, 10, 4), date(2021, 10, 8), cache, delay=0, session=s)
    assert out2["skipped_existing"] == 1 and out2["nontrading"] == 4
    assert len(s.calls) == n_calls                             # nothing asked twice


def test_download_range_stops_when_blocked(tmp_path):
    s = _Session({"nsearchives": _Resp(403)})
    out = dl.download_range(date(2021, 10, 4), date(2021, 12, 31), str(tmp_path / "c"), delay=0, session=s, max_errors=3)
    assert out["error"] == 3 and out["ok"] == 0


# ------------------------------------------------------------------ panel
def _bhav(days, sym_isin_prices, vals):
    rows = []
    for i, d in enumerate(days):
        for (sym, isin), prices in sym_isin_prices.items():
            close = prices[i]
            prev = prices[i - 1] if i else close
            rows.append(dict(DATE=d, SYMBOL=sym, SERIES="EQ", ISIN=isin, OPEN=close, HIGH=close, LOW=close,
                             CLOSE=close, PREV=prev, QTY=1000, VAL=vals[sym], TRADES=10))
    return pd.DataFrame(rows)


def _scr(tmp, sym, mcap_cr, price, face=10.0, ec=None, promoter=50.0):
    d = tmp / sym
    d.mkdir(parents=True)
    json.dump({"symbol": sym, "view": "consolidated", "mcap_cr": mcap_cr, "price": price,
               "headline_raw": {"Face Value": f"Rs {face}"}}, open(d / "meta.json", "w", encoding="utf-8"))
    bs = pd.DataFrame({"x": ["Equity Capital", "Reserves"], "Mar 2025": [ec if ec is not None else mcap_cr / price * face, 5.0]})
    sh = pd.DataFrame({"x": ["Promoters +", "Public +"], "Jun 2025": [f"{promoter}%", f"{100 - promoter}%"]})
    pickle.dump({"balance-sheet": [bs], "shareholding": [sh]}, open(d / "secs.pkl", "wb"))


def test_assert_sources_allows_only_the_two():
    assert ALLOWED_SOURCES == ("nse_bhavcopy", "screener")
    assert_sources(["screener", "nse_bhavcopy"])
    with pytest.raises(ValueError):
        assert_sources(["nse_bhavcopy", "accord"])


def test_screener_shares_reads_what_fetch_writes(tmp_path):
    _scr(tmp_path, "AAA", mcap_cr=1000.0, price=100.0, face=10.0, promoter=60.0)
    out = screener_shares(str(tmp_path), ["AAA", "MISSING"])
    r = out.iloc[0]
    assert len(out) == 1 and r["symbol"] == "AAA"
    assert r["shares_cr"] == pytest.approx(10.0)                 # 1000 / 100
    assert r["free_float_frac"] == pytest.approx(0.4)
    assert r["shares_ratio"] == pytest.approx(1.0)               # equity capital / face value agrees


def test_rupee_turnover_does_not_move_at_a_split_and_missing_screener_is_nan(tmp_path):
    days = pd.bdate_range("2023-01-02", periods=120)
    price_split = np.r_[np.full(60, 400.0), np.full(60, 100.0)]  # 4:1 split at day 60 (raw price / 4)
    price_flat = np.full(120, 50.0)
    df = _bhav(days, {("SPLIT", "INE111A01011"): price_split, ("FLAT", "INE222B01012"): price_flat,
                      ("GONE", "INE333C01013"): price_flat * 2},
               {"SPLIT": 5e8, "FLAT": 2e8, "GONE": 1e8})
    # SPLIT and FLAT are listed on Screener (current shares), GONE is not (delisted)
    _scr(tmp_path, "SPLIT", mcap_cr=2000.0, price=100.0)     # 20 crore shares on today's basis
    _scr(tmp_path, "FLAT", mcap_cr=500.0, price=50.0)
    shares = screener_shares(str(tmp_path), ["SPLIT", "FLAT", "GONE"])
    panel = build_turnover_panel(df, shares, top_n=3, window=10, lookback_sessions=20, min_sessions=10)
    s = panel[panel["symbol"] == "SPLIT"].set_index("date")["turnover_window"].dropna()
    before, after = s.iloc[10], s.iloc[-1]                     # one window before the split, one after
    assert before == pytest.approx(after, rel=1e-6)            # same daily value, same market cap in rupees
    # mcap is continuous in rupees across the split (price x shares on today's basis)
    m = panel[panel["symbol"] == "SPLIT"].set_index("date")["mcap_cr_est"].dropna()
    assert m.iloc[0] == pytest.approx(m.iloc[-1], rel=1e-6)
    # no Screener page -> no shares -> turnover NaN, and the coverage report says so
    assert panel[panel["symbol"] == "GONE"]["turnover_window"].isna().all()
    cov = coverage_report(panel)
    assert cov["entities_without_screener_shares"] == 1
    assert 0 < cov["share_of_universe_stock_days_with_turnover"] < 1


def test_universe_symbols_lists_everyone_who_was_ever_in(tmp_path):
    days = pd.bdate_range("2023-01-02", periods=80)
    df = _bhav(days, {("AAA", "INE111A01011"): np.full(80, 10.0), ("BBB", "INE222B01012"): np.full(80, 20.0)},
               {"AAA": 3e8, "BBB": 1e8})
    syms = universe_symbols(df, top_n=2, lookback_sessions=20, min_sessions=10)
    assert syms == ["AAA", "BBB"]
