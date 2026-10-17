"""NIST LMSF "Marionette protease gradient plate prep v5" on a simulated STAR, for the 3D viewer.

The method's `main`, call for call, on Python ports of its two libraries (`venus_interop.plr.libraries`:
GSF-IMS shared submethods, PlateAndLidMovement), on its own deck imported with
`plr_import.lay_to_plr`. Sequences follow Venus's rules (`methods.sequences`), so every step uses the
wells and tips the method does; the GSF-IMS port is checked against the HSL library step for step
(tests/test_gsf_ims_port.py).

  python marionette_demo.py --corpus DIR            headless: runs, checks the volumes, prints them
  python marionette_demo.py --corpus DIR --view     serves the viewer and plays the run

`--corpus` is the layout corpus (`raw/3ed5809e547e.lay` and the definitions it uses). Run on the PLR
fork's `nist-viz` branch (upstream main + PR 1470's motion and collisions), with it on PYTHONPATH.

What the method gets from its parameters file, which is not in the NIST repository, is given here as
options; the defaults are illustrative, chosen so every volume is one a channel can move.

Deviations from the method, and why:
  - The deck is Venus's: a plate or lid that moves is a different labware at each place in Venus, so
    a move hands the object to the holder the destination's placeholder stood on, and later
    sequences that name the placeholder resolve to the object that moved there.
  - The CO-RE grip tools and the tip waste are PLR's (`hamilton_core_gripper_1000ul_5ml_on_waste`,
    a `Trash`), put where the layout has its own: PLR's gripper needs its holder, and the imported
    labware is only a box.
  - Reservoir "wells" are Venus's pipetting positions in one cavity, so the ones used are given
    room for the whole run's liquid.
  - Liquid classes: the libraries' own by name where PLR has them; the FastMixing ones it lacks are
    listed at the end of a run and PLR's default is used, until Venus's liquid-class database is read.
  - The 1 mm "tap" of PlateAndLidMovement's plate moves is not drawn: PLR puts a plate on its site.
"""

import argparse
import asyncio
import logging
import pathlib
import sys
import warnings
from dataclasses import dataclass
from typing import Optional, Sequence

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from nist_deck import VenusDeck, give_room, install, make_room  # noqa: E402

from venus_interop.plr.libraries.common_96head import Common96HeadSubMethods  # noqa: E402
from venus_interop.plr.libraries.gsf_ims import GsfIms  # noqa: E402
from venus_interop.plr.libraries.plate_and_lid import PlateAndLidMovement  # noqa: E402
from venus_interop.plr.libraries.tip_count import TipCount, TipCounters  # noqa: E402
from venus_interop.plr.libraries.tip_handling_96 import TipHandling96  # noqa: E402
from venus_interop.plr.liquid_classes import VenusLiquidClasses  # noqa: E402

from pylabrobot.hamilton.star.device import RECORDING_STAR, STARDevice  # noqa: E402
from pylabrobot.resources import set_tip_tracking, set_volume_tracking  # noqa: E402

LAYOUT = "3ed5809e547e.lay"  # Fitness Selection.Marionette protease.v5.lay


@dataclass
class Parameters:
  """The method's parameters (`GetParams`); the defaults are illustrative."""

  culture_volume: float = 500.0  # uL; the method clamps it to 200-500
  dilution_factor: float = 10.0  # culture : cells
  plate_number: int = 3  # 2-5; TMP from plate 3 on
  van_stock_dilution: float = 50.0
  sal_tmp_stock_dilution: float = 50.0
  dilution_series_factor: float = 2.0
  sal_stock_conc: Sequence[float] = (1750.0, 2500.0)  # stocks 1 and 2, in the units of the maxima
  sal_grad_max_conc: Sequence[float] = (35.0, 50.0)  # the method's defaults
  is_pipetting: bool = True


