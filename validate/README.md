# Independent validation

> Does the engine compute what it claims to compute?

```bash
python validate/cross_check.py --excel
```

Exits 0 if everything agrees, 1 if anything does not. Takes a few minutes.

## Why this exists

`ros/engine/` is tested, but every one of those tests was written by the author
of the engine. A shared misunderstanding -- about what a weight means after a
day of drift, when a cost is charged, which bar a signal may be traded on --
would be baked into the engine AND into its tests, and the suite would pass
while the numbers were wrong.

So the engine is checked against things that do not share its assumptions.

## The three implementations

| | Reads the workbook via | Accounting | Metrics |
|---|---|---|---|
| **Engine** `ros/` | `pandas.read_excel` | portfolio weights, renormalised daily | pandas |
| **Clean room** `independent.py` | raw `openpyxl` | unit holdings + cash balance | explicit loops |
| **Excel** `to_excel.py` | n/a | live cell formulas | Excel functions |

The middle column is the point. The engine carries weights and renormalises
them each day; the clean-room implementation carries unit holdings and a cash
balance and derives NAV as `units . prices + cash`, the way a fund accountant
would. The two are mathematically equivalent, so they must agree -- but a
renormalisation bug can only live in one of them.

`independent.py` imports nothing from `ros`. That is enforced by
`tests/test_independent_agrees.py`, not by good intentions.

## What is compared

48 quantities: the parsed prices themselves, the cash proxy, `sigma_bench`,
the rebalance calendar, then for three strategies the full NAV path, rebalance
count, costs, turnover, CAGR, volatility, max drawdown and both Sharpe
conventions. Tolerance is 1e-10 -- nothing here is a fitted number, so a
"close enough" threshold would only hide the bugs this is built to find.

## The Excel workbook

`--excel` writes `outputs/validation/backtest_audit.xlsx`. Every NAV cell is a
live formula, so a colleague who does not read Python can trace one number from
a raw price to the headline Sharpe, or change a price and watch everything move.

openpyxl writes formulas without evaluating them, so the workbook is not
verified until something calculates it. With the optional evaluator installed:

```bash
python -m pip install formulas
```

`cross_check.py --excel` computes every formula and checks it against the
engine. Without it the script says plainly that the formulas were written but
never calculated, rather than implying they were checked.

That step earned its keep immediately: it caught a real bug where `1/{years}`
expanded to `1/(days)/365.25`, which Excel reads left to right as
`(1/days)/365.25`. Every date-scaled metric came out near zero. Reading the
formula could not show that. Evaluating it could.

## What agreement proves, and what it does not

**Proves:** the arithmetic. NAV compounding, cost timing, the turnover
definition, the causal lag, month-end rebalance selection, and every headline
metric.

**Does not prove:** the assumptions. All three charge 30bp because the Strategy
Card says 30bp. All three use a flat 6% cash proxy because no Indian risk-free
series exists in the snapshot. All three inherit the backfill bias in the NSE
factor indices -- every series starts at exactly 1000.00, which means the
history was reconstructed after the rules were written.

Three implementations agreeing on a wrong assumption are precisely wrong
together. Assumptions are Gate A and Gate B's job, and no amount of
cross-checking retires them.
