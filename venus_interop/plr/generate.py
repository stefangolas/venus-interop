"""Generate PyLabRobot resources (factory source code and 3D models) from Venus labware definitions.

For each definition:
  - if `name_match` finds exactly one PLR resource that is the same labware, emit an alias to it;
  - otherwise build a `LabwareSpec` from the .rck/.ctr/.tml/.lid and emit a PLR factory for it.
Models: the authored Hamilton .x/.hxx when the definition names one, else one generated from the
spec's geometry (body box with every well cut out, carrier with site pockets, lid shell).

Venus draws most SBS labware on a nominal 127 x 86 footprint; within 1 mm of SBS the spec snaps the
footprint to 127.76 x 85.48 and re-centres the positions (which keeps them where Venus puts them
relative to the labware's centre). Every approximation is listed in the factory's docstring.
"""
from __future__ import annotations

import dataclasses
import json
import math
import re
from typing import Optional

from venus_interop.files.definitions import Carrier as CarrierDef
from venus_interop.files.definitions import Definition, DefinitionStore, Lid as LidDef, Rack

SBS = (127.76, 85.48)
SBS_TOL = 1.0
_EQN = re.compile(r"^[0-9h+\-*/(). ]+$")


# ---------------------------------------------------------------------------------------- containers


@dataclasses.dataclass
class Segment:
  """One .ctr segment, from z0 to z1 above the container floor."""

  z0: float
  z1: float
  shape: int  # 0 cylinder (DZ), 1 box (DX x DY), 3 frustum (DX top, DY bottom), 4 round bottom (DZ), 5 V bottom (DZ)
  dx: float
  dy: float
  dz: float
  eqn: str  # volume in uL of a fill h mm deep within the segment

  def volume(self, h: float) -> float:
    if not _EQN.match(self.eqn):
      raise ValueError(f"unexpected volume equation {self.eqn!r}")
    return float(eval(self.eqn, {"__builtins__": {}}, {"h": h}))  # noqa: S307 - checked above

  def radius_at(self, t: float) -> float:
    """Radius (round shapes) at height t within the segment."""
    h = self.z1 - self.z0
    if self.shape == 0:
      return self.dz / 2
    if self.shape == 3:
      return (self.dy + (self.dx - self.dy) * (t / h if h else 1)) / 2
    if self.shape == 4:  # spherical cap of radius r: radius at height t from its bottom
      r = self.dz / 2
      return math.sqrt(max(r * r - (r - t) ** 2, 0.0))
    if self.shape == 5:  # cone to a point
      return self.dz / 2 * (t / h if h else 1)
    raise ValueError(self.shape)


@dataclasses.dataclass
class Container:
  path: str
  depth: float
  size: tuple[float, float]  # top footprint
  segments: list[Segment]  # bottom first

  @property
  def is_box(self) -> bool:
    return self.segments[-1].shape == 1 if self.segments else False

  @property
  def bottom(self) -> str:
    """PLR bottom type: flat, U or V, from the lowest segment."""
    s = self.segments[0].shape if self.segments else -1
    return {4: "U", 5: "V"}.get(s, "flat")

  def volume(self, h: float) -> float:
    return sum(s.volume(min(max(h - s.z0, 0.0), s.z1 - s.z0)) for s in self.segments)

  @property
  def max_volume(self) -> float:
    return self.volume(self.depth)


def container(d: Definition) -> Container:
  segs = []
  n = 1
  while f"{n}.Shape" in d.fields:
    g = lambda k, n=n: d.num(f"{n}.{k}")  # noqa: E731
    segs.append(Segment(g("Min"), g("Max"), int(g("Shape")), g("DX"), g("DY"), g("DZ"),
                        d.fields.get(f"{n}.EqnOfVol", "0").strip()))
    n += 1
  segs.sort(key=lambda s: s.z0)
  return Container(d.path, d.num("Depth") or (segs[-1].z1 if segs else 0.0),
                   (d.num("Dim.Dx"), d.num("Dim.Dy") or d.num("Dim.Dx")), segs)


# ---------------------------------------------------------------------------------------- specs


