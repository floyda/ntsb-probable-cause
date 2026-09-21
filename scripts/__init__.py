"""Repository tooling scripts. Not part of the library.

Every module here carries a ``Status`` block directly under its summary line, saying which of
three kinds it is. Read that block before reading anything else in the file:

- **Live tool** -- run again whenever its input changes. Most have a ``make`` target, and
  ``README.md`` lists them.
- **One-shot, complete** -- it produced a committed file, usually under ``docs/results/``, and
  its job is done. It is kept because this project publishes no number without the script
  behind it, not because anything still calls it.
- **Deprecated** -- the mechanism it measured no longer exists in the code, usually because
  this very script is the evidence that removed it. Its text describes a measurement, never
  the pipeline. Two scripts are in this state after S2: ``score_handcheck.py`` and
  ``doctype_scan.py``.

``scripts/exploratory/`` holds per-stage design arithmetic. Nothing there is a result.
"""
