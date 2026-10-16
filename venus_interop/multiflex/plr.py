"""A pylabrobot MFXCarrier from the multiflex catalogue: a generic configurator.

Every site becomes a holder at the catalogue's site. Plate sites take an SBS plate (127.76 x 85.48)
centred on the 127 x 86 site, as Venus does (CONVENTIONS.md 3b); tip sites take a rack at their corner.
This complements, and does not replace, hand-written factories with real module geometry (heater
shakers, CPAC, ODTC): it knows where labware goes, not what the modules look like.
"""
from __future__ import annotations

from typing import Optional, Union

from pylabrobot.resources import Coordinate, MFXCarrier, PlateHolder, ResourceHolder

from venus_interop.multiflex.assembly import sites
from venus_interop.multiflex.catalogue import Baseplate, Catalogue, Module, catalogue

SBS = (127.76, 85.48)
BASEPLATE_HEIGHT = 18.0  # Origin3DZ of every baseplate: where modules stand


def mfx_carrier(name: str, baseplate: Union[int, Baseplate], modules: dict[int, Union[str, Module]],
                cat: Optional[Catalogue] = None) -> MFXCarrier:
  """`modules`: position (1 = back) -> catalogue key or Module. PLR site index 0 is the front."""
  cat = cat or catalogue()
  b = cat.baseplates[baseplate] if isinstance(baseplate, int) else baseplate
  holders = {}
  ordered = sorted(sites(b, modules, cat), key=lambda s: (s.y, s.z))  # PLR: index 0 at the front
  for i, s in enumerate(ordered):
    meta = {"venus": {"site_id": s.id, "module": s.module.key, "part_no": s.module.part_no}}
    if s.module.tip_rack:
      h = ResourceHolder(f"{name}_{s.id}", s.dx, s.dy, 0, metadata=meta)
    else:
      h = PlateHolder(f"{name}_{s.id}", s.dx, s.dy, 0, pedestal_size_z=0,
                      child_location=Coordinate((s.dx - SBS[0]) / 2, (s.dy - SBS[1]) / 2, 0), metadata=meta)
    h.location = Coordinate(s.x, s.y, s.z)
    holders[i] = h
  return MFXCarrier(name, b.width, 497.0, BASEPLATE_HEIGHT, sites=holders, model=b.template)
