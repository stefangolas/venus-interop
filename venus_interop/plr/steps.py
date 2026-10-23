"""Venus pipetting step settings, and how they become PyLabRobot STAR arguments: one place for every
port.

A Venus Aspirate or Dispense step's record (`.stp`) holds, per channel, what decides where the tip
goes: cLLD sensitivity (0: off), the submerge depth below the surface found, the fluid height above
the container bottom (with cLLD off), liquid following, and the mix. `Pipetting` keeps those; a port
builds one per step from the record's values, and the port tests build the same from the record as
the HSL interpreter binds it (`Pipetting.from_record`), so a port's settings are checked against
the record, not only its wells.

The mapping to PLR (`plr_arguments`):
  cLLD on    lld_mode capacitive, immersion depth = submerge, surface following = liquid following
  cLLD off   lld_mode OFF (given: PLR's default under surface following is capacitive),
             liquid height = fluid height, surface following = liquid following
  mix        a pre-mix (aspirate) or post-mix (dispense) of the cycles and volume, at the mix
             position above the surface (aspirate)
  aspirate mode  the firmware's aspiration type: 1 consecutive aspiration (no blow-out air drawn
             again: none given), 2 aspirate all (no error when the container holds less than
             asked); 0, 1, 2 read from the order the dialog help lists them (CONVENTIONS §11)
What PLR takes no argument for (the cLLD sensitivity level, Venus's dispense modes) stays in
`Pipetting` for the comparison, not in the call. Mix flow rate: the steps leave it to the liquid
class (its aspirate or dispense mix flow rate); MIX_FLOW where no class is known.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Any, Optional, Union

MIX_FLOW = 250.0  # uL/s

# Called with ("Aspirate" | "Dispense", channels, Pipetting), or ("CoreGrip", None, CoreGrip), for
# every step: how a port test sees the Venus settings a port meant, including those PLR takes no
# argument for (the cLLD level, the plate check)
OBSERVERS: list = []



def _per_channel(v) -> Union[float, tuple[float, ...]]:
  """A setting as the interpreter binds it (one value, or a list where the channels differ)."""
  if isinstance(v, (list, tuple)):
    return tuple(float(x or 0) for x in v)
  return float(v or 0)


def _volumes(v) -> list[float]:
  return list(v) if isinstance(v, tuple) else [v]


@dataclasses.dataclass(frozen=True)
class Pipetting:
  clld: int  # cLLD sensitivity, 0 = off
  submerge: float = 0.0  # mm below the surface found (cLLD on)
  fluid_height: float = 0.0  # mm above the bottom (cLLD off)
  liquid_following: bool = False
  mix_cycles: int = 0
  mix_volume: Union[float, tuple[float, ...]] = 0.0  # one per channel (in channel order) where they differ
  mix_position: float = 0.0  # mm above the surface (aspirate)
  aspirate_mode: int = 0  # 0 aspiration, 1 consecutive aspiration, 2 aspirate all
  # what the record says, sent only under PLR_VENUS_FAITHFUL_CFG (venus_heights); None: not in it
  pull_out: Optional[float] = None  # mm risen before the transport air (po)
  touch_off: Optional[float] = None  # mm above a Z touch (zo)

  @classmethod
  def from_record(cls, s: dict[str, Any]) -> "Pipetting":
    """From a step's settings as the HSL interpreter records them (names as stp_pars gives them)."""
    def optional(name):
      v = s.get(name)
      return None if v in (None, "") else float(v)
    return cls(clld=int(s.get("cLLD sensitivity", 0) or 0), submerge=float(s.get("submerge depth", 0) or 0),
               fluid_height=float(s.get("fluid height", 0) or 0),
               liquid_following=bool(int(s.get("LiquidFollowing", 0) or 0)),
               mix_cycles=int(s.get("mix cycles", 0) or 0), mix_volume=_per_channel(s.get("mix volume", 0)),
               mix_position=float(s.get("mix position", 0) or 0),
               aspirate_mode=int(s.get("aspirate mode", 0) or 0),
               pull_out=optional("pull-out distance"), touch_off=optional("touch-off position"))

  def effective(self) -> "Pipetting":
    """Only what takes effect: the submerge depth with cLLD on, the fluid height with it off, the
    mix's volume and position with cycles. Two steps that pipette alike compare equal."""
    mixing = self.mix_cycles > 0 and max(_volumes(self.mix_volume)) > 0
    return dataclasses.replace(
      self, submerge=self.submerge if self.clld else 0.0, fluid_height=0.0 if self.clld else self.fluid_height,
      mix_cycles=self.mix_cycles if mixing else 0, mix_volume=self.mix_volume if mixing else 0.0,
      mix_position=self.mix_position if mixing else 0.0)


