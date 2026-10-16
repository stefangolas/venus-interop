"""The capture log: what a Venus layout says beyond "this labware on this carrier site".

A placement whose fields all follow from the rules (CONVENTIONS.md sections 3-4) is a pure assignment,
the same information as pylabrobot's `carrier[i] = plate`. Everything else is information the layout
carries: a nudge off the site, a height that differs from the site or stack (often taught), an
alternative at the same place as another rack, labware off any carrier, rotation, an edited default
sequence, a hand-set lid height. `capture(layout, store)` lists each one with its size.
"""
from __future__ import annotations

import collections
import dataclasses
from typing import Optional

from venus_interop.rules import placement as rules
from venus_interop.files.layout import Layout

TOL = 0.01  # mm
CLSID = {"carrier": "{77DF9B91-671E-4974-8380-38AD0B4E0D86}", "rack": "{8E1D6C02-F939-11D1-8D14-008029ED67EA}"}


@dataclasses.dataclass
class Item:
  labware: str
  field: str  # x/y, z, alternative, position, rotation, sequence, lid z, clsid, definition
  text: str
  size: Optional[float] = None  # mm, for x/y and z
  z_mode: Optional[int] = None  # the layout's ZTransValue: 2 = height set by hand
  rack: Optional[str] = None  # the labware's definition
  carrier: Optional[str] = None  # its carrier's definition and site id
  offset: Optional[tuple] = None  # (dx, dy) or (dz,) from where the rules put it, mm
  layout: Optional[str] = None  # which layout (set by tools that read several)

  def as_dict(self) -> dict:
    return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}


def expected_heights(layout: Layout, store, by_id) -> dict[str, Optional[float]]:
  """The rule height of each rack on a site: site Z for the bottom rack, stack height above it,
  None for an alternative at the same height as another rack."""
  out: dict[str, Optional[float]] = {}
  groups = collections.defaultdict(list)
  for p in layout.labware:
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
        out[p.id] = None  # an alternative at the same height
        continue
      if prev is None:
        out[p.id] = z
      else:
        # above another rack: stacked on it, or an alternative at the site's own height (e.g. a
        # different tip rack for the same site); measure from whichever explains it better
        stacked = prev[0].z + prev[1].stack_height
        out[p.id] = min((stacked, z), key=lambda h: abs(p.z - h))
      prev = (p, rack)
  return out


def capture(layout: Layout, store) -> list[Item]:
  if layout.header.get("Deck", "").lower() not in rules.STAR_DECKS:
    return []
  by_id = layout.by_id()
  heights = expected_heights(layout, store, by_id)
  out: list[Item] = []
  for p in layout.labware:
    parent_p = by_id.get(p.template) if p.template != "default" else None
    where = f"{parent_p.file} site {p.site_id}" if parent_p is not None else "deck"

    def add(f, t, size=None, offset=None, p=p, where=where):
      out.append(Item(p.id, f, t, size, p.z_mode, p.file, where, offset))
    if p.angle != 0:
      add("rotation", f"Angle {p.angle}")
    if p.kind in CLSID and p.clsid != CLSID[p.kind]:
      add("clsid", p.clsid)
    d = store.get(p.file)
    if d is None:
      add("definition", "missing: its placement cannot be checked")
      continue
    if p.kind == "carrier":
      rail = rules.parse_rail(p.site_id) if p.template == "default" else None
      if rail is None:
        add("position", "carrier off the rails")
      else:
        x, y, z = rules.rail_location(rail)
        off = max(abs(p.tform[0] - x), abs(p.tform[1] - y), abs(p.z - z))
        if off > TOL:
          add("x/y", f"{off:.2f} mm off its rail position", off)
      continue
    rack = store.rack(p.file)
    if rack is None:
      continue  # lids and other non-rack labware: their own entries below or not analysed
    corner = rules.rack_corner(p.tform[:2], rack)
    parent = by_id.get(p.template) if p.template != "default" else None
    carrier = store.carrier(parent.file) if parent is not None else None
    site = carrier.sites.get(p.site_id) if carrier else None
    if parent is None:
      rail = rules.parse_rail(p.site_id)
      if rail is None:
        add("position", "free on the deck: no carrier, no rail")
      else:
        x, y, _ = rules.rail_location(rail)
        off = max(abs(corner[0] - x), abs(corner[1] - y))
        if off > TOL:
          add("x/y", f"{off:.2f} mm off its rail position", off)
    elif site is None:
      add("position", f"on site {p.site_id!r}, which its carrier does not define")
    else:
      dx, dy = corner[0] - (parent.tform[0] + site.x), corner[1] - (parent.tform[1] + site.y)
      if max(abs(dx), abs(dy)) > TOL:
        add("x/y", f"({dx:+.2f}, {dy:+.2f}) mm off site {p.site_id}", max(abs(dx), abs(dy)),
            (round(dx, 3), round(dy, 3)))
      if p.id in heights:
        z = heights[p.id]
        if z is None:
          add("alternative", "at the same place and height as another rack")
        elif abs(p.z - z) > TOL:
          base = rack.num("Cntr.1.base")
          if base and abs((p.z - z) - base) <= 0.3:
            # 93 racks in the corpora, all ZTransValue 2: tip racks, wastes, teaching blocks
            note = (f"{p.z - z:+.2f} mm from the site: the rack's container base ({base:+g}), "
                    "as if the site height was entered as the base's height")
          else:
            note = f"{p.z - z:+.2f} mm from the site/stack height"
          add("z", note, abs(p.z - z), (round(p.z - z, 3),))
    if p.def_seq_valid:
      seq = layout.sequence(p.id)
      if seq is None:
        add("sequence", "default sequence deleted")
      elif seq.items != rules.default_sequence(p.id, rack):
        add("sequence", "default sequence edited")
    if p.lid is not None:
      out.append(Item(p.lid.id, "lid z", "lid height set by hand (no rule)", None, p.lid.z_mode))
  return out