class Marionette:
  """The method's `main`, call for call, on the Python ports of its libraries."""

  # main's tip sequences, in the order of GetTipCounters' counters
  TIP_SEQUENCES = ["Tips_1000_Channels", "Tips_300_Channels", "Tips_50_Channels", "Tips_1000_Offset_pickup"]

  def __init__(self, star: STARDevice, v: VenusDeck, p: Parameters, say=print,
               counters: Optional[TipCounters] = None, liquid_classes: Optional[VenusLiquidClasses] = None):
    self.v, self.par, self.say = v, p, say
    self.gsf = GsfIms(star, v, say, liquid_classes=liquid_classes)
    self.plm = PlateAndLidMovement(star, v, say=say)
    self.c96 = Common96HeadSubMethods(star, v, say)
    self.tips = TipCount(v, counters or TipCounters())

  async def run(self) -> None:
    p, gsf, plm = self.par, self.gsf, self.plm
    seq = self.v.seq
    T1000, T300, MEDIA = "Tips_1000_Channels", "Tips_300_Channels", "Media_pipette_from_4"
    GRIP = "COREGripTool_OnWaste_1000ul_0001"

    # the tip racks as the last run left them (no counter stored: as the layout has them)
    counters = TipHandling96().GetTipCounters(1)
    for tips, counter in zip(self.TIP_SEQUENCES, counters):
      self.tips.Read2(tips, counter)

    await plm.MoveGrowthPlateWithLid("Move_Growth_Plate_Handoff", "Growth_Plate_Handoff_lid",
                                     "Move_Growth_Plate", "Growth_Plate_lid", GRIP, 1, 0)
    await plm.MoveLid("Growth_Plate_lid", "Lid_parking_Growth_Plate", GRIP, 0, 0)
    await plm.MoveLid("Media_source_lid", "Lid_parking_Media_trough", GRIP, 0, 1)

    # main's volume model
    culture = min(max(p.culture_volume, 200.0), 500.0)  # GetParams clamps it
    m = p.dilution_series_factor / (p.dilution_series_factor - 1.0)
    cell = culture / p.dilution_factor
    media = culture - cell
    transfer = media * m - media
    first_tmp_plate = 3
    with_tmp = p.plate_number >= first_tmp_plate
    inducer_ref = culture if p.plate_number < first_tmp_plate else media
    tmp_ref = media if p.plate_number > first_tmp_plate else culture
    tmp = tmp_ref / p.sal_tmp_stock_dilution if with_tmp else 0.0
    grad_start_tmp = tmp * m
    van_grad_add_sal = inducer_ref / p.sal_tmp_stock_dilution
    van_grad_start_add_sal = van_grad_add_sal * m
    grad_start_media = media * m
    van = inducer_ref / p.van_stock_dilution
    grad_start_van = van * m
    sal_1, sal_2 = (inducer_ref / (s / g) * m for s, g in zip(p.sal_stock_conc, p.sal_grad_max_conc))
    self.say(f"volumes: media {media:.1f}, transfer {transfer:.1f}, TMP {tmp:.1f}, "
             f"salicylate starts {sal_1:.1f} {sal_2:.1f}, vancomycin {van:.1f} / start {grad_start_van:.1f}")

    if p.is_pipetting:
      await gsf.tip_pickup(T1000, 4)
      await gsf.pipette_media(MEDIA, "regular_wells_with_tmp_sal_grad", media - tmp, 1, T1000, 4)
      await gsf.pipette_media(MEDIA, "regular_wells_with_tmp_van_grad", media - van_grad_add_sal - tmp, 0, T1000, 4)
      await gsf.pipette_media(MEDIA, "sal_1_grad_start", grad_start_media - sal_1 - grad_start_tmp, 0, T1000, 4)
      await gsf.pipette_media(MEDIA, "sal_2_grad_start", grad_start_media - sal_2 - grad_start_tmp, 0, T1000, 4)
      await gsf.pipette_media(MEDIA, "van_grad_start_wells_with_tmp",
                              grad_start_media - grad_start_van - van_grad_start_add_sal - grad_start_tmp, 0, T1000, 4)
      await gsf.pipette_media(MEDIA, "regular_wells_no_tmp_no_van", media, 0, T1000, 4)
      await gsf.pipette_media(MEDIA, "regular_wells_no_tmp_with_van", media - van, 0, T1000, 4)
      await gsf.tip_eject(4)
      for name in ("regular_wells_with_tmp_sal_grad", "regular_wells_with_tmp_van_grad", "sal_1_grad_start",
                   "sal_2_grad_start", "van_grad_start_wells_with_tmp", "regular_wells_no_tmp_with_van"):
        seq(name).reset()

    await plm.MoveLid("Lid_parking_Media_trough", "Media_source_lid", GRIP, 1, 0)
    await plm.MoveLid("Reagent_Stock_Plate_lid", "Lid_parking_Reagent_Stock", GRIP, 0, 1)

    if p.is_pipetting:
      for k, (stock, start) in enumerate((("Sal_stock_1_4", sal_1), ("Sal_stock_2_4", sal_2)), start=1):
        await gsf.tip_pickup(T300, 4)
        await gsf.add_reagent_reuse_tips(stock, f"sal_{k}_grad_start", start, 1, 0, T300, 4)
        await gsf.add_reagent_reuse_tips(stock, f"van_grad_start_wells_with_sal_{k}", van_grad_start_add_sal, 0, 0, T300, 4)
        await gsf.add_reagent_reuse_tips(stock, f"regular_wells_with_sal_{k}", van_grad_add_sal, 0, 0, T300, 4)
        await gsf.tip_eject(4)

    if with_tmp:  # not gated by is_pipetting in the method
      await gsf.add_reagent_replace_tips("TMP_stock", "regular_wells_with_tmp_sal_grad", tmp, 0, 0, T300, 8)
      await gsf.add_reagent_replace_tips("TMP_stock", "regular_wells_with_tmp_van_grad", tmp, 0, 0, T300, 8)
      await gsf.add_reagent_replace_tips("TMP_stock", "sal_grad_start_wells_add_tmp", grad_start_tmp, 0, 0, T300, 8)
      await gsf.add_reagent_replace_tips("TMP_stock", "van_grad_start_wells_with_tmp", grad_start_tmp, 0, 0, T300, 8)
      seq("sal_grad_start_wells_add_tmp").reset()
      seq("van_grad_start_wells_with_tmp").reset()

    if p.is_pipetting:
      await gsf.add_reagent_replace_tips("Van_stock_1", "van_grad_start_wells_with_tmp", grad_start_van, 0, 0, T1000, 8)
      await gsf.add_reagent_replace_tips("Van_stock_1_4", "regular_wells_no_tmp_with_van", van, 0, 0, T1000, 4)

    # not gated by is_pipetting in the method
    await gsf.pipette_dil_series("van_gradient_pipette_from", "van_gradient_pipette_to", transfer, 2, transfer, T1000, 8)
    await gsf.pipette_dil_series("sal_grad_pipette_from", "sal_grad_pipette_to", transfer, 2, transfer, T1000, 8)

    await plm.MoveLid("Lid_parking_Reagent_Stock", "Reagent_Stock_Plate_lid", GRIP, 1, 0)
    await plm.MoveLid("Lid_parking_Growth_Plate", "Growth_Plate_lid", GRIP, 0, 1)
    for tips, counter in zip(self.TIP_SEQUENCES, counters):  # CleanUp
      self.tips.Write2(tips, counter)
    await self.c96.Clear96HeadAndArm(None, "clear_96_head_seq")
    if gsf.missing_classes:
      self.say("liquid classes PLR lacks (its default used): " + ", ".join(sorted(gsf.missing_classes)))
    self.media = media


