"""PyLabRobot deck -> Venus layout (SPEC.md 2.5).

Resources imported from a layout carry their raw Venus fields in `metadata["venus"]`. Those fields
are written back verbatim, except that position fields are recomputed when the resource has moved
in PLR. Resources without Venus metadata are not supported yet (SPEC.md step 4).
"""
from __future__ import annotations

from typing import Optional

from pylabrobot.resources import Deck, Resource

from venus_interop.files import hxcfg
from venus_interop.files.definitions import DefinitionStore
from venus_interop.files.layout import Layer, Layout, Placement, Sequence, fmt
from venus_interop.plr.plr_import import VENUS, venus_corner

TOL = 2e-4  # pylabrobot rounds coordinates to 4 decimals; Venus stores float32 noise


class UnmappedResources(ValueError):
  pass


def _section(d: dict) -> hxcfg.Section:
  entries = [tuple(e) for e in d["entries"]] if d.get("entries") is not None else None
  return hxcfg.Section(d["type"], d["version"], d["name"], entries=entries, items=d.get("items"))


def _cfg(meta: dict) -> hxcfg.CfgFile:
  f = meta["file"]
  sections = []
  for s in f["sections"]:
    if s.get("placeholder"):
      # rebuilt by Layout.to_cfg; an empty cover section is dropped there
      sections.append(hxcfg.Section("DECKLAY", s["version"], s["name"], entries=[]))
    else:
      sections.append(_section(s))
  return hxcfg.CfgFile(f["version"], f["valid"], sections, hxcfg.Footer(**f["footer"]), f["binary"])


def _update_position(p: Placement, r: Resource, store: DefinitionStore) -> None:
  """Rewrite TForm.3/ZTrans only when the PLR location differs from what the fields say."""
  have = venus_corner(p, store)
  loc = r.get_absolute_location()
  now = (loc.x, loc.y, loc.z)
  if all(abs(a - b) <= TOL for a, b in zip(have, now)):
    return
  dx, dy = now[0] - have[0], now[1] - have[1]
  x, y, _ = p.tform
  p.set_tform(x + dx, y + dy)
  p.z = now[2]


def plr_to_lay(deck: Deck, store: DefinitionStore, allow_unmapped: bool = False) -> Layout:
  meta = deck.metadata.get(VENUS)
  if meta is None:
    raise UnmappedResources("deck has no Venus metadata: use deck_export.export")

  resources = {r.name: r for r in deck.get_all_resources()}
  unmapped = [
    r.name for r in deck.children
    if VENUS not in r.metadata and not r.name.startswith(deck.name + "_")
  ]
  if unmapped and not allow_unmapped:
    raise UnmappedResources(f"resources without Venus metadata (use deck_export.export): {unmapped}")

  lids = {r.metadata[VENUS]["lid_of"]: r for r in resources.values()
          if "lid_of" in r.metadata.get(VENUS, {})}
  labware = []
  for lid in meta["order"]:
    r = resources.get(lid)
    if r is None:
      continue  # removed in PLR
    p = Placement(dict(r.metadata[VENUS]["fields"]))
    _update_position(p, r, store)
    lid_r: Optional[Resource] = lids.get(lid)
    if lid_r is not None:
      p.lid = Placement(dict(lid_r.metadata[VENUS]["fields"]))
      loc = lid_r.get_absolute_location()
      lx, ly, _ = p.lid.tform
      if abs(lx - loc.x) > TOL or abs(ly - loc.y) > TOL or abs(p.lid.z - loc.z) > TOL:
        p.lid.set_tform(loc.x, loc.y)
        p.lid.z = loc.z
    labware.append(p)

  sequences = [Sequence(s["name"], [tuple(i) for i in s["items"]], s["read_only"], s["extra"])
               for s in meta["sequences"]]
  layers = None if meta["layers"] is None else [
    Layer(x["fields"], x["labware"], x["sequences"]) for x in meta["layers"]]
  return Layout(_cfg(meta), meta["instrument"], dict(meta["header"]), labware, sequences, layers)
