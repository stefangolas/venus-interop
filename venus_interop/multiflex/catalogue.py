"""Hamilton's Multiflex Carrier Assistant catalogue (MultiMFX.INI, v4.10) as data.

Parsed from the tool's installer by plr-viz3d-scratch/hamilton_library (see docs/MULTIFLEX_ASSEMBLY.md):
4 baseplates and 99 module entries. Values are Hamilton's, in mm, in the carrier frame Venus uses in a
.tml (X across, Y front to back, origin at the front-left-bottom corner).
"""
from __future__ import annotations

import dataclasses
import functools
import json
import pathlib
from typing import Optional

DATA = pathlib.Path(__file__).parent / "data" / "mfx_catalogue.json"


def _f(d: dict, k: str, default: float = 0.0) -> float:
  try:
    return float(d.get(k, default))
  except (TypeError, ValueError):
    return default


@dataclasses.dataclass(frozen=True)
class Baseplate:
  index: int  # 1..4, as the catalogue numbers them (Carrier1..Carrier4)
  name: str
  template: str  # Venus template name, e.g. MFX_CAR_L5_XXX_A00
  origin_x: float  # site X of position 1
  origin_y: float  # site Y of position 1 (the back position)
  pitch_y: float  # Y step to the next position (negative: towards the front)
  origin_3d: tuple[float, float, float]
  offset_3d_x: float
  has_bracket: bool
  fields: dict = dataclasses.field(compare=False, repr=False)

  @property
  def width(self) -> float:
    """Carrier width (Dim.Dx) of the assembled carrier, from the template family."""
    return {1: 135.0, 2: 135.0, 3: 157.5, 4: 112.5}[self.index]

  @property
  def positions(self) -> int:
    return {1: 5, 2: 4, 3: 4, 4: 3}[self.index]


@dataclasses.dataclass(frozen=True)
class Module:
  key: str  # catalogue entry, e.g. Modul17
  name: str
  abbr: str
  id_name: str  # what Venus puts in a site id: "<position>_<IdName>"
  base: float  # Z of the labware site
  width: float
  length: float
  offset_x: float  # OriginLOffsetX
  offset_y: float  # OriginPOffsetY
  part_no: str
  not_valid_for: tuple[int, ...]  # baseplate indexes this module may not go on
  add_module: Optional[str]  # companion entry placed on the same position (a second site)
  tip_rack: bool
  fields: dict = dataclasses.field(compare=False, repr=False)


class Catalogue:
  def __init__(self, data: Optional[dict] = None):
    data = data if data is not None else json.loads(DATA.read_text())
    self.baseplates: dict[int, Baseplate] = {}
    for key, v in data["carriers"].items():
      i = int(key.replace("Carrier", ""))
      self.baseplates[i] = Baseplate(
        i, v["Name"], v.get("Template", ""), _f(v, "OriginX"), _f(v, "OriginY"), _f(v, "OffsetY"),
        (_f(v, "Origin3DX"), _f(v, "Origin3DY"), _f(v, "Origin3DZ")), _f(v, "Offset3DX"), v.get("HasBracket") == "Y", v)
    self.modules: dict[str, Module] = {}
    for key, v in data["modules"].items():
      nv = tuple(int(x) for x in str(v.get("NotValidForCarrier", "")).replace(";", ",").split(",") if x.strip().isdigit())
      add = v.get("AddModul")
      self.modules[key] = Module(
        key, v.get("Name", "").split("=")[0].strip(), v.get("Abbr", ""), v.get("IdName", ""), _f(v, "Base"),
        _f(v, "Width"), _f(v, "Length"), _f(v, "OriginLOffsetX"), _f(v, "OriginPOffsetY"), v.get("PartNo", ""), nv,
        f"Modul{add}" if add else None,
        # a tip module's site has the tip rack's footprint. (The catalogue's own "TipRack=Y" flag is also
        # set on every heater-shaker nest, so it does not mean "tip module"; its meaning is unknown.)
        (_f(v, "Width"), _f(v, "Length")) == (122.4, 82.6), v)

  def by_id_name(self, id_name: str) -> list[Module]:
    """Catalogue entries with this IdName (several modules share one, e.g. 2 mm and 3 mm nests)."""
    low = id_name.lower()
    return [m for m in self.modules.values() if m.id_name.lower() == low]

  def baseplate_for_template(self, width: float, site_ys: list[float]) -> Optional[Baseplate]:
    """The baseplate a Venus-built carrier was assembled on, from its width and site Ys."""
    if width == 157.5:
      return self.baseplates[3]
    if width == 112.5:
      return self.baseplates[4]
    if width == 135:
      five = any(abs(y - 392.5) < 3 or abs(y - 394.2) < 3 for y in site_ys) or not site_ys
      return self.baseplates[1 if five else 2]
    return None


@functools.lru_cache(maxsize=1)
def catalogue() -> Catalogue:
  return Catalogue()
