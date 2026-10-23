"""NIST LMSF's GSF-IMS shared submethods (`GSF-IMS.shared_submethods.hsi`) on a PLR STAR.

The library is 1,281 lines and 40 functions of Venus code; what it does is one pattern and one
variant, over the method's sequences:

  fill       for each n-channel slice of the destination: aspirate from the same n source
             positions (a trough or n tubes; manual counting), dispense into the slice (automatic
             counting). The entry points differ in when tips change, a pre-wet, and mixing:
               pipette_media (+_volume_arr)  tips held by the caller; optional pre-wet
               add_reagent_reuse_tips (+_vol_arr) tips picked up and ejected around it, or not
             The _arr variants take one volume per slice (the array is destination length / n
             long); add_reagents_reuse_tips_vol_arr skips a slice of volume 0, stepping the
             destination n positions on by hand.
               add_reagent_replace_tips   new tips for every slice; mix after dispensing
               pipette_cells_from_tubes   mix before aspirating, 8 mm below the surface
  series     pipette_dil_series: slice i of the source into slice i of the destination, one set
             of tips, mix before aspirating 3 mm below the surface.

The rest is argument checks (the source has exactly n positions; the destination a multiple of
n), the channel pattern (`"1" * n`), and tracing. Sequence state follows Venus's rules
(`methods.sequences`), so a run consumes exactly the wells and tips the method does.

Settings, from the library's .stp records (step GUIDs in brackets):
  aspirate   cLLD (labware's sensitivity), submerge 2 mm, liquid following; liquid class by tip:
             300 uL StandardVolumeFilter_Water_FastMixing_DispenseSurface_Empty, 1000 uL
             HighVolumeFilter_Water_FastMixing_DispenseSurface_Empty  [33da8612, 05a6e94c, 32abdc77]
  dispense   the aspirate's class; to liquid: cLLD, submerge 2 mm, liquid following [68beb8be];
             otherwise 0.3 mm above the bottom, no LLD [fb45c82b]; mix 2 mm below the surface
"""
from __future__ import annotations

from typing import Optional, Sequence, Union

from venus_interop.methods import sequences as sq
from venus_interop.plr import steps
from venus_interop.plr.steps import Pipetting
from venus_interop.plr.venus_deck import VenusDeck

from pylabrobot.hamilton.star.liquid_classes import mapping as star_classes
from pylabrobot.lib.liquid_handling.mix import Mix

LIBRARY = "GSF_IMS_SHARED_SUBMETHODS"  # the Venus namespace ported

CLASS_BY_TIP = {  # aspirate_w_err_handling: STAR_TIP_TOOLS::GetTipType 1 / 5
  300: "StandardVolumeFilter_Water_FastMixing_DispenseSurface_Empty",
  1000: "HighVolumeFilter_Water_FastMixing_DispenseSurface_Empty",
}
SERIES_CLASS = "HighVolumeFilter_Water_FastMixing_DispenseSurface_Empty"  # fixed in 05a6e94c, 32abdc77


class SubmethodError(ValueError):
  """The library's own checks failing (its ErrRaise): Venus aborts the method."""
SUBMERGE = 2.0
CLLD = 5  # the records' cLLD sensitivity ("from labware")
DISPENSE_HEIGHT = 0.3  # fb45c82b, the dispense not to liquid
RECORD = dict(pull_out=5.0, touch_off=0.5)  # every step record's pull-out distance and touch-off position

Volumes = Union[float, Sequence[float]]


