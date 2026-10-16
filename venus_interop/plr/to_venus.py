"""PyLabRobot resource -> Venus labware definition files (.rck + .ctr, .lid, .tml).

For labware PLR has and Venus doesn't. Files are written relative to a folder under the Venus
Labware directory (default `PLR\\`), named after the PLR model, with both the Labware-relative path
and the `.\\` twin that Venus writes. See CONVENTIONS.md section 5 for the fields.

Venus's volume model is a stack of segments, each with a volume formula in the fill height. A PLR
well's volume function is sampled into SEGMENTS such segments with linear formulas, so the Venus
volume is the PLR volume interpolated linearly between the sample heights.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Optional

from pylabrobot.resources import (
  Carrier, Container, Coordinate, ItemizedResource, Lid, Resource, TipRack, TipSpot, Trash, Trough,
)

from venus_interop.files import hxcfg
from venus_interop.files.layout import fmt

SEGMENTS = 10  # starting split of the depth
MAX_SEGMENTS = 40
MIN_SEGMENT = 0.05  # mm
GRID_TOL = 1e-3
TIP_TYPE = {(10, False): 2, (10, True): 3, (50, False): 22, (50, True): 23, (300, False): 0, (300, True): 1,
            (1000, False): 4, (1000, True): 5, (5000, False): 25, (4000, True): 29}


class UnsupportedResource(ValueError):
  pass


@dataclasses.dataclass
class VenusFiles:
  """Definition files for one resource: {Labware-relative path: CfgFile}; `main` is the one a layout names."""

  main: str
  files: dict[str, hxcfg.CfgFile]
  notes: list[str]


def _cfg(type_: str, version: int, fields: dict[str, str]) -> hxcfg.CfgFile:
  return hxcfg.CfgFile(version=3, sections=[hxcfg.Section(type_, version, "default", entries=sorted(fields.items()))],
                       footer=hxcfg.Footer(author="venus_interop", valid=1, time="2026-10-15 00:00"))


def _common(description: str) -> dict[str, str]:
  return {"Description": description, "ViewName": description, "ReadOnly": "0", "Visible": "0",
          "CategoryCnt": "0", "Barcode.Value": "", "BackgrndClr": "16777215"}


def _grid(r: ItemizedResource):
  """(rows, columns, dx, dy, front-left centre) of a regular grid of items, in PLR's frame."""
  centres = []
  for it in r.get_all_items():
    c = it.location + it.get_anchor(x="c", y="c")
    centres.append((round(c.x, 4), round(c.y, 4)))
  xs, ys = sorted({x for x, _ in centres}), sorted({y for _, y in centres})
  if len(xs) * len(ys) != len(centres):
    raise UnsupportedResource(f"{r.name}: items are not a full rectangular grid")

  def pitch(v):
    steps = {round(b - a, 3) for a, b in zip(v, v[1:])}
    if len(steps) > 1 and max(steps) - min(steps) > GRID_TOL:
      raise UnsupportedResource(f"{r.name}: uneven pitch {sorted(steps)}")
    return steps.pop() if steps else 0.0

  return len(ys), len(xs), pitch(xs), pitch(ys), (xs[0], ys[0])


def _cubic(v0: float, v1: float, v2: float, v3: float, dz: float) -> tuple[float, float, float]:
  """a, b, c with a h + b h^2 + c h^3 through (dz/3, v1 - v0), (2dz/3, v2 - v0), (dz, v3 - v0).

  Exact for a frustum, a cone or a spherical cap, whose volumes are cubic in the fill height."""
  hs = [dz / 3, 2 * dz / 3, dz]
  ys = [v1 - v0, v2 - v0, v3 - v0]
  m = [[h, h * h, h ** 3] for h in hs]
  det = lambda a: (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1]) - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])  # noqa: E731
                   + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
  d = det(m)
  out = []
  for col in range(3):
    mc = [row[:] for row in m]
    for i in range(3):
      mc[i][col] = ys[i]
    out.append(det(mc) / d)
  return out[0], out[1], out[2]


