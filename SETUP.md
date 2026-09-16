# Setup — running this in VS Code

Ten minutes, and **no API key**.

## 1. What you need

- **VS Code**
- **Python 3.10+** (`python3 --version`)
- **A Claude account** with a paid plan — this is what replaces an API key.
  Claude Code signs in with your account; you are not billed per call and there
  is no key to manage.

## 2. Clone

```bash
git clone https://github.com/haixing281002/BACKTESTER.git
cd BACKTESTER
pip install -r requirements.txt
```

The repository already contains the price workbook and the test-case paper, so
there is nothing to download or upload.

## 3. Check it works before involving Claude at all

```bash
python -m pytest tests/ -q
python run_pipeline.py --card cards/devanathan_2026_india_factor_adaptation.yaml
```

The first should print `41 passed`. The second takes 2–4 minutes and ends at
**Gate B PENDING** — that is correct, not an error. The pipeline scores the
evidence and stops, because the decision belongs to a person.

Everything in that run is deterministic Python. **No model was involved.**

## 4. Add Claude Code

Install the **Claude Code** extension from the VS Code marketplace, then sign in
with your Claude account when prompted. (Current install and sign-in steps:
<https://code.claude.com/docs>.) There is also a CLI — `npm install -g
@anthropic-ai/claude-code`, then run `claude` inside the repo — if you prefer the
terminal.

Open the **BACKTESTER folder** as your workspace, not a parent directory: the
project context in `CLAUDE.md` and the commands in `.claude/commands/` are picked
up relative to the workspace root.

## 5. Confirm Claude loaded the project

Ask it:

> what commands does this repo define, and what is the one rule it follows?

It should answer without looking anything up: eleven stage commands, and *models
interpret, code computes, humans allocate*. If it does not, the workspace root is
wrong.

## 6. Run a paper

```
/paper docs/devanathan_2026_simple_dynamic_sbg.pdf
```

That walks all eleven checkpoints and **stops at both gates** for a human. Or take
one stage at a time:

| Command | Stage |
|---|---|
| `/triage` | 00 — is this worth reading? |
| `/ingest` | 01 — read the rendered PDF, page-anchored analysis |
| `/draft-card` → `/critique-card` | 02 — write the card, then attack it |
| `/gate-a` | Gate A — assembles a human queue, decides nothing |
| `/map-data` | 03 — the gate binds, Claude advises |
| `/run` | 03–08 — the deterministic pipeline |
| `/critique-results` | 06–07 — attack our own backtest |
| `/gate-b` | Gate B — assembles a brief, votes on nothing |
| `/librarian` | 08 — has this been asked before? |

## 7. Your own paper

Drop any PDF into `docs/papers/` and run `/paper docs/papers/<file>.pdf`.

The **dataset never changes** — your NIFTY factor sleeves stay as they are. The
paper supplies the mechanism; the data supplies the universe. That is what makes
an arbitrary paper testable against this book.

There is also a no-LLM path, useful for seeing what a plain regex reader can and
cannot do:

```python
from colab_papers import analyse, compare, draft_card, run
analyse("docs/papers/x.pdf")     # what the deterministic reader finds
draft_card("docs/papers/x.pdf")  # a runnable card skeleton, no model
```

## What to expect, honestly

- **Gate B always ends PENDING** unless a named human records a decision:
  `--decision REJECT --decided-by "Name" --rationale "…"`
- **The test case fails**, and should. It loses to an index you can buy. That is
  the system working, not a bug.
- **The stage commands are new and lightly exercised.** The mechanics are tested;
  the prompts get their real test on a paper nobody has run yet.
- Colab alternative, if you would rather not install anything: paste the one-liner
  in `colab_bootstrap.py` into a blank notebook.

## Where to read next

- `CLAUDE.md` — the rules, loaded automatically by Claude Code
- `docs/PIPELINE_REVIEW.md` — what breaks at each step, with red and green flags
- `docs/paper_to_position_pipeline.html` — the chart this implements