def summary(layout: Layout, items: list[Item]) -> dict:
  carrying = {i.labware for i in items}
  ids = [p.id for p in layout.labware] + [p.lid.id for p in layout.labware if p.lid]
  by_field = collections.Counter(i.field for i in items)
  return {"labware": len(ids), "pure assignments": sum(1 for i in ids if i not in carrying),
          "carrying information": len(carrying), "by field": dict(by_field)}


def _name(path: str) -> str:
  return path.replace("\\", "/").rsplit("/", 1)[-1].lower()


def systematic(items: list[Item], min_layouts: int = 2, spread: float = 0.05) -> list[dict]:
  """Offsets grouped by (field, labware file name, carrier file name and site), counted over distinct
  layouts (Item.layout; copies of one layout count once). A group whose offsets agree within `spread`
  mm in at least `min_layouts` distinct layouts is systematic: a missing rule (a nest, a pedestal, a
  module height), not a nudge."""
  groups = collections.defaultdict(list)
  for i in items:
    if i.offset is not None:
      carrier, _, site = (i.carrier or "").partition(" site ")
      groups[(i.field, _name(i.rack or ""), f"{_name(carrier)} site {site}" if site else _name(carrier))].append(i)
  out = []
  for (field, rack, carrier), its in groups.items():
    offs = [i.offset for i in its]
    span = max(max(o[k] for o in offs) - min(o[k] for o in offs) for k in range(len(offs[0])))
    mean = tuple(round(sum(o[k] for o in offs) / len(offs), 3) for k in range(len(offs[0])))
    layouts = len({i.layout for i in its})
    out.append({"field": field, "rack": rack, "carrier": carrier, "placements": len(offs), "layouts": layouts,
                "offset": mean, "spread": round(span, 3), "systematic": layouts >= min_layouts and span <= spread})
  return sorted(out, key=lambda g: (not g["systematic"], -g["layouts"], -g["placements"]))


def by_labware(items: list[Item], placements: dict[str, int]) -> list[dict]:
  """Per labware file name: how often it sits off its site, over all placements on carrier sites.
  `placements`: file name -> number of placements on carrier sites (from the layouts)."""
  off = collections.defaultdict(lambda: {"x/y": 0, "z": 0})
  for i in items:
    if i.field in ("x/y", "z") and i.carrier and i.carrier != "deck":
      off[_name(i.rack or "")][i.field] += 1
  rows = []
  for name, n in placements.items():
    o = off.get(name, {"x/y": 0, "z": 0})
    rows.append({"labware": name, "placements": n, "x/y off": o["x/y"], "z off": o["z"],
                 "share off": round(max(o["x/y"], o["z"]) / n, 3) if n else 0.0})
  return sorted(rows, key=lambda r: (-r["share off"], -r["placements"]))