def _bounded(volume, depth):
  """The volume function, extended linearly above the height it is defined to.

  Some PLR volume functions stop short of the well's own depth (e.g. defined to 10.8 in a 11.2 deep
  well); above that the cross-section at the top of their range is kept."""
  if volume is None:
    return None
  try:
    volume(depth)
    return volume
  except ValueError:
    pass
  except Exception:  # noqa: BLE001 - no usable volume model
    return None
  lo, hi = 0.0, depth
  try:
    volume(lo)
  except Exception:  # noqa: BLE001
    return None
  for _ in range(50):  # the highest height it accepts
    mid = (lo + hi) / 2
    try:
      volume(mid)
      lo = mid
    except ValueError:
      hi = mid
  top, step = lo, min(lo / 100, 0.01) or 1e-3
  slope = (volume(top) - volume(top - step)) / step

  def extended(h):
    return volume(h) if h <= top else volume(top) + slope * (h - top)

  return extended


def _container_fields(item: Resource, path: str, depth: Optional[float] = None) -> dict[str, str]:
  """A .ctr for one well/tube/tip: SEGMENTS stacked segments, each with a cubic volume formula fitted
  through the PLR volume at four heights (exact for frustums, cones and spherical caps)."""
  depth = depth if depth is not None else item.get_size_z()
  sx, sy = item.get_size_x(), item.get_size_y()
  f = _common("")
  f.update({"Depth": fmt(depth), "Dim.Dx": fmt(sx), "Dim.Dy": fmt(sy), "Dim.Dz": "0", "Shape": "0",
            "BaseMM": "0", "Clearance": fmt(depth + 2), "LS": "1", "LSHt": fmt(depth), "MaxDepth": "0",
            "UseBndry": "0", "TchOff": "0", "TchBase": "0"})
  box = str(getattr(item, "cross_section_type", "")).lower().endswith("rectangle")
  volume = _bounded(getattr(item, "compute_volume_from_height", None), depth)
  if volume is None:  # no volume model: a straight wall from the footprint
    area0 = sx * sy if box else math.pi * sx * sy / 4

    def volume(h):
      return area0 * h
  def vol(h):
    return float(volume(min(max(h, 0.0), depth)))  # float drift past the ends

  def fit(z0, z1):
    dz = z1 - z0
    return _cubic(*(vol(z0 + j * dz / 3) for j in range(4)), dz)

  def good(z0, z1, abc):
    """The cubic matches the volume at three more heights, to 0.1 % of the segment's volume."""
    a, b, c = abc
    total = max(abs(vol(z1) - vol(z0)), 1e-9)
    for t in (1 / 6, 1 / 2, 5 / 6):
      h = (z1 - z0) * t
      if abs(a * h + b * h * h + c * h ** 3 - (vol(z0 + h) - vol(z0))) > 1e-3 * total:
        return False
    return True

  # split where a cubic can't follow the shape (a step between two diameters, say), up to MAX_SEGMENTS
  pieces = [(depth * k / SEGMENTS, depth * (k + 1) / SEGMENTS) for k in range(SEGMENTS)]
  done = []
  while pieces:
    z0, z1 = pieces.pop(0)
    abc = fit(z0, z1)
    if good(z0, z1, abc) or z1 - z0 < MIN_SEGMENT or len(done) + len(pieces) + 2 > MAX_SEGMENTS:
      done.append((z0, z1, abc))
    else:
      mid = (z0 + z1) / 2
      pieces[:0] = [(z0, mid), (mid, z1)]
  done.sort()
  for k, (z0, z1, (a, b, c)) in enumerate(done):
    n = len(done) - k  # Venus numbers segments from the top
    dz = z1 - z0
    eqn = f"h*({a:.8f} + h*({b:.8f} + h*({c:.8f})))"
    bottom, top = max(a, 0.0), max(a + 2 * b * dz + 3 * c * dz * dz, 0.0)  # cross-section areas
    if box:
      ratio = sx / sy if sy else 1.0
      w = math.sqrt((bottom + top) / 2 * ratio)
      shape, dx_, dy_, dz_ = "1", fmt(round(w, 4)), fmt(round(w / ratio, 4)), "0"
    else:
      shape, dz_ = "3", "0"
      dx_, dy_ = (fmt(round(2 * math.sqrt(x / math.pi), 4)) for x in (top, bottom))
    f.update({f"{n}.Shape": shape, f"{n}.DX": dx_, f"{n}.DY": dy_, f"{n}.DZ": dz_,
              f"{n}.Min": fmt(round(z0, 6)), f"{n}.Max": fmt(round(z1, 6)), f"{n}.EqnOfVol": eqn})
  f["Segments"] = str(len(done))
  return f


