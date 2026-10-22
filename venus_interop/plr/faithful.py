"""Venus-faithful defaults for a PLR STAR: where a port leaves a setting to the driver, use the value
Venus would take from its instrument configuration, so the firmware matches Venus's
(docs/FIRMWARE_EQUIVALENCE.md section 2.10).

One switch, the environment variable PLR_VENUS_FAITHFUL_CFG:
  unset or empty   PLR's own defaults (nothing changes)
  stock            Venus's stock values (STOCK, from an unedited ML_STAR.cfg)
  <path>           the values in that instrument .cfg (Config\\ML_STAR.cfg, ML_Starlet.cfg, ...)

`apply(star)` after `star.setup()` puts the profile on the device. A height a port passes is
always kept; only what it leaves as None is filled. Covered so far: traverse heights (channels, tip
pick-up and eject, the CO-RE gripper, the 96-head). Venus-faithful LLD is to join this profile,
under the same variable.
"""
from __future__ import annotations

import dataclasses
import functools
import os
import pathlib
from typing import Optional

ENV = "PLR_VENUS_FAITHFUL_CFG"

# CommandEdit keys of an unedited ML_STAR.cfg (Venus 4, the file dated 2017-03-14)
STOCK = {"TraverseHeight": 245.0, "Head96TraverseHeight": 245.0, "ZSwapTraverseHeight": 275.0}


@dataclasses.dataclass(frozen=True)
class VenusProfile:
  traverse_height: float  # TraverseHeight: the channels, tip pick-up and eject
  head96_traverse_height: float  # Head96TraverseHeight
  core_gripper_traverse_height: float  # ZSwapTraverseHeight: the CO-RE gripper holding a plate (ZSwapGetPlate)
  source: str  # "stock" or the .cfg it was read from

  @classmethod
  def from_values(cls, values: dict, source: str) -> "VenusProfile":
    v = {**STOCK, **{k: float(x) for k, x in values.items() if k in STOCK}}
    return cls(v["TraverseHeight"], v["Head96TraverseHeight"], v["ZSwapTraverseHeight"], source)

  @classmethod
  def stock(cls) -> "VenusProfile":
    return cls.from_values({}, "stock")

  @classmethod
  def from_cfg(cls, path) -> "VenusProfile":
    """From an instrument .cfg's CommandEdit section; a key the file lacks takes the stock value."""
    from venus_interop.files import hxcfg

    cfg = hxcfg.read(pathlib.Path(path))
    values = {}
    for s in cfg.sections:
      if s.type == "CommandEdit":
        values.update(dict(s.entries or []))
    return cls.from_values(values, str(path))


def profile() -> Optional[VenusProfile]:
  """The profile PLR_VENUS_FAITHFUL_CFG asks for, or None when it is unset."""
  value = os.environ.get(ENV, "").strip()
  if not value:
    return None
  if value.lower() == "stock":
    return VenusProfile.stock()
  path = pathlib.Path(value)
  if not path.is_file():
    raise FileNotFoundError(f"{ENV}={value}: no such instrument .cfg (or use 'stock')")
  return VenusProfile.from_cfg(path)


def _fill(method, **defaults):
  """`method` with the given keyword arguments filled where the caller gave None or nothing."""
  @functools.wraps(method)
  async def wrapper(*args, **kwargs):
    for k, v in defaults.items():
      if kwargs.get(k) is None:
        kwargs[k] = v
    return await method(*args, **kwargs)
  wrapper.venus_faithful = True
  return wrapper


def _at_height(owner, method, height: float):
  """`method` run with `owner.default_minimum_traverse_height` at `height` (for commands whose
  height comes only from that default)."""
  @functools.wraps(method)
  async def wrapper(*args, **kwargs):
    before = owner.default_minimum_traverse_height
    owner.default_minimum_traverse_height = height
    try:
      return await method(*args, **kwargs)
    finally:
      owner.default_minimum_traverse_height = before
  wrapper.venus_faithful = True
  return wrapper


def apply(star, p: Optional[VenusProfile] = None) -> Optional[VenusProfile]:
  """Put a profile (the given one, else the environment's) on a set-up STARDevice. Returns what
  was applied, None for nothing."""
  p = p or profile()
  if p is None:
    return None
  pip = star.pipettes
  if pip is not None:
    pip.default_minimum_traverse_height = p.traverse_height
    # tip commands travel as high as the tips allow when given no height; Venus travels at its own
    if not getattr(pip.pick_up_tips, "venus_faithful", False):
      pip.pick_up_tips = _fill(pip.pick_up_tips, minimum_traverse_height_start=p.traverse_height)
      pip.drop_tips = _fill(pip.drop_tips, minimum_traverse_height_start=p.traverse_height,
                            minimum_traverse_height_end=p.traverse_height)  # discard_tips goes through it
  grippers = star.core_grippers
  if grippers is not None:
    # gripping and placing (C0ZP/ZR) travel at ZSwapTraverseHeight; taking and returning the tools
    # (C0ZT/ZS) is a channel move and travels at TraverseHeight (Marionette's firmware: 275 / 245)
    grippers.default_minimum_traverse_height = p.core_gripper_traverse_height
    if not getattr(grippers.pick_up_tools_at_location, "venus_faithful", False):
      grippers.pick_up_tools_at_location = _at_height(grippers, grippers.pick_up_tools_at_location, p.traverse_height)
      grippers.drop_tools = _at_height(grippers, grippers.drop_tools, p.traverse_height)
  if star.head96 is not None:
    star.head96.configuration = dataclasses.replace(star.head96.configuration,
                                                    traversal_z_position=p.head96_traverse_height)
  return p
