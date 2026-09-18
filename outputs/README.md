# Run artifacts

**This folder is yours and is not tracked.** Everything here belongs to the run
that produced it, on the machine that produced it: reports, metrics, charts,
point-in-time snapshots, interpretation artifacts, and the strategy library.

## Why it is gitignored

It was committed once. The clutter was not the problem — a fresh clone arrived
with **ten strategy-library entries about somebody else's paper**, and the
library is not decoration:

- `/librarian` answers *"has this question been asked before?"* from it. Shipped
  entries make a new fund inherit another research programme's prior answers.
- `trials_for_family()` feeds the **deflated Sharpe** trial count. Inherited
  trials silently change the significance of your own results.

Snapshots, reports and charts for a paper you are not working on are merely
confusing. A pre-populated library is wrong.

## Where the worked examples went

`examples/outputs/` — the Devanathan and Moskowitz runs, kept as reference:

```
examples/outputs/reports/      the full pipeline report, end to end
examples/outputs/library/      what a library entry looks like
examples/outputs/snapshots/    a PIT snapshot and its manifest
examples/outputs/charts/       the four diagnostic charts
examples/outputs/backtest_audit.xlsx   the live-formula Excel model
```

Read them to see what a finished run produces. Nothing in the code path reads
them, and `StrategyLibrary` is rooted at `outputs/library` — never at the
examples.

## What lands here when you run

```
outputs/interpretation/        per-paper analysis, critique, Gate A queue
outputs/interpretation/_lineage/   who interpreted what, and when
outputs/library/               one entry per run, keyed by card + fingerprint
outputs/snapshots/             point-in-time data, content-hashed
outputs/report_<card>.txt      the run
```

Artifacts are keyed by the paper's slug, so two papers never collide. If you see
a name here you do not recognise, it is from an earlier run on this machine —
not something the pipeline reached for. Delete it if you want a clean slate;
nothing depends on it.
