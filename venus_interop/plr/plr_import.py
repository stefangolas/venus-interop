"""Venus layout -> PyLabRobot deck (SPEC.md 2.5).

Geometry comes from the labware definitions, so the deck is usable on its own. Everything PLR has no
place for (raw Venus fields, sequences, layers, other file sections) goes into `metadata["venus"]`,
which lets `plr_export.plr_to_lay` reproduce the original file byte for byte.
"""
from __future__ import annotations

import dataclasses
import math
import re
import warnings
from typing import Optional

from pylabrobot.resources import Carrier, Coordinate, Lid, Plate, Resource, ResourceHolder, Rotation, TipRack, TipSpot, Well
from pylabrobot.resources.hamilton import HamiltonSTARDeck
from pylabrobot.resources.hamilton import tip_creators
from pylabrobot.resources.utils import create_ordered_items_2d
from pylabrobot.resources.well import CrossSectionType

from venus_interop.plr import generate
from venus_interop.rules import placement as rules
from venus_interop.files.definitions import Carrier as CarrierDef
from venus_interop.files.definitions import DefinitionStore, Rack, normalize
from venus_interop.files.layout import Layout, Placement

VENUS = "venus"

# Deck file -> HamiltonSTARDeck arguments (sizes as in pylabrobot's STARDeck / STARLetDeck).
DECKS = {
  "ml_star2.dck": dict(num_tracks=54, size_x=1545.0, size_y=653.5, size_z=334.7),
  "ml_flexstar.dck": dict(num_tracks=54, size_x=1545.0, size_y=653.5, size_z=334.7),
  "ml_starlet.dck": dict(num_tracks=30, size_x=1005.0, size_y=653.5, size_z=334.7),
}


class UnsupportedLayout(ValueError):
  pass


# ---------------------------------------------------------------------------------------- metadata


def section_to_json(s) -> dict:
  return {"type": s.type, "version": s.version, "name": s.name, "entries": s.entries, "items": s.items}


def layout_metadata(layout: Layout) -> dict:
  """Everything at file level that PLR does not model."""
  cfg = layout.cfg
  return {
    "instrument": layout.instrument,
    "header": layout.header,
    "order": [p.id for p in layout.labware],
    "sequences": [dataclasses.asdict(s) for s in layout.sequences],
    "layers": None if layout.layers is None else [dataclasses.asdict(x) for x in layout.layers],
    "file": {
      "version": cfg.version,
      "valid": cfg.valid,
      "binary": cfg.binary,
      "footer": dataclasses.asdict(cfg.footer),
      # DECKLAY sections are rebuilt from the deck; the rest pass through unchanged.
      "sections": [
        section_to_json(s) if not (s.type == "DECKLAY" and s.name in (layout.instrument, layout.instrument + "_COVER"))
        else {"type": "DECKLAY", "name": s.name, "placeholder": True, "version": s.version}
        for s in cfg.sections
      ],
    },
  }


# ---------------------------------------------------------------------------------------- geometry


def z_above_bottom(z_mode: int, rack: Optional[Rack], store: DefinitionStore) -> float:
  """How far above the rack's bottom a placement's stored ZTrans is, by its ZTransValue, as Venus
  reports positions (docs/FIRMWARE_EQUIVALENCE.md section 2.4): 1 = the rack's bottom, 0 = the
  container base (Cntr.1.base), 2 = the container floor (the base + the .ctr's BaseMM)."""
  if rack is None or z_mode == 1:
    return 0.0
  base = rack.num("Cntr.1.base")
  if z_mode == 0:
    return base
  ctr = store.ref(rack, "Cntr.1.file")
  return base + (ctr.num("BaseMM") if ctr is not None else 0.0)


def turn(p: Placement) -> tuple[float, float]:
  """(cos, sin) of a placement's rotation about Z, from TForm.1 (where the labware's X axis
  points). Venus's Angle 90 is (0, -1): a quarter turn clockwise seen from above."""
  if "TForm.1.X" not in p.fields:
    return 1.0, 0.0
  return p._num("TForm.1.X"), p._num("TForm.1.Y")


