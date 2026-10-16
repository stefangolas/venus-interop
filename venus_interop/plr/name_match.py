"""Find the PyLabRobot resource that is the same physical labware as a Venus definition.

Both sides are reduced to one fingerprint, independent of class: the pipetting positions (well,
tip or site centres) relative to the footprint centre, the footprint, and the height. Venus draws
most plates on a nominal 127 x 86 footprint where PLR uses the true 127.76 x 85.48, so positions are
compared from the centre, not the corner.
"""
from __future__ import annotations

import dataclasses
import importlib
import inspect
import logging
import math
import os
import re
from typing import Callable, Optional

from pylabrobot.resources import Carrier, Container, ItemizedResource, Resource, TipRack

from venus_interop.files.definitions import Carrier as CarrierDef
from venus_interop.files.definitions import Definition, Rack
from venus_interop.plr.plr_import import _container_size, build_carrier, build_rack

POSITION_TOL = 0.75  # mm, RMS over all positions
FOOTPRINT_TOL = 1.5  # mm, per axis
HEIGHT_TOL = 2.0  # mm


# Hamilton tip type id (a rack's MlStarTipRack / MlStarXLTipRack property) -> (volume uL, filter)
TIP_TYPES = {0: (300, False), 1: (300, True), 2: (10, False), 3: (10, True), 4: (1000, False),
             5: (1000, True), 22: (50, False), 23: (50, True), 25: (5000, False), 29: (4000, True),
             36: (300, False), 45: (300, True), 35: (250, False), 44: (150, True)}


@dataclasses.dataclass
class Fingerprint:
  kind: str  # tips | wells | sites | single
  size: tuple[float, float, float]
  positions: list[tuple[float, float]]  # centres relative to the footprint centre, sorted
  item: Optional[tuple[float, float, float]] = None  # well (size x, size y, depth)
  tip: Optional[tuple[float, bool, float]] = None  # (volume uL, filter, length mm): nominal for Venus, capacity for PLR

  @property
  def count(self) -> int:
    return len(self.positions)


def fingerprint(r: Resource) -> Fingerprint:
  sx, sy, sz = r.get_size_x(), r.get_size_y(), r.get_size_z()
  cx, cy = sx / 2, sy / 2
  if isinstance(r, Carrier):
    kind, items = "sites", list(r.sites.values())
  elif isinstance(r, ItemizedResource):
    kind, items = ("tips" if isinstance(r, TipRack) else "wells"), r.get_all_items()
  else:
    return Fingerprint("single", (sx, sy, sz), [(0.0, 0.0)])
  pos = []
  for it in items:
    c = it.location + it.get_anchor(x="c", y="c")
    pos.append((round(c.x - cx, 3), round(c.y - cy, 3)))
  fp = Fingerprint(kind, (sx, sy, sz), sorted(pos))
  if kind == "wells" and items:
    w = items[0]
    fp.item = (w.get_size_x(), w.get_size_y(), w.get_size_z())
  if kind == "tips" and items:
    try:
      t = items[0].make_tip()
      fp.tip = (t.maximal_volume, t.has_filter, getattr(t, "total_tip_length", None) or t.get_size_z())
    except Exception:  # noqa: BLE001 - some PLR tip creators raise (4/5 mL)
      pass
  return fp


def venus_fingerprint(d: Definition, store) -> Optional[Fingerprint]:
  logging.disable(logging.WARNING)
  try:
    if isinstance(d, Rack):
      r = build_rack("x", d, store)
      if d.fields.get("ConnectedCtr") == "1":  # one liquid: a trough drawn as a grid of positions
        return Fingerprint("single", (r.get_size_x(), r.get_size_y(), r.get_size_z()), [(0.0, 0.0)])
      fp = fingerprint(r)
      if fp.kind == "tips":
        code = d.properties.get("MlStarTipRack") or d.properties.get("MlStarXLTipRack")
        kind = TIP_TYPES.get(int(code)) if code not in (None, "") else None
        fp.tip = (*kind, _container_size(d, store)[2]) if kind else None
      return fp
    if isinstance(d, CarrierDef):
      return fingerprint(build_carrier("x", d))
  except Exception:  # noqa: BLE001 - a definition PLR can't represent has no fingerprint
    return None
  finally:
    logging.disable(logging.NOTSET)
  return None


# ---------------------------------------------------------------------------------------- PLR side


@dataclasses.dataclass
class Candidate:
  factory: str  # module.function
  cls: str
  fp: Fingerprint
  doc: str