def fill(v: VenusDeck) -> None:
  """The sources full enough for the run, the wells that take liquid able to hold it."""
  give_room(v.items("Media_pipette_from_4"), 30_000.0)
  for seq in ("Sal_stock_1_4", "Sal_stock_2_4", "TMP_stock", "Van_stock_1", "Van_stock_1_4"):
    give_room(v.items(seq), 5_000.0)
  # The dilution series end in the waste trough, dispensing to the liquid (cLLD): dry, Venus raises
  # a Liquid Level error there (repeat once, then the operator), so the trough starts with a heel.
  # The Growth Plate is not on the deck yet.
  waste = v.resource("Liquid_waste").get_all_items()
  give_room(waste, 1_000.0)
  make_room(waste, 20_000.0)


def report(v: VenusDeck, media: float) -> None:
  plate = v.resource("Growth_Plate")
  got = [round(w.tracker.get_used_volume(), 1) for w in plate.get_all_items()]
  # A cLLD search hands the well's tracker the volume it measured, read to 0.1 mm, so the wells
  # dispensed into to the liquid end a few uL either side.
  print(f"Growth Plate: every well {media:.1f} uL expected, give or take the cLLD reads; "
        f"min {min(got)}, max {max(got)}")
  by_column = {c + 1: sorted(set(got[c * 8:c * 8 + 8])) for c in range(12)}
  for c, values in by_column.items():
    print(f"  column {c:2}: {values}")


