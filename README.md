# AI Research Operating System — paper → backtest → governed decision

A deterministic research pipeline that ingests a quantitative finance paper, forces it
through a structured Strategy Card, checks whether we can actually get the data, runs it
on frozen point-in-time snapshots, validates it against selection bias, and returns a
governed promotion decision.

Built to the architecture in `docs/ai_research_operating_system.pdf`, including its three
non-negotiable upgrades:

1. **Point-in-time lineage and frozen snapshots are mandatory** — no result without lineage.
2. **Paper replication is separated from India investability validation** — different
   questions, different verdicts, and an adaptation may never claim to be a replication.
3. **`promising` / `rejected` is replaced by a governed promotion ladder**, and negative
   results are stored as reusable assets.

The design rule everything follows: **AI interprets, deterministic systems compute,
humans govern.** A paper enters the system as a *card* (data), never as code.

---

## Quick start

New here, or setting this up on someone else's machine? **`SETUP.md`** is the
ten-minute version.

```bash
pip install -r requirements.txt

# a US multi-asset paper we cannot get data for -> fails fast at Step 03, in seconds
python run_pipeline.py --card cards/devanathan_2026_replication.yaml

# the same mechanism adapted to NIFTY500 factor sleeves -> full 8-step run
python run_pipeline.py --card cards/devanathan_2026_india_factor_adaptation.yaml

# a structurally different paper (trend following) -> proves the engine is paper-agnostic
python run_pipeline.py --card cards/moskowitz_2012_tsmom_india.yaml

pytest tests/ -q
```

Outputs land in `outputs/`: a full text report, a metrics CSV, four diagnostic charts,
the frozen snapshot + manifest, and an append-only library entry.

---

## The eight steps

| Step | Module | What it does | Can it stop the pipeline? |
|---|---|---|---|
| 01 Ingest | `ros/cards/extract.py` | PDF → page-anchored evidence, table recovery, extraction-quality report | Yes — a scanned PDF is not cardable |
| 02 Strategy Card | `ros/cards/schema.py` | Validated YAML card; ambiguities logged **with resolutions** | Yes — unresolved ambiguity blocks |
| **Gate A** | `ros/governance/gates.py` | Researcher owns the economic interpretation | Yes |
| 03 Data feasibility | `ros/feasibility.py` | Requirements → AVAILABLE / PROXY / DEGRADED / UNAVAILABLE | Yes — **fail fast** |
| 04 PIT data | `ros/data/snapshot.py` | Frozen, hashed snapshot + full lineage | Yes — empty/incomplete snapshot |
| 05 Build + execute | `ros/engine/` | Template-constrained allocators, daily accounting, look-ahead tripwires | Yes — tripwire trips |
| 06 Research validation | `ros/validation/research.py` | Replication gap, sub-periods, walk-forward, bootstrap, deflated Sharpe, sensitivities | No — informs Gate B |
| 07 Portfolio validation | `ros/validation/portfolio.py` | Benchmark-relative, factor fingerprint, orthogonality, incremental IR, mandate, capacity | No — informs Gate B |
| **Gate B** | `ros/governance/gates.py` | PM / IC owns the investment decision | Yes |
| 08 Library | `ros/governance/library.py` | Promotion ladder + append-only research graph | — |

See **`docs/PIPELINE_REVIEW.md`** for the issues, red flags and green flags at every step.

---

## Adding a new paper

A new paper is a **YAML file**, not a code change. That is the whole point of the
template-constrained design: implementation risk is bounded because the surface area a
paper can touch is bounded.

```
1. Write cards/<paper>.yaml           (universe, template, params, costs, ambiguities)
2. Declare its data_requirements      (Step 03 resolves them against the firm registry)
3. python run_pipeline.py --card cards/<paper>.yaml
```

If the paper needs a mechanism no existing template covers, the extension is deliberately
small and reviewable:

- a new **allocator template** in `ros/engine/templates.py` (~30 lines, decorated with
  `@template("name")`), and/or
- a new **signal primitive** in `ros/engine/primitives.py` (~5 lines, `@primitive("name")`).

Nothing else changes — not the accounting engine, not the validation suite, not the gates,
not the ladder. `cards/moskowitz_2012_tsmom_india.yaml` exists purely to demonstrate this:
supporting a long-short futures trend-following paper cost **one template and one branch in
the alpha builder**, and it ran through all eight steps unmodified.

