<!-- Quant AI Researcher -->
# Spec audit rule changes

Every change to the audit rules (`lightyear/spec_audit.py`, `lightyear/numbers_audit.py`) is compared on every past run
that keeps its approved card (`card_approved.yaml`), old rules against new, before it is committed:

```
python -m lightyear.rule_compare OLD_REF [NEW_REF] --out docs/spec_audit_rule_changes/<date>_<what>.csv
```

Each entry names the audit code hash it brings in (sha256 of both files with LF line endings, first 16 characters).
`tests/test_spec_audit_rules_logged.py` fails when the audit code's hash is not listed here. Runs from before 2026-10-30
keep no approved card and cannot be re-audited.

| Date | Audit code hash | Change | Old vs new on past runs | Comparison |
|---|---|---|---|---|
| 2026-11-02 (logged 2026-11-11) | (historical, commit 7e0e4f6) | Start rule loosened from "first fill = the first session on or after the start" to "first fill between the start and the first return", three minutes after the old rule failed run 20261102-105054-0427 | Under the OLD rules run 20261102-105054-0427 fails 3 rules (start rule, fill exactly one session after signal, Tuesday signal): its first signal is one session before the window, as its card's start rule allows. Run 20261030-191604-3399 is unchanged. | `spec_audit_rule_changes/2026-11-11_start_rule_7e0e4f6_old_vs_new.csv` |
| 2026-11-11 | 274084d44ad188b3 | Cash share computed (was a literal pass; tolerance 1e-5 of NAV for whole-share rounding); numbers audit added (NAV rebuilt from trades x Ace prices on the run's own price basis, gap / trend-average / membership filters from source, fill price against the card's `fill_price`) | Both re-auditable runs: NAV rebuild, filters and membership PASS; fill price FAILS on both (their cards do not name `fill_price`); nothing that passed before now fails otherwise | `spec_audit_rule_changes/2026-11-11_pre_checkup_vs_numbers_audit.csv` |

Quant AI Researcher
