"""Recalculate a workbook with desktop Excel (COM) and report formula errors.

Windows fallback for the xlsx skill's recalc.py, which needs LibreOffice. Opens the file in Excel,
forces a full calculation, saves it in place (so cached values exist for pandas / previewers) and prints JSON.

usage: python scripts/xlsx_recalc_excel.py outputs/<name>.xlsx
"""
import json
import os
import sys


def main(path):
    import win32com.client as win32

    path = os.path.abspath(path)
    xl = win32.DispatchEx("Excel.Application")
    xl.Visible = False
    xl.DisplayAlerts = False
    errors, total = {}, 0
    try:
        wb = xl.Workbooks.Open(path)
        xl.CalculateFull()
        for ws in wb.Worksheets:
            used = ws.UsedRange
            for cell in used.Cells:
                if cell.HasFormula:
                    total += 1
                    v = cell.Text
                    if isinstance(v, str) and v.startswith("#"):
                        errors.setdefault(v, []).append(f"{ws.Name}!{cell.Address.replace('$', '')}")
        wb.Save()
        wb.Close(False)
    finally:
        xl.Quit()
    n_err = sum(len(v) for v in errors.values())
    print(json.dumps({"status": "success" if not n_err else "errors_found", "total_formulas": total,
                      "total_errors": n_err, "error_summary": {k: v[:100] for k, v in errors.items()}}, indent=2))


if __name__ == "__main__":
    main(sys.argv[1])