def _tip_type(tip) -> Optional[int]:
  """The Hamilton tip type, only if pylabrobot's creator for it makes a tip of the same length."""
  from pylabrobot.resources.hamilton import tip_creators

  from venus_interop.plr.generate import BROKEN_TIP_CREATORS, TIP_CREATORS

  nominal = getattr(tip, "nominal_volume", None) or min(
    (n for n, _ in TIP_TYPE if n <= tip.maximal_volume <= 1.35 * n), default=None)
  code = TIP_TYPE.get((nominal, tip.has_filter)) if nominal else None
  creator = TIP_CREATORS.get(code)
  if code is None or creator is None or creator in BROKEN_TIP_CREATORS:
    return code
  ref = getattr(tip_creators, creator)("probe")
  return code if abs(ref.get_size_z() - tip.get_size_z()) < 0.05 else None


def rack_files(r: ItemizedResource, folder: str, name: str) -> VenusFiles:
  rows, cols, dx, dy, (bx, by) = _grid(r)
  notes = []
  first = r.get_item(0)  # A1
  item = first
  floor = item.location.z
  if isinstance(item, TipSpot):
    tip = item.make_tip()
    sink = getattr(r, "sinking_depth", 0.0) or 0.0
    length = getattr(tip, "total_tip_length", None) or tip.get_size_z()
    floor = item.location.z - sink - (length - tip.fitting_depth)
    item = tip
    notes.append("tip container base = spot z - rack sinking depth - (tip length - fitting depth): unverified")
  elif item.get_size_z() == 0:
    child = item.children[0] if item.children else None  # a tube in a holder
    if child is not None:
      floor = item.location.z + child.location.z
      item = child
    else:
      notes.append("empty holders: container sized to the holder, up to the rack's top")
  ctr_rel = f"{folder}\\{name}.ctr"
  rck = _common(r.model or name)
  sx, sy, sz = r.get_size_x(), r.get_size_y(), r.get_size_z()
  rck.update({
    "Dim.Dx": fmt(sx), "Dim.Dy": fmt(sy), "Dim.Dz": fmt(sz), "Rows": str(rows), "Columns": str(cols),
    "Dx": fmt(dx), "Dy": fmt(dy), "BndryX": fmt(bx), "BndryY": fmt(by), "UseBndry": "1",
    "Cntr.1.file": ctr_rel, "Cntr.1.fileRel": f".\\{name}.ctr", "Cntr.1.base": fmt(round(floor, 4)),
    "Cntr.1.offsetx": "0", "Cntr.1.offsety": "0", "SingleCntr": "1", "ConnectedCtr": "0",
    "IX.Index": "1", "IX.Inc": "0", "IX.First": "1", "IX.Start": "0",  # A1, B1 ... = PLR identifiers
    "Shape": "1", "Stagger": "0", "Options": "0", "DataType": "2", "StackHt": fmt(sz),
    "Hole.Shape": "0", "Hole.X": fmt(item.get_size_x()), "Hole.Y": fmt(item.get_size_y()),
    "Hole.Z": fmt(item.get_size_x()), "SegmentCount_x": "0", "SegmentCount_y": "0",
  })
  if isinstance(r, TipRack):
    props = {"PlrTipFilter": "1" if item.has_filter else "0", "PlrTipFittingDepth": fmt(item.fitting_depth),
             "PlrTipMaxVolume": fmt(item.maximal_volume)}
    code = _tip_type(item)
    if code is None:
      notes.append("no Hamilton tip type for this tip: Venus will not treat it as a tip rack")
    else:
      # the properties Venus's own tip racks carry (e.g. ML_STAR\STF_L.rck): tip type for single channels
      # and the CO-RE 96 head, and both as tip waste
      props.update({"MlStarTipRack": str(code), "MlStarCore96TipRack": str(code), "MlStarIsWasteRack": "1",
                    "MlStarIsCore96WasteRack": "1"})
    rck["PropertyCnt"] = str(len(props))
    for i, (k, v) in enumerate(props.items(), 1):
      rck[f"Property.{i}"], rck[f"PropertyValue.{i}"] = k, v
  depth = item.get_size_z() or max(sz - floor, 0.0)
  ctr = _container_fields(item, ctr_rel, depth)
  if isinstance(first, TipSpot):  # the container's footprint is the rack's hole, as the importer reads it
    ctr["Dim.Dx"], ctr["Dim.Dy"] = fmt(first.get_size_x()), fmt(first.get_size_y())
    rck["Hole.X"], rck["Hole.Y"], rck["Hole.Z"] = fmt(first.get_size_x()), fmt(first.get_size_y()), fmt(first.get_size_x())
  return VenusFiles(f"{folder}\\{name}.rck",
                    {f"{folder}\\{name}.rck": _cfg("RECTRACK", 3, rck), ctr_rel: _cfg("CONTAINER", 3, ctr)}, notes)