def rotation_z(p: Placement) -> float:
  """The placement's rotation as PLR's Rotation.z, in degrees (counter-clockwise): -Angle."""
  c, s = turn(p)
  return round(math.degrees(math.atan2(s, c)), 6) % 360


def venus_lid_z(lid: Placement, lid_def, plate_bottom: float) -> float:
  """Where Venus puts a plate's lid (its bottom, deck Z). With ZTransValue 0 it ignores the stored
  ZTrans: the lid stands RackBaseToCoverBase above the plate's bottom (Marionette's lid grips, three
  lids, exact; docs/FIRMWARE_EQUIVALENCE.md section 2.12). Otherwise, unmeasured, the stored ZTrans."""
  if lid.fields.get("ZTransValue") == "0" and lid_def is not None and "RackBaseToCoverBase" in lid_def.fields:
    return round(plate_bottom + lid_def.rack_base_to_cover_base, 4)
  return lid.z


def venus_corner(p: Placement, store: DefinitionStore) -> tuple[float, float, float]:
  """The placement's origin in deck coordinates, as Venus places it: the front-left-bottom corner,
  or for rotated labware the point that corner turns to. Venus turns a rack about its position 1
  (TForm.3): every rotated labware in the sweep, exact (docs/FIRMWARE_EQUIVALENCE.md section 2.4)."""
  x, y, _ = p.tform
  rack = store.rack(p.file)
  if rack is not None:
    dx, dy = rules.a1_offset(rack)
    c, s = turn(p)
    x, y = x - (c * dx - s * dy), y - (s * dx + c * dy)
  elif p.kind == "lid" and p.z_mode == 0:
    # a lid placed as labware (a lid park): with ZTransValue 0 the stored Z is the cover's underside,
    # its CoverThickness below the top, so the lid's bottom is its height less that thickness lower
    # (Marionette's lid parks: 6.65 mm, 9.15 - 2.5, two parks exact; ZTransValue 1 is the bottom)
    lid = store.lid(p.file)
    if lid is not None and "CoverThickness" in lid.fields:
      return x, y, round(p.z - (lid.dim[2] - lid.num("CoverThickness")), 4)
  return x, y, p.z - z_above_bottom(p.z_mode, rack, store)


def _tip_creator(rack: Rack, store: Optional[DefinitionStore] = None):
  """The tip a rack holds, as (creator, how it was decided).

  1. the Hamilton tip type in the rack (MlStarTipRack / MlStarXLTipRack) -> pylabrobot's creator;
  2. tips described by our own files (PlrTip* properties) -> a tip with those numbers;
  3. only then a guess from the file name (recorded in the ledger)."""
  from pylabrobot.resources import Tip

  from venus_interop.plr.generate import BROKEN_TIP_CREATORS, TIP_CREATORS

  props = rack.properties
  code = props.get("MlStarTipRack") or props.get("MlStarXLTipRack")
  name = TIP_CREATORS.get(int(code)) if code not in (None, "") else None
  if name and name not in BROKEN_TIP_CREATORS:
    return getattr(tip_creators, name), f"Hamilton tip type {code}"
  if "PlrTipFilter" in props or (name in BROKEN_TIP_CREATORS and store is not None):
    ctr = store.ref(rack, "Cntr.1.file") if store is not None else None
    length = ctr.num("Depth") if ctr is not None else 0.0
    diameter = ctr.num("Dim.Dx") if ctr is not None else 7.0
    has_filter = props.get("PlrTipFilter") == "1" or "filter" in props.get("managedSequenceName", "").lower()
    fitting = float(props.get("PlrTipFittingDepth", 8.0))
    volume = float(props.get("PlrTipMaxVolume", 0.0) or 0.0)

    def make_tip(n: str) -> Tip:
      return Tip(n, diameter=diameter, size_z=length, has_filter=has_filter, maximal_volume=volume,
                 fitting_depth=fitting, model=f"{rack.path}_tip")

    why = "from the rack's PlrTip properties" if "PlrTipFilter" in props else       f"pylabrobot's {name} cannot build a tip; from the .ctr"
    return make_tip, why
  low = rack.path.lower()
  filt = "f" in low.rsplit("/", 1)[-1].split("_")[0] or "filter" in low
  if "50" in low:
    guess = tip_creators.hamilton_tip_50uL_filter if filt else tip_creators.hamilton_tip_50uL
  elif "10ul" in low:
    guess = tip_creators.hamilton_tip_10uL_filter if filt else tip_creators.hamilton_tip_10uL
  elif "ht" in low or "1000" in low or "5ml" in low:
    guess = tip_creators.hamilton_tip_1000uL_filter if filt else tip_creators.hamilton_tip_1000uL
  else:
    guess = tip_creators.hamilton_tip_300uL_filter if filt else tip_creators.hamilton_tip_300uL
  return guess, "guessed from the file name (no tip type in the rack)"


