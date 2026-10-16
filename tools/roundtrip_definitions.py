"""Round trips for labware definitions, reported per resource.

  python tools/roundtrip_definitions.py plr                 PLR -> Venus files -> PLR, over PLR's catalogue
  python tools/roundtrip_definitions.py venus --corpus DIR  Venus -> PLR -> Venus files -> PLR, corpus definitions

Compares what both sides model: footprint, positions (from the centre), item size and depth, the
container floor, volume at five heights, tip type. Prints a summary and the worst cases.
"""
import argparse
import collections
import csv
import importlib
import logging
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pylabrobot.resources import Carrier, ItemizedResource, Lid, TipRack  # noqa: E402

from venus_interop.plr import generate, name_match, to_venus  # noqa: E402
from venus_interop.files.definitions import DEFAULT_VENUS_LABWARE, DefinitionStore, normalize  # noqa: E402

TOL = {"footprint": 1.0, "positions": 1e-3, "item": 0.01, "depth": 0.01, "floor": 0.01, "volume": 0.01}


def build(spec):
  mod = type(importlib)("g")
  exec(compile(generate.HEADER + generate.emit(spec), "<generated>", "exec"), mod.__dict__)  # noqa: S102
  return getattr(mod, spec.name)("x")


def first_item(r):
  it = r.get_item(0)  # A1
  if not hasattr(it, "max_volume") and it.children:  # tube in a holder
    return it.children[0], it.location.z + it.children[0].location.z
  return it, it.location.z


def compare(a, b) -> dict:
  """Differences between two PLR resources describing the same labware (b came back from Venus)."""
  d = {}
  d["footprint"] = max(abs(a.get_size_x() - b.get_size_x()), abs(a.get_size_y() - b.get_size_y()))
  d["height"] = abs(a.get_size_z() - b.get_size_z())
  fa, fb = name_match.fingerprint(a), name_match.fingerprint(b)
  if isinstance(a, Carrier):  # where a child lands: holder location + its child offset
    def landing(c):  # the Venus site: where a rack's corner goes (to_venus.site_corner)
      return sorted((round(p.x, 3), round(p.y, 3)) for p in (to_venus.site_corner(h) for h in c.sites.values()))
    la, lb = landing(a), landing(b)
    d["positions"] = name_match._rms(la, lb) if len(la) == len(lb) else float("inf")
  else:
    d["positions"] = name_match._rms(fa.positions, fb.positions) if fa.count == fb.count else float("inf")
  if isinstance(a, ItemizedResource) and not isinstance(a, TipRack):
    (ia, za), (ib, zb) = first_item(a), first_item(b)
    d["item"] = max(abs(ia.get_size_x() - ib.get_size_x()), abs(ia.get_size_y() - ib.get_size_y()))
    d["depth"] = abs(ia.get_size_z() - ib.get_size_z())
    d["floor"] = abs(za - zb)
    try:
      hs = [ia.get_size_z() * k / 4 for k in range(1, 5)]
      va = [ia.compute_volume_from_height(h) for h in hs]
      vb = [ib.compute_volume_from_height(h) for h in hs]
      d["volume"] = max(abs(x - y) / max(abs(x), 1e-9) for x, y in zip(va, vb))
    except Exception:  # noqa: BLE001 - no volume model on one side
      d["volume"] = None
  if isinstance(a, TipRack):
    d["tip"] = 0.0 if (fa.tip and fb.tip and fa.tip[1] == fb.tip[1]
                       and abs(fa.tip[2] - fb.tip[2]) < 0.01) else float("inf")
  return d


def plr_roundtrip(catalogue):
  results = {}
  with tempfile.TemporaryDirectory() as tmp:
    lab = pathlib.Path(tmp) / "Labware"
    for c in catalogue:
      fn = c.factory.rsplit(".", 1)[-1]
      mod = importlib.import_module(c.factory.rsplit(".", 1)[0])
      a = getattr(mod, fn)("x")
      try:
        files = to_venus.venus_files(a, name=fn)
        to_venus.write(files, lab)
        store = DefinitionStore([lab])
        d = store.get(files.main)
        b = build(generate.spec_for(d, store, fn))
        results[fn] = (type(a).__name__, compare(a, b), files.notes)
      except Exception as e:  # noqa: BLE001
        results[fn] = (type(a).__name__, {"error": f"{type(e).__name__}: {e}"}, [])
  return results


def venus_roundtrip(corpus):
  index = {}
  with open(pathlib.Path(corpus) / "defs_index.tsv", encoding="utf-8") as f:
    for name, rel, src in csv.reader(f, delimiter="\t"):
      if (pathlib.Path(corpus) / "defs_raw" / name).exists():
        index[rel] = pathlib.Path(corpus) / "defs_raw" / name
  store = DefinitionStore([DEFAULT_VENUS_LABWARE], index)
  results = {}
  with tempfile.TemporaryDirectory() as tmp:
    lab = pathlib.Path(tmp) / "Labware"
    for rel in sorted(index):
      if not rel.endswith((".rck", ".tml", ".lid")):
        continue
      d = store.get(rel)
      if d is None:
        continue
      name = generate.factory_name(rel)
      try:
        a = build(generate.spec_for(d, store, name))
        files = to_venus.venus_files(a, name=name)
        to_venus.write(files, lab)
        back = DefinitionStore([lab])
        b = build(generate.spec_for(back.get(files.main), back, name))
        results[rel] = (type(a).__name__, compare(a, b), files.notes)
      except Exception as e:  # noqa: BLE001
        results[rel] = (type(d).__name__, {"error": f"{type(e).__name__}: {e}"}, [])
  return results


def report(results):
  by_class = collections.defaultdict(collections.Counter)
  worst = collections.defaultdict(list)
  for name, (cls, d, _) in results.items():
    if "error" in d:
      by_class[cls]["error"] += 1
      worst["error"].append((name, d["error"][:90]))
      continue
    bad = [k for k, v in d.items() if v is not None and k in TOL and v > TOL[k]] + \
          [k for k in ("tip",) if d.get(k) not in (None, 0.0)]
    by_class[cls]["ok" if not bad else "differs: " + ",".join(bad)] += 1
    for k in bad:
      worst[k].append((name, round(d[k], 4) if d[k] != float("inf") else "count/kind"))
  for cls, c in sorted(by_class.items()):
    print(f"{cls:22} {dict(c)}")
  for k, v in worst.items():
    print(f"  {k}: {len(v)} e.g. {sorted(v, key=lambda x: str(x[1]))[-4:]}")


if __name__ == "__main__":
  ap = argparse.ArgumentParser()
  ap.add_argument("direction", choices=["plr", "venus"])
  ap.add_argument("--corpus")
  a = ap.parse_args()
  logging.disable(logging.WARNING)
  if a.direction == "plr":
    cat = [c for c in name_match.plr_catalogue() if "Deprecated alias" not in c.doc]
    report(plr_roundtrip(cat))
  else:
    report(venus_roundtrip(a.corpus))