@dataclasses.dataclass
class LabwareSpec:
  """Everything a factory and a model need, in PLR's frame (front-left-bottom corner, mm)."""

  name: str  # factory name
  kind: str  # plate | tip_rack | trough | tube_rack | carrier | lid | resource
  source: str  # Venus definition path
  size: tuple[float, float, float]
  description: str = ""
  # grid labware
  rows: int = 0
  columns: int = 0
  pitch: tuple[float, float] = (0.0, 0.0)
  a1_front_left: tuple[float, float] = (0.0, 0.0)  # centre of the front-left position (Venus BndryX/Y)
  floor: float = 0.0  # container floor above the labware's bottom (Cntr.1.base)
  container: Optional[Container] = None
  tip_creator: Optional[str] = None
  tip_filter: bool = False
  tip_fitting_depth: float = 8.0  # pylabrobot's Hamilton tips use 8; unknown for Venus tips
  tip_max_volume: Optional[float] = None
  # carriers
  sites: list[tuple[str, float, float, float, float, float]] = dataclasses.field(default_factory=list)
  # lids
  nesting_z_height: Optional[float] = None
  notes: list[str] = dataclasses.field(default_factory=list)

  @property
  def positions(self) -> list[tuple[str, float, float]]:
    """(identifier, centre x, centre y) for each position, A1 at the back left."""
    out = []
    for c in range(self.columns):
      for r in range(self.rows):
        y = self.a1_front_left[1] + (self.rows - 1 - r) * self.pitch[1]
        out.append((f"{_row(r + 1)}{c + 1}", self.a1_front_left[0] + c * self.pitch[0], y))
    return out


def _row(r: int) -> str:
  s = ""
  while r:
    r -= 1
    s = chr(65 + r % 26) + s
    r //= 26
  return s


def factory_name(path: str) -> str:
  stem = path.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
  name = re.sub(r"\W+", "_", stem).strip("_")
  return ("venus_" + name) if not name or name[0].isdigit() else name


def _snap(spec: LabwareSpec) -> None:
  sx, sy, sz = spec.size
  if abs(sx - SBS[0]) <= SBS_TOL and abs(sy - SBS[1]) <= SBS_TOL and (sx, sy) != SBS:
    shift = ((SBS[0] - sx) / 2, (SBS[1] - sy) / 2)
    spec.size = (SBS[0], SBS[1], sz)
    spec.a1_front_left = (spec.a1_front_left[0] + shift[0], spec.a1_front_left[1] + shift[1])
    spec.sites = [(i, x + shift[0], y + shift[1], z, dx, dy) for i, x, y, z, dx, dy in spec.sites]
    spec.notes.append(f"footprint {sx} x {sy} snapped to SBS {SBS[0]} x {SBS[1]}, positions re-centred")


BROKEN_TIP_CREATORS = {"hamilton_tip_5000uL", "hamilton_tip_4000uL_filter"}  # raise in pylabrobot 1.0.0b1
TIP_CREATORS = {  # Hamilton tip type id -> pylabrobot creator
  0: "hamilton_tip_300uL", 1: "hamilton_tip_300uL_filter", 2: "hamilton_tip_10uL", 3: "hamilton_tip_10uL_filter",
  4: "hamilton_tip_1000uL", 5: "hamilton_tip_1000uL_filter", 22: "hamilton_tip_50uL", 23: "hamilton_tip_50uL_filter",
  25: "hamilton_tip_5000uL", 29: "hamilton_tip_4000uL_filter", 36: "hamilton_tip_300uL_filter_slim",
  45: "hamilton_tip_300uL_filter_slim",
}