def _floor(c: Resource) -> float:
  """Container floor above its own bottom; 0 where pylabrobot leaves it undefined (it raises)."""
  try:
    return float(c.material_z_thickness or 0)
  except NotImplementedError:
    return 0.0


def single_files(c: Resource, folder: str, name: str) -> VenusFiles:
  """A lone tube or container as a one-position Venus rack the size of its footprint."""
  sx, sy, sz = c.get_size_x(), c.get_size_y(), c.get_size_z()
  ctr_rel = f"{folder}\\{name}.ctr"
  rck = _common(c.model or name)
  rck.update({
    "Dim.Dx": fmt(sx), "Dim.Dy": fmt(sy), "Dim.Dz": fmt(sz), "Rows": "1", "Columns": "1", "Dx": "0", "Dy": "0",
    "BndryX": fmt(sx / 2), "BndryY": fmt(sy / 2), "UseBndry": "1",
    "Cntr.1.file": ctr_rel, "Cntr.1.fileRel": f".\\{name}.ctr", "Cntr.1.base": fmt(_floor(c)),
    "Cntr.1.offsetx": "0", "Cntr.1.offsety": "0", "SingleCntr": "1", "ConnectedCtr": "0",
    "IX.Index": "1", "IX.Inc": "0", "IX.First": "1", "IX.Start": "0",
    "Shape": "1", "Stagger": "0", "Options": "0", "DataType": "2", "StackHt": fmt(sz),
  })
  ctr = _container_fields(c, ctr_rel, sz - _floor(c))
  return VenusFiles(f"{folder}\\{name}.rck", {f"{folder}\\{name}.rck": _cfg("RECTRACK", 3, rck),
                                              ctr_rel: _cfg("CONTAINER", 3, ctr)},
                    ["single container: a 1 x 1 rack the size of its footprint"])