def _container_size(rack: Rack, store: DefinitionStore) -> tuple[float, float, float]:
  """Well footprint and depth, from the rack's container (.ctr) when it can be found."""
  ctr = store.ref(rack, "Cntr.1.file")
  if ctr is not None and ctr.num("Dim.Dx"):
    return ctr.num("Dim.Dx"), ctr.num("Dim.Dy") or ctr.num("Dim.Dx"), ctr.num("Depth") or ctr.num("Dim.Dz")
  pitch = min(v for v in (rack.dx, rack.dy, 9.0) if v > 0)
  return pitch, pitch, rack.dim[2]


def _volume_functions(geometry) -> dict:
  """A well's volume-of-height and height-of-volume from its .ctr segments (each segment's
  EqnOfVol over the depth within it), as PLR's well functions.

  PLR serializes a function as its code and closure and rebuilds it with other globals, so these
  use only built-ins and keep plain data in their closures: (floor, top, equation) per segment. The
  height inverts the volume by bisection; a volume past the brim reads as the brim."""
  segs = tuple((s.z0, s.z1, s.eqn) for s in geometry.segments)
  depth = float(geometry.depth)

  def volume_from_height(h):
    total = 0.0
    for z0, z1, eqn in segs:
      total += eval(eqn, {"__builtins__": {}}, {"h": min(max(h - z0, 0.0), z1 - z0)})  # noqa: S307
    return total

  def height_from_volume(v):
    lo, hi = 0.0, depth
    for _ in range(60):
      mid = (lo + hi) / 2
      filled = 0.0
      for z0, z1, eqn in segs:
        filled += eval(eqn, {"__builtins__": {}}, {"h": min(max(mid - z0, 0.0), z1 - z0)})  # noqa: S307
      if filled < v:
        lo = mid
      else:
        hi = mid
    return (lo + hi) / 2

  return dict(compute_volume_from_height=volume_from_height, compute_height_from_volume=height_from_volume)