def spec_for(d: Definition, store: DefinitionStore, name: Optional[str] = None) -> LabwareSpec:
  name = name or factory_name(d.path)
  desc = d.fields.get("Description", "").strip()
  if isinstance(d, CarrierDef):
    s = LabwareSpec(name, "carrier", d.path, d.dim, desc,
                    sites=[(st.id, st.x, st.y, st.z, st.dx, st.dy)  # PLR: index 0 at the front
                           for st in sorted(d.sites.values(), key=lambda s: (s.y, s.x))])
    return s
  if isinstance(d, LidDef):
    s = LabwareSpec(name, "lid", d.path, d.dim, desc)
    plate = store.rack(d.path.rsplit(".", 1)[0] + ".rck")
    if plate is not None:
      s.nesting_z_height = plate.dim[2] - d.rack_base_to_cover_base
    else:
      s.notes.append("nesting height unknown (no .rck of the same name); set to 0")
    _snap(s)
    return s
  if not isinstance(d, Rack):
    return LabwareSpec(name, "resource", d.path, d.dim, desc, notes=["not a rack, carrier or lid: body only"])

  ctr_def = store.ref(d, "Cntr.1.file")
  ctr = container(ctr_def) if ctr_def is not None else None
  s = LabwareSpec(name, "plate", d.path, d.dim, desc, rows=d.rows or 1, columns=d.columns or 1,
                  pitch=(d.dx, d.dy), a1_front_left=d.boundary, floor=d.num("Cntr.1.base"), container=ctr)
  if ctr is None:
    s.notes.append("container definition not found: wells sized to the pitch")
  if not d.rows or not d.columns:
    s.kind = "resource"
    s.notes.append(f"no grid ({d.hole_count} positions): body only")
  elif d.is_tip_rack:
    s.kind = "tip_rack"
    code = d.properties.get("MlStarTipRack") or d.properties.get("MlStarXLTipRack")
    if "PlrTipFilter" in d.properties:  # written by to_venus
      s.tip_filter = d.properties["PlrTipFilter"] == "1"
      s.tip_fitting_depth = float(d.properties.get("PlrTipFittingDepth", 8.0))
      s.tip_max_volume = float(d.properties["PlrTipMaxVolume"]) if "PlrTipMaxVolume" in d.properties else None
    else:
      s.tip_filter = "filter" in d.properties.get("managedSequenceName", "").lower() or bool(
        re.search(r"(^|[_/])(htf|stf|ltf|tip_50ulf|4mltf)", d.path) or "filter" in d.path)
    s.tip_creator = TIP_CREATORS.get(int(code)) if code not in (None, "") else None
    if s.tip_creator in BROKEN_TIP_CREATORS:
      s.notes.append(f"pylabrobot's {s.tip_creator} cannot build a tip (no diameter); tip built from the .ctr")
      s.tip_creator = None
    elif s.tip_creator is None:
      s.notes.append(f"tip type {code!r} has no pylabrobot tip creator; tip built from the .ctr")
    s.notes.append("tip spot height taken from Venus's container base; unverified against PLR's tip racks")
  elif d.fields.get("ConnectedCtr") == "1":
    s.kind = "trough"
    s.notes.append(f"Venus draws this as {d.rows} x {d.columns} positions sharing one liquid; PLR: one trough")
  elif "smp_car" in d.path or (ctr and re.search(r"cup|tube|vial", ctr.path)):
    s.kind = "tube_rack"
  if d.fields.get("Stagger", "0") not in ("0", ""):
    s.notes.append(f"Stagger {d.fields['Stagger']} ignored: positions are a plain grid")
  if ctr and any(seg.shape not in (0, 1, 3, 4, 5) for seg in ctr.segments):
    s.notes.append("container has segment shapes this generator does not draw")
  if s.kind in ("plate", "trough", "tip_rack"):
    _snap(s)
  return s


# ---------------------------------------------------------------------------------------- source code

HEADER = '''"""PyLabRobot resources generated from Venus labware definitions by venus_interop.plr.generate.

Do not edit by hand: regenerate instead. Each factory's docstring names its Venus source and lists
every value that was approximated.
"""
# flake8: noqa
from pylabrobot.resources import (
  Carrier, Coordinate, Lid, Plate, Resource, ResourceHolder, Tip, TipRack, TipSpot, Trough, Tube, TubeRack, Well,
)
from pylabrobot.resources.hamilton import tip_creators
from pylabrobot.resources.utils import create_ordered_items_2d
from pylabrobot.resources.well import CrossSectionType, WellBottomType


def _height_from_volume(volume_fn, depth):
  """Invert a monotonic volume function by bisection."""

  def height(volume: float) -> float:
    lo, hi = 0.0, depth
    for _ in range(60):
      mid = (lo + hi) / 2
      if volume_fn(mid) < volume:
        lo = mid
      else:
        hi = mid
    return (lo + hi) / 2

  return height
'''