def trough_files(t: Trough, folder: str, name: str) -> VenusFiles:
  """A trough as Venus draws one: positions on a 9 mm grid over the cavity, sharing one liquid."""
  sx, sy, sz = t.get_size_x(), t.get_size_y(), t.get_size_z()
  rows, cols = max(1, int(sy // 9)), max(1, int(sx // 9))
  ctr_rel = f"{folder}\\{name}.ctr"
  rck = _common(t.model or name)
  rck.update({
    "Dim.Dx": fmt(sx), "Dim.Dy": fmt(sy), "Dim.Dz": fmt(sz), "Rows": str(rows), "Columns": str(cols),
    "Dx": "9", "Dy": "9", "BndryX": fmt(round((sx - (cols - 1) * 9) / 2, 4)),
    "BndryY": fmt(round((sy - (rows - 1) * 9) / 2, 4)), "UseBndry": "1",
    "Cntr.1.file": ctr_rel, "Cntr.1.fileRel": f".\\{name}.ctr",
    "Cntr.1.base": fmt(_floor(t)), "Cntr.1.offsetx": "0", "Cntr.1.offsety": "0",
    "SingleCntr": "1", "ConnectedCtr": "1", "IX.Index": "1", "IX.Inc": "0", "IX.First": "1", "IX.Start": "0",
    "Shape": "1", "Stagger": "0", "Options": "0", "DataType": "2", "StackHt": fmt(sz),
  })
  ctr = _container_fields(t, ctr_rel)
  return VenusFiles(f"{folder}\\{name}.rck", {f"{folder}\\{name}.rck": _cfg("RECTRACK", 3, rck),
                                              ctr_rel: _cfg("CONTAINER", 3, ctr)},
                    ["trough: positions on a 9 mm grid sharing one liquid (ConnectedCtr = 1); unverified in Venus"])


def lid_files(lid: Lid, folder: str, name: str, plate: Optional[Resource] = None) -> VenusFiles:
  plate = plate or lid.parent
  sx, sy, sz = lid.get_size_x(), lid.get_size_y(), lid.get_size_z()
  f = _common(lid.model or name)
  notes = []
  if plate is not None:
    r2c = plate.get_size_z() - lid.nesting_z_height
    ext = (plate.get_size_x(), plate.get_size_y())
  else:
    r2c, ext = 0.0, (sx, sy)
    notes.append("no plate given: RackBaseToCoverBase set to 0")
  f.update({"Dim.Dx": fmt(sx), "Dim.Dy": fmt(sy), "Dim.Dz": fmt(sz), "CoverThickness": "1",
            "RackBaseToCoverBase": fmt(round(r2c, 4)), "StackHt": fmt(sz),
            "CoveredStackHt": fmt(round(r2c + sz, 4)), "XExtent": fmt(ext[0]), "YExtent": fmt(ext[1])})
  notes.append("CoverThickness unknown in PLR: 1 mm")
  return VenusFiles(f"{folder}\\{name}.lid", {f"{folder}\\{name}.lid": _cfg("COVER", 1, f)}, notes)


def site_corner(h) -> Coordinate:
  """Where a Venus site is for a PLR holder: the corner and bottom a rack would have on it.

  Independent of what stands on the holder: a plate holder lowers each plate onto its pedestal by an
  amount that depends on the plate, so the site is the holder's position for a generic item. A tip
  rack holder only takes tip racks, centres them and sinks them by the rack's sinking depth; the site
  is the rack's corner at the holder's height (Venus measures a tip rack from its site)."""
  try:
    return h.location + h.get_default_child_location(Resource("probe", h.get_size_x(), h.get_size_y(), 0))
  except (ValueError, TypeError):
    pass
  probe = next((sib.children[0] for sib in getattr(h.parent, "sites", {}).values() if sib.children), None)
  if probe is not None:
    off = h.get_default_child_location(probe)
    return h.location + Coordinate(off.x, off.y, off.z + (getattr(probe, "sinking_depth", 0.0) or 0.0))
  # an empty tip rack holder: a Hamilton tip rack (122.4 x 82.6) centred on it, turned like the holder
  # (TIP_CAR_288 holds portrait racks)
  rx, ry = (122.4, 82.6) if h.get_size_x() >= h.get_size_y() else (82.6, 122.4)
  return h.location + Coordinate((h.get_size_x() - rx) / 2, (h.get_size_y() - ry) / 2, 0)


def carrier_files(c: Carrier, folder: str, name: str) -> VenusFiles:
  f = _common(c.model or name)
  sx, sy, sz = c.get_size_x(), c.get_size_y(), c.get_size_z()
  f.update({"Dim.Dx": fmt(sx), "Dim.Dy": fmt(sy), "Dim.Dz": fmt(sz), "UseBndry": "0",
            "PropertyCnt": "1", "Property.1": "MlStarCarWidthAsT", "PropertyValue.1": str(round(sx / 22.5))})
  holders = sorted(c.sites.values(), key=lambda h: (-h.location.y, h.location.x))  # Venus: site 1 at the back
  for n, h in enumerate(holders, 1):
    loc = site_corner(h)
    site_id = h.metadata.get("venus", {}).get("site_id", str(n))
    f.update({f"Site.{n}.Id": site_id, f"Site.{n}.X": fmt(round(loc.x, 4)), f"Site.{n}.Y": fmt(round(loc.y, 4)),
              f"Site.{n}.Z": fmt(round(loc.z, 4)), f"Site.{n}.Dx": fmt(h.get_size_x()),
              f"Site.{n}.Dy": fmt(h.get_size_y()), f"Site.{n}.Label": "1", f"Site.{n}.Visible": "1",
              f"Site.{n}.Stack": "0", f"Site.{n}.StackSize": "1", f"Site.{n}.IsCovered": "0",
              f"Site.{n}.SnapBase": "0"})
  f["Site.Cnt"] = str(len(holders))
  return VenusFiles(f"{folder}\\{name}.tml", {f"{folder}\\{name}.tml": _cfg("TEMPLATE", 1, f)}, [])


def venus_files(r: Resource, folder: str = "PLR", name: Optional[str] = None) -> VenusFiles:
  """Definition files for a PLR resource, named after its model (or `name`)."""
  name = name or r.model or r.name
  if isinstance(r, Lid):
    return lid_files(r, folder, name)
  if isinstance(r, Carrier):
    return carrier_files(r, folder, name)
  if isinstance(r, Trough):
    return trough_files(r, folder, name)
  if isinstance(r, ItemizedResource):
    return rack_files(r, folder, name)
  if isinstance(r, Container) and not isinstance(r, Trash):
    return single_files(r, folder, name)
  if type(r) is Resource:  # a plain body: device placeholders, verification sites
    f = _common(r.model or name)
    f.update({"Dim.Dx": fmt(r.get_size_x()), "Dim.Dy": fmt(r.get_size_y()), "Dim.Dz": fmt(r.get_size_z()),
              "Rows": "0", "Columns": "0", "HoleCnt": "0", "Dx": "0", "Dy": "0", "BndryX": "0", "BndryY": "0",
              "UseBndry": "0", "Shape": "1", "Options": "0", "DataType": "2", "StackHt": fmt(r.get_size_z())})
    return VenusFiles(f"{folder}\\{name}.rck", {f"{folder}\\{name}.rck": _cfg("RECTRACK", 3, f)},
                      ["plain body: a rack with no positions"])
  raise UnsupportedResource(f"{r.name}: {type(r).__name__} has no Venus definition writer")


def write(files: VenusFiles, labware_root) -> list:
  """Write the files under a Labware folder (binary, fresh footers). Returns the paths written."""
  import pathlib

  out = []
  for rel, cfg in files.files.items():
    p = pathlib.Path(labware_root) / rel.replace("\\", "/")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(hxcfg.write_binary(cfg))
    out.append(p)
  return out