def plr_arguments(step: Pipetting, n: int, aspirate: bool, mix_flow: Optional[float] = None) -> dict[str, Any]:
  """The STAR aspirate / dispense keyword arguments for `n` channels; a mix at `mix_flow` (the
  liquid class's mix flow rate), MIX_FLOW when not given."""
  from pylabrobot.hamilton.star.driver.lld_mode import LLDMode
  from pylabrobot.lib.liquid_handling.mix import Mix

  s = step.effective()
  out: dict[str, Any] = {"auto_surface_following": s.liquid_following}
  if s.clld:
    out.update(lld_mode=LLDMode.CAPACITIVE, immersion_depths=[s.submerge] * n)
  else:  # OFF given, not left to PLR: with surface following, its default is CAPACITIVE
    out.update(lld_mode=LLDMode.OFF, liquid_heights=[s.fluid_height] * n)
  if aspirate and s.aspirate_mode:
    out["aspiration_types"] = [s.aspirate_mode] * n
    if s.aspirate_mode == 1:
      out["blow_out_air_volumes"] = [0.0] * n
  if s.mix_cycles:
    flow = MIX_FLOW if mix_flow is None else mix_flow
    vols = _volumes(s.mix_volume)
    mixes = [Mix(volume=v, repetitions=s.mix_cycles, flow_rate=flow) for v in (vols if len(vols) == n else vols * n)]
    if aspirate:
      out.update(pre_mixes=mixes, mix_positions_from_liquid_surface=[s.mix_position] * n)
    else:
      out.update(post_mixes=mixes)
  return out


def venus_heights(pipettes, wells, step: Pipetting, extra: dict) -> dict[str, Any]:
  """Venus's heights for the wells, as the step's PLR arguments, when the pipettes carry a Venus
  profile (`faithful.apply`, PLR_VENUS_FAITHFUL_CFG); none otherwise. As Venus's firmware shows
  (docs/FIRMWARE_EQUIVALENCE.md section 2.4): the minimum height `zx` is the floor + the
  container's MaxDepth, the liquid height `zl` the step's fluid height above `zx`, and under cLLD
  the firmware's search starts at the floor + the container's LSHt (`lp`). A well without the
  imported MaxDepth keeps PLR's (the floor)."""
  if getattr(pipettes, "venus_profile", None) is None:
    return {}
  offsets = extra.get("resource_offsets") or [None] * len(wells)
  depths = [w.metadata.get("venus", {}).get("max_depth", 0.0) for w in wells]
  floors = [w.get_location_wrt(w.get_root(), "c", "c", "cavity_bottom").z + (o.z if o is not None else 0.0)
            for w, o in zip(wells, offsets)]
  minimum = [round(f + d, 2) for f, d in zip(floors, depths)]
  out: dict[str, Any] = {"minimum_allowed_z_positions_during": minimum}
  # zl from zx as sent (the driver's 0.1 mm, round(z * 10)), with LLD or without: Marionette's
  # dispenses at 0.3 mm read zx 181.0, zl 181.3 (from the unrounded zx it would be 181.4), its
  # aspirates under cLLD zl = zx + 5.0, the step's fluid height
  sent = [round(m * 10) / 10 for m in minimum]
  out["liquid_heights"] = [round(s + step.fluid_height - f, 4) for s, f in zip(sent, floors)]
  # lp = floor + LSHt, sent with LLD off too (Marionette's dispenses at 0.3 mm: 199.5); under cLLD
  # the firmware searches from it (faithful.apply turns firmware LLD on)
  searches = [w.metadata.get("venus", {}).get("lld_search_height") for w in wells]
  if all(s is not None for s in searches):
    out["lld_search_heights"] = [round(f + s, 2) for f, s in zip(floors, searches)]
  # no second section (zu, zr 0) in a one-segment container, as Venus sends it (Marionette's three
  # plates); PLR's default is a 3.2 mm cone. A container of several segments keeps PLR's: unmeasured
  if all(w.metadata.get("venus", {}).get("segments") == 1 for w in wells):
    out["second_section_heights"] = [0.0] * len(wells)
    out["second_section_ratios"] = [0.0] * len(wells)
  if step.pull_out is not None:
    out["pull_out_distances_transport_air"] = [step.pull_out] * len(wells)
  return {k: v for k, v in out.items() if extra.get(k) is None}