def _f(x: float) -> str:
  return repr(round(float(x), 4))


def _doc(spec: LabwareSpec) -> str:
  lines = [spec.description or spec.name, "", f"Generated from Venus definition `{spec.source}`."]
  if spec.container is not None:
    lines.append(f"Container: `{spec.container.path}`.")
  lines += [f"- {n}" for n in spec.notes]
  return "\n  ".join(lines)


def _volume_fn(spec: LabwareSpec) -> str:
  segs = ", ".join(f"({_f(s.z0)}, {_f(s.z1)}, lambda h: {s.eqn})" for s in spec.container.segments)
  return (f"\n\n_{spec.name}_segments = [{segs}]\n\n\ndef _{spec.name}_volume(h: float) -> float:\n"
          f"  return sum(v(min(max(h - z0, 0.0), z1 - z0)) for z0, z1, v in _{spec.name}_segments)\n")


def emit(spec: LabwareSpec) -> str:
  """Source of one factory (plus helpers), in the style of pylabrobot's own."""
  n, (sx, sy, sz) = spec.name, spec.size
  head = f"\n\ndef {n}(name: str) -> "
  doc = f'  """{_doc(spec)}\n  """\n'
  if spec.kind == "carrier":
    sites = "".join(
      f"      {i}: ResourceHolder(name + {('_site_' + sid)!r}, {_f(dx)}, {_f(dy)}, 0),\n"
      for i, (sid, x, y, z, dx, dy) in enumerate(spec.sites))
    locs = "".join(f"  sites[{i}].location = Coordinate({_f(x)}, {_f(y)}, {_f(z)})\n"
                   for i, (sid, x, y, z, dx, dy) in enumerate(spec.sites))
    return (head + "Carrier:\n" + doc + f"  sites = {{\n{sites}  }}\n{locs}"
            f"  return Carrier(name, {_f(sx)}, {_f(sy)}, {_f(sz)}, sites=sites, model={n!r})\n")
  if spec.kind == "lid":
    return (head + "Lid:\n" + doc + f"  return Lid(name, {_f(sx)}, {_f(sy)}, {_f(sz)}, "
            f"nesting_z_height={_f(spec.nesting_z_height or 0)}, model={n!r})\n")
  if spec.kind == "resource":
    return head + "Resource:\n" + doc + f"  return Resource(name, {_f(sx)}, {_f(sy)}, {_f(sz)}, model={n!r})\n"

  ctr = spec.container
  wx, wy = ctr.size if ctr else (min(spec.pitch) or 9.0,) * 2
  depth = ctr.depth if ctr else sz
  pre = _volume_fn(spec) if ctr and ctr.segments and spec.kind != "tip_rack" else ""
  vol = (f"      max_volume={_f(ctr.max_volume)},\n      compute_volume_from_height=_{n}_volume,\n"
         f"      compute_height_from_volume=_height_from_volume(_{n}_volume, {_f(depth)}),\n") if pre else ""
  grid = (f"      num_items_x={spec.columns},\n      num_items_y={spec.rows},\n"
          f"      dx={_f(spec.a1_front_left[0] - wx / 2)},\n      dy={_f(spec.a1_front_left[1] - wy / 2)},\n"
          f"      dz={_f(max(spec.floor, 0.0)) if spec.kind != 'tip_rack' else '_seat'},\n"
          f"      item_dx={_f(spec.pitch[0]) if spec.columns > 1 else None},\n"
          f"      item_dy={_f(spec.pitch[1]) if spec.rows > 1 else None},\n"
          f"      size_x={_f(wx)},\n      size_y={_f(wy)},\n      name_prefix=name,\n")
  if spec.kind == "trough":
    return pre + head + "Trough:\n" + doc + (
      f"  return Trough(name, {_f(sx)}, {_f(sy)}, {_f(sz)},\n"
      f"    max_volume={_f(ctr.max_volume * spec.rows * spec.columns) if ctr else 0},\n"
      f"    material_z_thickness={_f(max(spec.floor, 0.0))},\n"
      f"    bottom_type={ctr.bottom if ctr else 'unknown'!r},\n    model={n!r},\n  )\n")
  if spec.kind == "tip_rack":
    creator = f"tip_creators.{spec.tip_creator}" if spec.tip_creator else f"_{n}_tip"
    tip = "" if spec.tip_creator else (
      f"\n\ndef _{n}_tip(name: str) -> Tip:\n"
      f'  """From the Venus container: length = its depth, volume = its volume."""\n'
      f"  return Tip(name, diameter={_f(wx)}, size_z={_f(depth)}, has_filter={spec.tip_filter},\n"
      f"    maximal_volume={_f(spec.tip_max_volume if spec.tip_max_volume is not None else (ctr.max_volume if ctr else 0))},"
      f" fitting_depth={_f(spec.tip_fitting_depth)}, model={n + '_tip'!r})\n")
    seat = (f"  _probe = {creator}('probe')\n"
            f"  _seat = {_f(spec.floor)} + _probe.get_size_z() - _probe.fitting_depth  # Venus base = tip bottom\n")
    return tip + head + "TipRack:\n" + doc + seat + (
      f"  return TipRack(name, {_f(sx)}, {_f(sy)}, {_f(sz)}, model={n!r},\n"
      f"    ordered_items=create_ordered_items_2d(\n      TipSpot,\n{grid}      make_tip={creator},\n    ),\n  )\n")
  bottom = {"flat": "WellBottomType.FLAT", "U": "WellBottomType.U", "V": "WellBottomType.V"}[ctr.bottom if ctr else "flat"]
  section = "CrossSectionType.RECTANGLE" if (ctr and ctr.is_box) or abs(wx - wy) > 1e-6 else "CrossSectionType.CIRCLE"
  if spec.kind == "tube_rack":
    return pre + head + "TubeRack:\n" + doc + (
      f"  holders = create_ordered_items_2d(\n      ResourceHolder,\n{grid}      size_z=0,\n    )\n"
      f"  for spot in holders.values():\n"
      f"    spot.assign_child_resource(Tube(spot.name + '_tube', {_f(wx)}, {_f(wy)}, {_f(depth)},\n"
      f"      max_volume={_f(ctr.max_volume) if ctr else 0}), location=Coordinate.zero())\n"
      f"  return TubeRack(name, {_f(sx)}, {_f(sy)}, {_f(sz)}, ordered_items=holders, model={n!r})\n")
  return pre + head + "Plate:\n" + doc + (
    f"  return Plate(name, {_f(sx)}, {_f(sy)}, {_f(sz)}, model={n!r},\n"
    f"    ordered_items=create_ordered_items_2d(\n      Well,\n{grid}      size_z={_f(depth)},\n"
    f"      bottom_type={bottom},\n      cross_section_type={section},\n{vol}    ),\n  )\n")


