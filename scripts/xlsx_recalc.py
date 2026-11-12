# Quant AI Researcher
"""Recalculate a workbook in place and report what could not be calculated. Prints one JSON object.

Engine: desktop Excel where it is installed (the SE Return Analytics sheet uses LET, SCAN and LAMBDA, which only Excel
calculates), LibreOffice otherwise. The engine used is in the result, with every cell that holds an error after
recalculation, and separately the cells this engine cannot calculate at all (`not_calculated`).

usage: python scripts/xlsx_recalc.py <file.xlsx> [--engine excel|libreoffice]
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXCEL_ONLY = ("_xlfn.LET", "_xlfn.SCAN", "_xlfn.LAMBDA", "_xlfn._xlws.FILTER", "_xlpm.")


def excel_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        import win32com.client  # noqa: F401
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Excel.Application"))
        return True
    except Exception:  # noqa: BLE001 -- any failure here means "no Excel": the fallback engine is used and named
        return False


def _scan(path: str) -> dict:
    """Formula count and the cells holding an error, read back from the saved file."""
    import openpyxl
    f = openpyxl.load_workbook(path)
    v = openpyxl.load_workbook(path, data_only=True)
    total, errors, excel_only = 0, {}, []
    for ws in f.worksheets:
        wv = v[ws.title]
        for row in ws.iter_rows():
            for c in row:
                text = c.value.text if hasattr(c.value, "text") else c.value
                if not (isinstance(text, str) and text.startswith("=")):
                    continue
                total += 1
                val = wv[c.coordinate].value
                ref = f"{ws.title}!{c.coordinate}"
                if isinstance(val, str) and val.startswith("#") or val is None and any(k in text for k in EXCEL_ONLY):
                    errors.setdefault(val if isinstance(val, str) else "(no value)", []).append(ref)
                    if any(k in text for k in EXCEL_ONLY):
                        excel_only.append(ref)
    return {"total_formulas": total, "errors": errors, "excel_only_errors": excel_only}


def with_excel(path: str) -> None:
    import win32com.client as win32
    xl = win32.DispatchEx("Excel.Application")
    xl.Visible = False
    xl.DisplayAlerts = False
    try:
        wb = xl.Workbooks.Open(os.path.abspath(path), UpdateLinks=0)
        xl.CalculateFullRebuild()
        wb.Save()
        wb.Close(False)
    finally:
        xl.Quit()


def main(path: str, engine: str | None = None) -> dict:
    engine = engine or ("excel" if excel_available() else "libreoffice")
    if engine == "excel":
        with_excel(path)
    else:
        p = subprocess.run([sys.executable, os.path.join(HERE, "xlsx_recalc_libreoffice.py"), path], capture_output=True, text=True, check=False)
        if not (p.stdout or "").strip().startswith("{"):
            return {"status": "failed", "engine": engine, "error": (p.stderr or p.stdout)[-500:]}
    s = _scan(path)
    n = sum(len(x) for x in s["errors"].values())
    # Under LibreOffice the Excel-only cells are expected failures: they are listed, never rewritten to suit the engine.
    not_calc = s["excel_only_errors"] if engine != "excel" else []
    real = n - len(not_calc)
    return {"status": "success" if real == 0 else "errors_found", "engine": engine, "total_formulas": s["total_formulas"],
            "total_errors": real, "error_summary": {k: [c for c in v if c not in not_calc][:100] for k, v in s["errors"].items() if [c for c in v if c not in not_calc]},
            "not_calculated": not_calc[:400], "n_not_calculated": len(not_calc)}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    eng = next((sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--engine" and i + 1 < len(sys.argv)), None)
    print(json.dumps(main(args[0], eng), indent=2))
