"""Where Hamilton's stock files and pylabrobot's models of the same labware disagree.

  python tools/audit_stock.py

For every factory in venus_interop/plr/data/stock_map.json, build it in pylabrobot, read the stock Venus file
the way the importer does, and list every difference (the same check deck_export makes before it uses a
stock file). No output for a factory means the two agree to 0.001 mm.
"""
import importlib
import logging
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pylabrobot.resources import Resource  # noqa: E402
from pylabrobot.resources.hamilton import STARDeck  # noqa: E402

from venus_interop.plr import deck_export  # noqa: E402
from venus_interop.files.definitions import DEFAULT_VENUS_LABWARE, DefinitionStore  # noqa: E402


def main():
  logging.disable(logging.WARNING)
  store = DefinitionStore([DEFAULT_VENUS_LABWARE])
  ex = deck_export._Exporter(STARDeck(), store, "PLR")
  agree, disagree = [], []
  for fn, entry in sorted(deck_export.stock_map().items()):
    mod, f = entry["factory"].rsplit(".", 1)
    r = getattr(importlib.import_module(mod), f)(fn)
    holder = Resource("audit", 1e4, 1e4, 1e4)
    holder.assign_child_resource(r, location=deck_export.Coordinate(0, 0, 0))
    d = store.get(entry["file"])
    if d is None:
      print(f"{fn:42} {entry['file']}: not installed here")
      continue
    diffs = ex.stock_differences(r, entry["file"], d)
    (disagree if diffs else agree).append(fn)
    for q, a, b, size in diffs:
      print(f"{fn:42} {entry['file']:36} {q:22} PLR {a}  Venus {b}  ({size:.3g} mm)")
  print(f"\nagree exactly: {len(agree)}  {agree}\ndisagree: {len(disagree)}")


if __name__ == "__main__":
  main()
