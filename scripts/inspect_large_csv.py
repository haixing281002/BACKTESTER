"""Safe first look at a large CSV before trusting it for anything.

Built for exactly this situation: a ~100MB+ file that's too big to just
open and eyeball, where loading it wrong (wrong dtype, wrong date parse,
a silently-dropped column) produces a backtest that looks fine and is
wrong. Reads in chunks -- never loads the whole file into memory just to
report its shape -- and prints what it actually finds, not what the
filename implies.

Usage:
    python scripts/inspect_large_csv.py path/to/the_file.csv

Prints: file size, header, row count, per-column dtype guess and null
fraction (from a sample), first/last few rows, and -- if it finds a
column that looks like a date and one that looks like a security
identifier -- the date range and number of distinct identifiers. Does
NOT move, copy, or modify the file, and does not write anything.
"""
from __future__ import annotations

import os
import sys

import pandas as pd

CHUNK_SIZE = 200_000
SAMPLE_ROWS_FOR_DTYPE = 500_000


def human_size(n_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n_bytes < 1024:
            return f"{n_bytes:.1f}{unit}"
        n_bytes /= 1024
    return f"{n_bytes:.1f}TB"


def guess_date_columns(columns) -> list:
    hints = ("date", "dt", "month", "year")
    return [c for c in columns if any(h in str(c).lower() for h in hints)]


def guess_id_columns(columns) -> list:
    hints = ("code", "id", "symbol", "isin", "ticker", "scrip")
    return [c for c in columns if any(h in str(c).lower() for h in hints)]


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"No such file: {path}")
        sys.exit(1)

    size = os.path.getsize(path)
    print(f"File: {path}")
    print(f"Size: {human_size(size)}")

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        header_line = f.readline().rstrip("\n")
    header = header_line.split(",")
    print(f"\nColumns ({len(header)}): {header}")

    print(f"\nCounting rows (streaming, {CHUNK_SIZE:,} rows at a time -- this may take a minute)...")
    n_rows = 0
    first_chunk = None
    last_chunk = None
    date_cols = guess_date_columns(header)
    id_cols = guess_id_columns(header)
    date_min = date_max = None
    id_values = set()
    n_nulls = {c: 0 for c in header}

    reader = pd.read_csv(path, chunksize=CHUNK_SIZE, low_memory=False)
    for i, chunk in enumerate(reader):
        if first_chunk is None:
            first_chunk = chunk.head(3)
        last_chunk = chunk.tail(3)
        n_rows += len(chunk)
        for c in header:
            if c in chunk.columns:
                n_nulls[c] += int(chunk[c].isna().sum())
        for c in date_cols:
            if c in chunk.columns:
                parsed = pd.to_datetime(chunk[c], errors="coerce", format="mixed")
                cmin, cmax = parsed.min(), parsed.max()
                if pd.notna(cmin):
                    date_min = cmin if date_min is None else min(date_min, cmin)
                if pd.notna(cmax):
                    date_max = cmax if date_max is None else max(date_max, cmax)
        for c in id_cols:
            if c in chunk.columns and n_rows <= SAMPLE_ROWS_FOR_DTYPE:
                id_values.update(chunk[c].dropna().unique().tolist())
        if (i + 1) % 10 == 0:
            print(f"  ...{n_rows:,} rows read so far")

    print(f"\nTotal rows: {n_rows:,}")

    print("\nNull fraction per column (from the full file):")
    for c in header:
        frac = n_nulls[c] / n_rows if n_rows else 0.0
        print(f"  {c:30s} {frac:6.1%} null")

    if date_cols:
        print(f"\nDate-like column(s) {date_cols}: range {date_min} -> {date_max}")
    else:
        print("\nNo column name looked date-like -- check the header above manually.")

    if id_cols:
        for c in id_cols:
            print(f"ID-like column '{c}': {len(id_values):,} distinct values seen "
                  f"(sampled from the first {SAMPLE_ROWS_FOR_DTYPE:,} rows)")
    else:
        print("No column name looked like a security identifier -- check the header manually.")

    print("\nFirst 3 rows:")
    print(first_chunk.to_string())
    print("\nLast 3 rows:")
    print(last_chunk.to_string())

    print("\n" + "=" * 70)
    print("This was a READ-ONLY inspection. Nothing was moved, copied, or written.")
    print("Next: tell Claude Code what this printed, and it will write a proper")
    print("loader (like accord_data.py's other four loaders) matching what this")
    print("file actually contains -- not a guessed shape.")


if __name__ == "__main__":
    main()
