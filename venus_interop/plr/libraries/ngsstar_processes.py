"""Hamilton's NGSStar framework, `NGSStarProcesses` (`NGSStar\\<kit>\\Library\\NGSStarProcesses.hsi`):
the pipetting and transport functions every NGS STAR kit method is built on. Ported so far:

  PIP_ReagentsFromTubeOrTroughOrPlateToPlate   (817 lines in Venus) a reagent into each position of
      the dispense sequence, a slice of channels at a time. The library writes the loop out once per
      tip type; here it is once, with what differs per tip type in TIP_SETTINGS. Per slice: the tip
      planner (STAR Tip Tools) and a pick-up, every slice or only the first; aspirate by cLLD
      (height 0) or from a fixed height above the bottom (liquid following above 1.8 mm); dispense
      by cLLD (height 0) or at a fixed height; tips out if exchanged; both sequences on by the
      channel count. Tips out at the end when not exchanged.

  PIP_MixOnly   (1,000 lines) a reagent's containers mixed in place, the mix volume measured with
      a liquid search (PLR's probe_liquid_volumes for Venus's 0 uL cLLD aspirate and
      HSLML_STAR::MeasureContainerVolume2) and shared among the channels in a trough.

Repaired, where the library is evidently wrong and Venus would hang, lose work or stop the run
(`faithful=True` keeps the library's behaviour; the differential tests use it): PIP_MixOnly's
containers folded onto one labware, and its 300 uL copy looping without end (both in its
docstring); STAR Tip Tools' planner asking for tips with tips left (star_tip_tools).

The tip type and dispense mode come from the liquid class in Venus's database (`liquid_classes`, a
VenusLiquidClasses; or a table of them). Dispense modes 2 and 4 ("part",
multi-dispense) take other functions, not ported yet. Not ported yet, and in scope: the run report
lines and the sample-tracking mapping file each transfer writes (STCC; the port test answers its
calls with no-ops for now). Not ported, by design: the status lines, the volume plausibility dialog,
the sequence check dialog, the tip scheduling for the loading screen.
"""
from __future__ import annotations

import dataclasses
from typing import Optional

from venus_interop.methods import sequences as sq
from venus_interop.plr import steps
from venus_interop.plr.libraries.star_tip_tools import StarTipTools
from venus_interop.plr.steps import CoreGrip, IswapGrip, Pipetting

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
# PIP_MixOnly, per tip type: the most a channel mixes, and what a negative mix volume becomes, in uL
MIX_ONLY_MAX = {SVFT: 270.0, HVFT: 900.0, LVFT: 45.0}
MIX_ONLY_FLOOR = {SVFT: 15.0, HVFT: 50.0, LVFT: 10.0}
MIX_ONLY_SHARE = 0.75  # of the volume measured in the container, mixed

ISWAP, CORE_GRIPPER = 1, 2  # the framework's transport tools (t_intTransportTool)
# The CO-RE transports' records (_Trp_MIDIwithCOREGripper, _Trp_HSPwithCOREGripper): grip speed
# 277.8, z speed 128.7 getting; z speed 50, x acceleration 4 placing
MIDI_GRIP = CoreGrip(height=8, width=79, opening=87, force=9, z_speed=128.7, press=0.3, x_acceleration=4,
                     place_z_speed=50, check=1)
HSP_GRIP = CoreGrip(height=5, width=81.3, opening=86, force=8, z_speed=128.7, press=0.3, x_acceleration=4,
                    place_z_speed=50, check=0)
