# Quant AI Researcher
"""Which gate and which metric definitions produced a result. Every manifest and workbook records these two."""
# v3 (2026-11-12): statistical tests only. The capacity block and the two book rows left the gate; no pass mark or
# formula changed, so a run scores the same status under v2 and v3 unless its capacity block had FAILED.
# v4 (2026-11-13, operator): the mandate row left the gate, and a passing data-integrity row carries no text. No pass
# mark or formula changed: a run scores the same status under v3 and v4 unless its mandate row had FAILED.
GATE_VERSION = "v4"
METRICS_VERSION = "v2"