def build_rack(name: str, rack: Rack, store: DefinitionStore) -> Resource:
  sx, sy, sz = rack.dim
  rows, cols = rack.rows, rack.columns
  listed = not (rows and cols) and not rack.is_tip_rack and rack.positions
  if not listed and (not rows or not cols or rack.fields.get("Stagger", "0") not in ("0", "")):
    return Resource(name, sx, sy, sz, category="venus_rack")
  wx, wy, depth = _container_size(rack, store)
  bx, by = rack.boundary
  # a negative base (filter and binding plates, the 96-head wastes) puts the containers below the
  # rack's bottom, as Venus reports them (docs/FIRMWARE_EQUIVALENCE.md section 2.4)
  dz = rack.num("Cntr.1.base")
  if rack.is_tip_rack:
    creator, how = _tip_creator(rack, store)
    probe = creator("probe")
    # where the pick-up ends, which is what PLR's tip spot is (the driver's end of pick-up): Venus
    # ends it at the container base + the .ctr's MaxDepth (its start is the base + Depth), as its
    # firmware shows (docs/FIRMWARE_EQUIVALENCE.md section 2.7); a tip length minus the fitting
    # depth over the base where the .ctr gives no MaxDepth
    tip_ctr = store.ref(rack, "Cntr.1.file")
    seat = tip_ctr.num("MaxDepth") if tip_ctr is not None else 0.0
    seat = seat or probe.get_size_z() - probe.fitting_depth
    items = create_ordered_items_2d(TipSpot, make_tip=creator, **_grid(name, rack, wx, wy,
                                    rack.num("Cntr.1.base") + seat))
    tr = TipRack(name, sx, sy, sz, ordered_items=items)
    tr.metadata[VENUS] = {"tip": how}
    return tr
  # the cross-section of the container's top segment, as generate.py reads it; a well with unequal
  # sides is rectangular whatever the segments say
  ctr = store.ref(rack, "Cntr.1.file")
  geometry = generate.container(ctr) if ctr is not None else None
  box = geometry is not None and geometry.is_box
  shape = CrossSectionType.CIRCLE if abs(wx - wy) < 1e-9 and not box else CrossSectionType.RECTANGLE
  # volume and height from the container's own segments (their EqnOfVol), so a liquid surface found
  # or set converts as Venus converts it (PLR's cLLD needs them); none when the .ctr has no segments
  volume_fns = {}
  if geometry is not None and geometry.segments and all(generate._EQN.match(s.eqn) for s in geometry.segments):
    volume_fns = _volume_functions(geometry)
  # the well stands on Venus's container base; the .ctr's BaseMM is material under the cavity floor,
  # which Venus's minimum height and eject heights stand on (docs/FIRMWARE_EQUIVALENCE.md section 2.4)
  base_mm = ctr.num("BaseMM") if ctr is not None else 0.0
  well = dict(size_z=depth, cross_section_type=shape, material_z_thickness=base_mm, **volume_fns)
  if listed:
    # positions listed one by one, in Venus's order: named by column (X) and row (Y, back first)
    xs = sorted({x for x, _ in rack.positions})
    ys = sorted({y for _, y in rack.positions}, reverse=True)
    items = {}
    for x, y in rack.positions:
      key = f"{chr(ord('A') + ys.index(y))}{xs.index(x) + 1}"
      items[key] = Well(f"{name}_well_{key}", size_x=wx, size_y=wy, **well)
      items[key].location = Coordinate(round(bx + x - wx / 2, 4), round(by + y - wy / 2, 4), dz)
    return _with_heights(Plate(name, sx, sy, sz, ordered_items=items), ctr, rack)
  if rack.fields.get("IX.Start", "0") == "1":
    # position 1 at the front-left and rows counting back (rules.placement.a1_offset): the wells
    # take Venus's names, in Venus's order (a portrait plate named as the landscape plate it is
    # turned into)
    items = {}
    for key, r, c in rules.default_grid(rack):
      items[key] = Well(f"{name}_well_{key}", size_x=wx, size_y=wy, **well)
      items[key].location = Coordinate(round(bx + (c - 1) * rack.dx - wx / 2, 4),
                                       round(by + (r - 1) * rack.dy - wy / 2, 4), dz)
    return _with_heights(Plate(name, sx, sy, sz, ordered_items=items), ctr, rack)
  items = create_ordered_items_2d(Well, **well, **_grid(name, rack, wx, wy, dz))
  return _with_heights(Plate(name, sx, sy, sz, ordered_items=items), ctr, rack)


_AREA = re.compile(r"^\s*h\s*\*\s*([0-9.]+)\s*$")


def _with_heights(plate: Plate, ctr, rack: Optional[Rack] = None) -> Plate:
  """The container's MaxDepth and LSHt on each well (metadata["venus"]): the heights Venus measures
  its minimum height and LLD search start from, over the floor (docs/FIRMWARE_EQUIVALENCE.md
  section 2.4). PLR has no field for them; `steps` uses them when PLR_VENUS_FAITHFUL_CFG is set.
  Also what Venus's liquid following divides by: the cross-section of a one-segment container
  (its EqnOfVol, h * area), and whether the rack's positions share one cavity (ConnectedCtr)."""
  if ctr is not None:
    m = _AREA.match(ctr.fields.get("1.EqnOfVol", "")) if ctr.int("Segments") == 1 else None
    for w in plate.get_all_items():
      w.metadata[VENUS] = {"max_depth": ctr.num("MaxDepth"), "lld_search_height": ctr.num("LSHt"),
                           "segments": ctr.int("Segments"), "area": float(m.group(1)) if m else None,
                           "connected": rack is not None and rack.fields.get("ConnectedCtr") == "1"}
  return plate