# Trp_HSPFromAndToODTCwithiSWAP's GetPlate records: the short side, 5 mm below the top
ODTC_GRIP = IswapGrip(height=5, width=82.2, opening=85, force=5)
# The elbow stops tried, in order (Venus leaves it to the arm): the right first, as the KAPA demo
# found on the same deck (the others sweep the arm over the 96-head waste behind the ODTC)
ODTC_ELBOWS = ("right", None, "front", "left")
# Trp_HamiltonComfortLid's records: by the iSWAP (GetPlate, MovePlate, OpenGripper) or the CO-RE gripper
LID_GRIP = IswapGrip(height=5, width=85.3, opening=89, force=2)
LID_CORE_GRIP = CoreGrip(height=5, width=85.3, opening=88, force=8, z_speed=128.7, press=0, x_acceleration=4,
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
               front_channel: int = 7, say=print, tip_counters: Optional[dict[int, str]] = None,
               time_scale: float = 0.0, sleep=None, clock=None, iswap=None, clinical_starlet: bool = False,
               faithful: bool = False):
    """`tips`: tip type -> the tip sequence (the framework's t_seqTips300 / 1000 / 50).
    `liquid_classes`: a VenusLiquidClasses (the kit's database, read by tools/liquid_classes.py),
    or a table name -> (tip type, dispense mode) with PLR's STAR classes. `faithful`: keep the
    library's defects the port repairs (the module docstring lists them), as the differential
    tests compare with the HSL."""
    self.p, self.v, self.tips, self.classes = star.pipettes, deck, tips, liquid_classes
    self.channels, self.faithful = channels, faithful
    self.planner = planner or StarTipTools(deck, channels, faithful=faithful)
    self.missing_classes: set[str] = set()
    self.star, self.say = star, say
    self._gripper, self.transport_tool = gripper, transport_tool
    self._iswap = iswap  # an iSWAPTransport; made from the STAR's iSWAP when first needed
    self.clinical_starlet = clinical_starlet  # t_blnClinicalNGSStarlet
    self.front_channel = front_channel  # t_intFrontChannelCORETransport: 1 = back ... 8 = front
    # tip type -> the framework's tip counter name (t_strTipCounterNameTip50 / 300 / 1000)
    self.tip_counters = tip_counters or {}
    import asyncio
    import time
    self.time_scale, self.sleep = time_scale, sleep or asyncio.sleep
    self.clock = clock or time.monotonic
    self._timers: dict[str, float] = {}

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

  def _wells(self, items):
    return [self.v.resolve(it) for it in items]

  async def _pick_up(self, ML_STAR, tips: str, control, width: int) -> list[int]:
    """Tips for a pass `width` positions wide: on the channels and from the tips STAR Tip Tools'
    planner chooses, no more than the pass takes (Venus's AlignSequences caps the tip sequence)."""
    pattern = self.planner.Optimized1mLTipPickup(ML_STAR, tips, control)
    self.v.seq(tips).set_max(width)
    spots = self._take(tips, pattern, sq.AUTOMATIC, sq.ALL_POSITIONS)
    held = sorted(spots)
    await self.p.pick_up_tips(self._wells(spots[c] for c in held), use_channels=held)
    return held

  async def PIP_ReagentsFromTubeOrTroughOrPlateToPlate(
      self, ML_STAR, aspiration: str, dispense: str, volume: float, liquid_class: str, mix_cycles: int,
      mix_volume_aspiration: float, mix_volume_dispense: float, aspirate_height: float,
      dispense_height: float, tip_exchange: bool, increment_aspiration: bool,
      liquid_following_at_fixed_dispense: bool):
    tip_type, dispense_mode = self._codes(liquid_class)
    if dispense_mode in (2, 4):
      raise NotImplementedError("dispense mode 'part' (multi-dispense) is not ported yet")
    tips, cfg, lc = self.tips[tip_type], TIP_SETTINGS[tip_type], self._lc(liquid_class)
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
    held = []
    for targets, sources in sq.batches(self.channels, self.v.seq(dispense), self.v.seq(aspiration),
                                       advance=(bool(increment_aspiration),)):
      if tip_exchange or not held:
        held = await self._pick_up(ML_STAR, tips, dispense, len(targets))
      ch = list(range(len(targets)))
      await steps.aspirate(self.p, self._wells(sources), [volume] * len(ch), ch, aspirate, lc)
      await steps.dispense(self.p, self._wells(targets), [volume] * len(ch), ch, dispense_step, lc)
      if tip_exchange:
        await self.p.discard_tips(use_channels=held)
    self.v.seq(tips).set_max(self.v.seq(tips).total)
    if held and not tip_exchange:
      await self.p.discard_tips(use_channels=held)

  async def PIP_Supernatant_SVFTSingleDispenseFromPlateToLiquidWaste(self, ML_STAR, aspiration, dispense,
                                                                      volume: float, liquid_class: str):
    """The supernatant of each position of `aspiration` into `dispense` (the liquid waste), with
    300 uL tips, new ones each slice: a draw by cLLD (0.5 mm under the surface, following it) that
    doesn't fail on less liquid ("aspirate all"), then a consecutive 50 uL from 0.7 mm above the
    bottom, then the tips drained in jet mode at 15 mm. The first draw is the volume less 50 uL;
    within 20 uL of the tip's 300 it is 250, so the two take 300 whatever the volume asked (kept
    as the library has it)."""
    tip_type, dispense_mode = self._codes(liquid_class)
    if dispense_mode in (2, 4):  # Venus: an error dialog, then abort
      raise RuntimeError(f"{liquid_class}: unsupported dispense mode (part volume) for supernatant removal")
    if tip_type != SVFT:  # Venus: an error dialog, then abort
      raise RuntimeError(f"{liquid_class}: unsupported tip type {tip_type} for supernatant removal (300 uL only)")
    # left out: _DATA_PlausibilityCheckVolume (an operator dialog on a volume too large for the tip),
    # _DATA_ScheduleTips (the tips shown on the loading screen), and around the loop
    # HSLML_STAR::AspirationMonitoring_1000ulChannel_Off / _On (no PLR counterpart)
    first, second = (250.0, 50.0) if 300 - volume < 20 else (volume - 50.0, 50.0)
    draw_all = Pipetting(1, 0.5, liquid_following=True, aspirate_mode=2)
    off_bottom = Pipetting(0, fluid_height=0.7, aspirate_mode=1)
    drain = Pipetting(0, fluid_height=15.0)
    tips, lc = self.tips[SVFT], self._lc(liquid_class)
    for wells, waste in sq.batches(self.channels, self.v.seq(aspiration), self.v.seq(dispense)):
      held = await self._pick_up(ML_STAR, tips, aspiration, len(wells))
      ch = list(range(len(wells)))
      for step, v in ((draw_all, first), (off_bottom, second)):
        await steps.aspirate(self.p, self._wells(wells), [v] * len(ch), ch, step, lc)
      await steps.dispense(self.p, self._wells(waste), [first + second] * len(ch), ch, drain, lc)
      await self.p.discard_tips(use_channels=held)
      self.DATA_TipCounterWrite(ML_STAR)
    self.v.seq(tips).set_max(self.v.seq(tips).total)
    # left out of the port so far, and in scope: the run report line ("Remove supernatant ...") and
    # the sample-tracking mapping file (SupernatantToWaste_<LabID>_<BC>_<No>)

  async def PIP_MixOnly(self, ML_STAR, aspiration, aspirate_height: float, liquid_class: str, mix_cycles: int,
                        mix_volume: float):
    """Mix each container of `aspiration` in place, its distinct containers a channel slice at a
    time, with one set of tips. At height 0 (cLLD) the mix volume is measured: channel 1 finds the
    liquid in the slice's first container, and each channel mixes 75 % of what it holds (a trough,
    the first container's labware id with "RGT", shared among the channels; at most one per
    container, up to all of them), up to the tip type's most; `mix_volume` is not used. At a fixed
    height above the bottom, `mix_volume` (up to the most), following the liquid above 1.8 mm. A
    mix is an aspirate of 0 uL with the mix cycles, 1 mm under the surface or at the height.

    Two of the library's defects are repaired (`faithful` keeps them):
      - it takes the distinct position ids and puts them all on the sequence's last labware (ten
        troughs at position 1 become one mix); it builds the distinct labware ids alongside and
        never uses them. Here: the distinct (labware, position) pairs.
      - its 300 uL copy (one per tip type) mixes inside the first pass's block, so past one slice
        it loops without end; the 1000 and 50 uL copies mix on every pass. Here: every pass.
        Faithful, more containers than channels with 300 uL tips is an error."""
    tip_type, _ = self._codes(liquid_class)
    tips, lc = self.tips[tip_type], self._lc(liquid_class)
    seq = self.v.seq(aspiration)
    items = seq.items[:seq.end]
    if not items:
      return
    if self.faithful:
      containers = [(items[-1][0], pos) for pos in dict.fromkeys(pos for _, pos in items)]
    else:
      containers = list(dict.fromkeys(tuple(it) for it in items))
    mix = sq.Sequence("l_seqAspirationMixOnly", containers)
    lab = containers[0][0]
    if self.faithful and tip_type == SVFT and len(containers) > self.channels:
      raise RuntimeError(f"{aspiration}: {len(containers)} positions to mix with 300 uL tips; the library mixes "
                         f"the first {self.channels} and loops without end on the rest")
    pattern = self.CREATE_CHANNEL_PATTERN(1, len(containers), 8)
    # left out: the run report line ("Mix reagents ...", in scope, not ported yet); _DATA_ScheduleTips
    # (the tips shown on the loading screen); _DATA_PlausibilityCheckVolume (an operator dialog on a
    # mix volume too large for the tip, asked only when `mix_volume` > 0)
    trough = "RGT" in lab
    active = min(len(containers), self.channels)
    held = []
    for (wells,) in sq.batches(self.channels, mix):
      if not held:
        held = await self._pick_up2(ML_STAR, tips, self.tip_counters.get(tip_type, ""), pattern, len(wells))
      ch = list(range(len(wells)))
      if aspirate_height == 0:
        (measured,) = await self.p.probe_liquid_volumes([self.v.resolve(wells[0])], use_channels=[0])
        per = measured * MIX_ONLY_SHARE / (active if trough else 1)
        per = min(per, MIX_ONLY_MAX[tip_type])
        # left out: the OptimizeFollowSpeed step ("Tip Tracking Speed": liquid following 1.5x as
        # fast on the channels' next step, the mix; PLR takes following distances, not a speed:
        # CONVENTIONS §11); and
        # Venus's simulation-mode values (12 mL measured, 200 uL mixed, 20 with 50 uL tips)
        per = MIX_ONLY_FLOOR[tip_type] if per < 0 else per
        step = Pipetting(1, 1.0, liquid_following=True, mix_cycles=mix_cycles, mix_volume=per,
                         mix_position=MIX_POSITION)
      else:
        per = min(mix_volume, MIX_ONLY_MAX[tip_type])
        step = Pipetting(0, fluid_height=aspirate_height, liquid_following=aspirate_height > LIQUID_FOLLOWING_ABOVE,
                         mix_cycles=mix_cycles, mix_volume=per, mix_position=MIX_POSITION)
      await steps.aspirate(self.p, self._wells(wells), [0.0] * len(ch), ch, step, lc)
    self.v.seq(tips).set_max(self.v.seq(tips).total)
    await self.p.discard_tips(use_channels=held)
    self.DATA_TipCounterWrite(ML_STAR)

  @staticmethod
  def CREATE_CHANNEL_PATTERN(first: int, count: int, channels: int) -> str:
    """Create_Channel_Pattern: `count` channels on from channel `first`, of `channels`. Its source
    is on no machine here; read from its name and its one use (1, positions, 8): taken as settled
    (user, 2026-10-19)."""
    return ("0" * (first - 1) + "1" * count + "0" * channels)[:channels]

  async def _pick_up2(self, ML_STAR, tips: str, counter: str, pattern: str, width: int) -> list[int]:
    """Tips on the channels of `pattern`, from the tips STAR Tip Tools' planner chooses for it
    (Optimized1mLTipPickup2), no more than the pass takes."""
    self.planner.Optimized1mLTipPickup2(ML_STAR, tips, counter, pattern)
    self.v.seq(tips).set_max(width)
    spots = self._take(tips, pattern, sq.AUTOMATIC, sq.ALL_POSITIONS)
    held = sorted(spots)
    await self.p.pick_up_tips(self._wells(spots[c] for c in held), use_channels=held)
    return held

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

  async def Trp_HSPFromAndToODTCwithiSWAP(self, ML_STAR, source, destination, track_to_read_barcode=0,
                                          park_after_move=0, read_barcode=None):
    """A hard-shell PCR plate into or out of the ODTC by the iSWAP: the short side, 5 mm below the
    top (from the left instead, inverted, on a Clinical NGS STARlet unless it comes from the ODTC);
    then the arm parked, or only its Z homed (`R0ZI`: up to the top of its travel here)."""
    import dataclasses

    src_lab = self.v.seq(source).current_item()[0]
    dst_lab = self.v.seq(destination).current_item()[0]
    grip = dataclasses.replace(ODTC_GRIP, inverse=self.clinical_starlet and src_lab != "HSP_ODTC")
    if track_to_read_barcode and int(track_to_read_barcode) > 0:
      self.say(f"{src_lab}: barcode read at the autoload not modelled")
    await self._by_iswap(src_lab, dst_lab, grip, park_after_move)
    # left out of the port so far, and in scope: the run report line ("Transport plate using iSWAP ...")
    return "" if track_to_read_barcode and int(track_to_read_barcode) > 0 else "No barcode reading activated"

  async def Trp_HamiltonComfortLid(self, ML_STAR, source, destination, park_after_move=0,
                                   reachable_with_core_gripper=0):
    """A Hamilton ComfortLid moved: by the CO-RE gripper when the destination is reachable with it
    (the flag compared with TRUE: Avenio's call passing 4 takes the iSWAP, as in Venus), else by the
    iSWAP, the short side 5 mm below the top at force 2, let go by opening to 95 mm over the lid
    waste, 89 elsewhere."""
    # left out: _DATA_ScheduleConsumables (the lids shown on the loading screen)
    src_lab = self.v.seq(source).current_item()[0]
    dst_lab = self.v.seq(destination).current_item()[0]
    lid = self.v.resource(src_lab)
    if int(reachable_with_core_gripper) == 1:
      pick, drop = steps.core_grip_arguments(LID_CORE_GRIP)
      await self._gripper_().to_placeholder(lid, dst_lab, front_channel=self.front_channel - 1,
                                            eject=bool(park_after_move), grip=pick, release=drop)
    else:
      opening = 95 if dst_lab == "Ham_ComfortLid_Waste" else 89
      await self._by_iswap(src_lab, dst_lab, LID_GRIP, park_after_move,
                           release=dict(open_margin=round(opening - LID_GRIP.width, 4)))
    # left out of the port so far, and in scope: the run report line

  async def _by_iswap(self, src_lab: str, dst_lab: str, grip: IswapGrip, park, release=None):
    """The labware at `src_lab` to `dst_lab` by the iSWAP; then the arm parked, or only its Z homed
    (Venus's `R0ZI`: up to the top of its travel here)."""
    if self._iswap is None:
      from pylabrobot.hamilton.star.driver.features.iswap_transport import iSWAPTransport
      self._iswap = iSWAPTransport(self.star.iswap)
    await self._gripper_().to_placeholder(self.v.resource(src_lab), dst_lab, iswap=self._iswap,
                                          direction=grip.direction, elbows=ODTC_ELBOWS,
                                          grip=steps.iswap_grip_arguments(grip), release=release)
    if park:
      await self.star.iswap.park(traverse_height=280.0)
    else:
      await self.star.iswap.elbow_move_to_safe_z_height()

  # -- sequences ------------------------------------------------------------------------------

  def DATA_CreateNewSequencesOrTransportSequences(self, template, position_ids, sequence_type: int,
                                                  name: str = "created") -> sq.Sequence:
    """1: the positions `position_ids` on the template's current labware (to pipette); 2: each
    labware of the template once, at A1 (to transport). From position 1."""
    t = self.v.seq(template)
    if int(sequence_type) == 1:
      lab = (t.current_item() or ("", ""))[0]
      return sq.Sequence(name, [(lab, str(p)) for p in position_ids])
    if int(sequence_type) == 2:
      return sq.Sequence(name, [(lab, "A1") for lab in dict.fromkeys(lab for lab, _ in t.items)])
    return sq.Sequence(name, [])

  # -- incubation timers -----------------------------------------------------------------------

  async def DATA_IncubationTimer(self, timer: str, seconds: float, mode: int):
    """1: start and wait; 2: start only; 3: wait for a timer started before (what is left of it).
    Venus skips the timers in simulation mode: `time_scale` 0 does the same; 1 is real time."""
    import math

    seconds = math.floor(seconds)
    now = self.clock()
    if int(mode) == 1:
      await self.sleep(seconds * self.time_scale)
    elif int(mode) == 2:
      self._timers[timer] = now + seconds
    elif int(mode) == 3:
      left = self._timers.pop(timer, now) - now
      await self.sleep(max(0.0, left) * self.time_scale)

  # -- tip counters ----------------------------------------------------------------------------

  def DATA_TipCounterWrite(self, ML_STAR=None):
    """Each tip sequence (50, 300, 1000 uL) into its counter (STAR_TIP_TOOLS::TipCounter_Write)."""
    for tip_type, counter in self.tip_counters.items():
      self.planner.TipCounter_Write(ML_STAR, self.tips[tip_type], counter)

  def DATA_TipCounterRead(self, ML_STAR=None, required_50=0, required_300=0, required_1000=0, tip_types=4):
    """The tip sequences of `tip_types` (1: 50, 2: 300, 3: 1000 uL, 4: all) from their counters.
    Too few tips for what is required is Venus's reload dialog: here an error naming the shortfall."""
    which = {1: [LVFT], 2: [SVFT], 3: [HVFT]}.get(int(tip_types), [LVFT, SVFT, HVFT])
    need = {LVFT: required_50, SVFT: required_300, HVFT: required_1000}
    for tip_type in which:
      if tip_type not in self.tips or tip_type not in self.tip_counters:
        continue
      have = self.planner.TipCounter_Read(ML_STAR, self.tips[tip_type], self.tip_counters[tip_type])
      if have < int(need[tip_type]):
        raise RuntimeError(f"{self.tips[tip_type]}: {have} tips for {need[tip_type]} required "
                           "(Venus asks the operator to reload)")
