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
from typing import Any, Optional

MIX_FLOW = 250.0  # uL/s

# Called with ("Aspirate" | "Dispense", channels, Pipetting), or ("CoreGrip", None, CoreGrip), for
# every step: how a port test sees the Venus settings a port meant, including those PLR takes no
# argument for (the cLLD level, the plate check)
OBSERVERS: list = []


@dataclasses.dataclass(frozen=True)
class Pipetting:
  clld: int  # cLLD sensitivity, 0 = off
  submerge: float = 0.0  # mm below the surface found (cLLD on)
  fluid_height: float = 0.0  # mm above the bottom (cLLD off)
  liquid_following: bool = False
  mix_cycles: int = 0
  mix_volume: float = 0.0
  mix_position: float = 0.0  # mm above the surface (aspirate)
  aspirate_mode: int = 0  # 0 aspiration, 1 consecutive aspiration, 2 aspirate all

  @classmethod
  def from_record(cls, s: dict[str, Any]) -> "Pipetting":
    """From a step's settings as the HSL interpreter records them (names as stp_pars gives them)."""
    return cls(clld=int(s.get("cLLD sensitivity", 0) or 0), submerge=float(s.get("submerge depth", 0) or 0),
               fluid_height=float(s.get("fluid height", 0) or 0),
               liquid_following=bool(int(s.get("LiquidFollowing", 0) or 0)),
               mix_cycles=int(s.get("mix cycles", 0) or 0), mix_volume=float(s.get("mix volume", 0) or 0),
               mix_position=float(s.get("mix position", 0) or 0),
               aspirate_mode=int(s.get("aspirate mode", 0) or 0))

  def effective(self) -> "Pipetting":
    """Only what takes effect: the submerge depth with cLLD on, the fluid height with it off, the
    mix's volume and position with cycles. Two steps that pipette alike compare equal."""
    mixing = self.mix_cycles > 0 and self.mix_volume > 0
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
    mix = Mix(volume=s.mix_volume, repetitions=s.mix_cycles, flow_rate=MIX_FLOW if mix_flow is None else mix_flow)
    if aspirate:
      out.update(pre_mixes=[mix] * n, mix_positions_from_liquid_surface=[s.mix_position] * n)
    else:
      out.update(post_mixes=[mix] * n)
  return out


async def aspirate(pipettes, wells, volumes, channels, step: Pipetting, liquid_class: Optional[Any] = None,
                   **extra):
  """A Venus Aspirate step on PLR: the wells per channel, the step's settings, the class if known."""
  for observe in OBSERVERS:
    observe("Aspirate", channels, step)
  kw = plr_arguments(step, len(channels), aspirate=True,
                     mix_flow=getattr(liquid_class, "aspiration_mix_flow_rate", None))
  if liquid_class is not None:
    kw["hamilton_liquid_classes"] = [liquid_class] * len(channels)
  await pipettes.aspirate(wells, volumes, use_channels=channels, **kw, **extra)


async def dispense(pipettes, wells, volumes, channels, step: Pipetting, liquid_class: Optional[Any] = None,
                   **extra):
  for observe in OBSERVERS:
    observe("Dispense", channels, step)
  kw = plr_arguments(step, len(channels), aspirate=False,
                     mix_flow=getattr(liquid_class, "dispense_mix_flow_rate", None))
  if liquid_class is not None:
    kw["hamilton_liquid_classes"] = [liquid_class] * len(channels)
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