def _grid(name: str, rack: Rack, wx: float, wy: float, dz: float) -> dict:
  """`create_ordered_items_2d`'s grid for a Rows x Columns rack."""
  bx, by = rack.boundary
  cols, rows = rack.columns, rack.rows
  return dict(num_items_x=cols, num_items_y=rows, dx=bx - wx / 2, dy=by - wy / 2, dz=dz,
              item_dx=rack.dx if cols > 1 else None, item_dy=rack.dy if rows > 1 else None,
              name_prefix=name, size_x=wx, size_y=wy)


def build_carrier(name: str, carrier: CarrierDef) -> Carrier:
  sites = {}
  for i, site in enumerate(sorted(carrier.sites.values(), key=lambda s: (s.y, s.x))):  # PLR: index 0 at the front
    holder = ResourceHolder(f"{name}_site_{site.id}", site.dx, site.dy, 0, metadata={VENUS: {"site_id": site.id}})
    holder.location = Coordinate(site.x, site.y, site.z)
    sites[i] = holder
  sx, sy, sz = carrier.dim
  return Carrier(name, sx, sy, sz, sites=sites)


def build_resource(p: Placement, store: DefinitionStore) -> Resource:
  d = store.get(p.file)
  if isinstance(d, Rack):
    r = build_rack(p.id, d, store)
  elif isinstance(d, CarrierDef):
    r = build_carrier(p.id, d)
  else:
    sx, sy, sz = d.dim if d is not None else (0.0, 0.0, 0.0)
    r = Resource(p.id, sx, sy, sz, category=f"venus_{p.kind}")
  r.metadata[VENUS] = {**r.metadata.get(VENUS, {}), "fields": dict(p.fields), "definition_found": d is not None}
  return r


# ---------------------------------------------------------------------------------------- import


def _overlapping(deck: Resource, r: Resource, loc: Coordinate) -> Resource:
  def overlap(a0, a1, b0, b1):
    return a0 < b1 and b0 < a1
  for o in deck.children:
    ol = o.location
    if (overlap(loc.x, loc.x + r.get_size_x(), ol.x, ol.x + o.get_size_x())
        and overlap(loc.y, loc.y + r.get_size_y(), ol.y, ol.y + o.get_size_y())) or ol == loc:
      return o
  raise ValueError(f"{r.name}: deck refused it but nothing overlaps")


def _extra_site(carrier: Carrier, site_id: str, corner) -> ResourceHolder:
  """A site the layout uses but the carrier definition lacks (or the definition is missing)."""
  name = f"{carrier.name}_site_{site_id}"
  existing = _site_holder(carrier, site_id)
  if existing is not None:
    return existing
  holder = ResourceHolder(name, 0, 0, 0, metadata={VENUS: {"site_id": site_id, "extra": True}})
  o = carrier.get_absolute_location()
  carrier.assign_child_resource(holder, location=Coordinate(corner[0] - o.x, corner[1] - o.y, corner[2] - o.z),
                                spot=max(carrier.sites, default=-1) + 1)
  return holder


def _attach(deck: Resource, parent: Resource, r: Resource, corner: tuple[float, float, float]) -> None:
  """Put `r` with its corner at `corner` (deck coordinates) under `parent`, or somewhere pylabrobot
  accepts it again when the deck is loaded from JSON. Export only uses absolute positions."""
  def climb(p: Resource) -> Resource:
    while isinstance(p, Lid):  # lids take no children
      p = p.parent
    return p

  parent = climb(parent)
  x, y, z = corner
  if parent is deck:
    try:
      deck.assign_child_resource(r, location=Coordinate(x, y, z))
      return
    except ValueError:
      # Venus allows overlapping labware (e.g. alternative wastes at one spot); PLR refuses it
      # when loading a deck, so nest it under what it overlaps.
      parent = _overlapping(deck, r, Coordinate(x, y, z))
      r.metadata.setdefault(VENUS, {})["nested_under"] = parent.name
      if climb(parent) is not parent:
        raise UnsupportedLayout(f"{r.name} overlaps {parent.name}, which pylabrobot will not nest it under")
  if isinstance(parent, Carrier):  # carriers only take sites
    parent = _extra_site(parent, r.name, corner)
  o = parent.get_absolute_location()
  # under a rotated parent (labware nested under a turned plate): its location in the parent's
  # frame, its rotation relative to the parent's, so it ends up where and how Venus has it
  turned = parent.get_absolute_rotation().z % 360
  if turned:
    c, s = math.cos(math.radians(turned)), math.sin(math.radians(turned))
    ddx, ddy = x - o.x, y - o.y
    r.rotation = Rotation(z=(r.rotation.z - turned) % 360)
    Resource.assign_child_resource(parent, r, location=Coordinate(round(c * ddx + s * ddy, 4),
                                                                  round(-s * ddx + c * ddy, 4), z - o.z))
    return
  Resource.assign_child_resource(parent, r, location=Coordinate(x - o.x, y - o.y, z - o.z))