Registered today:

- **Templates**: `fixed_weight`, `vol_target`, `markowitz_l1`, `ts_momentum`, `inverse_vol`,
  `equal_risk_contribution`, `min_variance`, `equal_weight`
- **Primitives**: `simple_returns`, `trailing_vol`, `portfolio_trailing_vol`, `ewma_return`,
  `rolling_cov`, `total_return_momentum`, `vol_scaled_momentum`, `zscore`,
  `cross_sectional_rank`, `vol_ratio`

---

## What the engine guarantees

**Causality.** Signals are shifted by `1 + lag_days` before use: the weights applied to
day *t*'s return were decided from data available at *t-1-lag* at the latest. Two planted
look-ahead controls (same-bar and next-bar leaks) run on every backtest and must both be
caught, so the tripwire is proven live rather than assumed.

**Fair comparison.** `align_runs()` truncates every strategy and benchmark to a common
start date and rebases to 1.0. Without it, a strategy needing a 252-day warm-up carries a
year of flat NAV while its benchmark banks real returns — which silently moved the Sharpe
ranking in this very project before it was fixed.

**Honest accounting.** Costs are charged at the half-spread on the realised weight change,
deducted from NAV at the rebalance, and turnover is reported on the same basis. The
`markowitz_l1` allocator anticipates the same cost it is charged.

**Reproducibility.** Every run stores the source file hash, the materialised frame's
content hash, the engine code hash and the git commit. `snapshot.verify()` re-derives the
content hash on demand.

**Trial honesty.** The deflated Sharpe ratio's trial budget is
`card declaration + configurations executed this run + distinct prior configurations in the
library`. Re-running an *identical* configuration does not inflate it (no selection
occurred); running a *different* one does, even months later in another session.

---

## Repository layout

```
ros/
  cards/      schema.py       Strategy Card: dataclasses, controlled vocabularies, fingerprint
              extract.py      PDF ingestion, text-geometry table parser, target conflicts
  data/       registry.py     capability catalogue with pit_status
              firm_registry.py what THIS fund holds, with caveats
              loaders.py      NSE workbook loader, cash proxy, data audit
              snapshot.py     frozen snapshots, lineage, content/code hashing
  engine/     primitives.py   registered causal signal primitives
              templates.py    registered allocator templates
              prepare.py      card + snapshot -> causal allocator inputs
              backtest.py     daily accounting, rebalance calendars, look-ahead tripwire
  validation/ metrics.py      geometric AND conventional Sharpe, CVaR, drawdown, turnover
              research.py     replication gap, walk-forward, stationary bootstrap, DSR
              portfolio.py    benchmark-relative, fingerprint, orthogonality, incremental IR
  governance/ gates.py        Gate A, Gate B, promotion ladder
              library.py      append-only research graph, duplicate + similarity detection
  runner.py                   card -> executed run set, alignment
run_pipeline.py               the 8-step driver
cards/                        Strategy Cards (one YAML per paper)
tests/                        17 engine-correctness tests
docs/PIPELINE_REVIEW.md       step-by-step issues, red flags, green flags, findings
```

---

## Running it in VS Code (no API key)

`CLAUDE.md` and `.claude/commands/` turn every LLM-owned stage in the chart into a
slash command. **In the editor, Claude Code is the model** — the same seven roles,
performed in session, with no API key and better context than the API agents get.

```
/paper docs/papers/your_paper.pdf     # the whole chain, stopping at both gates
```

or stage by stage:

| Command | Stage | Owner |
|---|---|---|
| `/triage` | 00 | LLM owns |
| `/ingest` | 01 | LLM owns — reads the **rendered** PDF |
| `/draft-card` → `/critique-card` | 02 | LLM owns, code validates |
| `/gate-a` | Gate A | **assembles the queue; does not decide** |
| `/map-data` | 03 | code binds, LLM advises |
| `/run` | 03–08 | code owns |
| `/critique-results` | 06–07 | code computes, LLM critiques |
| `/gate-b` | Gate B | **assembles the brief; does not vote** |
| `/librarian` | 08 | code stores, LLM recalls |