def emit_alias(name: str, factory: str, source: str) -> str:
  mod, fn = factory.rsplit(".", 1)
  return (f"\n\nfrom {mod} import {fn} as _{name}_plr\n\n\ndef {name}(name: str):\n"
          f'  """Venus `{source}`: the same labware as pylabrobot\'s `{fn}`."""\n'
          f"  return _{name}_plr(name)\n")


# ---------------------------------------------------------------------------------------- models


def _revolve(profile: list[tuple[float, float]], sections: int = 32):
  import trimesh
  return trimesh.creation.revolve(profile, sections=sections)


def cavity(ctr: Container, extra_top: float = 1.0):
  """One container's inner volume as a solid, floor at z = 0, open past the top by `extra_top`."""
  import trimesh

  parts = []
  for i, s in enumerate(ctr.segments):
    h = s.z1 - s.z0 + (extra_top if i == len(ctr.segments) - 1 else 0.0)
    if h <= 0:
      continue
    if s.shape == 1:
      box = trimesh.creation.box((s.dx, s.dy or s.dx, h))
      box.apply_translation((0, 0, s.z0 + h / 2))
      parts.append(box)
      continue
    steps = 8 if s.shape == 4 else 1
    pts = [(s.radius_at(min(k * (h / steps), s.z1 - s.z0)), s.z0 + k * h / steps) for k in range(steps + 1)]
    profile = [(0.0, pts[0][1])] + [(max(r, 1e-3), z) for r, z in pts] + [(0.0, pts[-1][1])]
    parts.append(_revolve(profile))
  if not parts:
    return None
  return trimesh.boolean.union(parts, engine="manifold") if len(parts) > 1 else parts[0]