def plr_catalogue() -> list[Candidate]:
  """Every pylabrobot resource factory that builds from a name alone."""
  import pylabrobot.resources as R

  root = os.path.dirname(R.__file__)
  out = []
  logging.disable(logging.WARNING)
  for dirpath, _, files in os.walk(root):
    for f in files:
      if not f.endswith(".py") or f.endswith("_tests.py") or f == "__init__.py":
        continue
      modname = "pylabrobot.resources." + os.path.relpath(os.path.join(dirpath, f[:-3]), root).replace(os.sep, ".")
      try:
        mod = importlib.import_module(modname)
      except BaseException:  # noqa: BLE001 - deprecated modules raise on import
        continue
      for fname, fn in inspect.getmembers(mod, inspect.isfunction):
        if fn.__module__ != modname or fname.startswith("_"):
          continue
        try:
          required = [p for p in inspect.signature(fn).parameters.values() if p.default is p.empty]
        except (TypeError, ValueError):
          continue
        if len(required) != 1 or required[0].name != "name":
          continue
        try:
          r = fn(name="x")
        except BaseException:  # noqa: BLE001 - deprecated aliases raise
          continue
        if isinstance(r, (ItemizedResource, Carrier, Container)) and not type(r).__name__.startswith("Tecan"):
          out.append(Candidate(f"{modname}.{fname}", type(r).__name__, fingerprint(r), inspect.getdoc(fn) or ""))
  logging.disable(logging.NOTSET)
  return out


# ---------------------------------------------------------------------------------------- scoring


@dataclasses.dataclass
class Match:
  candidate: Candidate
  position_rms: float
  footprint: float  # max per-axis difference
  height: float
  name_score: float
  content_ok: bool = True  # same tip (volume, filter) or same well (size, depth) within tolerance

  @property
  def verdict(self) -> str:
    if (self.position_rms <= POSITION_TOL and self.footprint <= FOOTPRINT_TOL and self.height <= HEIGHT_TOL
        and self.content_ok):
      return "match"
    if self.position_rms <= POSITION_TOL:
      return "same layout, different body"
    return "weak"


def _tokens(s: str) -> set[str]:
  s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
  return {t for t in re.split(r"[^a-z0-9]+", s.lower()) if t and t not in {"a00", "l", "rck", "tml", "x"}}


def name_similarity(venus_path: str, c: Candidate) -> float:
  venus_path = venus_path.replace(chr(92), "/")
  v = _tokens(venus_path.rsplit("/", 1)[-1].rsplit(".", 1)[0])
  stem = venus_path.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
  if re.search(rf"hamilton name:\s*'?{re.escape(stem)}'?", c.doc.lower()):
    return 1.0
  p = _tokens(c.factory.rsplit(".", 1)[-1])
  return len(v & p) / len(v | p) if v and p else 0.0


def _rms(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> float:
  return math.sqrt(sum((x1 - x2) ** 2 + (y1 - y2) ** 2 for (x1, y1), (x2, y2) in zip(a, b)) / len(a))


def compatible(venus: Fingerprint, plr: Fingerprint) -> bool:
  if venus.count != plr.count:
    return False
  # tips match tips; wells, sites and single containers may match each other (a Venus tube rack
  # is a PLR tube carrier, a magnet .rck is a plate on an adapter)
  return (venus.kind == "tips") == (plr.kind == "tips")


WELL_SIZE_TOL = 1.0  # mm
WELL_DEPTH_TOL = 2.0  # mm


def _content_ok(venus: Fingerprint, plr: Fingerprint) -> bool:
  if venus.kind == "tips":
    if venus.tip is None or plr.tip is None:
      return False
    (nominal, filt, length), (capacity, plr_filt, plr_length) = venus.tip, plr.tip
    return filt == plr_filt and nominal <= capacity <= 1.35 * nominal and abs(length - plr_length) <= 1.5
  if venus.item is not None and plr.item is not None:
    return (abs(venus.item[0] - plr.item[0]) <= WELL_SIZE_TOL and abs(venus.item[1] - plr.item[1]) <= WELL_SIZE_TOL
            and abs(venus.item[2] - plr.item[2]) <= WELL_DEPTH_TOL)
  return True


def best_matches(path: str, venus: Fingerprint, catalogue: list[Candidate], n: int = 3) -> list[Match]:
  out = []
  for c in catalogue:
    if not compatible(venus, c.fp):
      continue
    out.append(Match(
      c,
      _rms(venus.positions, c.fp.positions),
      max(abs(a - b) for a, b in zip(venus.size[:2], c.fp.size[:2])),
      abs(venus.size[2] - c.fp.size[2]),
      name_similarity(path, c),
      _content_ok(venus, c.fp),
    ))
  out.sort(key=lambda m: (m.verdict != "match", m.verdict != "same layout, different body",
                          -m.name_score, m.position_rms + m.footprint / 4 + m.height / 4))
  return out[:n]


def alias_target(rel, fp, matches, plr):
  """A PLR factory that is provably this labware, with the reason, or None.

  A unique geometric match is not enough (the Nalgene 300 mL trough fits an Axygen trough plate);
  one of these must also hold: the tip type is identical, the PLR function has the Venus file's name,
  or its docstring names the Hamilton file.
  """
  stem = rel.replace(chr(92), "/").rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
  for m in matches:
    if m.candidate.factory.rsplit(".", 1)[-1].lower() == stem:
      return m.candidate.factory, "same name"
  for m in matches:
    if m.name_score >= 1.0:
      return m.candidate.factory, "docstring names the Hamilton file"
  if fp is not None and fp.kind == "tips" and len(plr) == 1:
    return next(iter(plr)), "same rack geometry and tip type"
  return None