Both paths emit the **same artifacts against the same schemas** in
`ros/agents/schemas.py`. The producer is recorded, never special-cased:

```bash
python -m ros.interpretation history
```
```
stage         by           operator     valid  artifact
01_ingest     claude-code  N. Ganesh    True   outputs/interpretation/x__analysis.json
02_card       claude-code  N. Ganesh    None   cards/x_adaptation.yaml
02_critique   claude-code  N. Ganesh    True   outputs/interpretation/x__critique.json
```

Every record hashes its artifact and its inputs, names the **person** accountable
(an unnamed operator is refused), and validates the artifact against its schema —
so an invalid one is recorded as `valid=False` rather than passing quietly.

---

## The agentic layer

`ros/agents/` puts Claude where a model is genuinely better than code — reading documents,
judging whether two things mean the same thing, spotting a pattern in a diagnostic table,
writing the memo — and nowhere else. Arithmetic, portfolio accounting, statistical inference
and both gates stay deterministic.

```bash
# no API key needed -- replays recorded fixtures
python run_agentic.py --pdf docs/<paper>.pdf --mode adaptation \
    --replay ros/agents/fixtures/devanathan_2026.json

# live, once ANTHROPIC_API_KEY is set (or `ant auth login`)
python run_agentic.py --pdf docs/<paper>.pdf --mode adaptation
```

It stops at Gate A with a human review queue. The deterministic pipeline then runs unchanged
on the drafted card.

| Agent | Model | Step | Job |
|---|---|---|---|
| `TriageAgent` | Haiku 4.5 | 00 | Screen a stack of papers cheaply |
| `PaperAnalystAgent` | Opus 5 | 01 | Read the rendered PDF: tables, equations, accounting bases |
| `CardDrafterAgent` | Opus 5 | 02 | Draft the Strategy Card |
| `AmbiguityCriticAgent` | Opus 5 | 02 | Attack the draft; find what it waved through |
| `DataMapperAgent` | Opus 5 | 03 | Semantic requirement→registry matching (advisory) |
| `TemplateMatcherAgent` | Opus 5 | 05 | Pick a registered allocator; never write code |
| `ResultsCriticAgent` | Opus 5 | 06/07 | Attack our own backtest |
| `LibrarianAgent` | Opus 5 | 08 | Semantic recall over past failures |

**What keeps the model subordinate:**

- Every output is a Pydantic instance, never prose a parser consumes.
- A drafted card re-enters through the same `load_card()` the human path uses. Invalid card,
  no run.
- `assess()` still owns the feasibility verdict; the model's opinion is recorded alongside it,
  and disagreements are surfaced, never resolved in the model's favour.
- The agent layer cannot write to the data registry, so a model cannot conjure data into being.
- Backtesting, bootstrap, deflated Sharpe and both gates never see an LLM.
- All agents share one cached system prefix and one cached document block, so a paper is
  uploaded once and read by seven agents.

Non-determinism is contained by freezing the model's card and hashing *that* — the card is
re-derivable even though the model is not.

`docs/paper_to_position_pipeline.html` charts every stage, its LLM insertion point and its
failure modes.

---

## Running it in Google Colab

`colab/Research_OS_Colab.ipynb` is a **self-contained** notebook: the entire `ros` package is
embedded as a base64 tarball, so it needs no GitHub access and nothing to download.

1. Open [colab.research.google.com](https://colab.research.google.com) → **Upload notebook**
2. Run cell **0.1** (installs cvxpy, clarabel, pdfplumber, openpyxl — 60–90s)
3. Run cell **0.2** (unpacks the engine)
4. Run cell **0.3** and upload **both** required inputs — select them together with
   ctrl-click / cmd-click:
   - `Factor_Indices_Historical_Price_Data.xlsx` (the price history)
   - the research paper `.pdf` (Step 01 ingests it for page evidence)

   The cell hard-fails if either is missing, and rejects a scanned PDF with no
   extractable text.
5. Run the rest top to bottom — about 5–8 minutes on a free CPU runtime

The notebook walks all eight steps with the reasoning inline, and ends with an editable
cell where you write and run your own Strategy Card.

**Regenerating the notebook** after changing the engine:

```bash
python build_colab.py     # re-tars the package and rebuilds the .ipynb
```

Every code cell is executed end to end as a verification step before release.
