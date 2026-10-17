"""Venus liquid classes as PyLabRobot ones, by their Venus names.

`tools/liquid_classes.py` reads a Venus liquid-class database (`Config\\ML_STARLiquids.mdb`, a
method's or an install's) into JSON; `VenusLiquidClasses.from_json` loads it. A port asks for a
class by the name its step records give (`get`), and for the Venus codes a library decides by
(`tip_type`, `dispense_mode`: NGSStar picks its tip sequence and its dispense path by them). A name
the database lacks falls back to PLR's own STAR table, which holds Hamilton's stock classes.
"""
from __future__ import annotations

import json
import pathlib
from typing import Optional


class VenusLiquidClasses:
  def __init__(self, classes: list[dict]):
    self.by_name = {c["name"]: c for c in classes}
    self.missing: set[str] = set()

  @classmethod
  def from_json(cls, path: pathlib.Path) -> "VenusLiquidClasses":
    return cls(json.loads(pathlib.Path(path).read_text(encoding="utf-8")))

  def get(self, name: str):
    """The PLR HamiltonLiquidClass, from the database, else PLR's STAR table; None (and the name
    in `missing`) when neither has it."""
    c = self.by_name.get(name)
    if c is not None:
      from pylabrobot.hamilton.liquid_classes.base import HamiltonLiquidClass
      return HamiltonLiquidClass(curve={a: b for a, b in c["curve"]}, **c["parameters"])
    from pylabrobot.hamilton.star.liquid_classes import mapping
    lc = getattr(mapping, name, None)
    if lc is None:
      self.missing.add(name)
    return lc

  def tip_type(self, name: str) -> Optional[int]:
    c = self.by_name.get(name)
    return None if c is None else int(c["tip_type"])

  def dispense_mode(self, name: str) -> Optional[int]:
    c = self.by_name.get(name)
    return None if c is None else int(c["dispense_mode"])
