"""Venus labware definitions (.rck racks, .tml carriers, .lid lids, .ctr containers) and where to find them."""
from __future__ import annotations

import dataclasses
import os
import pathlib
import re
from typing import Iterable, Mapping, Optional, Union

from venus_interop.files import hxcfg

PathLike = Union[str, pathlib.Path]
DEFAULT_VENUS_LABWARE = pathlib.Path(r"C:\Program Files (x86)\HAMILTON\Labware")


def normalize(rel: str) -> str:
  """'ML_STAR\\PLT_CAR_L5AC_A00.tml' or an absolute path under ...\\Labware\\ -> 'ml_star/plt_car_l5ac_a00.tml'."""
  p = rel.replace("\\", "/").lower()
  i = p.rfind("/labware/")
  return p[i + len("/labware/"):] if i >= 0 else p.lstrip("/")


@dataclasses.dataclass
class Definition:
  path: str  # normalized relative path
  type: str  # RECTRACK, TEMPLATE, COVER, CONTAINER, ...
  fields: dict[str, str]
  source: Optional[pathlib.Path] = dataclasses.field(default=None, compare=False, repr=False)  # file it came from

  def num(self, key: str, default: float = 0.0) -> float:
    v = self.fields.get(key)
    return float(v) if v not in (None, "") else default

  def int(self, key: str, default: int = 0) -> int:
    return int(self.num(key, default))

  @property
  def dim(self) -> tuple[float, float, float]:
    return self.num("Dim.Dx"), self.num("Dim.Dy"), self.num("Dim.Dz")


@dataclasses.dataclass
class Rack(Definition):
  """A .rck: plate, tip rack, trough or tool holder. Positions are defined relative to the corner."""

  @property
  def rows(self) -> int:
    return self.int("Rows")

  @property
  def columns(self) -> int:
    return self.int("Columns")

  @property
  def dx(self) -> float:
    return self.num("Dx")

  @property
  def dy(self) -> float:
    return self.num("Dy")

  @property
  def boundary(self) -> tuple[float, float]:
    """BndryX, BndryY: the front-left position's centre, from the rack's front-left corner."""
    return self.num("BndryX"), self.num("BndryY")

  @property
  def stack_height(self) -> float:
    return self.num("StackHt")

  @property
  def positions(self) -> list[tuple[float, float]]:
    """Positions listed one by one (`1.X`, `1.Y` ... up to HoleCnt), as offsets from the first
    position's centre (BndryX, BndryY); empty for a grid rack. In the corpus only racks without
    Rows/Columns list them (10: a trough, verification sites, CO-RE grip tools), the first at 0, 0,
    and every list sits centred in its rack's footprint (CONVENTIONS.md section 5)."""
    out = []
    for i in range(1, self.hole_count + 1):
      if f"{i}.X" not in self.fields:
        return []
      out.append((self.num(f"{i}.X"), self.num(f"{i}.Y")))
    return out

  @property
  def hole_count(self) -> int:
    return self.int("HoleCnt") or (self.rows * self.columns) or 1

  @property
  def index_mode(self) -> str:
    """IX.Index: '1' names positions A1, B1, ...; anything else numbers them."""
    return self.fields.get("IX.Index", "")

  @property
  def properties(self) -> dict[str, str]:
    """Property.N / PropertyValue.N pairs (MlStarTipRack, MlStarCore96TipRack, ...)."""
    return {v: self.fields.get("PropertyValue." + k.split(".", 1)[1], "")
            for k, v in self.fields.items() if re.fullmatch(r"Property\.\d+", k)}

  @property
  def is_tip_rack(self) -> bool:
    """Tip racks carry an MlStar*TipRack property (DataType 2 is common to most racks)."""
    return any((k.startswith("MlStar") and k.endswith("TipRack")) or k == "PlrTipFilter" for k in self.properties)


@dataclasses.dataclass
class Site:
  id: str
  x: float
  y: float
  z: float
  dx: float
  dy: float


@dataclasses.dataclass
class Carrier(Definition):
  """A .tml: carrier or other template with named sites, relative to its own origin."""

  @property
  def sites(self) -> dict[str, Site]:
    out = {}
    for k, v in self.fields.items():
      m = re.fullmatch(r"Site\.(\d+)\.Id", k)
      if m:
        g = lambda f, n=m.group(1): self.num(f"Site.{n}.{f}")
        out[v] = Site(v, g("X"), g("Y"), g("Z"), g("Dx"), g("Dy"))
    return out


@dataclasses.dataclass
class Lid(Definition):
  @property
  def rack_base_to_cover_base(self) -> float:
    return self.num("RackBaseToCoverBase")


_CLASSES = {"RECTRACK": Rack, "TEMPLATE": Carrier, "COVER": Lid}


