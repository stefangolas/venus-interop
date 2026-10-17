"""Hamilton's NGSStar framework, `NGSStarProcesses` (`NGSStar\\<kit>\\Library\\NGSStarProcesses.hsi`):
the pipetting and transport functions every NGS STAR kit method is built on. Ported so far:

  PIP_ReagentsFromTubeOrTroughOrPlateToPlate   (817 lines in Venus) a reagent into each position of
      the dispense sequence, a slice of channels at a time. The library writes the loop out once per
      tip type; here it is once, with what differs per tip type in TIP_SETTINGS. Per slice: the tip
      planner (STAR Tip Tools) and a pick-up, every slice or only the first; aspirate by cLLD
      (height 0) or from a fixed height above the bottom (liquid following above 1.8 mm); dispense
      by cLLD (height 0) or at a fixed height; tips out if exchanged; both sequences on by the
      channel count. Tips out at the end when not exchanged.

The tip type and dispense mode come from the liquid class in Venus's database (`liquid_classes`, a
VenusLiquidClasses; or a table of them). Dispense modes 2 and 4 ("part",
multi-dispense) take other functions, not ported yet. Not ported, by design: the report and status
lines, the volume plausibility dialog, the sequence check dialog, the tip scheduling for the loading
screen, the sample-tracking mapping file (STCC).
"""
from __future__ import annotations

import dataclasses
from typing import Optional

from venus_interop.methods import sequences as sq
from venus_interop.plr import steps
from venus_interop.plr.libraries.star_tip_tools import StarTipTools
from venus_interop.plr.steps import CoreGrip, Pipetting

from pylabrobot.hamilton.star.liquid_classes import mapping as star_classes

LIBRARY = "NGSSTARPROCESSES"  # the Venus namespace ported

SVFT, HVFT, LVFT = 1, 5, 23  # Venus tip types: 300 uL, 1000 uL, 50 uL filter tips


@dataclasses.dataclass(frozen=True)
class TipSettings:
  """What the library's cLLD step records set differently per tip type."""
  aspirate_submerge: float  # mm below the surface found
  dispense_clld: int  # cLLD sensitivity
  dispense_submerge: float


TIP_SETTINGS = {SVFT: TipSettings(0.5, 2, 0.5), HVFT: TipSettings(2.0, 1, 0.6), LVFT: TipSettings(0.5, 1, 0.5)}
LIQUID_FOLLOWING_ABOVE = 1.8  # mm: a fixed-height aspirate follows the liquid above this
MIX_POSITION = 1.0  # mm above the surface: the aspirate records' and the cLLD dispense records'

ISWAP, CORE_GRIPPER = 1, 2  # the framework's transport tools (t_intTransportTool)
# The CO-RE transports' records (_Trp_MIDIwithCOREGripper, _Trp_HSPwithCOREGripper): grip speed
# 277.8, z speed 128.7 getting; z speed 50, x acceleration 4 placing
MIDI_GRIP = CoreGrip(height=8, width=79, opening=87, force=9, z_speed=128.7, press=0.3, x_acceleration=4,
                     place_z_speed=50, check=1)
HSP_GRIP = CoreGrip(height=5, width=81.3, opening=86, force=8, z_speed=128.7, press=0.3, x_acceleration=4,
                    place_z_speed=50, check=0)
# Drops into the waste chutes and onto the stacker: the source and the destination shifted first, in
# mm (VIRTUALLABWARE::MoveSeq), and back after
SHIFTS = {
  "MIDI_Waste": ((-20, 0, 0), (-60, 0, 8)), "MIDI_Waste_CORE": ((-20, 0, 0), (-60, 0, 8)),
  "HSP_Waste": ((-20, 0, 0), (-60, 0, 0)), "HSP_Waste_CORE": ((-20, 0, 0), (-60, 0, 0)),
  "HSP_DFP_OnStacker": ((-35, 0, 0), (-35, 0, 0)),
}


