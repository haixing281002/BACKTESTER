"""Step 01 -- INGEST. Deterministic evidence extraction from a paper PDF.

This module does NOT decide what the strategy is. It produces page-anchored
evidence and an extraction-quality report that tells a human (and the AI that
drafts the card) how much of the PDF can actually be trusted.

The distinction matters: PDF text extraction silently destroys mathematics.
`w^spy_t + w^agg_t <= 1` comes out as `wspy +wagg +wgld <= 1` with subscripts
dropped, and rotated figure labels come out reversed ("nruter evitalumuC").
An LLM handed that text will confidently invent a formula. So we measure the
damage and refuse to let equations become card fields without human sign-off.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

try:
    import pdfplumber
except ImportError:  # pragma: no cover
    pdfplumber = None


# --------------------------------------------------------------------------
# Evidence containers
# --------------------------------------------------------------------------
@dataclass
class PageEvidence:
    page: int                    # 1-indexed, matches what a human sees in a viewer
    text: str
    n_chars: int
    n_tables: int
    tables: List[List[List[Optional[str]]]] = field(default_factory=list)
    math_density: float = 0.0    # fraction of lines that look like broken math
    reversed_text: bool = False  # rotated axis labels detected -> figure page


@dataclass
class Hit:
    """A regex hit with its page, so every card field can cite page evidence."""
    kind: str
    value: str
    page: int
    context: str


@dataclass
class ExtractionQuality:
    n_pages: int
    n_chars: int
    n_empty_pages: int
    n_table_pages: int
    mean_math_density: float
    reversed_pages: List[int]
    is_scanned: bool
    warnings: List[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return not self.is_scanned and self.n_chars > 2000


@dataclass
class Document:
    path: str
    sha256: str
    pages: List[PageEvidence]
    hits: List[Hit]
    quality: ExtractionQuality
    numeric_tables: List[Dict[str, Any]] = field(default_factory=list)

    def text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    def page_text(self, page: int) -> str:
        return self.pages[page - 1].text

    def hits_of(self, kind: str) -> List[Hit]:
        return [h for h in self.hits if h.kind == kind]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # page text is bulky; keep it out of the JSON manifest
        for p in d["pages"]:
            p.pop("text", None)
            p.pop("tables", None)
        return d


# --------------------------------------------------------------------------
# Heuristic scanners. Each returns page-anchored candidates -- never decisions.
# --------------------------------------------------------------------------
_SCANNERS: Dict[str, str] = {
    # rebalance cadence
    "rebalance": r"\b(rebalanc\w+)\s+(daily|weekly|monthly|quarterly|annually|semi-annually)\b"
                 r"|\b(daily|weekly|monthly|quarterly|annual|annually)\s+rebalanc\w+",
    # explicit cost assumptions
    "cost_bps": r"(\d+(?:\.\d+)?)\s*basis\s*points?|(\d+(?:\.\d+)?)\s*bps\b|bid-ask spread[^.]{0,60}?(\d\.\d+)",
    # lookback / estimation windows
    "lookback": r"trailing window of (\d+)\s*(?:trading\s*)?days?"
                r"|(\d+)[- ]day (?:trailing|rolling|lookback|moving)"
                r"|half-?life of (\d+)\s*(?:trading\s*)?days?",
    # volatility target
    "target_vol": r"(?:target|targeted)[^.]{0,40}?volatility[^.]{0,40}?(\d+(?:\.\d+)?)\s*%"
                  r"|(\d+(?:\.\d+)?)\s*%\s*annualized[^.]{0,20}(?:volatility|target)"
                  r"|volatility target of[^.]{0,20}?(\d+(?:\.\d+)?)\s*%",
    # sample period
    "sample_period": r"\b((?:19|20)\d{2})\s*[-–—to]{1,4}\s*((?:19|20)\d{2})\b"
                     r"|from\s+\w+\.?\s+\d{1,2}(?:st|nd|rd|th)?\s+((?:19|20)\d{2})\s+to",
    # instruments / tickers
    "ticker": r"\b(SPY|AGG|GLD|TLT|IEF|QQQ|IWM|VTI|EFA|EEM|NIFTY\s?\d*|SENSEX)\b",
    # constraints
    "constraint": r"\b(long[- ]only|no leverage|unlevered|no derivatives|nonnegative|leverage)\b",
    # benchmark
    "benchmark": r"\b(60/40|50/30/20|equal[- ]weight|1/N|market[- ]cap weighted|risk parity)\b",
    # data provenance
    "data_source": r"\b(Yahoo Finance|FRED|CRSP|Compustat|Bloomberg|Kenneth French|Refinitiv|NSE|BSE|Capitaline|Prowess)\b",
    # code availability -- a strong green flag
    "code_url": r"(https?://(?:github\.com|gitlab\.com)/[\w\-./]+)",
    # headline risk-adjusted numbers, for replication targets
    "sharpe": r"Sharpe ratio[^.\n]{0,60}?(\d\.\d{1,2})",
}

# Broken-math fingerprints: subscripts collapsed, operators orphaned, cid artifacts.
_MATH_PAT = re.compile(
    r"\(cid:\d+\)"                       # unmapped glyphs
    r"|[≤≥≠±∑∏√∈∥⊤θσαβλρτηΣΩ]"          # math unicode
    r"|\b[a-zA-Z]\s*=\s*[-+]?\d"         # scalar assignment
    r"|\^\{|_\{"                          # latex remnants
    r"|\b\d+\s*[Tt]\s*w\b"               # collapsed transpose e.g. '1Tw'
)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _looks_reversed(text: str) -> bool:
    """Rotated figure labels extract backwards. Detect by checking whether
    reversing rare long tokens produces dictionary-ish English."""
    markers = ("nruter", "ytilitalov", "thgieW", "oiter", "eprahS", "etaD", "raeY")
    return any(m in text for m in markers)


def _math_density(text: str) -> float:
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return 0.0
    return sum(1 for l in lines if _MATH_PAT.search(l)) / len(lines)


def _numeric_table(tbl: List[List[Optional[str]]]) -> bool:
    """A table worth keeping as a replication target: >=2 rows, >=2 numeric cells
    per row on average."""
    if not tbl or len(tbl) < 2:
        return False
    num = 0
    cells = 0
    for row in tbl:
        for c in row or []:
            if c is None:
                continue
            cells += 1
            if re.fullmatch(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?", c.strip()):
                num += 1
    return cells > 0 and num / cells > 0.35


def extract_document(path: str, max_pages: Optional[int] = None) -> Document:
    """Parse a PDF into page-anchored evidence plus an extraction-quality report."""
    if pdfplumber is None:
        raise RuntimeError("pdfplumber is required for PDF ingestion (pip install pdfplumber)")

    pages: List[PageEvidence] = []
    numeric_tables: List[Dict[str, Any]] = []

    with pdfplumber.open(path) as pdf:
        page_iter = pdf.pages[:max_pages] if max_pages else pdf.pages
        for i, pg in enumerate(page_iter, start=1):
            text = pg.extract_text() or ""
            try:
                tables = pg.extract_tables() or []
            except Exception:
                tables = []
            pages.append(PageEvidence(
                page=i, text=text, n_chars=len(text), n_tables=len(tables),
                tables=tables,
                math_density=_math_density(text),
                reversed_text=_looks_reversed(text),
            ))
            for t in tables:
                if _numeric_table(t):
                    numeric_tables.append({"page": i, "rows": t})

    total_chars = sum(p.n_chars for p in pages)
    empty = sum(1 for p in pages if p.n_chars < 50)
    quality = ExtractionQuality(
        n_pages=len(pages),
        n_chars=total_chars,
        n_empty_pages=empty,
        n_table_pages=sum(1 for p in pages if p.n_tables),
        mean_math_density=(sum(p.math_density for p in pages) / len(pages)) if pages else 0.0,
        reversed_pages=[p.page for p in pages if p.reversed_text],
        is_scanned=bool(pages) and total_chars / max(len(pages), 1) < 200,
    )
    if quality.is_scanned:
        quality.warnings.append(
            "Near-zero text per page: PDF is likely scanned. OCR required; do NOT card it from this text.")
    if quality.mean_math_density > 0.05:
        quality.warnings.append(
            f"Math-bearing lines on {quality.mean_math_density:.0%} of lines. Equations are "
            "unreliable after extraction -- any card field derived from a formula needs "
            "human verification against the rendered page.")
    if quality.reversed_pages:
        quality.warnings.append(
            f"Reversed (rotated) text on pages {quality.reversed_pages}: figure axis labels. "
            "Numbers must not be read off these pages.")
    if empty:
        quality.warnings.append(f"{empty} page(s) produced almost no text (figures/images).")

    # run scanners
    hits: List[Hit] = []
    for kind, pat in _SCANNERS.items():
        rx = re.compile(pat, re.IGNORECASE)
        for p in pages:
            if p.reversed_text:
                continue  # never harvest values from mangled figure pages
            for m in rx.finditer(p.text):
                val = next((g for g in m.groups() if g), m.group(0))
                s, e = max(0, m.start() - 70), min(len(p.text), m.end() + 70)
                hits.append(Hit(kind=kind, value=str(val).strip(), page=p.page,
                                context=" ".join(p.text[s:e].split())))

    return Document(path=path, sha256=_sha256(path), pages=pages, hits=hits,
                    quality=quality, numeric_tables=numeric_tables)


def summarize(doc: Document, top: int = 6) -> str:
    """Human-readable ingestion summary -- the thing a researcher reads at Gate A."""
    q = doc.quality
    out = [
        "STEP 01 -- INGEST",
        f"  file          : {doc.path}",
        f"  sha256        : {doc.sha256[:16]}...",
        f"  pages         : {q.n_pages}   chars: {q.n_chars:,}   table-pages: {q.n_table_pages}",
        f"  math density  : {q.mean_math_density:.1%} of lines   scanned: {q.is_scanned}",
        f"  numeric tables: {len(doc.numeric_tables)} (candidate replication targets)",
    ]
    if q.warnings:
        out.append("  EXTRACTION WARNINGS:")
        out += [f"    ! {w}" for w in q.warnings]
    out.append("  CANDIDATE FIELDS (page-anchored, for human confirmation):")
    seen: Dict[str, List[Tuple[str, int]]] = {}
    for h in doc.hits:
        seen.setdefault(h.kind, [])
        if len(seen[h.kind]) < top and (h.value, h.page) not in seen[h.kind]:
            seen[h.kind].append((h.value, h.page))
    for kind in _SCANNERS:
        vals = seen.get(kind, [])
        if vals:
            rendered = ", ".join(f"{v} (p{p})" for v, p in vals)
            out.append(f"    {kind:<14}: {rendered}")
        else:
            out.append(f"    {kind:<14}: -- none found --")
    return "\n".join(out)


# --------------------------------------------------------------------------
# Text-geometry table parser.
#
# Why this exists: pdfplumber's extract_tables() finds ruled tables. Academic
# papers use LaTeX booktabs, which draw almost no rules, so extract_tables()
# returns nothing on exactly the pages that matter -- the results tables that
# define our replication targets. We therefore parse tables from text geometry:
# a table row is a text label followed by >=2 numeric tokens.
# --------------------------------------------------------------------------
_NUM = re.compile(r"^[-+]?\(?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?%?$")
_CAPTION = re.compile(r"^Table\s+(\d+|[A-Z]\d*)\s*[:.]\s*(.*)", re.IGNORECASE)


def _tokenize_row(line: str) -> Optional[Tuple[str, List[float]]]:
    """Split 'Simple Markowitz 10.4% 9.3% 0.91' -> ('Simple Markowitz', [10.4, 9.3, 0.91]).

    Percent signs are stripped and the value divided by 100, so a table reports
    values in the units the engine compares against.
    """
    toks = line.split()
    if len(toks) < 3:
        return None
    # walk from the right while tokens are numeric
    vals: List[float] = []
    i = len(toks)
    while i > 0 and _NUM.match(toks[i - 1]):
        t = toks[i - 1]
        neg = t.startswith("(") and t.endswith(")")
        t = t.strip("()")
        pct = t.endswith("%")
        t = t.rstrip("%").replace(",", "")
        try:
            v = float(t)
        except ValueError:
            break
        if pct:
            v /= 100.0
        if neg:
            v = -v
        vals.append(v)
        i -= 1
    vals.reverse()
    label = " ".join(toks[:i]).strip()
    if len(vals) < 2 or not label:
        return None
    # a label that is itself mostly digits is a data artifact, not a row label
    if sum(c.isdigit() for c in label) > len(label) / 2:
        return None
    return label, vals


def parse_text_tables(doc: "Document", min_rows: int = 2) -> List[Dict[str, Any]]:
    """Recover numeric tables from text layout, anchored to their 'Table N:' caption.

    Returns dicts: {page, table_id, caption, header, rows: {label: [values]}}.
    Generic across papers -- nothing here knows about this particular paper.
    """
    found: List[Dict[str, Any]] = []

    for p in doc.pages:
        if p.reversed_text:
            continue  # figure page: numbers here are axis ticks, not results
        lines = [l.rstrip() for l in p.text.splitlines()]
        blocks: List[Tuple[int, int, List[Tuple[str, List[float]]]]] = []
        cur: List[Tuple[str, List[float]]] = []
        start = 0
        for idx, line in enumerate(lines):
            parsed = _tokenize_row(line)
            if parsed:
                if not cur:
                    start = idx
                cur.append(parsed)
            else:
                if len(cur) >= min_rows:
                    blocks.append((start, idx, cur))
                cur = []
        if len(cur) >= min_rows:
            blocks.append((start, len(lines), cur))

        for start, end, rows in blocks:
            width = {len(v) for _, v in rows}
            # a real table has a consistent number of columns
            if len(width) > 2:
                continue

            header = ""
            for back in range(1, 4):
                j = start - back
                if j >= 0 and lines[j].strip() and not _tokenize_row(lines[j]):
                    header = lines[j].strip()
                    break

            caption, table_id = "", None
            for fwd in range(0, 6):
                j = end + fwd
                if j < len(lines):
                    m = _CAPTION.match(lines[j].strip())
                    if m:
                        table_id, caption = m.group(1), m.group(2).strip()
                        break
            if table_id is None:  # also look just above (caption-on-top style)
                for back in range(1, 4):
                    j = start - back
                    if j >= 0:
                        m = _CAPTION.match(lines[j].strip())
                        if m:
                            table_id, caption = m.group(1), m.group(2).strip()
                            break

            found.append({
                "page": p.page,
                "table_id": table_id,
                "caption": caption,
                "header": header,
                "n_cols": max(width),
                "rows": {lbl: vals for lbl, vals in rows},
            })
    return found


def propose_replication_targets(
    tables: List[Dict[str, Any]],
    metric_aliases: Optional[Dict[str, List[str]]] = None,
) -> List[Dict[str, Any]]:
    """Turn parsed tables into candidate replication targets.

    Matches header words to canonical metric names so the same code works for any
    paper that prints a portfolio-by-metric results table. Output is a PROPOSAL:
    a human confirms it at Gate A before it becomes a pass/fail criterion.
    """
    aliases = metric_aliases or {
        "cagr": ["return", "cagr", "annualized return", "ann. return"],
        "vol": ["volatility", "vol", "risk", "std"],
        "sharpe": ["sharpe"],
        "max_dd": ["max dd", "maxdd", "max drawdown", "maximum drawdown"],
        "mean_dd": ["mean dd", "meandd", "mean drawdown", "average drawdown"],
        "turnover": ["turnover"],
    }
    proposals: List[Dict[str, Any]] = []
    for t in tables:
        header = (t.get("header") or "").lower()
        if not header:
            continue
        # map each header word-group to a column index
        hdr_tokens = header.split()
        cols: List[Optional[str]] = []
        i = 0
        while i < len(hdr_tokens):
            matched = None
            for canon, names in aliases.items():
                for nm in sorted(names, key=len, reverse=True):
                    span = len(nm.split())
                    cand = " ".join(hdr_tokens[i:i + span]).lower()
                    if cand == nm:
                        matched, i = (canon, i + span)
                        break
                if matched:
                    break
            if matched:
                cols.append(matched)
            else:
                cols.append(None)
                i += 1
        metric_cols = [c for c in cols if c]
        if not metric_cols:
            continue
        for label, vals in t["rows"].items():
            if len(vals) != len(metric_cols):
                continue
            for metric, value in zip(metric_cols, vals):
                proposals.append({
                    "portfolio": label,
                    "metric": metric,
                    "value": value,
                    "evidence_page": t["page"],
                    "source_table": t.get("table_id"),
                })
    return proposals


def detect_target_conflicts(proposals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Find (portfolio, metric) pairs that appear with different values.

    This is not a parser bug -- it is the paper reporting the same metric under
    different accounting bases (pre-tax, inflation-adjusted, post-tax bracket,
    subperiod). Harvesting all of them yields a replication test that can never
    fail, because some row always matches. The human must pick the basis at
    Gate A; until then the pipeline refuses to score replication.
    """
    from collections import defaultdict
    buckets = defaultdict(list)
    for p in proposals:
        buckets[(p["portfolio"], p["metric"])].append(p)
    conflicts = []
    for (pf, metric), rows in buckets.items():
        vals = {round(r["value"], 6) for r in rows}
        if len(vals) > 1:
            conflicts.append({
                "portfolio": pf,
                "metric": metric,
                "values": sorted(vals),
                "pages": sorted({r["evidence_page"] for r in rows}),
            })
    return sorted(conflicts, key=lambda c: (c["portfolio"], c["metric"]))