def _site_holder(parent: Resource, site_id: str) -> Optional[ResourceHolder]:
  if isinstance(parent, Carrier):
    for holder in parent.sites.values():
      if holder.metadata.get(VENUS, {}).get("site_id") == site_id:
        return holder
  return None


def lay_to_plr(layout: Layout, store: DefinitionStore, name: str = "deck") -> HamiltonSTARDeck:
  deck_file = layout.header.get("Deck", "").lower()
  if deck_file not in DECKS:
    raise UnsupportedLayout(f"deck {layout.header.get('Deck')!r} is not a STAR-family deck")
  deck = HamiltonSTARDeck(
    name=name, with_waste_block=False, with_trash=False, with_trash96=False,
    with_teaching_needle_rack=False, core_grippers=None, **DECKS[deck_file],
  )
  deck.metadata[VENUS] = layout_metadata(layout)

  by_id = layout.by_id()
  built: dict[str, Resource] = {}

  def place(p: Placement) -> Resource:
    if p.id in built:
      return built[p.id]
    r = build_resource(p, store)
    if rotation_z(p):
      r.rotation = Rotation(z=rotation_z(p))
      if store.rack(p.file) is None:
        warnings.warn(f"{p.id}: rotated {p.kind} (Angle {p.angle}): turned about its TForm.3, unverified in Venus")
    x, y, z = venus_corner(p, store)
    parent_p = by_id.get(p.template) if p.template != "default" else None
    parent: Resource = deck
    if parent_p is not None and parent_p is not p:
      parent = place(parent_p)
      if isinstance(parent, Carrier):
        parent = _site_holder(parent, p.site_id) or _extra_site(parent, p.site_id, (x, y, z))
    _attach(deck, parent, r, (x, y, z))
    built[p.id] = r
    return r

  for p in layout.labware:
    r = place(p)
    if p.lid is not None:
      lid_def = store.lid(p.lid.file)
      sx, sy, sz = lid_def.dim if lid_def is not None else (0.0, 0.0, 0.0)
      o = r.get_absolute_location()
      lid_z = venus_lid_z(p.lid, lid_def, o.z)
      above = lid_z - o.z
      # PLR seats a lid nesting_z_height into its plate: so a lid put back lands where Venus has it
      nesting = round(r.get_size_z() - above, 4)
      lid = Lid(p.lid.id, sx, sy, sz, nesting_z_height=max(nesting, 0.0), metadata={VENUS: {"fields": dict(p.lid.fields)}})
      lx, ly, _ = p.lid.tform  # a lid's TForm.3 is its corner
      lid.metadata[VENUS]["lid_of"] = p.id
      # in the plate's own frame: a rotated plate turns its lid with it, the stored corner stays put
      # (where Venus puts a rotated plate's lid is unmeasured)
      c, s = turn(p)
      ddx, ddy = lx - o.x, ly - o.y
      loc = Coordinate(round(c * ddx + s * ddy, 4), round(-s * ddx + c * ddy, 4), round(above, 4))
      try:
        r.assign_child_resource(lid, location=loc)
      except (ValueError, TypeError):
        # PLR refuses some Venus lids (e.g. narrower than the plate): keep it on the plate as a
        # plain resource; metadata still links it as the lid
        lid = Resource(p.lid.id, sx, sy, sz, category="venus_lid", metadata=lid.metadata)
        Resource.assign_child_resource(r, lid, location=loc)
  deck.metadata[VENUS]["deltas"] = [d.as_dict() for d in import_deltas(layout, deck, store)]
  from venus_interop.rules import capture
  from venus_interop.rules.deltas import Delta

  log = capture.capture(layout, store)
  # a definition found only by file name may be a different file with the same name: if the layout
  # places the labware well off where that file would sit, the two disagree (e.g. a copy of HTF_L.rck
  # measured from the tip bottom, 83.45 mm below the stock file's reference)
  substituted = {normalize(p.file): p for p in layout.labware if normalize(p.file) in store.resolved_by_name}
  for i in log:
    p = next((q for q in substituted.values() if q.id == i.labware), None)
    # offsets the container-base pattern explains (CONVENTIONS.md 3b) are not evidence of a different file
    if p is not None and i.field in ("x/y", "z") and (i.size or 0) > 1.0 and "container base" not in i.text:
      deck.metadata[VENUS]["deltas"].append(Delta(
        p.id, "interpretation", "substituted definition", venus=p.file, size=i.size,
        detail=f"Found only by name ({store.resolved_by_name[normalize(p.file)]}), and the layout puts it {i.text}: "
               + ("the layout was almost certainly made with a different file of the same name."
                  if i.size > 10 else
                  "this may be a different file of the same name, or a taught position; the layout cannot tell which."),
        decision="Built from the substitute anyway; check this labware against the file the layout was made with.").as_dict())
  deck.metadata[VENUS]["capture"] = {"summary": capture.summary(layout, log), "items": [i.as_dict() for i in log]}
  return deck


