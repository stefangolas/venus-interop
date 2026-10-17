"""Hamilton's NGSStar framework, `NGSStarProcesses` (`NGSStar\\<kit>\\Library\\NGSStarProcesses.hsi`):
the pipetting and transport functions every NGS STAR kit method is built on. Ported so far:

  PIP_ReagentsFromTubeOrTroughOrPlateToPlate   (817 lines in Venus) a reagent into each position of
      the dispense sequence, a slice of channels at a time. The library writes the loop out once per
      tip type; here it is once, with what differs per tip type in TIP_SETTINGS. Per slice: the tip
      planner (STAR Tip Tools) and a pick-up, every slice or only the first; aspirate by cLLD
      (height 0) or from a fixed height above the bottom (liquid following above 1.8 mm); dispense
      by cLLD (height 0) or at a fixed height; tips out if exchanged; both sequences on by the
      channel count. Tips out at the end when not exchanged.

The tip type and dispense mode come from the liquid class in Venus's database: until that is read,
`liquid_classes` gives them (name -> (tip type, dispense mode)). Dispense modes 2 and 4 ("part",
multi-dispense) take other functions, not ported yet. Not ported, by design: the report and status
lines, the volume plausibility dialog, the sequence check dialog, the tip scheduling for the loading
screen, the sample-tracking mapping file (STCC).
"""
from __future__ import annotations

import dataclasses
from typing import Optional

from venus_interop.methods import sequences as sq
from venus_interop.plr.libraries.star_tip_tools import StarTipTools

from pylabrobot.hamilton.star.driver.lld_mode import LLDMode
from pylabrobot.hamilton.star.liquid_classes import mapping as star_classes
from pylabrobot.lib.liquid_handling.mix import Mix

LIBRARY = "NGSSTARPROCESSES"  # the Venus namespace ported

SVFT, HVFT, LVFT = 1, 5, 23  # Venus tip types: 300 uL, 1000 uL, 50 uL filter tips


@dataclasses.dataclass(frozen=True)
class TipSettings:
  """What the library's step records set differently per tip type."""
  aspirate_submerge: float  # mm below the surface, aspirating by cLLD
  dispense_submerge: float  # mm below the surface, dispensing by cLLD
  dispense_clld: int  # the dispense's cLLD sensitivity (PLR takes none per call)


TIP_SETTINGS = {SVFT: TipSettings(0.5, 0.5, 2), HVFT: TipSettings(2.0, 0.6, 1), LVFT: TipSettings(0.5, 0.5, 1)}
LIQUID_FOLLOWING_ABOVE = 1.8  # mm: a fixed-height aspirate follows the liquid above this
MIX_FLOW = 250.0  # uL/s; the steps leave it to the class: an assumption until classes are read


class NGSStarProcesses:
  def __init__(self, star, deck, tips: dict[int, str], liquid_classes: dict[str, tuple[int, int]],
               channels: int = 8, planner: Optional[StarTipTools] = None):
    """`tips`: tip type -> the tip sequence (the framework's t_seqTips300 / 1000 / 50)."""
    self.p, self.v, self.tips, self.classes = star.pipettes, deck, tips, liquid_classes
    self.channels = channels
    self.planner = planner or StarTipTools(deck, channels)
    self.missing_classes: set[str] = set()

  def _take(self, seq: str, pattern: str, counting: int, use: int) -> dict:
    taken = sq.take(self.v.seq(seq), pattern, counting, use)
    return {ch - 1: item for ch, item in taken.channels.items()}

  def _lc(self, name: str):
    lc = getattr(star_classes, name, None)
    if lc is None:
      self.missing_classes.add(name)
    return lc

  async def PIP_ReagentsFromTubeOrTroughOrPlateToPlate(
      self, ML_STAR, aspiration: str, dispense: str, volume: float, liquid_class: str, mix_cycles: int,
      mix_volume_aspiration: float, mix_volume_dispense: float, aspirate_height: float,
      dispense_height: float, tip_exchange: bool, increment_aspiration: bool,
      liquid_following_at_fixed_dispense: bool):
    tip_type, dispense_mode = self.classes[liquid_class]
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
      wells = self._take(aspiration, pattern, sq.MANUAL, sq.CHANNEL_PATTERN)
      ch = sorted(wells)
      mix = _mix(mix_cycles, mix_volume_aspiration)
      where = (dict(lld_mode=LLDMode.CAPACITIVE, immersion_depths=[cfg.aspirate_submerge] * len(ch),
                    auto_surface_following=True) if aspirate_height == 0 else
               dict(liquid_heights=[aspirate_height] * len(ch),
                    auto_surface_following=aspirate_height > LIQUID_FOLLOWING_ABOVE))
      await self.p.aspirate([self.v.resolve(wells[c]) for c in ch], [volume] * len(ch), use_channels=ch,
                            hamilton_liquid_classes=[lc] * len(ch) if lc else None,
                            pre_mixes=[mix] * len(ch) if mix else None, **where)
      wells = self._take(dispense, pattern, sq.MANUAL, sq.CHANNEL_PATTERN)
      ch = sorted(wells)
      mix = _mix(mix_cycles, mix_volume_dispense)
      where = (dict(lld_mode=LLDMode.CAPACITIVE, immersion_depths=[cfg.dispense_submerge] * len(ch),
                    auto_surface_following=True) if dispense_height == 0 else
               dict(liquid_heights=[dispense_height] * len(ch),
                    auto_surface_following=bool(liquid_following_at_fixed_dispense)))
      await self.p.dispense([self.v.resolve(wells[c]) for c in ch], [volume] * len(ch), use_channels=ch,
                            hamilton_liquid_classes=[lc] * len(ch) if lc else None,
                            post_mixes=[mix] * len(ch) if mix else None, **where)
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


def _mix(cycles, volume) -> Optional[Mix]:
  return Mix(volume=float(volume), repetitions=int(cycles), flow_rate=MIX_FLOW) if cycles and volume else None
