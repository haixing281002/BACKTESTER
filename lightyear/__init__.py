"""Lightyear: the paper-to-Gate-B pipeline as a local, interactive web page.

    python -m lightyear            # opens http://127.0.0.1:8100

Upload a PDF -> Claude Code (headless, your own login, no API key) runs stages 00-02 and assembles
Gate A -> you approve -> Claude Code runs stages 03-07 and writes the Gate B brief -> Lightyear builds
the interactive charts and the colour-coded workbook from the run's files -> a named human records
the Gate B decision on the page.

The model interprets and writes code; deterministic Python computes every number shown; a human decides.
"""
__version__ = "1.0.0"
