"""How much of the labware used in layouts has a 3D model, and from where.

  python tools/model_coverage.py --corpus DIR [--ngs DIR] [--glb-dirs DIR ...]

For each definition used (and each placement of it):
  authored  the definition names a Hamilton model (3DModel) and the .x/.hxx is found here
  named     it names one, but the file is not here
  plr       pylabrobot (or the given --glb-dirs) has a model with the definition's or its mapped factory's name
  none      nothing; tools/generate_labware.py would generate one
"""
import argparse
import collections
import csv
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from venus_interop.files import layout  # noqa: E402
from venus_interop.files.definitions import DEFAULT_VENUS_LABWARE, DefinitionStore, normalize  # noqa: E402
from venus_interop.rules import placement as rules  # noqa: E402


def glb_names(dirs):
  names = set()
  for d in dirs:
    for dp, _, fs in os.walk(d):
      names |= {f.rsplit(".", 1)[0].lower() for f in fs if f.lower().endswith(".glb")}
  return names


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--corpus")
  ap.add_argument("--ngs")
  ap.add_argument("--glb-dirs", nargs="*", default=[])
  a = ap.parse_args()
  items = []
  if a.corpus:
    index = {}
    with open(pathlib.Path(a.corpus) / "defs_index.tsv", encoding="utf-8") as f:
      for name, rel, _ in csv.reader(f, delimiter="\t"):
        if (pathlib.Path(a.corpus) / "defs_raw" / name).exists():
          index[rel] = pathlib.Path(a.corpus) / "defs_raw" / name
    st = DefinitionStore([DEFAULT_VENUS_LABWARE], index)
    items += [(p, st) for p in sorted((pathlib.Path(a.corpus) / "raw").glob("*.lay"))]
  if a.ngs:
    ngs = pathlib.Path(a.ngs)
    kits = [pathlib.Path(dp, d) for base in (ngs, pathlib.Path(r"C:\Program Files (x86)\HAMILTON\NGSStar"))
            if base.exists() for dp, ds, _ in os.walk(base) for d in ds if d.lower() == "labware"]
    st = DefinitionStore(kits + [DEFAULT_VENUS_LABWARE], by_name=True)
    items += [(p, st) for p in sorted(ngs.rglob("*.lay"))]

  try:
    import pylabrobot

    plr_glbs = glb_names([pathlib.Path(pylabrobot.__file__).parent])
  except ImportError:
    plr_glbs = set()
  extra = glb_names(a.glb_dirs)
  stock = json.loads((ROOT / "venus_interop" / "plr" / "data" / "stock_map.json").read_text())
  venus_to_plr = {normalize(e["file"]): fn.lower() for fn, e in stock.items()}

  used = collections.Counter()
  status = {}
  for path, st in items:
    lay = layout.read_layout(path)
    if lay.header.get("Deck", "").lower() not in rules.STAR_DECKS:
      continue
    for p in lay.labware + [p.lid for p in lay.labware if p.lid]:
      key = normalize(p.file)
      used[key] += 1
      if key in status:
        continue
      d = st.get(p.file)
      stem = key.rsplit("/", 1)[-1].rsplit(".", 1)[0]
      kind = key.rsplit(".", 1)[-1]
      if d is None:
        status[key] = (kind, "definition missing")
        continue
      ref = d.fields.get("3DModel") or d.fields.get("3DModelRel")
      found = None
      if ref:
        found = st.find(ref) or (d.source.parent / ref.replace("\\", "/") if d.source else None)
        found = found if found is not None and pathlib.Path(found).exists() else st.find_by_name(ref)
      if found is not None:
        status[key] = (kind, "authored (Hamilton .x/.hxx here)")
      elif {stem, venus_to_plr.get(key, "")} & (plr_glbs | extra):
        status[key] = (kind, "pylabrobot / scratch .glb")
      elif ref:
        status[key] = (kind, "named, file not here")
      else:
        status[key] = (kind, "none (would be generated)")

  def table(weight):
    t = collections.defaultdict(collections.Counter)
    for key, (kind, s) in status.items():
      t[kind][s] += used[key] if weight else 1
    return t

  for title, weight in (("distinct definitions", False), ("placements", True)):
    print(f"\n{title}:")
    t = table(weight)
    for kind in ("tml", "rck", "lid", "ctr"):
      if kind not in t:
        continue
      n = sum(t[kind].values())
      parts = ", ".join(f"{s} {v} ({100 * v / n:.0f}%)" for s, v in t[kind].most_common())
      print(f"  {kind:4} {n:5}: {parts}")


if __name__ == "__main__":
  main()