def load(path: PathLike, rel: Optional[str] = None) -> Definition:
  cfg = hxcfg.read(path)
  sec = next(s for s in cfg.sections if not s.is_list and s.type not in ("HxPars",))
  cls = _CLASSES.get(sec.type, Definition)
  return cls(rel or normalize(str(path)), sec.type, sec.as_dict(), pathlib.Path(path))


class DefinitionStore:
  """Resolves `Labware.N.File` values to definitions.

  Looks in `index` (normalized relative path -> file) first, then under each root, matching
  case-insensitively the way Windows does.
  """

  def __init__(self, roots: Iterable[PathLike] = (), index: Optional[Mapping[str, PathLike]] = None,
               by_name: bool = False):
    self.roots = [pathlib.Path(r) for r in roots]
    self.index = {normalize(k): pathlib.Path(v) for k, v in (index or {}).items()}
    self._cache: dict[str, Optional[Definition]] = {}
    self._walked: dict[pathlib.Path, dict[str, pathlib.Path]] = {}
    self.missing: set[str] = set()
    self.by_name_fallback = by_name
    self.resolved_by_name: dict[str, pathlib.Path] = {}  # references found only by file name

  @classmethod
  def default(cls) -> DefinitionStore:
    return cls([DEFAULT_VENUS_LABWARE] if DEFAULT_VENUS_LABWARE.is_dir() else [])

  def _walk(self, root: pathlib.Path) -> dict[str, pathlib.Path]:
    if root not in self._walked:
      found = {}
      for dirpath, _, files in os.walk(root):
        for f in files:
          p = pathlib.Path(dirpath, f)
          found[p.relative_to(root).as_posix().lower()] = p
      self._walked[root] = found
    return self._walked[root]

  def find(self, rel: str) -> Optional[pathlib.Path]:
    key = normalize(rel)
    if key in self.index:
      return self.index[key]
    for root in self.roots:
      p = self._walk(root).get(key)
      if p is not None:
        return p
    return None

  def add(self, rel: str, definition: Definition) -> None:
    """Register a definition directly (tests, or definitions built in code)."""
    self._cache[normalize(rel)] = definition

  def get(self, rel: str) -> Optional[Definition]:
    key = normalize(rel)
    if key not in self._cache:
      path = self.find(key)
      if path is None and self.by_name_fallback:
        # layouts often name the author's folders; kits ship the file elsewhere under the same name
        path = self.find_by_name(key)
        if path is not None:
          self.resolved_by_name[key] = path
      try:
        self._cache[key] = load(path, key) if path else None
      except (hxcfg.FormatError, StopIteration, OSError):
        self._cache[key] = None
      if self._cache[key] is None:
        self.missing.add(key)
    return self._cache[key]

  def find_by_name(self, name: str) -> Optional[pathlib.Path]:
    """A file with this name in the index, else under the roots in their order (first root wins)."""
    name = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
    hits = sorted(str(v) for k, v in self.index.items() if k.rsplit("/", 1)[-1] == name)
    for root in self.roots:
      if hits:
        break
      hits = sorted(str(v) for k, v in self._walk(root).items() if k.rsplit("/", 1)[-1] == name)
    return pathlib.Path(hits[0]) if hits else None

  def ref(self, d: Definition, key: str) -> Optional[Definition]:
    """Follow a reference inside a definition, e.g. a rack's `Cntr.1.file`, the way Venus does:
    the Labware-relative path, then its `<key>Rel` twin relative to the referring file, then the
    file name anywhere. The Labware-relative copy is sometimes a stale absolute path."""
    value, twin = d.fields.get(key, ""), d.fields.get(key + "Rel", "")
    if not value and not twin:
      return None
    if value:
      found = self.get(value)  # also finds definitions registered with add()
      if found is not None:
        return found
    candidates = []
    if twin and d.source is not None:
      candidates.append(d.source.parent / twin.replace("\\", "/"))
    candidates.append(self.find_by_name(value or twin))
    for path in candidates:
      if path is not None and path.exists():
        key_norm = normalize(value or twin)
        try:
          self._cache[key_norm] = load(path, key_norm)
        except (hxcfg.FormatError, StopIteration, OSError):
          continue
        self.missing.discard(key_norm)
        return self._cache[key_norm]
    if value:
      self.missing.add(normalize(value))
    return None

  def rack(self, rel: str) -> Optional[Rack]:
    d = self.get(rel)
    return d if isinstance(d, Rack) else None

  def carrier(self, rel: str) -> Optional[Carrier]:
    d = self.get(rel)
    return d if isinstance(d, Carrier) else None

  def lid(self, rel: str) -> Optional[Lid]:
    d = self.get(rel)
    return d if isinstance(d, Lid) else None
