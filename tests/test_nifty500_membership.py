"""ros/data/nifty500.py: point-in-time NIFTY 500 membership from the holdings workbook, on a synthetic workbook in
the real layout, plus a live check when the real file is present."""
import os
import sys

import pandas as pd
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ros.data import nifty500 as n
from ros.data import sources
from tests.test_ace_prices import write_holdings_xlsx

I = [f"INE{i:03d}X0101{i % 10}" for i in range(600)]      # 600 well-formed ISINs


def member(i, flags=None):
    return (f"T{i} IS Equity", I[i], f"T{i}", f"Co {i}", flags or {})


@pytest.fixture
def world(tmp_path, monkeypatch):
    snaps = {
        "2023-03-31": [member(i, {"n50": i < 50, "n100": i < 100, "mc150": 100 <= i < 250}) for i in range(500)],
        "2023-06-30": [member(i, {"n50": i < 50, "n100": i < 100, "mc150": 100 <= i < 250}) for i in range(500)],
        "2023-09-30": [member(i) for i in range(300)],                                  # truncated pull: skipped
        "2023-12-31": [member(i) for i in range(10, 510)] + [("DEAD1 IS Equity", None, None, "Gone Ltd", {})],
        "2024-03-31": [member(i) for i in range(10, 510)],
    }
    xlsx = tmp_path / "h.xlsx"
    write_holdings_xlsx(xlsx, [(1, "Co 0", "T0", "T0 IN", I[0], "X")], snaps)
    upd = tmp_path / "updates"
    upd.mkdir()
    out = tmp_path / "cache"
    monkeypatch.setattr(sources, "NIFTY500_HOLDINGS_XLSX", str(xlsx))
    monkeypatch.setattr(sources, "NIFTY500_UPDATES_DIR", str(upd))
    monkeypatch.setattr(sources, "PROCESSED_DIR", str(out))
    return {"xlsx": str(xlsx), "upd": upd, "out": str(out)}


def test_snapshots_are_read_with_their_flags_and_incomplete_ones_are_skipped(world):
    summ = n.snapshot_summary()
    assert list(summ.index.strftime("%Y-%m-%d")) == ["2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31", "2024-03-31"]
    assert summ.loc["2023-09-30", "complete"] == False
    assert summ.loc["2023-03-31", "in_nifty50"] == 50 and summ.loc["2023-12-31", "unmapped"] == 1
    assert n.snapshot_dates().strftime("%Y-%m-%d").tolist() == ["2023-03-31", "2023-06-30", "2023-12-31", "2024-03-31"]


def test_membership_spells_follow_the_snapshots_not_the_calendar(world):
    m = n.load_membership()
    first = m[m["isin"] == I[0]].iloc[0]
    assert first["start_date"] == pd.Timestamp("2023-03-31") and first["end_date"] == pd.Timestamp("2023-12-31")
    late = m[m["isin"] == I[505]].iloc[0]
    assert late["start_date"] == pd.Timestamp("2023-12-31") and pd.isna(late["end_date"])
    assert "DEAD1" not in set(m["symbol"].dropna()), "an unmapped Bloomberg id never becomes a member"
    # the truncated 2023-09-30 pull did not end anyone's spell
    assert (m["end_date"].dropna() != pd.Timestamp("2023-09-30")).all()


def test_members_on_carries_a_list_forward_until_the_next_snapshot(world):
    assert len(n.members_on("2023-03-31")) == 500
    assert len(n.members_on("2023-11-15")) == 500 and I[0] in set(n.members_on("2023-11-15")["isin"])
    assert I[0] not in set(n.members_on("2023-12-31")["isin"]) and I[505] in set(n.members_on("2023-12-31")["isin"])
    assert len(n.members_on("2024-09-01")) == 500, "after the last snapshot the list is carried forward"
    with pytest.raises(n.MembershipError, match="before the first snapshot"):
        n.members_on("2022-12-31")
    assert len(n.members_on("2023-04-03", index="NIFTY 50")) == 50
    assert len(n.members_on("2023-04-03", index="NIFTY LARGEMIDCAP 250")) == 250, "union of the 100 and Midcap flags"
    assert len(n.members_on("2023-04-03", index="NIFTY MIDSMALLCAP 400")) == 150, "no Smallcap flags in this world"
    assert n.members_on("2024-01-02", index="NIFTY SMALLCAP 250").empty, "an index with no members is empty, not an error"
    with pytest.raises(n.MembershipError, match="unknown index"):
        n.members_on("2023-04-03", index="NIFTY 7")