class GsfIms:
  """The library's entry points, by their Venus names and arguments (sequences by name)."""

  def __init__(self, star, deck: VenusDeck, say=print, liquid_classes=None):
    """`liquid_classes`: a VenusLiquidClasses (the method's database, read by
    tools/liquid_classes.py); PLR's STAR table alone when None, which lacks the library's
    FastMixing classes."""
    self.star, self.v, self.say = star, deck, say
    self.p = star.pipettes
    self.classes = liquid_classes
    # classes neither has: PLR's default is used for them
    self.missing_classes: set[str] = set()

  # -- the two steps everything is made of ----------------------------------------------------

  def _lc(self, name: str):
    lc = self.classes.get(name) if self.classes is not None else getattr(star_classes, name, None)
    if lc is None:
      self.missing_classes.add(name)
    return lc

  def _class(self, tips: str):
    # the rack's tip type, as STAR_TIP_TOOLS::GetTipType reads the labware, whether the spot still
    # holds a tip or not (Marionette's 300 uL aspirates got the 1000 uL class from a used spot)
    spot = self.v.resolve(self.v.seq(tips).items[0])
    tip = spot.tip_for_pickup() if spot.has_tip() else spot.make_tip()
    # the nearest tip size: a 300 uL filter tip holds 360 uL, which rounded to 400 and fell back to
    # the 1000 uL class (Marionette: 25 aspirates at 250 uL/s where Venus drew at 100)
    name = CLASS_BY_TIP[min(CLASS_BY_TIP, key=lambda size: abs(size - tip.maximal_volume))]
    return name, self._lc(name)

  def _wells(self, items):
    return [self.v.resolve(it) for it in items]

  def _take(self, seq: str, n: int, counting: int) -> dict:
    taken = sq.take(self.v.seq(seq), "1" * n + "0" * (8 - n), counting)
    return {ch - 1: self.v.resolve(item) for ch, item in taken.channels.items()}

  async def aspirate(self, seq: str, volumes: Volumes, n: int, counting: int, tips: str, **kw):
    wells = self._take(seq, n, counting)
    await self.aspirate_wells([wells[c] for c in sorted(wells)], volumes, tips, **kw)

  async def dispense(self, seq: str, volumes: Volumes, n: int, counting: int, to_liquid: bool, **kw):
    wells = self._take(seq, n, counting)
    await self.dispense_wells([wells[c] for c in sorted(wells)], volumes, to_liquid, **kw)

  async def aspirate_wells(self, wells, volumes: Volumes, tips: str, mix: Optional[Mix] = None,
                           mix_position: float = 2.0, class_name: str = ""):
    """Channel i from wells[i]."""
    ch = list(range(len(wells)))
    name, lc = (class_name, self._lc(class_name)) if class_name else self._class(tips)
    step = Pipetting(CLLD, SUBMERGE, fluid_height=5.0, liquid_following=True, mix_position=mix_position,
                     **_mix_fields(mix), **RECORD)
    await steps.aspirate(self.p, wells, _per_channel(volumes, ch), ch, step, lc)
    self._last_class = lc

  async def dispense_wells(self, wells, volumes: Volumes, to_liquid: bool, mix: Optional[Mix] = None):
    ch = list(range(len(wells)))
    step = (Pipetting(CLLD, SUBMERGE, liquid_following=True, mix_position=2.0, **_mix_fields(mix), **RECORD)
            if to_liquid else
            Pipetting(0, SUBMERGE, fluid_height=DISPENSE_HEIGHT, liquid_following=True, mix_position=2.0,
                      **_mix_fields(mix), **RECORD))
    # the class's "Empty" (..._DispenseSurface_Empty) is a blow-out at the surface, firmware mode 3
    # as Venus sends it; PLR's `empty` is mode 4, emptying the tip where it stands
    await steps.dispense(self.p, wells, _per_channel(volumes, ch), ch, step, self._last_class,
                         blow_out=[True] * len(ch))

  # -- tips ------------------------------------------------------------------------------------

  async def tip_pickup(self, tips: str, number_channels: int):
    taken = self._take(tips, number_channels, sq.AUTOMATIC)
    ch = sorted(taken)
    await self.p.pick_up_tips([taken[c] for c in ch], use_channels=ch)

  async def tip_eject(self, number_channels: int):
    await steps.eject_to_waste(self.p, list(range(number_channels)))

  # -- the pattern -----------------------------------------------------------------------------

  def _check(self, asp: str, disp: str, n: int):
    """check_seq_lengths_and_channels: n source positions; the destination a multiple of n."""
    a, d = self.v.seq(asp).total, self.v.seq(disp).total
    if a != n or d % a:
      raise SubmethodError(f"GSF-IMS: {asp} has {a} positions for {n} channels, {disp} has {d}")

  async def fill(self, asp: str, disp: str, volumes: Volumes, tips: str, n: int, *,
                 prewet: bool = False, own_tips: bool = False, new_tips_each: bool = False,
                 to_liquid: bool = False, mix_after: Optional[Mix] = None,
                 mix_before: Optional[Mix] = None, mix_position: float = 2.0, class_name: str = "",
                 skip_zero: bool = False):
    """`volumes`: one volume for every slice, or a list of one per slice."""
    self._check(asp, disp, n)
    per_slice = isinstance(volumes, (list, tuple))
    if per_slice and len(volumes) * n != self.v.seq(disp).total:
      raise SubmethodError(f"GSF-IMS: {len(volumes)} volumes for {disp}'s {self.v.seq(disp).total} positions / {n}")
    if own_tips:
      await self.tip_pickup(tips, n)
    if prewet:
      top = max(volumes) if per_slice else volumes
      await self.aspirate(asp, top, n, sq.MANUAL, tips, class_name=class_name)
      await self.dispense(asp, top, n, sq.MANUAL, to_liquid=True)
    d = self.v.seq(disp)
    d.set_current_position(1)  # the editor's loop over the destination: from position 1
    for i, (targets, sources) in enumerate(sq.batches(n, d, self.v.seq(asp))):
      vols = volumes[i] if per_slice else volumes
      if skip_zero and not vols:  # the slice skipped (SeqIncrement(disp_seq, number_channels))
        continue
      if new_tips_each:
        await self.tip_pickup(tips, n)
      await self.aspirate_wells(self._wells(sources), vols, tips, mix=mix_before, mix_position=mix_position,
                                class_name=class_name)
      await self.dispense_wells(self._wells(targets), vols, to_liquid, mix=mix_after)
      if new_tips_each:
        await self.tip_eject(n)
    if own_tips:
      await self.tip_eject(n)

  # -- the library's entry points --------------------------------------------------------------

  async def pipette_media(self, asp_seq, disp_seq, p_vol, pre_wet_tips, tips, number_channels):
    await self.fill(asp_seq, disp_seq, p_vol, tips, number_channels, prewet=bool(pre_wet_tips))

  async def pipette_media_volume_arr(self, asp_seq, disp_seq, p_vol_arr, pre_wet_tips, tips,
                                     number_channels):
    await self.fill(asp_seq, disp_seq, list(p_vol_arr), tips, number_channels, prewet=bool(pre_wet_tips))

  async def add_reagent_reuse_tips(self, asp_seq, disp_seq, p_vol, pre_wet_tips,
                                   pickup_and_eject_tips, tips, number_channels):
    await self.fill(asp_seq, disp_seq, p_vol, tips, number_channels, prewet=bool(pre_wet_tips),
                    own_tips=bool(pickup_and_eject_tips), to_liquid=True)

  async def add_reagents_reuse_tips_vol_arr(self, asp_seq, disp_seq, p_vol_arr, pre_wet_tips,
                                            pickup_and_eject_tips, tips, number_channels):
    await self.fill(asp_seq, disp_seq, list(p_vol_arr), tips, number_channels,
                    prewet=bool(pre_wet_tips), own_tips=bool(pickup_and_eject_tips), to_liquid=True,
                    skip_zero=True)

  async def add_reagent_replace_tips(self, asp_seq, disp_seq, p_vol, mix_cycles, mix_volume, tips,
                                     number_channels):
    await self.fill(asp_seq, disp_seq, p_vol, tips, number_channels, new_tips_each=True,
                    to_liquid=True, mix_after=_mix(mix_cycles, mix_volume))

  async def pipette_cells_from_tubes(self, asp_seq, disp_seq, p_vol, mix_cycles, mix_volume, tips,
                                     number_channels):
    await self.fill(asp_seq, disp_seq, p_vol, tips, number_channels, own_tips=True, to_liquid=True,
                    mix_before=_mix(mix_cycles, mix_volume), mix_position=8.0, class_name=SERIES_CLASS)

  async def pipette_dil_series(self, from_seq, to_seq, p_vol, mix_cycles, mix_volume, tips,
                               number_channels):
    """Slice i of from_seq into slice i of to_seq, mixing the source first, on one set of tips."""
    f, t = self.v.seq(from_seq), self.v.seq(to_seq)
    if f.total != t.total:
      raise SubmethodError(f"GSF-IMS: {from_seq} has {f.total} positions, {to_seq} {t.total}")
    n = number_channels
    await self.tip_pickup(tips, n)
    f.set_current_position(1)
    t.set_current_position(1)
    for sources, targets in sq.batches(n, f, t, advance=(True,)):
      await self.aspirate_wells(self._wells(sources), p_vol, tips, mix=_mix(mix_cycles, mix_volume),
                                mix_position=3.0, class_name=SERIES_CLASS)
      await self.dispense_wells(self._wells(targets), p_vol, to_liquid=True)
    await self.tip_eject(n)

  async def simple_aspirate(self, asp_seq, asp_seq_counting, p_vol, tips, number_channels):
    await self.aspirate(asp_seq, p_vol, number_channels, int(asp_seq_counting), tips)

  async def simple_dispense(self, disp_seq, disp_seq_counting, disp_to_liquid, p_vol, mix_cycles,
                            mix_volume, number_channels):
    await self.dispense(disp_seq, p_vol, number_channels, int(disp_seq_counting), bool(disp_to_liquid),
                        mix=_mix(mix_cycles, mix_volume))


def _mix_fields(mix: Optional[Mix]) -> dict:
  return dict(mix_cycles=mix.repetitions, mix_volume=mix.volume) if mix else {}


def _mix(cycles, volume) -> Optional[Mix]:
  return Mix(volume=float(volume), repetitions=int(cycles), flow_rate=steps.MIX_FLOW) if cycles and volume else None


def _per_channel(volumes: Volumes, channels: list) -> list:
  if isinstance(volumes, (list, tuple)):
    return [float(volumes[c]) for c in channels]
  return [float(volumes)] * len(channels)
