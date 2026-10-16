"""Regenerate tests/known_exceptions.json and print a summary per rule.

  VENUS_INTEROP_CORPUS=<corpus> python tools/known_exceptions.py

Review the diff before committing: a new entry means a rule stopped holding somewhere.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import conftest  # noqa: E402
from venus_interop.rules import placement as rules  # noqa: E402
from venus_interop.files.layout import read_layout  # noqa: E402


def main():
  if conftest.CORPUS is None:
    sys.exit("set VENUS_INTEROP_CORPUS")
  store = conftest.store.__wrapped__()
  out, totals = {}, {r: [0, 0, 0] for r in rules.RULES}
  for path in conftest.LAYOUTS:
    rep = rules.rule_report(read_layout(path), store)
    fails = {}
    for r, res in rep.items():
      totals[r][0] += res.passed
      totals[r][1] += len(res.failures)
      totals[r][2] += res.skipped
      if res.failures:
        fails[r] = sorted({lid for lid, _ in res.failures})
    if fails:
      out[path.name] = fails
  (ROOT / "tests" / "known_exceptions.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
  for r, (p, f, s) in totals.items():
    print(f"{r:18} {p:5} pass  {f:4} known exceptions  {s:3} skipped")
  print(f"definitions not found: {len(store.missing)}")


if __name__ == "__main__":
  main()