def _venus_extras(pipettes, n: int, step: Pipetting, aspirate: bool, liquid_class, extra: dict) -> dict:
  """What Venus sends beside the heights, under a Venus profile: the step's touch-off position
  (zo), and with no mix the class's mix flow rate (Venus's ms 500.0 where PLR sends 100.0 / 1.0)."""
  if getattr(pipettes, "venus_profile", None) is None:
    return {}
  out: dict[str, Any] = {}
  if step.touch_off is not None:
    out["aspirate_positions_above_z_touch_off" if aspirate else "dispense_positions_above_z_touch_off"] = \
      [step.touch_off] * n
  mixes = "pre_mixes" if aspirate else "post_mixes"
  flow = getattr(liquid_class, "aspiration_mix_flow_rate" if aspirate else "dispense_mix_flow_rate", None)
  if not step.effective().mix_cycles and flow is not None:
    from pylabrobot.lib.liquid_handling.mix import Mix
    out[mixes] = [Mix(volume=0.0, repetitions=0, flow_rate=flow)] * n
  return {k: v for k, v in out.items() if extra.get(k) is None}


async def aspirate(pipettes, wells, volumes, channels, step: Pipetting, liquid_class: Optional[Any] = None,
                   **extra):
  """A Venus Aspirate step on PLR: the wells per channel, the step's settings, the class if known."""
  for observe in OBSERVERS:
    observe("Aspirate", channels, step)
  kw = plr_arguments(step, len(channels), aspirate=True,
                     mix_flow=getattr(liquid_class, "aspiration_mix_flow_rate", None))
  if liquid_class is not None:
    kw["hamilton_liquid_classes"] = [liquid_class] * len(channels)
  kw.update(venus_heights(pipettes, wells, step, extra))
  kw.update(_venus_extras(pipettes, len(channels), step, True, liquid_class, extra))
  await pipettes.aspirate(wells, volumes, use_channels=channels, **kw, **extra)


async def dispense(pipettes, wells, volumes, channels, step: Pipetting, liquid_class: Optional[Any] = None,
                   **extra):
  for observe in OBSERVERS:
    observe("Dispense", channels, step)
  kw = plr_arguments(step, len(channels), aspirate=False,
                     mix_flow=getattr(liquid_class, "dispense_mix_flow_rate", None))
  if liquid_class is not None:
    kw["hamilton_liquid_classes"] = [liquid_class] * len(channels)
  kw.update(venus_heights(pipettes, wells, step, extra))
  kw.update(_venus_extras(pipettes, len(channels), step, False, liquid_class, extra))
  await pipettes.dispense(wells, volumes, use_channels=channels, **kw, **extra)


@dataclasses.dataclass(frozen=True)
class CoreGrip:
  """A Venus CO-RE gripper get (ZSwapGetPlate) and place (ZSwapPlacePlate): what decides the PLR
  call. Grip force and grip speed are kept for the comparison only: PLR's grip strength runs 0-99
  where Venus's grip force runs 0-9, and Venus's grip speed has no stated unit (CONVENTIONS §11)."""
  height: float  # GripperAccessHeight: mm below the top
  width: float  # grip width, mm across the jaws
  opening: float  # grip opening before access, mm
  force: int
  z_speed: float  # mm/s, getting
  press: float = 0.0  # plate press, mm, placing
  x_acceleration: int = 1
  place_z_speed: float = 75.0  # mm/s, placing
  check: int = 0  # plate check on place: no PLR counterpart