def model_for(spec: LabwareSpec):
  """A generated model in metres, PLR frame. Returns (trimesh.Scene, provenance dict)."""
  import trimesh

  sx, sy, sz = spec.size
  body = trimesh.creation.box((sx, sy, sz))
  body.apply_translation((sx / 2, sy / 2, sz / 2))
  cut = []
  if spec.kind == "carrier":
    for _, x, y, z, dx, dy in spec.sites:
      if dx > 0 and dy > 0 and z < sz:
        pocket = trimesh.creation.box((dx, dy, sz - z + 1))
        pocket.apply_translation((x + dx / 2, y + dy / 2, z + (sz - z + 1) / 2))
        cut.append(pocket)
  elif spec.kind == "lid":
    t = 1.0
    inner = trimesh.creation.box((sx - 2 * t, sy - 2 * t, sz - t + 1))
    inner.apply_translation((sx / 2, sy / 2, (sz - t - 1) / 2))
    cut.append(inner)
  elif spec.kind == "trough" and spec.container is not None:
    w = spec.columns * spec.pitch[0] or spec.container.size[0]
    d = spec.rows * spec.pitch[1] or spec.container.size[1]
    depth = spec.container.depth
    box = trimesh.creation.box((w, d, depth + 1))
    box.apply_translation((sx / 2, sy / 2, max(spec.floor, 0) + (depth + 1) / 2))
    cut.append(box)
  elif spec.kind in ("plate", "tube_rack", "tip_rack") and spec.rows and spec.columns:
    one = cavity(spec.container) if spec.container is not None and spec.container.segments else None
    for _, x, y in spec.positions:
      if one is None:
        w = min(spec.pitch) * 0.8 or 6.0
        c = trimesh.creation.cylinder(radius=w / 2, height=sz + 1)
        c.apply_translation((x, y, sz / 2 + max(spec.floor, 0)))
      else:
        c = one.copy()
        c.apply_translation((x, y, spec.floor))
      cut.append(c)
  mesh = body
  if cut:
    mesh = trimesh.boolean.difference([body, trimesh.boolean.union(cut, engine="manifold")], engine="manifold")
  mesh.apply_scale(0.001)
  scene = trimesh.Scene()
  scene.add_geometry(mesh, geom_name=spec.name, node_name=spec.name)
  info = {"model": spec.name, "kind": "generated", "source": spec.source,
          "container": spec.container.path if spec.container else None,
          "triangles": int(len(mesh.faces)), "size_mm": [round(v, 3) for v in spec.size],
          "notes": "body is the definition's bounding box with each container cut out; no skirt, ribs or rims"}
  return scene, info


def authored_model(d: Definition, store: DefinitionStore, spec: LabwareSpec):
  """The Hamilton .x/.hxx the definition names, aligned to the spec's box. None if there is none."""
  from venus_interop.plr import xfile

  ref = d.fields.get("3DModel")
  path = store.find(ref) if ref else None
  if path is None:
    return None
  scene = xfile.load(path)
  lo, hi = scene.bounds
  size = hi - lo
  sx, sy, _ = spec.size
  shift = ((sx - size[0]) / 2 - lo[0], (sy - size[1]) / 2 - lo[1], -lo[2])
  scene.apply_translation(shift)
  scene.apply_scale(0.001)
  info = {"model": spec.name, "kind": "authored", "source": str(path), "definition": spec.source,
          "registration": "bounding box: footprint centred on the definition's, bottom at z = 0",
          "venus_3d_offset": [d.fields.get(f"3D{a}Offset") for a in "xyz"],
          "model_size_mm": [round(float(v), 2) for v in size], "definition_size_mm": list(spec.size)}
  return scene, info


def write_model(scene, info: dict, out_dir) -> None:
  import pathlib

  out = pathlib.Path(out_dir)
  out.mkdir(parents=True, exist_ok=True)
  scene.export(out / f"{info['model']}.glb")
  (out / f"{info['model']}.geometry.json").write_text(json.dumps(info, indent=1) + "\n")
