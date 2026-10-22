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

  The bead clean-ups: Process_CleanUp, Customized_Process_CleanUp_ElutionBufferInPlate,
      _AvenioCGP_1xEthanol and _2BeadAdditions (about 1,500 lines). Each is the same three parts
      (`_bind`, `_washes`, a tail of transports and shakes) of functions ported above: beads mixed
      and added, shaken on the heater shaker (the NGSStarPrep port's HHS_Shake), incubated, the
      plate on the magnet; per batch of columns the supernatant off, one or two ethanol washes, air
      drying, the resuspension; back to the shaker and onto the magnet again.

Repaired, where the library is evidently wrong and Venus would hang, lose work or stop the run
(`faithful=True` keeps the library's behaviour; the differential tests use it): PIP_MixOnly's
containers folded onto one labware, and its 300 uL copy looping without end (both in its
docstring); the clean-ups' batches without scale-up (_DATA_CalculateAndDefineBatchProcessCleanUp); the multi-dispense from a trough stopping on a column part full
(_PIP_MultidispenseFromTroughToPlate); STAR Tip Tools' planner asking for tips with tips left
(star_tip_tools).

The tip type and dispense mode come from the liquid class in Venus's database (`liquid_classes`, a
VenusLiquidClasses; or a table of them). Dispense modes 2 and 4 ("part", multi-dispense) go to
_PIP_MultidispenseFromTroughToPlate from a trough or a plate and to
_PIP_MultidispenseBeadsFromTubesToPlate from tubes (both ported, one loop). Not ported yet, and in scope: the run
report lines and the sample-tracking mapping file each transfer writes (STCC; the port test answers its
calls with no-ops for now). Not ported, by design: the status lines, the volume plausibility dialog,
the sequence check dialog, the tip scheduling for the loading screen.
"""
from __future__ import annotations

import dataclasses
import pathlib
from typing import Optional

from venus_interop.methods import sequences as sq
from venus_interop.plr import steps
from venus_interop.plr.libraries.ngsstar_report import CORE_OK, ISWAP_OK, RunReport, number_text, trimmed_volume
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
MIX_ONLY_SIMULATED = {SVFT: 200.0, HVFT: 200.0, LVFT: 20.0}  # the mix volume in simulation mode
MIX_ONLY_SHARE = 0.75  # of the volume measured in the container, mixed
# _PIP_MultidispenseFromTroughToPlate, per tip type: CalcAliquot_v2_1's pre-dispense, reserve and tip
# capacity (uL); the pre-dispense goes back into the trough first, the reserve with the drain after
ALIQUOT = {HVFT: (50.0, 50.0, 1000.0), SVFT: (10.0, 10.0, 300.0), LVFT: (5.0, 5.0, 50.0)}
# _PIP_MultidispenseBeadsFromTubesToPlate's: its 1000 uL copy keeps the 20 uL in the tips (its
# pre-dispense and drain switched off)
ALIQUOT_BEADS = {**ALIQUOT, HVFT: (20.0, 0.0, 1000.0)}
TROUGH_MARGIN = 1000.0  # uL: what a trough must hold beyond a pass's aspirates
INSUFFICIENT = "Insufficient liquid for current reagent detected. "
REFILL = {  # the refill dialog's lower text; the 50 uL copy's has the operator unload the carrier
  None: "Refill 1st available reagent trough and press OK to continue. Selectng Cancel will lead to an inacurate "
        "liquid transfer. Timeout of 600 seconds will be interpreted as selecting  CANCEL as well.",
  LVFT: "Open the front cover manually, unload the carrier, refill 1st available reagent trough - reload the carrier, "
        "close the front coverand and press OK to continue. Selectng Cancel will lead to an inacurate liquid transfer. "
        "Timeout of 600 seconds will be interpreted as selecting  CANCEL as well."}



@dataclasses.dataclass(frozen=True)
class Aliquots:
  """One pass of a multi-dispense, as ALIQUOT_FOR_EASYSTEPS_V2::CalcAliquot_v2_1 returns it."""
  loops: int  # dispense rounds
  aspirate: list[float]  # per channel (0: the channel takes no part)
  mix: list[float]
  dispense_patterns: list[str]  # per round
  aspirate_pattern: str


def CalcAliquot_v2_1(remaining: int, volume: float, pre: float, reserve: float, capacity: float, channels: int,
                     rows: int = 8) -> Aliquots:
  """ALIQUOT_FOR_EASYSTEPS_V2::CalcAliquot_v2_1(dispense sequence, volume, pre, reserve, capacity,
  &loops, channels, rows, &aspirate[], &mix[], &patterns[], &pattern). Its source is on no machine
  here (`Aliquot\\Aliquot_for_EasySteps v2.hs_`): read from its arguments and from how the library
  uses what it returns (an inference; the user was told, 2026-10-19). The dispense sequence's
  positions from the current one (`remaining`) go a column (`rows` positions, no more than the
  channels) per round, channel i on the column's i-th, for as many rounds as are left and as the
  tip holds: floor((capacity - pre - reserve) / volume). A channel aspirates its dispenses' volume
  plus the pre-dispense and the reserve. The mix volume is a guess (nothing the library does
  constrains it): the channel's aspirate volume."""
  import math

  width = min(channels, rows)
  per_tip = math.floor((capacity - pre - reserve) / volume) if volume > 0 else 0
  if per_tip < 1:
    raise ValueError(f"{volume} uL: not one dispense fits a {capacity:g} uL tip with {pre:g} + {reserve:g} uL")
  loops = min(math.ceil(remaining / width), per_tip)
  counts = [0] * channels
  patterns = []
  for k in range(loops):
    on = [k * width + i < remaining for i in range(width)] + [False] * (channels - width)
    patterns.append("".join("1" if c else "0" for c in on))
    counts = [n + c for n, c in zip(counts, on)]
  aspirate = [n * volume + pre + reserve if n else 0.0 for n in counts]
  return Aliquots(loops, aspirate, list(aspirate), patterns, "".join("1" if n else "0" for n in counts))


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


def _one_or_each(values: list[float]):
  """A per-channel setting as the interpreter records it: one value where the channels agree."""
  return values[0] if all(v == values[0] for v in values) else tuple(values)


class NGSStarProcesses:
  def __init__(self, star, deck, tips: dict[int, str], liquid_classes, channels: int = 8,
               planner: Optional[StarTipTools] = None, gripper=None, transport_tool: int = CORE_GRIPPER,
               front_channel: int = 7, say=print, tip_counters: Optional[dict[int, str]] = None,
               time_scale: float = 0.0, sleep=None, clock=None, iswap=None, clinical_starlet: bool = False,
               faithful: bool = False, report: Optional[RunReport] = None, operator=None,
               simulation: bool = False, lock_unlock: bool = False, prep=None):
    """`tips`: tip type -> the tip sequence (the framework's t_seqTips300 / 1000 / 50).
    `liquid_classes`: a VenusLiquidClasses (the kit's database, read by tools/liquid_classes.py),
    or a table name -> (tip type, dispense mode) with PLR's STAR classes. `faithful`: keep the
    library's defects the port repairs (the module docstring lists them), as the differential
    tests compare with the HSL. `report`: the run report (ngsstar_report; one in memory when
    none). `operator`: an operator.Operator, shown the status-window lines. `simulation`: the
    framework's simulation mode (t_blnSimulationModeON), in which the timers write no report and the
    multi-dispense measures no trough. `lock_unlock`: the front cover locked (t_blnLockUnlockSystem).
    `prep`: the NGSStarPrep port, whose heater shakers the clean-ups shake."""
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
    self.report = report if report is not None else RunReport()
    self.operator, self.simulation, self.lock_unlock, self.prep = operator, simulation, lock_unlock, prep
    self.max_tips_after_edit: dict[int, int] = {}
    self.samples = 0

  # -- the run report --------------------------------------------------------------------------

  def DATA_UpdateInformationIntoReportFile(self, text: str, to_status_window=1) -> None:
    """A line of text into the run report, and the status window when asked."""
    self.report.text(text)
    if int(to_status_window) and self.operator is not None:
      self.operator.status(text)

  def _labware(self, seq) -> str:
    return (self.v.seq(seq).current_item() or ("", ""))[0]

  def _report_transfer(self, what: str, source, target, volume) -> None:
    self.DATA_UpdateInformationIntoReportFile(
      f"{what} : {self._labware(source)} -----> {self._labware(target)}. Transfering {trimmed_volume(volume)} ul.")

  def _report_transport(self, picked, placed, tool: int, barcode: str) -> None:
    """_DATA_AnalyzeStepReturnValueOfTransportStepAndWriteToNGSStarReport: a stamped row of where the
    plate was picked up and put (the get and place steps' labware and position)."""
    name = {ISWAP: "iSWAP", CORE_GRIPPER: "CORE gripper"}.get(tool, "undefined tool - check definition")
    self.report.add({**self.report.stamp(), "LabID Source": picked[0], "PosID Source": picked[1],
                     "Transfer Volume": " transported to", "LabID Target": placed[0], "PosID Target": placed[1],
                     "Barcode": barcode, "Transport information": ISWAP_OK if tool == ISWAP else CORE_OK,
                     "Aspiration information": f" used tool : {name}"})

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
    self._report_transfer("Pipette reagents", aspiration, dispense, volume)
    tip_type, dispense_mode = self._codes(liquid_class)
    # left out: _DATA_PlausibilityCheckVolume (an operator dialog on a volume too large for the tip)
    if dispense_mode in (2, 4):  # "part": a multi-dispense
      if self._labware_type(self._labware(aspiration)) == "tube":
        await self._PIP_MultidispenseBeadsFromTubesToPlate(ML_STAR, aspiration, dispense, volume, liquid_class,
                                                           mix_cycles, dispense_height, 0)
      else:
        await self._PIP_MultidispenseFromTroughToPlate(ML_STAR, aspiration, dispense, volume, liquid_class,
                                                       mix_cycles)
      # left out of the port so far, and in scope: the sample-tracking mapping file
      return
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
    self._report_transfer("Remove supernatant", aspiration, dispense, volume)
    # left out: _DATA_CheckSequenceParameter (an operator dialog on sequences that don't match)
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
    # left out of the port so far, and in scope: the sample-tracking mapping file
    # (SupernatantToWaste_<LabID>_<BC>_<No>)

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
    source = self._labware(aspiration)
    self.DATA_UpdateInformationIntoReportFile(
      f"Mix reagents : {source} -----> {source}. Mix volume " +
      (" automated calculated by aspiration step." if not mix_volume else f"{trimmed_volume(mix_volume)} ul."))
    if self.faithful and tip_type == SVFT and len(containers) > self.channels:
      raise RuntimeError(f"{aspiration}: {len(containers)} positions to mix with 300 uL tips; the library mixes "
                         f"the first {self.channels} and loops without end on the rest")
    pattern = self.CREATE_CHANNEL_PATTERN(1, len(containers), 8)
    # left out: _DATA_ScheduleTips (the tips shown on the loading screen); _DATA_PlausibilityCheckVolume
    # (an operator dialog on a mix volume too large for the tip, asked only when `mix_volume` > 0)
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
        # CONVENTIONS §11)
        if self.simulation:  # Venus's simulation mode mixes a set volume
          per = MIX_ONLY_SIMULATED[tip_type]
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
  def _labware_type(lab: str) -> str:
    """_DATA_InterpreteLabwareID: by the labware id's name."""
    return "trough" if "RGT" in lab else "plate" if "HSP" in lab or "MIDI" in lab else "tube"

  def _ask(self, kind: str, text: str, **kw):
    from venus_interop.plr.operator import RunAborted

    if self.operator is None:
      raise RunAborted(f"the operator is asked, and there is none: {text}")
    return getattr(self.operator, kind)(text, **kw)

  async def _PIP_MultidispenseBeadsFromTubesToPlate(self, ML_STAR, aspiration, dispense, volume: float,
                                                    liquid_class: str, mix_cycles: int, dispense_height: float,
                                                    measure):
    """_PIP_MultidispenseFromTroughToPlate from tubes (Avenio's wash buffers in 5 mL tubes). The
    source is measured only when `measure` (the transfer passes FALSE). The 1000 uL copy differs
    from the trough's: CalcAliquot's (20, 0, 1000), its pre-dispense and drain switched off (the
    20 uL go out with the tips), its measure on the aspirate's channels (not channel 1 alone), its
    dispense at `dispense_height`. Its pick-up and measure are written with a pattern of a channel
    per position of the tube sequence; AlignSequences caps every sequence at the positions the
    shortest has left, so that gives the same channels as the aspirate's pattern, which the port
    uses. The 300 and 50 uL copies are the trough's."""
    await self._multidispense(ML_STAR, aspiration, dispense, volume, liquid_class, mix_cycles, beads=True,
                              dispense_height=dispense_height, measure=bool(int(measure)))

  async def _PIP_MultidispenseFromTroughToPlate(self, ML_STAR, aspiration, dispense, volume: float,
                                                liquid_class: str, mix_cycles: int):
    await self._multidispense(ML_STAR, aspiration, dispense, volume, liquid_class, mix_cycles)

  async def _multidispense(self, ML_STAR, aspiration, dispense, volume: float, liquid_class: str, mix_cycles: int,
                           beads: bool = False, dispense_height: float = 25.0, measure: bool = True):
    """`volume` into each position of `dispense` from a trough, several dispenses per aspirate
    (a "part" dispense mode), with one set of tips. Per pass (AlignSequences of the trough, the
    plate and the tips): CalcAliquot_v2_1 splits what is left of the plate into rounds of a column
    each. The trough is measured first (not in simulation: a 0 uL cLLD aspirate on channel 1 and
    HSLML_STAR::MeasureContainerVolume2, here PLR's probe_liquid_volumes). With too little for
    the pass's aspirates and 1 mL more, the next trough of the sequence is tried (`channels`
    positions on), then the operator is asked to refill (position 1 again on OK). Then the aspirate
    (cLLD, 2 mm under the surface, following it, mixing); the pre-dispense back into the trough; a
    dispense per round (25 mm above the bottom; the plate's sequence counting on); the tips
    drained into the trough (50 mm). The library writes this once per tip type: the copies differ
    only in the tip type, the numbers (ALIQUOT) and the 50 uL copy's front cover around the refill
    dialog.

    Repaired (`faithful` keeps it): a plate that is not whole columns stops the run in the
    library's report analysis after the part-full column's dispense (the comment at that place)."""
    tip_type, _ = self._codes(liquid_class)
    tips, lc = self.tips[tip_type], self._lc(liquid_class)
    pre, reserve, capacity = (ALIQUOT_BEADS if beads else ALIQUOT)[tip_type]
    src, dst, tip_seq = self.v.seq(aspiration), self.v.seq(dispense), self.v.seq(tips)
    tubes = beads and tip_type == HVFT  # the bead copy's 1000 uL differences
    height = float(dispense_height) if tubes else 25.0
    # left out: _DATA_CheckSequenceParameter (an operator dialog on sequences that don't match),
    # _DATA_ScheduleTips (the tips shown on the loading screen)
    if tip_type == HVFT:
      self.DATA_UpdateInformationIntoReportFile("...multi dispense using high volume tips activated...")
    held, first = [], True
    while dst.cur > 0:
      sq.align([(src, 1), (dst, 1), (tip_seq, 1)])
      a = CalcAliquot_v2_1(dst.end - dst.cur + 1, volume, pre, reserve, capacity, self.channels)
      if first:
        self.planner.Optimized1mLTipPickup2(ML_STAR, tips, self.tip_counters.get(tip_type, ""), a.aspirate_pattern)
        spots = self._take(tips, a.aspirate_pattern, sq.AUTOMATIC, sq.ALL_POSITIONS)
        held = sorted(spots)
        await self.p.pick_up_tips(self._wells(spots[c] for c in held), use_channels=held)
        first = False
      if measure and not self.simulation:
        await self._trough_check(src, sum(a.aspirate), tip_type, a.aspirate_pattern if tubes else "1")
      taken = self._take(aspiration, a.aspirate_pattern, sq.MANUAL, sq.CHANNEL_PATTERN)
      ch = sorted(taken)
      trough = self._wells(taken[c] for c in ch)
      draw = Pipetting(5, 2.0, liquid_following=True, mix_cycles=int(mix_cycles),
                       mix_volume=_one_or_each([a.mix[c] for c in ch]), mix_position=2.0)
      await steps.aspirate(self.p, trough, [a.aspirate[c] for c in ch], ch, draw, lc)
      if not tubes:
        await steps.dispense(self.p, trough, [pre] * len(ch), ch, Pipetting(0, fluid_height=50.0), lc)
      for pattern in a.dispense_patterns:
        wells = self._take(dispense, pattern, sq.AUTOMATIC, sq.CHANNEL_PATTERN)
        dch = sorted(wells)
        await steps.dispense(self.p, self._wells(wells[c] for c in dch), [volume] * len(dch), dch,
                             Pipetting(0, fluid_height=height), lc)
        # left out: _DATA_AnalyseStepReturnValueOfPipettingStepAndWriteToNGSStarReport (report rows
        # from the steps' per-position return values; their step data is empty in the interpreter, so
        # neither side writes them yet). Repaired: it looks up each of the aspirate's channels in the
        # dispense's return, so a round on fewer channels (a column part full) raises
        # (StepReturn::GetLabwareId of position 0, invalidParameter) and stops the run
        if self.faithful and len(dch) < len(ch):
          raise RuntimeError(f"{dispense}: a dispense on {len(dch)} of the aspirate's {len(ch)} channels; the "
                             "library's report analysis raises (StepReturn::GetLabwareId, invalid parameter)")
      # the drain ("drain tip in jet mode"): what the tips still hold, the reserve
      left = [a.aspirate[c] - pre - volume * sum(p[c] == "1" for p in a.dispense_patterns) for c in ch]
      if not tubes:
        await steps.dispense(self.p, trough, left, ch, Pipetting(0, fluid_height=50.0), lc, empty=[True] * len(ch))
      if tip_type != HVFT:  # the 1000 uL copy writes the counters once, after the loop
        self.DATA_TipCounterWrite(ML_STAR)
      if dst.cur > 0 and dst.max == 0:  # MECC::EndlessSequenceLoopWarning
        raise sq.SequenceError(f"{dst.name}: the multi-dispense loop would not end (max 0)")
    for s in (src, dst, tip_seq):
      s.set_max(s.total)
    src.set_current_position(1)
    dst.set_current_position(1)
    if tip_type == HVFT:
      self.DATA_TipCounterWrite(ML_STAR)
    await self.p.discard_tips(use_channels=held)
    # left out of the port so far, and in scope: the sample-tracking mapping file
    # (Multidispense_<LabID>_<BC>_<No>)

  async def _trough_check(self, src: sq.Sequence, aspirated: float, tip_type: int, pattern: str = "1") -> None:
    """Enough in the trough for a pass: measured at the trough's current position on the channels of
    `pattern`, channel 1's reading taken (GetContainerVolume(1)). If
    not, the next trough (`channels` positions on) while the sequence holds more than one, then the
    operator asked to refill (OK: position 1 again; Cancel: as it is, and the aspirate may fail).
    Venus's 600 s timeout counts as Cancel: no timeout here."""
    from venus_interop.plr.libraries.ngsstar_loading import cover_locked, cover_unlocked

    while True:
      probed = self._take(src, pattern, sq.MANUAL, sq.CHANNEL_PATTERN)
      on = sorted(probed)
      found = await self.p.probe_liquid_volumes(self._wells(probed[c] for c in on), use_channels=on)
      measured = found[0]
      if aspirated + TROUGH_MARGIN <= measured:
        return
      if src.end // self.channels > 1:  # integer division (CONVENTIONS §11)
        src.increment(self.channels)
        if src.cur != 0:
          continue
      break
    lock = tip_type == LVFT and self.lock_unlock
    if lock:
      await cover_unlocked(self.star)
    ok = self._ask("confirm", INSUFFICIENT + "\n" + REFILL.get(tip_type, REFILL[None]))
    if lock:
      await cover_locked(self.star, self._ask)
    if ok:
      src.set_current_position(1)

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

  # -- bead clean-ups --------------------------------------------------------------------------
  # Left out of all four: the status-window texts (VectorCustomDialogs::AppendStatusText), and the
  # t_blnDeactivatePipettingStepsForTransportTests switch (a framework test mode: pipetting skipped)

  async def _HHS_Shake(self, hhs, speed: int, seconds: float) -> None:
    """The heater shaker `hhs` at `speed` rpm for `seconds`, then stopped (not in simulation): the
    NGSStarPrep port's HHS_Shake. Venus's timer dialog lets the operator stop early: no counterpart."""
    if self.simulation:
      return
    if self.prep is None:
      raise RuntimeError("a heater shaker is asked for, and no NGSStarPrep was given")
    await self.prep.HHS_Shake(hhs, speed, seconds)

  def _DATA_CalculateAndDefineBatchProcessCleanUp(self, columns_per_batch: int, scale_up, magnet):
    """The magnet's positions in batches of `columns_per_batch` columns (8 positions each), and how
    many batches: one, the whole sequence, when it fits in one or `scale_up` is off. Else, from its
    current position, as many positions as a batch holds each, the sequence at position 1 after.
    Repaired (`faithful` keeps it): without scale-up the count is still the columns' batches while
    the list holds one, so the clean-up's second GetAt fails; here the count is the list's."""
    m = self.v.seq(magnet)
    n = int(columns_per_batch)
    columns = m.end // 8 + (m.end % 8 > 0)  # integer division (CONVENTIONS §11)
    count = columns // n + (columns % n > 0)
    if n >= columns or not int(scale_up):
      return [m.copy()], (count if self.faithful else 1)
    out = []
    for k in range(count):
      items = []
      for _ in range(n * 8):
        if m.current_item():
          items.append(m.current_item())
        m.increment(1)
      out.append(sq.Sequence(f"l_seqBatch{k + 1}", items))
    m.set_current_position(1)
    return out, count

  def _batches(self, batches, count, magnet):
    """The clean-up's loop over the batches: each aligned with the magnet's sequence, from position 1."""
    for k in range(count):
      if k >= len(batches):
        raise RuntimeError(f"batch {k + 1} of {count}: the library's batch array holds {len(batches)} (GetAt fails)")
      batch = batches[k].copy()
      sq.align([(batch, 1), (self.v.seq(magnet), 1)])
      batch.set_current_position(1)
      yield batch

  async def _bind(self, ML_STAR, beads, mix, hhs, magnet, volume, lc_beads, lc_mix, shaker, rpm, seconds, bind_time,
                  separation_time, increment=None):
    """Beads mixed in their containers and added to the samples on the heater shaker (new tips each
    slice, 1 mm above the bottom; the bead sequence moving on from tubes, not from a trough), shaken,
    incubated, the plate onto the magnet, the beads left to separate."""
    if increment is None:
      increment = self._labware_type(self._labware(beads)) == "tube"
    await self.PIP_MixOnly(ML_STAR, mix, 0, lc_mix, 10, 0)
    await self.PIP_ReagentsFromTubeOrTroughOrPlateToPlate(ML_STAR, beads, hhs, volume, lc_beads, 0, 0, 0, 0, 1, 1,
                                                          int(increment), 0)
    await self._HHS_Shake(shaker, rpm, seconds)
    await self.DATA_IncubationTimer("l_hldTimerIncubationAfterShakingAtHeaterShaker", bind_time, 1)
    await self.Trp_MIDI(ML_STAR, hhs, magnet, 0, 1, None, 4)
    await self.DATA_IncubationTimer("l_hdlTimerIncubationAtMagent", separation_time, 1)

  async def _washes(self, ML_STAR, batch, waste, ethanol, supernatant, lc_supernatant, v_ethanol, lc_ethanol,
                    lc_ethanol_waste, dry_time, washes, resuspend):
    """One batch on the magnet: the supernatant off; `washes` times ethanol on (6 mix cycles) and
    off (250 uL), the air-drying timer started before the last one comes off; dried; then
    `resuspend(batch)`."""
    await self.PIP_Supernatant_SVFTSingleDispenseFromPlateToLiquidWaste(ML_STAR, batch, waste, supernatant,
                                                                         lc_supernatant)
    for w in range(washes):
      await self._PIP_MultidispenseFromTroughToPlate(ML_STAR, ethanol, batch, v_ethanol, lc_ethanol, 6)
      if w == washes - 1:
        await self.DATA_IncubationTimer("l_hdlOverdryingTimerAirDryingEthanol", dry_time, 2)
      await self.PIP_Supernatant_SVFTSingleDispenseFromPlateToLiquidWaste(ML_STAR, batch, waste, 250, lc_ethanol_waste)
    batch.set_current_position(1)
    await self.DATA_IncubationTimer("l_hdlOverdryingTimerAirDryingEthanol", dry_time, 3)
    await resuspend(batch)

  async def _resuspended(self, ML_STAR, hhs, magnet, shaker, rpm, seconds, incubation, carry_over, extra=None):
    """Back to the heater shaker (`extra` there first: another reagent, more shaking), shaken,
    incubated, onto the magnet, left there against bead carry-over."""
    await self.Trp_MIDI(ML_STAR, magnet, hhs, 0, 1, None, 4)
    if extra is not None:
      await extra()
    await self._HHS_Shake(shaker, rpm, seconds)
    if extra is not None:  # the 1x-ethanol clean-up's: two more shakes
      await self._HHS_Shake(shaker, 1200, 10)
      await self._HHS_Shake(shaker, 600, 10)
    await self.DATA_IncubationTimer("l_hdlTimerIncubationAfterResuspendation", incubation, 1)
    await self.Trp_MIDI(ML_STAR, hhs, magnet, 0, 1, None, 4)
    await self.DATA_IncubationTimer("l_hdlTimerIncubationAvoidingBeadCarryOverAtMagneticStand", carry_over, 1)

  def _resuspend(self, ML_STAR, buffer, volume, lc, increment=0):
    """The resuspension into a batch: new tips each slice, 0.7 mm above the bottom."""
    async def go(batch):
      await self.PIP_ReagentsFromTubeOrTroughOrPlateToPlate(ML_STAR, buffer, batch, volume, lc, 0, 0, 0, 0, 0.7, 1,
                                                            int(increment), 0)
    return go

  async def Process_CleanUp(self, ML_STAR, beads, mix, hhs, ethanol, magnet, waste, buffer, v_ethanol, v_beads,
                            v_buffer, v_supernatant, lc_beads, lc_mix, lc_ethanol, lc_buffer, lc_supernatant,
                            lc_ethanol_waste, rpm_bind, rpm_resuspend, s_bind, s_resuspend, columns_per_batch, shaker,
                            scale_up, t_bind, t_magnet, t_dry, t_resuspended, t_carry_over,
                            title="Process clean up", increment_buffer=0):
    """Two ethanol washes."""
    self.DATA_UpdateInformationIntoReportFile(title)
    batches, count = self._DATA_CalculateAndDefineBatchProcessCleanUp(columns_per_batch, scale_up, magnet)
    await self._bind(ML_STAR, beads, mix, hhs, magnet, v_beads, lc_beads, lc_mix, shaker, rpm_bind, s_bind, t_bind,
                     t_magnet)
    for batch in self._batches(batches, count, magnet):
      await self._washes(ML_STAR, batch, waste, ethanol, v_supernatant, lc_supernatant, v_ethanol, lc_ethanol,
                         lc_ethanol_waste, t_dry, 2, self._resuspend(ML_STAR, buffer, v_buffer, lc_buffer,
                                                                     increment_buffer))
    await self._resuspended(ML_STAR, hhs, magnet, shaker, rpm_resuspend, s_resuspend, t_resuspended, t_carry_over)

  async def Customized_Process_CleanUp_ElutionBufferInPlate(self, ML_STAR, beads, mix, hhs, ethanol, magnet, waste,
                                                            buffer, increment_buffer, *rest):
    """Process_CleanUp with the resuspension's sequence moving on or not (`increment_buffer`)."""
    await self.Process_CleanUp(ML_STAR, beads, mix, hhs, ethanol, magnet, waste, buffer, *rest,
                               increment_buffer=increment_buffer)

  async def Customized_Process_CleanUp_AvenioCGP_1xEthanol(
      self, ML_STAR, beads, mix, hhs, ethanol, magnet, waste, component1, component2, v_ethanol, v_beads,
      v_component1, v_component2, v_supernatant, lc_beads, lc_mix, lc_ethanol, lc_component1, lc_component2,
      lc_supernatant, lc_ethanol_waste, rpm_bind, rpm_resuspend, s_bind, s_resuspend, columns_per_batch, shaker,
      scale_up, t_bind, t_magnet, t_dry, t_resuspended, t_carry_over):
    """One ethanol wash; the first component into each batch, the second (10 mix cycles of 50 uL as
    it dispenses, following the liquid) on the heater shaker, shaken three times."""
    self.DATA_UpdateInformationIntoReportFile("Process_CleanUp_AvenioCGP_1xEthanol")
    batches, count = self._DATA_CalculateAndDefineBatchProcessCleanUp(columns_per_batch, scale_up, magnet)
    await self._bind(ML_STAR, beads, mix, hhs, magnet, v_beads, lc_beads, lc_mix, shaker, rpm_bind, s_bind, t_bind,
                     t_magnet)
    for batch in self._batches(batches, count, magnet):
      await self._washes(ML_STAR, batch, waste, ethanol, v_supernatant, lc_supernatant, v_ethanol, lc_ethanol,
                         lc_ethanol_waste, t_dry, 1, self._resuspend(ML_STAR, component1, v_component1,
                                                                     lc_component1))

    async def second():
      await self.PIP_ReagentsFromTubeOrTroughOrPlateToPlate(ML_STAR, component2, hhs, v_component2, lc_component2, 10,
                                                            0, 50, 0, 0.7, 1, 0, 1)
    await self._resuspended(ML_STAR, hhs, magnet, shaker, rpm_resuspend, s_resuspend, t_resuspended, t_carry_over,
                            extra=second)

  async def Customized_Process_CleanUp_2BeadAdditions(
      self, ML_STAR, beads, mix, hhs, ethanol, magnet, waste, buffer, v_ethanol, v_beads_1, v_beads_2, v_buffer_1,
      v_buffer_2, v_supernatant_1, v_supernatant_2, lc_beads, lc_mix, lc_ethanol, lc_buffer, lc_supernatant,
      lc_ethanol_waste, rpm_bind, rpm_resuspend, s_bind, s_resuspend, columns_per_batch, shaker, scale_up, t_bind_1,
      t_bind_2, t_magnet, t_dry, t_resuspended, t_carry_over):
    """A first bead round (its supernatant off the whole plate, the buffer added on the shaker and
    shaken), the second beads added on top (mixed as they go in) and bound, then Process_CleanUp's
    washes and tail. Kept as the library has it: the bead sequence never moves on, and both rounds
    incubate for `t_bind_1` (`t_bind_2` is never used); the buffer's shake runs at the binding speed
    for the resuspension's time."""
    self.DATA_UpdateInformationIntoReportFile("Process_CleanUp_2BeadAdditions")
    batches, count = self._DATA_CalculateAndDefineBatchProcessCleanUp(columns_per_batch, scale_up, magnet)
    await self._bind(ML_STAR, beads, mix, hhs, magnet, v_beads_1, lc_beads, lc_mix, shaker, rpm_bind, s_bind,
                     t_bind_1, t_magnet, increment=False)
    await self.PIP_Supernatant_SVFTSingleDispenseFromPlateToLiquidWaste(ML_STAR, magnet, waste, v_supernatant_1,
                                                                         lc_supernatant)
    await self.Trp_MIDI(ML_STAR, magnet, hhs, 0, 1, None, 4)
    await self.PIP_ReagentsFromTubeOrTroughOrPlateToPlate(ML_STAR, buffer, hhs, v_buffer_1, lc_buffer, 2, 0, 0, 0, 1,
                                                          1, 0, 1)
    await self._HHS_Shake(shaker, rpm_bind, s_resuspend)
    await self.PIP_ReagentsFromTubeOrTroughOrPlateToPlate(ML_STAR, beads, hhs, v_beads_2, lc_beads, 2, 0, v_beads_2,
                                                          0, 1, 1, 0, 1)
    await self._HHS_Shake(shaker, rpm_bind, s_bind)
    await self.DATA_IncubationTimer("l_hldTimerIncubationAfterShakingAtHeaterShaker", t_bind_1, 1)
    await self.Trp_MIDI(ML_STAR, hhs, magnet, 0, 1, None, 4)
    await self.DATA_IncubationTimer("l_hdlTimerIncubationAtMagent", t_magnet, 1)
    for batch in self._batches(batches, count, magnet):
      await self._washes(ML_STAR, batch, waste, ethanol, v_supernatant_2, lc_supernatant, v_ethanol, lc_ethanol,
                         lc_ethanol_waste, t_dry, 2, self._resuspend(ML_STAR, buffer, v_buffer_2, lc_buffer))
    await self._resuspended(ML_STAR, hhs, magnet, shaker, rpm_resuspend, s_resuspend, t_resuspended, t_carry_over)

  # -- transports ------------------------------------------------------------------------------

  def _gripper_(self):
    if self._gripper is None:
      from venus_interop.plr.venus_deck import Gripper
      self._gripper = Gripper(self.star, self.v, self.say)
    return self._gripper

  def _tool_name(self) -> str:
    return {ISWAP: "iSWAP", CORE_GRIPPER: "CORE gripper"}.get(self.transport_tool, "undefined tool - check definition")

  async def _transport(self, kind: str, source: str, destination: str, grip: CoreGrip, park: bool, barcode_track):
    """Trp_MIDI's and Trp_HSP's move by the CO-RE gripper, between the report lines; returns the
    barcode text (o_strReadCurrentBarcode)."""
    from pylabrobot.resources import Coordinate

    from venus_interop.plr import steps

    self.DATA_UpdateInformationIntoReportFile(f"Transport {kind} plate")
    picked, placed = self.v.seq(source).current_item(), self.v.seq(destination).current_item()
    src_lab, dst_lab = picked[0], placed[0]
    # left out: _DATA_ScheduleConsumables (the plates shown on the loading screen)
    self.DATA_UpdateInformationIntoReportFile(
      f"Transport {kind} : {src_lab} -----> {dst_lab}. Tool used : {self._tool_name()}.")
    if self.transport_tool != CORE_GRIPPER:
      raise NotImplementedError("the iSWAP transports are not ported yet (Avenio uses the CO-RE gripper)")
    barcode = "No barcode reading activated"
    if barcode_track and int(barcode_track) > 0:
      self.say(f"{src_lab}: barcode read at the autoload not modelled")
      barcode = ""
    pick_shift, drop_shift = SHIFTS.get(dst_lab, ((0, 0, 0), (0, 0, 0)))
    pick, drop = steps.core_grip_arguments(grip, Coordinate(*pick_shift), Coordinate(*drop_shift))
    plate = self.v.resource(src_lab)
    await self._gripper_().to_placeholder(plate, dst_lab, front_channel=self.front_channel - 1, eject=bool(park),
                                          grip=pick, release=drop)
    self.DATA_UpdateInformationIntoReportFile(barcode)
    self._report_transport(picked, placed, self.transport_tool, barcode)
    return barcode

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
    return await self._transport("MIDI", source, destination, grip, park_after_move, track_to_read_barcode)

  async def Trp_HSP(self, ML_STAR, source: str, destination: str, track_to_read_barcode=0, park_after_move=1,
                    read_barcode=None, grip_mode_iswap=4):
    """A hard-shell PCR plate by the CO-RE gripper; the plate check only onto `HSP_CPAC` (the kit's
    CPAC position is `HSP_onCPAC`, so in Avenio it stays off, as in Venus)."""
    import dataclasses

    dst_lab = self.v.seq(destination).current_item()[0]
    grip = dataclasses.replace(HSP_GRIP, check=1 if dst_lab == "HSP_CPAC" else 0)
    return await self._transport("HSP", source, destination, grip, park_after_move, track_to_read_barcode)

  async def Trp_HSPFromAndToODTCwithiSWAP(self, ML_STAR, source, destination, track_to_read_barcode=0,
                                          park_after_move=0, read_barcode=None):
    """A hard-shell PCR plate into or out of the ODTC by the iSWAP: the short side, 5 mm below the
    top (from the left instead, inverted, on a Clinical NGS STARlet unless it comes from the ODTC);
    then the arm parked, or only its Z homed (`R0ZI`: up to the top of its travel here)."""
    import dataclasses

    self.DATA_UpdateInformationIntoReportFile("Transport HSP plate")
    picked, placed = self.v.seq(source).current_item(), self.v.seq(destination).current_item()
    src_lab, dst_lab = picked[0], placed[0]
    self.DATA_UpdateInformationIntoReportFile(
      f"Transport plate using iSWAP : {src_lab} -----> {dst_lab}. Tool used : iSWAP.")
    grip = dataclasses.replace(ODTC_GRIP, inverse=self.clinical_starlet and src_lab != "HSP_ODTC")
    barcode = "No barcode reading activated"
    if track_to_read_barcode and int(track_to_read_barcode) > 0:
      self.say(f"{src_lab}: barcode read at the autoload not modelled")
      barcode = ""
    await self._by_iswap(src_lab, dst_lab, grip, park_after_move)
    self._report_transport(picked, placed, ISWAP, barcode)
    return barcode

  async def Trp_HamiltonComfortLid(self, ML_STAR, source, destination, park_after_move=0,
                                   reachable_with_core_gripper=0):
    """A Hamilton ComfortLid moved: by the CO-RE gripper when the destination is reachable with it
    (the flag compared with TRUE: Avenio's call passing 4 takes the iSWAP, as in Venus), else by the
    iSWAP, the short side 5 mm below the top at force 2, let go by opening to 95 mm over the lid
    waste, 89 elsewhere. Kept as the library has it: the report's row names the iSWAP whichever
    moved the lid."""
    self.DATA_UpdateInformationIntoReportFile("Transport lid")
    picked, placed = self.v.seq(source).current_item(), self.v.seq(destination).current_item()
    src_lab, dst_lab = picked[0], placed[0]
    # left out: _DATA_ScheduleConsumables (the lids shown on the loading screen)
    lid = self.v.resource(src_lab)
    core = int(reachable_with_core_gripper) == 1
    tool = "CORE Gripper" if core else "iSWAP"
    self.DATA_UpdateInformationIntoReportFile(
      f"Transport Hamilton Comfort Lid using {tool} : {src_lab} -----> {dst_lab}. Tool used : {tool}.")
    if core:
      pick, drop = steps.core_grip_arguments(LID_CORE_GRIP)
      await self._gripper_().to_placeholder(lid, dst_lab, front_channel=self.front_channel - 1,
                                            eject=bool(park_after_move), grip=pick, release=drop)
    else:
      opening = 95 if dst_lab == "Ham_ComfortLid_Waste" else 89
      await self._by_iswap(src_lab, dst_lab, LID_GRIP, park_after_move,
                           release=dict(open_margin=round(opening - LID_GRIP.width, 4)))
    self._report_transport(picked, placed, ISWAP, "")

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
    done = f"Incubation performed . Duration : {number_text(seconds)} seconds."
    if int(mode) == 1:
      await self.sleep(seconds * self.time_scale)
    elif int(mode) == 2:
      self._timers[timer] = now + seconds
    elif int(mode) == 3:
      left = self._timers.pop(timer, now) - now
      await self.sleep(max(0.0, left) * self.time_scale)
    if int(mode) in (1, 3) and not self.simulation:
      self.DATA_UpdateInformationIntoReportFile(done)

  # -- the framework's set-up ------------------------------------------------------------------

  # the layout's tip sequences the framework looks for, and the counter names it then writes to
  TIP_SEQUENCES = {LVFT: "MlStar50ulTipWithFilter", SVFT: "MlStar300ulStandardVolumeTipWithFilter",
                   HVFT: "MlStar1000ulHighVolumeTipWithFilter"}
  COUNTERS = {LVFT: "50F_Counter", SVFT: "SVF_Counter", HVFT: "1000F_Counter"}

  def DATA_HandoverSequencesAndDataToSMT(self, ML_STAR, transport_tool, kit_supplier, kit_title,
                                         deactivate_pipetting=0, reduce_to_4_channels=0, email="", lock_unlock=0,
                                         use_mph=0, platform=1, counter50="", counter300="", counter1000="",
                                         report_folder=None):
    """The framework's state for a run: 4 or 8 channels (their pattern, the CO-RE transport's
    front channel), a Clinical NGS STARlet unless `platform` is 1, the front cover locking, the
    transport tool; each tip type's layout sequence (`TIP_SEQUENCES`, where the layout has it) read
    from its counter; the run report, named as Venus names its workbook
    (`<date>_<time>_NGSStarReport_<kit>`), as CSV in `report_folder` (in memory when None).
    Returns (the report's path, the 50, 300 and 1000 uL tip sequences).

    Kept as the library has it: each counter is read under the name given and written, from then
    on, under the framework's own (`COUNTERS`); Avenio gives those names. Left out: the e-mail
    alerts (an address only switches them on), the process timer (a trace), the firmware command
    `PXAA zp020` to all channels (a stored drive parameter PLR names no counterpart for: CONVENTIONS
    §11), the deactivate-pipetting test mode (`deactivate_pipetting` must be 0), the MPH 1000 uL
    sequence reduction (`use_mph`: 96-head runs not ported)."""
    import time

    from venus_interop.plr.libraries.ngsstar_report import RunReport

    if int(deactivate_pipetting) or int(use_mph):
      raise NotImplementedError("the framework's transport-test mode and its 96-head runs are not ported")
    self.channels = 4 if int(reduce_to_4_channels) else 8
    self.channel_pattern = "11110000" if self.channels == 4 else "11111111"
    self.transport_pattern = "00110000" if self.channels == 4 else "00000011"
    self.front_channel = self.channels
    self.planner.channels = self.channels
    self.clinical_starlet = int(platform) != 1
    self.lock_unlock = bool(int(lock_unlock))
    self.transport_tool = int(transport_tool)
    self.kit_supplier, self.kit_title, self.email = kit_supplier, kit_title, email
    given = {LVFT: counter50, SVFT: counter300, HVFT: counter1000}
    for tip_type, name in self.TIP_SEQUENCES.items():
      if name in self.v.sequences:
        self.tips[tip_type] = name
        self.planner.TipCounter_Read(ML_STAR, name, given[tip_type])
        self.tip_counters[tip_type] = self.COUNTERS[tip_type]
    self.DATA_TipCounterWrite(ML_STAR)
    stamp = time.strftime("%Y%m%d_%H%M%S", self.report.clock())
    path = None if report_folder is None else pathlib.Path(report_folder) / f"{stamp}_NGSStarReport_{kit_title}.csv"
    self.report = RunReport(path, clock=self.report.clock)
    return path, *(self.tips.get(t) for t in (LVFT, SVFT, HVFT))

  def DATA_TrackDataFromLoadingSMT(self, tips50_after_edit=0, tips300_after_edit=0, tips1000_after_edit=0,
                                   samples=0):
    """Numbers the loading library hands over (the tips left after the operator's edit, the
    samples), kept for the loading screen's tip scheduling, which is not ported."""
    for tip_type, n in ((LVFT, tips50_after_edit), (SVFT, tips300_after_edit), (HVFT, tips1000_after_edit)):
      if int(n):
        self.max_tips_after_edit[tip_type] = int(n)
    self.samples = int(samples)

  # -- tip counters ----------------------------------------------------------------------------

  async def PIP_DefragmentTipRacks(self, ML_STAR=None):
    """The 50, 300 and 1000 uL tip racks defragmented (STAR Tip Tools' DefragTipRacks1mL), in turn."""
    for tip_type in (LVFT, SVFT, HVFT):
      if tip_type in self.tips:
        await self.planner.DefragTipRacks1mL(ML_STAR, self.tips[tip_type], self.p)

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
