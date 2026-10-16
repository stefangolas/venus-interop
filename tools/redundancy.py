"""How much of a Venus layout is redundant, i.e. regenerable from (labware, carrier, site) alone.

  python tools/redundancy.py --corpus DIR [--ngs DIR]

For every placement, each field is checked against what the rules (CONVENTIONS.md section 3-4) would
write for that labware on that site. A placement whose fields are all derivable is a pure assignment
("this labware on this site"); anything else carries information the rules cannot reproduce, and the
report says which field and how much.
"""
import argparse
import collections
import csv
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from venus_interop.files import layout  # noqa: E402
from venus_interop.rules import placement as rules
from venus_interop.files.definitions import DEFAULT_VENUS_LABWARE, DefinitionStore  # noqa: E402

TOL = 0.01
CLSID = {"carrier": "{77DF9B91-671E-4974-8380-38AD0B4E0D86}", "rack": "{8E1D6C02-F939-11D1-8D14-008029ED67EA}"}


def placement_info(p, lay, store, by_id, z_of_site):
  """{field: description} for each field of p that the rules do not reproduce. Empty: pure assignment."""
  info = {}
  if p.angle != 0:
    info["rotation"] = f"Angle {p.angle}"
  if p.clsid != CLSID.get(p.kind, p.clsid):
    info["clsid"] = p.clsid
  d = store.get(p.file)
  if d is None:
    return {"definition": "missing: cannot be checked"}
  if p.kind == "carrier":
    rail = rules.parse_rail(p.site_id) if p.template == "default" else None
    if rail is None:
      info["position"] = "carrier off the rails"
    else:
      x, y, z = rules.rail_location(rail)
      off = max(abs(p.tform[0] - x), abs(p.tform[1] - y), abs(p.z - z))
      if off > TOL:
        info["position"] = f"{off:.2f} mm off its rail position"
    return info
  rack = store.rack(p.file)
  if rack is None:
    return {"definition": f"{d.type}, not a rack: not analysed"}
  corner = rules.rack_corner(p.tform[:2], rack)
  parent = by_id.get(p.template) if p.template != "default" else None
  carrier = store.carrier(parent.file) if parent is not None else None
  site = carrier.sites.get(p.site_id) if carrier else None
  if parent is None:
    rail = rules.parse_rail(p.site_id)
    if rail is None:
      info["position"] = "free on the deck (no carrier, no rail)"
    else:
      x, y, z = rules.rail_location(rail)
      off = max(abs(corner[0] - x), abs(corner[1] - y))
      if off > TOL:
        info["x/y"] = f"{off:.2f} mm off its rail position"
  elif site is None:
    info["position"] = "on a site its carrier does not define"
  else:
    sx, sy = parent.tform[0] + site.x, parent.tform[1] + site.y
    off = max(abs(corner[0] - sx), abs(corner[1] - sy))
    if off > TOL:
      info["x/y"] = f"{off:.2f} mm off its site"
    expected_z = z_of_site.get(p.id)
    if expected_z is None:
      info["z"] = "no derivable height (alternative at the same height as another rack)"
    elif abs(p.z - expected_z) > TOL:
      info["z"] = f"{p.z - expected_z:+.2f} mm from the site/stack height"
  if p.def_seq_valid:
    seq = lay.sequence(p.id)
    if seq is None or seq.items != rules.default_sequence(p.id, rack):
      info["sequence"] = "edited or deleted default sequence"
  if p.lid is not None:
    info["lid z"] = "lid heights are set by hand (no rule)"
  return info


