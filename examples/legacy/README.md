# Retired

## `build_colab.py`

Generated `colab/Research_OS_Colab.ipynb` — a self-contained notebook with the
engine embedded as a base64 tarball.

**Superseded by `colab_bootstrap.py`.** The notebook could not be kept correct:
Colab caches GitHub notebooks and offers a *Copy to Drive* that then reopens in
place of the original, so fixing the source did nothing for anyone running their
saved copy. The symptom — a cell that no longer exists still failing — looked
exactly like a fix that never landed. `colab_bootstrap.py` is fetched live over
https on every run, so there is nothing to cache and nothing to go stale.

It is kept here rather than deleted because it is a record of how the Colab path
worked. It is not on any code path, and it hardcodes a specific paper throughout
— which is why it is out of the top level, where the no-default-paper test scans.
