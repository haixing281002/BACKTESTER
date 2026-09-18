# Your Strategy Cards

**This folder starts empty, and that is deliberate.**

A card here is a card about a paper *you* are analysing. `/draft-card` writes one
per paper, named after the paper's slug, so `cards/` is a record of your own work
and nothing else.

The three worked examples live in `examples/cards/`, out of the way. Nothing in
the code path reads them — they are reference material for a human, not input.
They were previously in this folder, and the consequence was that `check_setup.py`
globbed `cards/*.yaml`, took the first alphabetically, and loaded a card about
somebody else's paper on every single run.

## Adding one

```bash
python run_interpret.py --pdf docs/papers/<your_paper>.pdf
```

It tells you which artifacts exist and what to run next. The card comes from
`/draft-card` after `/ingest` has read the paper.

## Looking at an example

Read them for the shape — how ambiguities are logged, how a universe translation
records its runners-up, how a long-short paper states what the long-only
adaptation cost. Do not copy one and edit it: a card carries a paper's sha256 and
its own ambiguities, and a card inherited from another paper is a card that
quietly asserts things nobody checked for yours.