def test_membership_panel_is_boolean_dates_by_isin_and_invents_nothing(world):
    dates = pd.bdate_range("2023-12-20", "2024-01-10")
    p = n.membership_panel(dates, columns=[I[0], I[505], "INE999Z09999"])
    assert p.dtypes.eq(bool).all() and p.index.name == "date"
    assert p.loc["2023-12-29", I[0]] and not p.loc["2024-01-01", I[0]]
    assert not p.loc["2023-12-29", I[505]] and p.loc["2024-01-01", I[505]]
    assert not p["INE999Z09999"].any()
    full = n.membership_panel(dates)
    assert full.shape[1] == 510


def test_staleness_knows_the_nse_review_calendar(world):
    s = n.staleness("2024-09-15")
    assert s["last_snapshot"] == "2024-03-31" and s["next_review"] == "2024-09-30" and not s["stale"]
    s = n.staleness("2024-10-01")
    assert s["stale"] and "2024-09-30.csv" in s["message"]
    assert n.next_review_after("2026-05-31") == pd.Timestamp("2026-09-30")
    assert n.next_review_after("2026-09-30") == pd.Timestamp("2027-03-31")


def test_an_update_csv_becomes_the_newest_snapshot(world):
    upd = world["upd"]
    pd.DataFrame({"isin": I[20:520], "symbol": [f"T{i}" for i in range(20, 520)]}).to_csv(upd / "2024-09-30.csv", index=False)
    assert n.snapshot_dates().max() == pd.Timestamp("2024-09-30")
    assert len(n.members_on("2024-10-01")) == 500 and I[10] not in set(n.members_on("2024-10-01")["isin"])
    assert not n.staleness("2024-12-31")["stale"]
    prov = n.provenance()
    assert prov["update_files"] == ["2024-09-30.csv"] and prov["last_snapshot"] == "2024-09-30"


@pytest.mark.parametrize("name,content,msg", [
    ("sep2024.csv", "isin\n" + "\n".join(I[:500]), "YYYY-MM-DD"),
    ("2024-09-30.csv", "symbol\nX", "'isin' column"),
    ("2024-09-30.csv", "isin\n" + "\n".join(I[:499] + ["BAD"]), "malformed ISIN"),
    ("2024-09-30.csv", "isin\n" + "\n".join(I[:100]), "MIN_COMPLETE"),
    ("2023-12-31.csv", "isin\n" + "\n".join(I[:500]), "must be later"),
])
def test_a_bad_update_file_is_refused_not_guessed(world, name, content, msg):
    (world["upd"] / name).write_text(content, encoding="utf-8")
    with pytest.raises(n.MembershipError, match=msg):
        n.load_snapshots()


def test_a_workbook_without_the_bifurcation_layout_is_refused(tmp_path, monkeypatch):
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.append(["Symbol", "Date"])
    wb.save(tmp_path / "x.xlsx")
    monkeypatch.setattr(sources, "PROCESSED_DIR", str(tmp_path / "c"))
    monkeypatch.setattr(sources, "NIFTY500_UPDATES_DIR", str(tmp_path / "u"))
    with pytest.raises(n.MembershipError, match="Bifurcation"):
        n.load_snapshots(str(tmp_path / "x.xlsx"))


@pytest.mark.skipif(not os.path.isfile(sources.NIFTY500_HOLDINGS_XLSX), reason="holdings workbook not on this machine")
def test_live_workbook_matches_what_the_module_documents():
    summ = n.snapshot_summary()
    assert summ.index.min() == pd.Timestamp("2012-03-31")
    assert summ.loc[~summ["complete"]].index.strftime("%Y-%m-%d").tolist() == ["2017-09-30", "2018-06-30", "2018-09-30"]
    assert summ.loc["2026-03-31", "in_nifty50"] == 50 and summ.loc["2026-03-31", "in_smallcap250"] == 250
    assert 495 <= len(n.members_on("2024-03-28")) <= 505
    assert 245 <= len(n.members_on("2024-03-28", index="NIFTY LARGEMIDCAP 250")) <= 255
    assert 395 <= len(n.members_on("2024-03-28", index="NIFTY MIDSMALLCAP 400")) <= 405
    assert n.staleness("2026-10-24")["next_review"] == "2026-09-30"
