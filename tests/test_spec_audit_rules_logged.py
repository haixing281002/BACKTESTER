# Quant AI Researcher
"""A change to the audit rules must be compared on past runs and logged (docs/spec_audit_rules_log.md)."""
import hashlib
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = ("lightyear/spec_audit.py", "lightyear/numbers_audit.py")


def audit_code_hash() -> str:
    h = hashlib.sha256()
    for f in FILES:
        h.update(f.encode())
        with open(os.path.join(REPO, f), "rb") as fh:
            h.update(fh.read().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


def test_the_current_audit_rules_are_in_the_change_log():
    with open(os.path.join(REPO, "docs", "spec_audit_rules_log.md"), encoding="utf-8") as fh:
        log = fh.read()
    h = audit_code_hash()
    assert h in log, (f"the spec audit rules changed (hash {h}) without an entry in docs/spec_audit_rules_log.md: run "
                      "python -m lightyear.rule_compare <old ref> on past runs and log old vs new")
