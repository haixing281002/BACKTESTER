---
description: "Stage 08 — has this question already been answered?"
argument-hint: "<what you propose to test>"
---

# Stage 08 — LIBRARIAN  (code stores, LLM recalls)

```bash
python -c "
from ros.governance.library import StrategyLibrary
import json
for e in StrategyLibrary('outputs/library').all():
    print(json.dumps({k: e.get(k) for k in
        ('entry_id','card_id','mode','outcome','attained_rung','stopped_at','lessons')}, indent=1))"
```

Proposed research: **$ARGUMENTS**

Cosine similarity over factor loadings already catches the same bet under a new
name. It does **not** catch *"we tested this mechanism two years ago on different
sleeves and it failed for a reason that still applies."* That needs reading, which
is why you are here.

Write `outputs/interpretation/<slug>__librarian.json` conforming to
`LibrarianAnswer`.

`supersedes_this` means the prior entry answers **this** question — not that it is
on a related topic. Recommend `do_not_run` only when a prior negative result still
applies for the same reason. If it failed for a reason that no longer holds — new
data, a fixed bug, a different mandate — say `proceed` and name what changed.

Be careful: wrongly saying "already answered" kills a good idea invisibly, and
nothing downstream will ever audit that.

```bash
python -m ros.interpretation record --stage 08_librarian \
    --output outputs/interpretation/<slug>__librarian.json --operator "<name>"
```
