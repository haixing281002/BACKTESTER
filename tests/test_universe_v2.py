# Quant AI Researcher by Harshil Pahuja
"""The NIFTY 500 universe v2 (data/processed/universe/) and the card field that selects it.

Every test here reads the committed artifacts; none needs the Ace file. The tests that compare v1 with v2 need the
holdings workbook and are skipped where it is absent.
"""
from __future__ import annotations

import itertools
import json
import os

import pandas as pd
import pytest
import yaml

from ros.data import nifty500, sources

UNI = nifty500.UNIVERSE_DIR
HAVE_V2 = os.path.exists(nifty500.V2_SPELLS)
HAVE_WB = os.path.isfile(sources.NIFTY500_HOLDINGS_XLSX)
pytestmark = pytest.mark.skipif(not HAVE_V2, reason="universe v2 not built on this machine")


def _csv(name, **kw):
    return pd.read_csv(os.path.join(UNI, name), skiprows=1, keep_default_na=False, **kw)


@pytest.fixture(scope="module")
def spells():
    return nifty500.load_membership(source="nifty500_members_v2")


@pytest.fixture(scope="module")
def daily():
    p = os.path.join(UNI, "nifty500_members_v2.parquet")
    if not os.path.exists(p):
        pytest.skip("daily parquet not on this machine")
    return pd.read_parquet(p)


def _members_on(spells, d):
    d = pd.Timestamp(d)
    x = spells[(spells["start_date"] <= d) & (spells["end_date"].isna() | (spells["end_date"] > d))]
    return set(x["isin"])


def test_loader_reads_v2_and_refuses_unknown_sources(spells):
    assert list(spells.columns) == ["isin", "symbol", "company_name", "start_date", "end_date", "source", "flags"]
    assert spells["isin"].str.fullmatch(r"IN[A-Z0-9]{10}").all(), "every v2 member is keyed by an ISIN"
    with pytest.raises(nifty500.MembershipError):
        nifty500.load_membership(source="bogus")
    with pytest.raises(nifty500.MembershipError):
        nifty500.load_membership(index="NIFTY 50", source="nifty500_members_v2")


def test_500_members_on_every_date_or_a_listed_exception(daily):
    """500 or 501 (TATAMTRDVR was a separate line Apr 2016 to Aug 2024) on every trading day from 2014, or a date
    inside data/processed/universe/member_count_exceptions.csv with its reason."""
    n = daily[daily["date"] >= "2014-01-01"].groupby("date").size()
    exc = _csv("member_count_exceptions.csv", parse_dates=["from", "to"])
    bad = []
    for d, k in n.items():
        if k in (500, 501):
            continue
        if not ((exc["from"] <= d) & (exc["to"] >= d) & (exc["count"].astype(int) == k)).any():
            bad.append((str(d.date()), int(k)))
    assert not bad, f"member counts with no listed exception: {bad[:10]}"


def test_no_duplicate_isin_on_any_date(daily):
    assert not daily.duplicated(["date", "isin"]).any()


def test_spells_do_not_overlap_per_isin(spells):
    s = spells.sort_values(["isin", "start_date"])
    prev_end = s.groupby("isin")["end_date"].shift()
    overlap = s[prev_end.notna() & (s["start_date"] < prev_end)]
    assert overlap.empty, overlap.head()


def test_no_member_is_priced_after_ace_stops_pricing_it(daily):
    """ace_has_close is the daily table's own record of an Ace close on that date; it can never be True after the
    security master's last date for the ISIN (nothing is invented after a delisting)."""
    try:
        from ros.data import ace
        sm = ace.security_master()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"security master not available: {e}")
    last = sm[sm["isin"].notna()].drop_duplicates("isin").set_index("isin")["last_date"]
    x = daily[daily["ace_has_close"]].copy()
    x["last"] = pd.to_datetime(x["isin"].map(last))
    late = x[x["last"].notna() & (x["date"] > x["last"])]
    assert late.empty, late.head()


def test_gap_membership_changes_only_on_approved_dates(daily):
    """Inside 2017-2018 a name enters or leaves only on the first gap day or on an apply_date of the approved shift
    table (plus the Dalmia Bharat fill, whose dates come from the NSE spell). Nothing is effective before its date."""
    shift = _csv("reports/shift_table_approved.csv", parse_dates=["al_date", "nse_effective", "apply_date"])
    assert (shift["apply_date"] <= shift["al_date"]).all(), "a change is never applied later than Alpha Lab saw it"
    assert (shift["nse_effective"] == shift["apply_date"]).all(), "every change in the approved table has an NSE date"
    gap = daily[(daily["date"] >= "2017-01-01") & (daily["date"] <= "2018-12-31")]
    days = sorted(gap["date"].unique())
    by = gap.groupby("date")["isin"].apply(set)
    allowed = set(shift["apply_date"]) | {days[0]}
    stray = []
    for prev, d in itertools.pairwise(days):
        if by[d] != by[prev] and d not in allowed:
            changed = (by[d] ^ by[prev]) - {i for i in by[d] ^ by[prev] if "dalmia" in str(gap.loc[gap["isin"] == i, "flags"].iloc[0]).lower()}
            if changed:
                stray.append((str(pd.Timestamp(d).date()), sorted(changed)[:5]))
    assert not stray, stray[:5]


