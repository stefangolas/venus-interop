"""Build venus_interop/plr/data/stock_map.json: PLR factory -> the Venus file that is provably the same labware.

  python tools/build_stock_map.py [--corpus DIR]

Uses the alias rule (name_match.alias_target): the same tip type and rack, the same name, or a PLR
docstring naming the Hamilton file. Scans the local Venus Labware folder and the corpus definitions.
When several Venus files match one factory, the shortest path under ML_STAR wins.
"""
import argparse
import importlib
import csv
import json
import logging
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from venus_interop.plr import name_match  # noqa: E402
from venus_interop.files.definitions import DEFAULT_VENUS_LABWARE, Carrier, DefinitionStore, Rack  # noqa: E402


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--corpus")
  a = ap.parse_args()
  logging.disable(logging.WARNING)

  index, rels = {}, {}
  if DEFAULT_VENUS_LABWARE.is_dir():
    for dirpath, _, files in os.walk(DEFAULT_VENUS_LABWARE):
      for f in files:
        if f.lower().endswith((".rck", ".tml")):
          p = pathlib.Path(dirpath, f)
          rels[str(p.relative_to(DEFAULT_VENUS_LABWARE))] = "venus install"
  if a.corpus:
    with open(pathlib.Path(a.corpus) / "defs_index.tsv", encoding="utf-8") as f:
      for name, rel, src in csv.reader(f, delimiter="\t"):
        p = pathlib.Path(a.corpus) / "defs_raw" / name
        if p.exists() and rel.endswith((".rck", ".tml")):
          index[rel] = p
          rels.setdefault(rel.replace("/", "\\"), "corpus")
  store = DefinitionStore([DEFAULT_VENUS_LABWARE] if DEFAULT_VENUS_LABWARE.is_dir() else [], index)
  catalogue = name_match.plr_catalogue()

  found = {}
  for rel, source in sorted(rels.items()):
    d = store.get(rel)
    if not isinstance(d, (Rack, Carrier)):
      continue
    fp = name_match.venus_fingerprint(d, store)
    if fp is None:
      continue
    matches = [m for m in name_match.best_matches(rel, fp, catalogue, 10) if m.verdict == "match"]
    plr = {m.candidate.factory for m in matches if "Deprecated alias" not in m.candidate.doc}
    target = name_match.alias_target(rel, fp, matches, plr)
    if target:
      fn = target[0].rsplit(".", 1)[-1]
      found.setdefault(fn, []).append({"file": rel, "why": target[1], "source": source, "factory": target[0]})

  out = {}
  for fn, options in sorted(found.items()):
    options.sort(key=lambda o: (o["why"] != "same name", not o["file"].lower().startswith("ml_star\\"), o["source"] != "venus install",
                                len(o["file"]), o["file"].lower()))
    mod, f = options[0]["factory"].rsplit(".", 1)
    model = getattr(importlib.import_module(mod), f)("probe").model  # factories often set their base's name
    out[fn] = {**options[0], "model": model, "alternatives": [o["file"] for o in options[1:]]}
  dest = ROOT / "venus_interop" / "plr" / "data" / "stock_map.json"
  dest.parent.mkdir(parents=True, exist_ok=True)
  dest.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
  for fn, e in out.items():
    print(f"{fn:44} -> {e['file']:50} ({e['why']}; {len(e['alternatives'])} alternatives)")


if __name__ == "__main__":
  main()
