"""Finding and requiring the paper a run is about.

There is no default paper. There used to be one -- the repo was built around a
single worked example and its filename leaked into entry points, Colab cells and
command defaults -- and a default paper is worse than no paper: a run that
silently analyses last week's PDF looks exactly like a run that analysed yours.

So every entry point demands one, and when none is given this module says what
is available rather than guessing.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from typing import List, Optional

# Where papers live. docs/papers/ is the drop folder; docs/ is scanned too
# because the repo's own examples sit there.
SEARCH_DIRS = ("docs/papers", "docs", "papers", ".")


class NoPaperGiven(SystemExit):
    """Raised instead of falling back to a default."""


@dataclass
class Paper:
    path: str
    slug: str
    sha256: str
    size: int

    @property
    def short_sha(self) -> str:
        return self.sha256[:16]


def slugify(path: str) -> str:
    """A stable, filesystem-safe name for this paper's artifacts."""
    stem = os.path.splitext(os.path.basename(path))[0]
    slug = re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_")
    return slug or "paper"


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def describe(path: str) -> Paper:
    return Paper(path=path, slug=slugify(path), sha256=sha256_of(path),
                 size=os.path.getsize(path))


def find_papers(dirs=SEARCH_DIRS) -> List[str]:
    """Every PDF the repo can see, nearest drop folder first, de-duplicated."""
    seen, out = set(), []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.lower().endswith(".pdf"):
                continue
            p = os.path.normpath(os.path.join(d, f))
            if p not in seen:
                seen.add(p)
                out.append(p)
    return out


def ask_for_a_paper(reason: str = "") -> str:
    """The message shown when no paper was supplied. Never picks one."""
    found = find_papers()
    L = []
    if reason:
        L += [reason, ""]
    L.append("WHICH PAPER?")
    L.append("")
    L.append("  This pipeline analyses one paper per run and has no default.")
    L.append("  A default would mean a run that quietly analysed the wrong PDF")
    L.append("  looked identical to one that analysed yours.")
    L.append("")
    if found:
        L.append(f"  PDFs already in the repo ({len(found)}):")
        for p in found:
            L.append(f"    {os.path.getsize(p):>10,} bytes   {p}")
        L.append("")
    L.append("  To analyse a NEW paper, put the PDF in docs/papers/ first:")
    L.append("")
    L.append("    Windows     Copy-Item \"$HOME\\Downloads\\paper.pdf\" docs\\papers\\")
    L.append("    macOS/Linux cp ~/Downloads/paper.pdf docs/papers/")
    L.append("")
    L.append("  Then name it explicitly:")
    L.append("")
    L.append("    python run_interpret.py --pdf docs/papers/<your_paper>.pdf")
    L.append("")
    L.append("  Or, in Claude Code:   /paper docs/papers/<your_paper>.pdf")
    return "\n".join(L)


def require_paper(path: Optional[str]) -> Paper:
    """Resolve a paper path, or exit with instructions. Never returns a default."""
    if not path:
        raise NoPaperGiven(ask_for_a_paper())
    if not os.path.exists(path):
        raise NoPaperGiven(ask_for_a_paper(
            f"No such file: {path}"))
    if not path.lower().endswith(".pdf"):
        raise NoPaperGiven(ask_for_a_paper(
            f"{path} is not a PDF. This stage reads rendered pages."))
    if os.path.getsize(path) < 1024:
        raise NoPaperGiven(ask_for_a_paper(
            f"{path} is {os.path.getsize(path)} bytes -- too small to be a paper. "
            f"An upload may have failed."))
    return describe(path)


def artifact_paths(paper: Paper, outdir: str = "outputs/interpretation") -> dict:
    """Where this paper's per-stage artifacts live. Slug-keyed, never shared."""
    return {
        "analysis": os.path.join(outdir, f"{paper.slug}__analysis.json"),
        "critique": os.path.join(outdir, f"{paper.slug}__critique.json"),
        "gate_a": os.path.join(outdir, f"{paper.slug}__gate_a_queue.md"),
        "card": os.path.join("cards", f"{paper.slug}.yaml"),
    }
