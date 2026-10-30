"""The Gate A intake manifest and the data registry share one pit_status vocabulary. (Moved from the former
test_master_universe.py when the master-universe CSV path was removed on 2026-10-30.)"""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)


def test_the_documented_pit_spelling_actually_works(tmp_path):
    """The README and the CLI stanza say `point_in_time`. The registry only accepted `true_pit`, so a manifest
    written exactly as instructed died with a bare ValueError -- on the one field that decides whether a live
    claim may rest on the data."""
    from ros.data import intake
    from ros.data.registry import DataRegistry
    (tmp_path / "x.csv").write_text("Date,v\n2020-01-01,1\n", encoding="utf-8")
    man = tmp_path / "MANIFEST.yaml"
    man.write_text("series:\n  - name: foo\n    kind: price\n    frequency: daily\n"
                   "    file: x.csv\n    pit_status: point_in_time\n"
                   '    licence: "t"\n', encoding="utf-8")
    old = intake.RAW_DIR
    try:
        intake.RAW_DIR = str(tmp_path)
        reg, added = intake.extend_registry(DataRegistry(), str(man))
        assert added == ["foo"]
        assert reg.get("foo").pit_status == "true_pit"
    finally:
        intake.RAW_DIR = old


def test_the_repo_manifest_declares_no_extra_series():
    """The three sources are code (ros/data/sources.py). The manifest stays for Gate A hand-overs and must parse."""
    from ros.data import intake
    assert intake.read_manifest() == []


@pytest.mark.parametrize("spelling,canonical", [
    ("point_in_time", "true_pit"), ("point-in-time", "true_pit"),
    ("PIT", "true_pit"), ("as_was", "true_pit"), ("true_pit", "true_pit"),
    ("back-filled", "backfilled"), ("backfilled", "backfilled"),
    ("restated", "restated"), ("unknown", "unknown"),
])
def test_pit_spellings_normalise_to_one_vocabulary(spelling, canonical):
    from ros.data.registry import DataCapability, normalise_pit_status
    assert normalise_pit_status(spelling) == canonical
    cap = DataCapability(name="x", kind="price", pit_status=spelling)
    assert cap.pit_status == canonical and not cap.validate()


def test_an_unknown_pit_status_is_still_refused_and_lists_the_options():
    """Normalising must not become accepting anything."""
    from ros.data.registry import DataCapability
    errs = DataCapability(name="x", kind="price", pit_status="probably fine").validate()
    assert errs and "true_pit" in errs[0] and "point_in_time" in errs[0]


def test_the_intake_and_registry_vocabularies_cannot_drift_again():
    """Every spelling the manifest advertises must survive the registry."""
    from ros.data.intake import PIT_STATUSES
    from ros.data.registry import DataCapability
    for spelling in PIT_STATUSES:
        cap = DataCapability(name="x", kind="price", pit_status=spelling)
        assert not cap.validate(), (
            f"the manifest advertises pit_status '{spelling}' but the registry "
            f"rejects it: {cap.validate()}")


def test_the_firm_registry_names_the_three_sources():
    from ros.data.firm_registry import build_firm_registry
    reg = build_firm_registry()
    assert reg.has("ACE_EQUITY_STOCK_PRICES") and reg.has("nifty500_membership_history") and reg.has("NIFTY 500")
    assert reg.get("nifty500_membership_history").pit_status == "true_pit"
    assert reg.get("ACE_EQUITY_STOCK_PRICES").kind == "price"
    assert not any("accord" in n.lower() or "bhavcopy" in n.lower() or "screener" in n.lower() for n in reg.names())
