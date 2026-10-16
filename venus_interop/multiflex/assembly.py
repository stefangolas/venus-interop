"""Multiflex assembly: baseplate + one module per position -> labware sites, and the check against
carriers Venus assembled (docs/MULTIFLEX_ASSEMBLY.md).

  X = B.OriginX + M.OriginLOffsetX
  Y = B.OriginY + (n - 1) * B.OffsetY + M.OriginPOffsetY       (n = 1 at the back)
  Z = M.Base
  (Dx, Dy) = (M.Width, M.Length)

A module's companion entry (AddModul) adds a second site on the same position at its own Base.
"""
from __future__ import annotations

import dataclasses
import re
from typing import Optional, Union

from venus_interop.multiflex.catalogue import Baseplate, Catalogue, Module, catalogue

TOL = 0.01  # mm


@dataclasses.dataclass(frozen=True)
class Site:
  id: str  # "<position>_<IdName>", as Venus names sites of assembled carriers
  position: int
  x: float
  y: float
  z: float
  dx: float
  dy: float
  module: Module


def site(baseplate: Baseplate, position: int, module: Module) -> Site:
  return Site(f"{position}_{module.id_name}", position, baseplate.origin_x + module.offset_x,
              baseplate.origin_y + (position - 1) * baseplate.pitch_y + module.offset_y, module.base,
              module.width, module.length, module)


def sites(baseplate: Union[int, Baseplate], modules: dict[int, Union[str, Module]],
          cat: Optional[Catalogue] = None) -> list[Site]:
  """Sites of an assembly. `modules`: position (1 = back) -> catalogue key ("Modul17") or Module."""
  cat = cat or catalogue()
  b = cat.baseplates[baseplate] if isinstance(baseplate, int) else baseplate
  out = []
  for position, m in sorted(modules.items()):
    module = cat.modules[m] if isinstance(m, str) else m
    if b.index in module.not_valid_for:
      raise ValueError(f"{module.name} is not valid on {b.name}")
    if not 1 <= position <= b.positions:
      raise ValueError(f"{b.name} has positions 1..{b.positions}")
    out.append(site(b, position, module))
    if module.add_module and module.add_module in cat.modules:
      out.append(site(b, position, cat.modules[module.add_module]))
  return out


@dataclasses.dataclass
class SiteCheck:
  site_id: str
  venus: tuple[float, float, float, float, float]
  rule: Optional[tuple[float, float, float, float, float]]
  module: Optional[str]
  error: Optional[float]  # largest |difference| over X, Y, Z, Dx, Dy

  @property
  def exact(self) -> bool:
    return self.error is not None and self.error <= TOL


def check(tml, cat: Optional[Catalogue] = None) -> tuple[Optional[Baseplate], list[SiteCheck]]:
  """Compare a Venus-built multiflex carrier (a definitions.Carrier) with the rule, site by site.

  Each site's module comes from its id (`<position>_<IdName>`); where several catalogue entries share
  the IdName, the closest is reported. Sites whose id names no module are listed with rule None."""
  cat = cat or catalogue()
  vsites = list(tml.sites.values())
  b = cat.baseplate_for_template(tml.dim[0], [s.y for s in vsites])
  out = []
  for s in sorted(vsites, key=lambda s: -s.y):
    venus = (s.x, s.y, s.z, s.dx, s.dy)
    if b is None:
      out.append(SiteCheck(s.id, venus, None, None, None))
      continue
    m = re.match(r"(\d+)_(.+)$", s.id)
    named = cat.by_id_name(m.group(2)) if m else []
    if m:
      position = int(m.group(1))
    else:  # no position in the id: the nearest position by Y
      position = min(range(1, b.positions + 1), key=lambda n: abs(b.origin_y + (n - 1) * b.pitch_y - s.y))
    if not 1 <= position <= b.positions or abs(b.origin_y + (position - 1) * b.pitch_y - s.y) > 30:
      out.append(SiteCheck(s.id, venus, None, "no baseplate position here", None))
      continue
    # a renamed site (e.g. "4_Trough") names no module: fit the closest catalogue module instead
    candidates, how = (named, "") if named else (
      [mm for mm in cat.modules.values() if b.index not in mm.not_valid_for], "fitted: ")
    best = None
    for module in candidates:
      r = site(b, position, module)
      pred = (r.x, r.y, r.z, r.dx, r.dy)
      err = max(abs(a - c) for a, c in zip(pred, venus))
      if best is None or err < best[0]:
        best = (err, pred, how + module.name)
    out.append(SiteCheck(s.id, venus, best and best[1], best and best[2], best and round(best[0], 3)))
  return b, out


def is_multiflex(tml) -> bool:
  return any(re.match(r"\d+_", s) for s in tml.sites)
