# Quant AI Researcher
"""How many versions of a strategy were actually tried on a paper, counted separately from a run's sensitivities
(Wave 3, operator's override: the checkup found the Clenow run's 13 left out at least 12 of them).

    book        the configurations the paper itself reports (the card's n_configs_tried)
    lightyear   distinct versions run through Lightyear on this paper: one per distinct parameter set in a run
                folder's manifest, and one per earlier run folder that reached results without a manifest. A run whose
                state.json says counts_as_version: false (a re-run the operator ruled is not a new version) is listed
                and not counted
    ledger      versions run outside Lightyear, recorded by hand with their source in data/reference/trial_ledger.csv

versions = book + lightyear + ledger. A run's sensitivities are reported beside it, never folded in.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LEDGER = os.path.join(REPO, "data", "reference", "trial_ledger.csv")
_VOLATILE = {"card_sha256_at_import", "gate_a_revisions", "n_trials", "n_versions", "n_sensitivities"}
_DONE = {"gate_b", "decided", "building"}


def _run_dirs():
    return sorted(glob.glob(os.path.join(REPO, "outputs", "lightyear", "2*"))
                  + glob.glob(os.path.join(REPO, "outputs", "lightyear_archive_*", "2*")))


def lightyear_versions(slug: str, exclude: str | None = None, dirs: list[str] | None = None) -> dict:
    keys, no_manifest, reruns = set(), [], []
    for d in dirs if dirs is not None else _run_dirs():
        if exclude and os.path.abspath(d) == os.path.abspath(exclude):
            continue
        sp = os.path.join(d, "state.json")
        if not os.path.isfile(sp):
            continue
        with open(sp, encoding="utf-8") as fh:
            st = json.load(fh)
        if st.get("slug") != slug or st.get("status") not in _DONE:
            continue
        if st.get("counts_as_version") is False:      # a logged re-run the operator ruled is not a new version (state.json)
            reruns.append(os.path.basename(d))
            continue
        mp = os.path.join(d, "manifest.json")
        params = {}
        if os.path.isfile(mp):
            with open(mp, encoding="utf-8") as fh:
                params = json.load(fh).get("params") or {}
        if params:
            key = json.dumps({k: params[k] for k in sorted(params) if k not in _VOLATILE}, sort_keys=True, default=str)
            keys.add(hashlib.sha256(key.encode()).hexdigest())
        else:
            no_manifest.append(os.path.basename(d))
    return {"n": len(keys) + len(no_manifest), "distinct_parameter_sets": len(keys), "runs_without_manifest": no_manifest,
            "reruns_not_counted": reruns}


def ledger(slug: str, path: str | None = None) -> pd.DataFrame:
    p = path or LEDGER
    if not os.path.isfile(p):
        return pd.DataFrame(columns=["slug", "study", "versions", "source", "note"])
    d = pd.read_csv(p, skiprows=1)
    return d[d["slug"] == slug]


def count(slug: str, book: int, exclude_run: str | None = None, dirs: list[str] | None = None,
          ledger_path: str | None = None) -> dict:
    ly = lightyear_versions(slug, exclude_run, dirs)
    led = ledger(slug, ledger_path)
    n_led = int(led["versions"].sum()) if len(led) else 0
    return {"book": int(book), "lightyear": ly["n"], "ledger": n_led, "versions": int(book) + ly["n"] + n_led,
            "lightyear_detail": ly, "ledger_studies": led[["study", "versions", "source"]].to_dict("records")}