def test_gap_sources_are_alpha_lab_or_the_dalmia_fill(daily):
    gap = daily[(daily["date"] >= "2017-01-01") & (daily["date"] <= "2018-12-31")]
    assert set(gap["source"]) == {"alpha_lab_gap", "nse_fill"}
    assert set(gap.loc[gap["source"] == "nse_fill", "symbol"]) == {"DALMIABHA"}


@pytest.mark.skipif(not HAVE_WB, reason="holdings workbook not on this machine")
def test_v1_vs_v2_differences_equal_the_reconciliation_table(spells, daily):
    """Recomputed from both loaders, not read from the build: on every workbook snapshot date (taken on the first
    trading day on or after it, since quarter-ends fall on weekends), the names only in v2 and only in v1 are exactly
    the rows of reports/v1_vs_v2_diff.csv for that date."""
    v1 = nifty500.load_membership()
    diff = _csv("reports/v1_vs_v2_diff.csv", parse_dates=["date"])
    diff = diff[diff["isin"] != ""]
    cal = pd.DatetimeIndex(sorted(daily["date"].unique()))
    for d in sorted(diff["date"].unique()):
        d = pd.Timestamp(d)
        dd = cal[cal >= d][0]
        a = _members_on(v1, dd)
        b = _members_on(spells, dd)
        want_v2 = set(diff.loc[(diff["date"] == d) & (diff["only_in"] == "v2"), "isin"])
        want_v1 = set(diff.loc[(diff["date"] == d) & (diff["only_in"] == "v1"), "isin"])
        assert (b - a) == want_v2, f"{d.date()}: only-in-v2 differs: {sorted((b - a) ^ want_v2)[:8]}"
        assert (a - b) == want_v1, f"{d.date()}: only-in-v1 differs: {sorted((a - b) ^ want_v1)[:8]}"


@pytest.mark.skipif(not HAVE_WB, reason="holdings workbook not on this machine")
def test_outside_the_gap_v2_never_removes_a_v1_name(spells):
    v1 = nifty500.load_membership()
    for d in ("2014-03-31", "2016-09-30", "2019-04-01", "2022-09-30", "2025-04-01"):     # trading days
        assert _members_on(v1, d) <= _members_on(spells, d), d


def test_first_signal_universe_is_the_sep_2013_review_list():
    f = nifty500.first_signal_universe("nse_review_2013-09-27")
    assert len(f) == 500 and f["isin"].is_unique
    assert f["in_ace_master"].sum() >= 460
    with pytest.raises(nifty500.MembershipError):
        nifty500.first_signal_universe("sep 2013")


def test_card_field_is_checked_against_the_manifest(tmp_path):
    """A run that read a different membership file from the one the approved card names must fail the card check."""
    from lightyear import contract
    card = {"paper": {"id": "x"}, "universe": {"membership_source": "nifty500_members_v2"},
            "signal": {"params": {"first_signal_date": "2013-12-31", "first_signal_universe": "nse_review_2013-09-27"}},
            "costs": {"spread_bps": 0}, "backtest_plan": {"sample_start": "2014-01-01", "sample_end": "2026-09-18"}}
    cp = tmp_path / "card.yaml"
    cp.write_text(yaml.safe_dump(card), encoding="utf-8")
    sha = contract.sha256_file(str(cp))
    run = tmp_path / "run"
    run.mkdir()
    ok = {"inputs": {"card": {"sha256": sha}}, "params": {"start": "2014-01-01", "end": "2026-09-18", "cost_bp": 0,
                                                           "membership_source": "nifty500_members_v2",
                                                           "first_signal_date": "2013-12-31", "first_signal_universe": "nse_review_2013-09-27"}}
    (run / "manifest.json").write_text(json.dumps(ok), encoding="utf-8")
    checks = contract.check_card_consistency(str(run), str(cp), approval={"card_sha256": sha})
    assert any(c["item"] == "universe.membership_source" and c["ok"] for c in checks)
    assert any(c["item"] == "signal.params.first_signal_date" and c["ok"] for c in checks)
    bad = dict(ok, params=dict(ok["params"], membership_source="holdings_workbook"))
    (run / "manifest.json").write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(contract.ContractError, match="membership_source"):
        contract.check_card_consistency(str(run), str(cp), approval={"card_sha256": sha})


def test_card_default_source_is_the_workbook():
    from ros.cards.schema import Universe
    assert Universe().membership_source == "holdings_workbook"
