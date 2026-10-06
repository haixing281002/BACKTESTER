"""Recalculate a workbook with headless LibreOffice and report formula errors (Windows-friendly).

The xlsx skill's recalc.py needs a unix socket, which Windows Python lacks. This does the same job by
converting the file to xlsx with soffice, which recalculates every formula and stores the cached values,
then scans the result with openpyxl. The file is replaced in place; JSON like recalc.py is printed.

soffice is found from $SOFFICE, then C:\\Users\\<you>\\LibreOffice\\program, then Program Files.

usage: python scripts/xlsx_recalc_libreoffice.py outputs/<name>.xlsx
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

import openpyxl

CANDIDATES = [os.environ.get("SOFFICE", ""),
              os.path.expanduser(r"~\LibreOffice\program\soffice.exe"),
              r"C:\Program Files\LibreOffice\program\soffice.exe",
              shutil.which("soffice") or ""]


def find_soffice():
    for p in CANDIDATES:
        if p and os.path.exists(p):
            return p
    raise SystemExit(json.dumps({"error": "soffice not found; set SOFFICE to its full path"}))


def main(path):
    path = os.path.abspath(path)
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([find_soffice(), "--headless", "--convert-to", "xlsx:Calc MS Excel 2007 XML",
                        "--outdir", tmp, path], check=True, capture_output=True, timeout=300)
        out = os.path.join(tmp, os.path.basename(path))
        vals, forms = openpyxl.load_workbook(out, data_only=True), openpyxl.load_workbook(out)
        errors, total = {}, 0
        for ws in forms:
            for row in ws.iter_rows():
                for c in row:
                    if isinstance(c.value, str) and c.value.startswith("="):
                        total += 1
                        v = vals[ws.title][c.coordinate].value
                        if isinstance(v, str) and v.startswith("#"):
                            errors.setdefault(v, []).append(f"{ws.title}!{c.coordinate}")
        shutil.copyfile(out, path)
    n_err = sum(len(v) for v in errors.values())
    print(json.dumps({"status": "success" if not n_err else "errors_found", "total_formulas": total,
                      "total_errors": n_err, "error_summary": {k: v[:100] for k, v in errors.items()}}, indent=2))


if __name__ == "__main__":
    main(sys.argv[1])
