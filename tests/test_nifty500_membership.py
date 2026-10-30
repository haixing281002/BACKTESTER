"""The hardcoded official NIFTY 500 membership file stays internally consistent and readable."""
import pandas as pd
import pytest

from ros.data import nifty500 as n5

M = n5.load_membership()
ALL = n5.load_membership(entry_types=None)
MONTH_END = pd.read_csv(n5.MEMBERSHIP_CSV.replace("nifty500_membership.csv", "nifty500_month_end.csv"),
                        parse_dates=["date"])


def test_every_date_has_500_or_501_tradable_members():
    for d in list(pd.date_range("2013-04-30", "2026-09-30", freq="BME")) + [pd.Timestamp("2026-10-20")]:
        n = len(n5.members_on(d, M))
        assert n in (500, 501), (d.date(), n)


def test_no_security_is_in_twice_on_the_same_day():
    for d in n5.change_dates(ALL):
        if d < n5.FIRST_DATE:
            continue
        x = n5.members_on(d, ALL)
        assert not x["symbol"].duplicated().any(), d.date()


def test_spells_are_well_formed():
    assert (ALL["end_date"].isna() | (ALL["end_date"] > ALL["start_date"])).all()
    assert set(ALL["entry_type"]) <= {"regular", "demerger_placeholder", "demerger_temporary"}
    assert ALL.loc[ALL["entry_type"] == "regular", "isin"].str.match(r"^IN[E0-9]").all()


def test_month_end_file_agrees_with_membership_file():
    for d, g in MONTH_END.groupby("date"):
        want = set(g.loc[g["entry_type"] == "regular", "symbol"])
        got = set(n5.members_on(d, M)["symbol"])
        assert want == got, d.date()


def test_effective_date_convention():
    # ind_prs22082025: Hero MotoCorp unaffected; GNFC excluded effective 30 Sep 2025 (close of 29 Sep)
    g = M[M["symbol"] == "GNFC"]
    assert (g["end_date"] == pd.Timestamp("2025-09-30")).any()
    assert "GNFC" in set(n5.members_on("2025-09-29", M)["symbol"])
    assert "GNFC" not in set(n5.members_on("2025-09-30", M)["symbol"])


def test_panel_matches_members_on():
    dates = pd.to_datetime(["2016-04-01", "2020-09-25", "2024-03-28"])
    p = n5.membership_panel(dates, m=M)
    for d in dates:
        assert set(p.columns[p.loc[d]]) == set(n5.members_on(d, M)["isin"])


def test_refuses_dates_before_the_file():
    with pytest.raises(ValueError):
        n5.members_on("2012-12-31", M)