def core_grip_arguments(grip: CoreGrip, pick_offset=None, drop_offset=None) -> tuple[dict, dict]:
  """(pick_up_resource, drop_resource) keyword arguments for PLR's CO-RE gripper: the jaws stand
  (opening - width) / 2 off the plate as they come down; offsets in mm (a labware shifted first)."""
  from pylabrobot.resources import Coordinate

  for observe in OBSERVERS:
    observe("CoreGrip", None, grip)
  pick = dict(pickup_distance_from_top=grip.height, resource_size_y=grip.width,
              y_clearance=round((grip.opening - grip.width) / 2, 4), grip_strength=grip.force,
              z_speed=grip.z_speed, offset=pick_offset or Coordinate(0, 0, 0))
  drop = dict(offset=drop_offset or Coordinate(0, 0, 0), press_on_distance=grip.press,
              x_acceleration_level=grip.x_acceleration, z_speed=grip.place_z_speed)
  return pick, drop


@dataclasses.dataclass(frozen=True)
class IswapGrip:
  """A Venus iSWAP get (GetPlate): what decides the PLR plan. The side gripped and from where:
  the short side (jaws across the plate's width) from the right, the large side from the front,
  each from the opposite side when inverted (pyhamilton's transport table: its "right" PCR grip
  is the 82.5 mm short-side one). Orientation is kept for the comparison only."""
  height: float  # GripperAccessHeight: mm below the top
  width: float  # grip width, mm across the jaws
  opening: float  # grip opening, mm
  force: int  # 0-9, as PLR's iSWAP grip strength
  inverse: bool = False  # InversGripping
  large_side: bool = False  # GrippLargeSite
  orientation: int = 1  # LabwareOrientation

  @property
  def direction(self) -> str:
    return ("back" if self.inverse else "front") if self.large_side else ("left" if self.inverse else "right")


def iswap_grip_arguments(grip: IswapGrip) -> dict:
  """The iSWAP pick-up plan's keyword arguments (iSWAPTransport.plan_pick_up)."""
  for observe in OBSERVERS:
    observe("IswapGrip", None, grip)
  return dict(pickup_distance_from_top=grip.height, width=grip.width,
              open_margin=round(grip.opening - grip.width, 4), grip_strength=grip.force)


# Venus's tip eject to the default waste (the deck's waste2.rck, MlStarIsSpecialEject), as its
# firmware shows it (probed in simulation, docs/FIRMWARE_EQUIVALENCE.md section 2.11): channel n
# goes to the n-th of as many points as the instrument has channels, spread evenly from the waste's
# first position to its last, whichever channels eject; the tips are let go from 10 mm above the
# waste's container bottom down to it (PLACE_SHIFT), travelling at 245 mm
WASTE_EJECT = "venus_waste_eject"


def waste_eject_geometry(first, last, bottom: float) -> dict:
  """What `eject_to_waste` needs, kept on the deck's trash: the waste's first and last positions
  (x, y) and its container bottom (z, including the container's BaseMM)."""
  return {"x": first[0], "first_y": first[1], "last_y": last[1], "bottom": bottom}


async def eject_to_waste(pipettes, use_channels: list[int]) -> None:
  """Eject the channels' tips into the default waste as Venus does; PLR's own `discard_tips` where
  the deck's trash carries no Venus waste geometry."""
  from pylabrobot.resources import Coordinate
  from pylabrobot.resources.hamilton.tip_creators import TipDropMethod

  deck = getattr(getattr(pipettes, "_driver", None), "deck", None)
  g = deck.get_trash_area().metadata.get(WASTE_EJECT) if deck is not None else None
  if g is None:
    await pipettes.discard_tips(use_channels=use_channels)
    return
  n = pipettes.num_channels
  step = (g["last_y"] - g["first_y"]) / (n - 1)
  # each point cut to 0.1 mm, not rounded, as Venus sends them (Marionette: 297.857 -> 297.8, 271.07
  # -> 271.0, 244.29 -> 244.2, 217.5 kept)
  ys = [math.floor((g["first_y"] + ch * step) * 10 + 1e-6) / 10 for ch in use_channels]
  await pipettes.drop_tips([Coordinate(g["x"], y, g["bottom"]) for y in ys],
                           use_channels=use_channels, drop_method=TipDropMethod.PLACE_SHIFT,
                           begin_tip_deposit_process=g["bottom"] + 10.0, end_tip_deposit_process=g["bottom"],
                           minimum_traverse_height_start=245.0, minimum_traverse_height_end=245.0)
