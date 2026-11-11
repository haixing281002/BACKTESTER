# Quant AI Researcher
"""Every version tried on a paper is counted (ros/validation/trials.py), separately from a run's sensitivities."""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ros.validation import trials


def _run(root, name, slug, status, params=None):
    d = root / name
    d.mkdir()
    (d / "state.json").write_text(json.dumps({"slug": slug, "status": status}), encoding="utf-8")
    if params is not None:
        (d / "manifest.json").write_text(json.dumps({"params": params}), encoding="utf-8")
    return str(d)


def test_versions_are_book_plus_lightyear_plus_ledger(tmp_path):
    dirs = [_run(tmp_path, "r1", "x", "gate_b", {"a": 1, "n_trials": 13}),
            _run(tmp_path, "r2", "x", "gate_b", {"a": 1, "n_trials": 27, "gate_a_revisions": ["note"]}),   # same version
            _run(tmp_path, "r3", "x", "decided", {"a": 2}),
            _run(tmp_path, "r4", "x", "gate_b"),                                                     # no manifest: one more
            _run(tmp_path, "r5", "x", "failed", {"a": 3}),                                            # never reached results
            _run(tmp_path, "r6", "other", "gate_b", {"a": 9}),
            _run(tmp_path, "r7", "x", "gate_b", {"a": 77})]                                           # a logged re-run: not counted
    st7 = tmp_path / "r7" / "state.json"
    st7.write_text(json.dumps({**json.loads(st7.read_text(encoding="utf-8")), "counts_as_version": False}), encoding="utf-8")
    led = tmp_path / "ledger.csv"
    led.write_text("# sig\nslug,study,versions,source,note\nx,old study,7,somewhere,\nother,z,3,s,\n", encoding="utf-8")
    c = trials.count("x", 9, dirs=dirs, ledger_path=str(led))
    assert (c["book"], c["lightyear"], c["ledger"], c["versions"]) == (9, 3, 7, 19)
    assert c["lightyear_detail"]["runs_without_manifest"] == ["r4"]
    assert c["lightyear_detail"]["reruns_not_counted"] == ["r7"]


def test_the_clenow_ledger_rows_exist():
    led = trials.ledger("oceanofpdf_com_stocks_on_the_move_andreas_clenow")
    assert int(led["versions"].sum()) >= 9 and led["source"].notna().all()