class NGSStarProcesses:
  def __init__(self, star, deck, tips: dict[int, str], liquid_classes, channels: int = 8,
               planner: Optional[StarTipTools] = None, gripper=None, transport_tool: int = CORE_GRIPPER,
               front_channel: int = 7, say=print):
    """`tips`: tip type -> the tip sequence (the framework's t_seqTips300 / 1000 / 50).
    `liquid_classes`: a VenusLiquidClasses (the kit's database, read by tools/liquid_classes.py),
    or a table name -> (tip type, dispense mode) with PLR's STAR classes."""
    self.p, self.v, self.tips, self.classes = star.pipettes, deck, tips, liquid_classes
    self.channels = channels
    self.planner = planner or StarTipTools(deck, channels)
    self.missing_classes: set[str] = set()
    self.star, self.say = star, say
    self._gripper, self.transport_tool = gripper, transport_tool
    self.front_channel = front_channel  # t_intFrontChannelCORETransport: 1 = back ... 8 = front

  def _take(self, seq: str, pattern: str, counting: int, use: int) -> dict:
    taken = sq.take(self.v.seq(seq), pattern, counting, use)
    return {ch - 1: item for ch, item in taken.channels.items()}

  def _codes(self, name: str) -> tuple[int, int]:
    """The class's Venus tip type and dispense mode (_DATA_GetTipTypeAndDispenseModeOfLiquidClass)."""
    if isinstance(self.classes, dict):
      return self.classes[name]
    tip, mode = self.classes.tip_type(name), self.classes.dispense_mode(name)
    if tip is None:
      raise KeyError(f"liquid class {name!r} is not in the database")
    return tip, mode

  def _lc(self, name: str):
    lc = (getattr(star_classes, name, None) if isinstance(self.classes, dict) else self.classes.get(name))
    if lc is None:
      self.missing_classes.add(name)
    return lc

  async def PIP_ReagentsFromTubeOrTroughOrPlateToPlate(
      self, ML_STAR, aspiration: str, dispense: str, volume: float, liquid_class: str, mix_cycles: int,
      mix_volume_aspiration: float, mix_volume_dispense: float, aspirate_height: float,
      dispense_height: float, tip_exchange: bool, increment_aspiration: bool,
      liquid_following_at_fixed_dispense: bool):
    tip_type, dispense_mode = self._codes(liquid_class)
    if dispense_mode in (2, 4):
      raise NotImplementedError("dispense mode 'part' (multi-dispense) is not ported yet")
    tips, cfg, lc = self.tips[tip_type], TIP_SETTINGS[tip_type], self._lc(liquid_class)
    asp, disp, tip_seq = self.v.seq(aspiration), self.v.seq(dispense), self.v.seq(tips)
    pattern, loop, held = "", 0, []
    while disp.cur > 0:
      sq.align([(asp, 1), (disp, 1), (tip_seq, 1)])
      loop += 1
      if tip_exchange or loop == 1:
        pattern = self.planner.Optimized1mLTipPickup(ML_STAR, tips, dispense)
        spots = self._take(tips, pattern, sq.AUTOMATIC, sq.ALL_POSITIONS)
        held = sorted(spots)
        await self.p.pick_up_tips([self.v.resolve(spots[c]) for c in held], use_channels=held)
      mix_a = mix_cycles if mix_volume_aspiration else 0
      aspirate = (Pipetting(1, cfg.aspirate_submerge, liquid_following=True, mix_cycles=mix_a,
                            mix_volume=mix_volume_aspiration, mix_position=MIX_POSITION)
                  if aspirate_height == 0 else
                  Pipetting(0, fluid_height=aspirate_height, liquid_following=aspirate_height > LIQUID_FOLLOWING_ABOVE,
                            mix_cycles=mix_a, mix_volume=mix_volume_aspiration, mix_position=MIX_POSITION))
      mix_d = mix_cycles if mix_volume_dispense else 0
      dispense_step = (Pipetting(cfg.dispense_clld, cfg.dispense_submerge, liquid_following=True,
                                 mix_cycles=mix_d, mix_volume=mix_volume_dispense, mix_position=MIX_POSITION)
                       if dispense_height == 0 else
                       Pipetting(0, fluid_height=dispense_height,
                                 liquid_following=bool(liquid_following_at_fixed_dispense),
                                 mix_cycles=mix_d, mix_volume=mix_volume_dispense))
      wells = self._take(aspiration, pattern, sq.MANUAL, sq.CHANNEL_PATTERN)
      ch = sorted(wells)
      await steps.aspirate(self.p, [self.v.resolve(wells[c]) for c in ch], [volume] * len(ch), ch, aspirate, lc)
      wells = self._take(dispense, pattern, sq.MANUAL, sq.CHANNEL_PATTERN)
      ch = sorted(wells)
      await steps.dispense(self.p, [self.v.resolve(wells[c]) for c in ch], [volume] * len(ch), ch, dispense_step, lc)
      if tip_exchange:
        await self.p.discard_tips(use_channels=held)
      if increment_aspiration:
        asp.increment(self.channels)
      disp.increment(self.channels)
    for s in (asp, disp, tip_seq):
      s.set_max(s.total)
    asp.set_current_position(1)
    disp.set_current_position(1)
    if not tip_exchange and loop:
      await self.p.discard_tips(use_channels=held)

  # -- transports ------------------------------------------------------------------------------

  def _gripper_(self):
    if self._gripper is None:
      from venus_interop.plr.venus_deck import Gripper
      self._gripper = Gripper(self.star, self.v, self.say)
    return self._gripper

  async def _transport(self, source: str, destination: str, grip: CoreGrip, park: bool, barcode_track):
    from pylabrobot.resources import Coordinate

    from venus_interop.plr import steps

    if self.transport_tool != CORE_GRIPPER:
      raise NotImplementedError("the iSWAP transports are not ported yet (Avenio uses the CO-RE gripper)")
    src_lab, dst_lab = self.v.seq(source).current_item()[0], self.v.seq(destination).current_item()[0]
    if barcode_track and int(barcode_track) > 0:
      self.say(f"{src_lab}: barcode read at the autoload not modelled")
    pick_shift, drop_shift = SHIFTS.get(dst_lab, ((0, 0, 0), (0, 0, 0)))
    pick, drop = steps.core_grip_arguments(grip, Coordinate(*pick_shift), Coordinate(*drop_shift))
    plate = self.v.resource(src_lab)
    await self._gripper_().to_placeholder(plate, dst_lab, front_channel=self.front_channel - 1, eject=bool(park),
                                          grip=pick, release=drop)
    return "" if not barcode_track else "No barcode reading activated"

  async def Trp_MIDI(self, ML_STAR, source: str, destination: str, track_to_read_barcode=0, park_after_move=1,
                     read_barcode=None, grip_mode_iswap=4):
    """A MIDI plate by the CO-RE gripper: grip 8 mm below the top for a MIDI source (15 otherwise);
    force 6 on the barcode path; no plate check onto the heater-shakers HHS4/HHS5 or the waste,
    and no press onto HHS4/HHS5."""
    import dataclasses

    src_lab = self.v.seq(source).current_item()[0]
    dst_lab = self.v.seq(destination).current_item()[0]
    grip = dataclasses.replace(
      MIDI_GRIP, height=8 if "MIDI" in src_lab else 15,
      force=6 if track_to_read_barcode and int(track_to_read_barcode) > 0 else MIDI_GRIP.force,
      check=0 if dst_lab in ("HHS4_MIDI", "HHS5_MIDI", "MIDI_Waste", "MIDI_Waste_CORE") else 1,
      press=0 if dst_lab in ("HHS4_MIDI", "HHS5_MIDI") else MIDI_GRIP.press)
    return await self._transport(source, destination, grip, park_after_move, track_to_read_barcode)

  async def Trp_HSP(self, ML_STAR, source: str, destination: str, track_to_read_barcode=0, park_after_move=1,
                    read_barcode=None, grip_mode_iswap=4):
    """A hard-shell PCR plate by the CO-RE gripper; the plate check only onto `HSP_CPAC` (the kit's
    CPAC position is `HSP_onCPAC`, so in Avenio it stays off, as in Venus)."""
    import dataclasses

    dst_lab = self.v.seq(destination).current_item()[0]
    grip = dataclasses.replace(HSP_GRIP, check=1 if dst_lab == "HSP_CPAC" else 0)
    return await self._transport(source, destination, grip, park_after_move, track_to_read_barcode)