def expected_heights(lay, store, by_id):
  """Site height for the bottom rack of each site, stack height for the ones above (rules.stack_z)."""
  out = {}
  groups = collections.defaultdict(list)
  for p in lay.labware:
    rack = store.rack(p.file)
    if rack is not None and p.template != "default":
      groups[(p.template, p.site_id)].append((p, rack))
  for (tpl, sid), members in groups.items():
    parent = by_id.get(tpl)
    carrier = store.carrier(parent.file) if parent is not None else None
    site = carrier.sites.get(sid) if carrier else None
    if site is None:
      continue
    z = parent.z + site.z
    members.sort(key=lambda pr: pr[0].z)
    prev = None
    for p, rack in members:
      if prev is not None and abs(p.z - prev[0].z) <= TOL:
        out[p.id] = None if p.id not in out else out[p.id]  # an alternative at the same height
        continue
      out[p.id] = z if prev is None else prev[0].z + prev[1].stack_height
      prev = (p, rack)
  return out


def analyse(paths_and_stores):
  totals = collections.Counter()
  fields = collections.Counter()
  examples = collections.defaultdict(list)
  per_deck = []
  for path, store in paths_and_stores:
    lay = layout.read_layout(path)
    if lay.header.get("Deck", "").lower() not in rules.STAR_DECKS:
      continue
    by_id = lay.by_id()
    heights = expected_heights(lay, store, by_id)
    pure = n = 0
    for p in lay.labware:
      info = placement_info(p, lay, store, by_id, heights)
      kind = p.kind if p.kind in ("carrier", "rack") else "other"
      n += 1
      if not info:
        pure += 1
        totals[(kind, "pure assignment")] += 1
      else:
        totals[(kind, "carries information")] += 1
        for f, why in info.items():
          fields[(kind, f)] += 1
          if len(examples[(kind, f)]) < 3:
            examples[(kind, f)].append(f"{pathlib.Path(path).name}:{p.id}: {why}")
    per_deck.append((pathlib.Path(path).name, pure, n))
  return totals, fields, examples, per_deck


def report(title, result):
  totals, fields, examples, per_deck = result
  print(f"\n=== {title}")
  for k, v in sorted(totals.items()):
    print(f"  {k[0]:8} {k[1]:20} {v}")
  print("  information carried, by field:")
  for (kind, f), v in fields.most_common():
    print(f"    {kind:8} {f:10} {v:5}   e.g. {examples[(kind, f)][0]}")
  return per_deck


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--corpus")
  ap.add_argument("--ngs")
  a = ap.parse_args()
  if a.corpus:
    index = {}
    with open(pathlib.Path(a.corpus) / "defs_index.tsv", encoding="utf-8") as f:
      for name, rel, src in csv.reader(f, delimiter="\t"):
        if (pathlib.Path(a.corpus) / "defs_raw" / name).exists():
          index[rel] = pathlib.Path(a.corpus) / "defs_raw" / name
    store = DefinitionStore([DEFAULT_VENUS_LABWARE], index)
    report("corpus", analyse([(p, store) for p in sorted((pathlib.Path(a.corpus) / "raw").glob("*.lay"))]))
  if a.ngs:
    ngs = pathlib.Path(a.ngs)
    roots = [pathlib.Path(dp, d) for base in (ngs, pathlib.Path(r"C:\Program Files (x86)\HAMILTON\NGSStar"))
             for dp, ds, _ in os.walk(base) for d in ds if d.lower() == "labware"]

    def toks(p):
      return {t for t in re.split(r"[^a-z0-9]+", str(p).lower()) if len(t) > 2} - {
        "labware", "users", "stefa", "protocols", "assets", "program", "files", "hamilton", "ngsstar", "ngsstarmoa",
        "lay", "deck"}

    items = []
    for lp in sorted(ngs.rglob("*.lay")):
      kit = sorted(roots, key=lambda r: -len(toks(r) & toks(lp)))
      items.append((lp, DefinitionStore([kit[0], DEFAULT_VENUS_LABWARE] + kit[1:], by_name=True)))
    for name, pure, n in report("NGS", analyse(items)):
      print(f"    {name:60} {pure:3}/{n} pure assignments")


if __name__ == "__main__":
  main()