TRACE = "Marionette protease.gradient plate prep.v5.condensed.md"


async def main(corpus: pathlib.Path, view: bool, p: Parameters, trace: pathlib.Path,
               tip_counters: Optional[pathlib.Path] = None, liquid_classes: Optional[pathlib.Path] = None) -> None:
  logging.disable(logging.WARNING)
  warnings.simplefilter("ignore")
  set_volume_tracking(True)
  set_tip_tracking(True)
  v = VenusDeck(corpus, LAYOUT)
  install(v)
  print("not on the deck at the start:", ", ".join(v.clear_absent(trace)))
  star = STARDevice(deck=v.deck, simulation=True, declared_configuration_json=RECORDING_STAR,
                    name="STAR")
  await star.setup()
  fill(v)

  if view:
    from pylabrobot.hamilton.star.motion import attach_viewer_motion
    from pylabrobot.visualizer3D.server import Viewer3D

    viewer = Viewer3D(star, name="marionette_demo.py", open_browser=False)
    await viewer.start()
    attach_viewer_motion(star.driver, viewer)
    print("viewer:", getattr(viewer, "url", ""), flush=True)
    await viewer.wait_for_browser()
    await asyncio.sleep(1.0)

  method = Marionette(star, v, p, counters=TipCounters(tip_counters),
                      liquid_classes=VenusLiquidClasses.from_json(liquid_classes) if liquid_classes else None)
  await method.run()
  report(v, method.media)
  if view:
    print("done", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
  ap = argparse.ArgumentParser()
  ap.add_argument("--corpus", type=pathlib.Path, required=True)
  ap.add_argument("--trace", type=pathlib.Path,
                  help="the method's trace; the corpus's sibling analysis/traces/the method's .condensed.md when not given")
  ap.add_argument("--view", action="store_true")
  ap.add_argument("--plate", type=int, default=3, help="plate number, 2-5 (TMP from 3 on)")
  ap.add_argument("--liquid-classes", type=pathlib.Path,
                  help="the method's liquid classes as JSON (tools/liquid_classes.py on NIST's Config/ML_STARLiquids.mdb); "
                       "PLR's STAR table when not given, which lacks the GSF-IMS FastMixing classes")
  ap.add_argument("--tip-counters", type=pathlib.Path,
                  help="a JSON file of Venus tip counters, read at the start and written at the end, as "
                       "the method's TipCount::Read2/Write2: the racks carry over between runs")
  ap.add_argument("--culture-volume", type=float, default=500.0)
  a = ap.parse_args()
  trace = a.trace or a.corpus.parent / "analysis" / "traces" / TRACE
  asyncio.run(main(a.corpus, a.view, Parameters(culture_volume=a.culture_volume, plate_number=a.plate), trace,
                   a.tip_counters, a.liquid_classes))