def import_deltas(layout: Layout, deck: Resource, store: DefinitionStore) -> list:
  """Every interpretation the import made (the delta ledger, venus_interop/rules/deltas.py). Positions are
  never changed on import: TForm.3 and ZTrans are reproduced exactly; these are the choices around them."""
  from venus_interop.rules.deltas import Delta

  out = []
  for p in layout.labware:
    r = deck.get_resource(p.id)
    meta = r.metadata.get(VENUS, {})
    if not meta.get("definition_found", True):
      out.append(Delta(p.id, "missing", "definition", venus=p.file,
                       decision="A plain box at the stored position: no wells, tips or sites."))
    found = store.resolved_by_name.get(normalize(p.file))
    if found is not None:
      out.append(Delta(p.id, "interpretation", "definition file", venus=p.file, detail=f"Found only by name: {found}.",
                       decision="Used that file; the layout's own path does not exist here."))
    if p.angle != 0:
      out.append(Delta(p.id, "interpretation", "rotation", venus=p.angle,
                       decision="Placed unrotated at its stored A1; the body and wells are not turned."))
    if "nested_under" in meta:
      out.append(Delta(p.id, "interpretation", "parent", plr=meta["nested_under"],
                       detail="Overlaps other labware; pylabrobot refuses overlaps on the deck.",
                       decision="Nested under the overlapped resource; absolute position unchanged."))
    if isinstance(r, TipRack) and "guessed" in meta.get("tip", ""):
      out.append(Delta(p.id, "interpretation", "tip type", venus=p.file, detail=meta["tip"],
                       decision="Tip spot heights depend on this guess."))
    if isinstance(r, TipRack):
      out.append(Delta(p.id, "convention", "tip spot height",
                       detail="Venus ends a pick-up at the container base + the .ctr's MaxDepth; a PLR tip spot is where it ends.",
                       decision="spot z = base + MaxDepth (base + tip length - fitting depth without one)."))
    if p.lid is not None:
      lid = deck.get_resource(p.lid.id)
      if lid.category == "venus_lid":
        out.append(Delta(p.lid.id, "interpretation", "lid type", detail="pylabrobot refused it as a Lid (too small).",
                         decision="A plain resource on its plate, linked by metadata lid_of."))
  for holder in deck.get_all_resources():
    if isinstance(holder, ResourceHolder) and holder.metadata.get(VENUS, {}).get("extra"):
      out.append(Delta(holder.name, "interpretation", "carrier site",
                       detail="A layout site the carrier definition does not have.", decision="Added a holder for it."))
  return out
