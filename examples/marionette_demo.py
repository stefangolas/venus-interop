"""NIST LMSF "Marionette protease gradient plate prep v5" on a simulated STAR, for the 3D viewer.

The method's operational logic (docs/notes/LMSF_OPERATIONAL_LOGIC.md section 2) on its own deck: the
layout is imported with `plr_import.lay_to_plr`, and every step names its wells by the layout's
sequences, as the method does, so the plate map is the layout's and not retyped here.

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
  - Liquid classes, dry versus in-liquid dispensing, and the gripper's grip heights are PLR's
    defaults: the method's are in Venus's liquid-class database, not read yet.
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

from nist_deck import Gripper, VenusDeck, chunks, give_room, install, make_room  # noqa: E402

from pylabrobot.hamilton.star.device import RECORDING_STAR, STARDevice  # noqa: E402
from pylabrobot.lib.liquid_handling.mix import Mix  # noqa: E402
from pylabrobot.resources import Resource, set_tip_tracking, set_volume_tracking  # noqa: E402

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


@dataclass
class Volumes:
  """The method's volume model, as `main` computes it."""

  media: float
  transfer: float  # dil_series_transf_vol
  multiplier: float  # dil_series_multiplier
  with_tmp: bool
  tmp: float
  grad_start_tmp: float
  van_grad_add_sal: float
  van_grad_start_add_sal: float
  grad_start_media: float
  van: float
  grad_start_van: float
  grad_start_sal: Sequence[float]


def volumes(p: Parameters) -> Volumes:
  culture = min(max(p.culture_volume, 200.0), 500.0)
  m = p.dilution_series_factor / (p.dilution_series_factor - 1.0)
  media = culture - culture / p.dilution_factor
  first_tmp_plate = 3
  with_tmp = p.plate_number >= first_tmp_plate
  inducer_ref = culture if p.plate_number < first_tmp_plate else media
  tmp_ref = media if p.plate_number > first_tmp_plate else culture
  tmp = tmp_ref / p.sal_tmp_stock_dilution if with_tmp else 0.0
  van_grad_add_sal = inducer_ref / p.sal_tmp_stock_dilution
  van = inducer_ref / p.van_stock_dilution
  start_dilution = [s / g for s, g in zip(p.sal_stock_conc, p.sal_grad_max_conc)]
  return Volumes(
    media=media, transfer=media * m - media, multiplier=m, with_tmp=with_tmp, tmp=tmp,
    grad_start_tmp=tmp * m, van_grad_add_sal=van_grad_add_sal, van_grad_start_add_sal=van_grad_add_sal * m,
    grad_start_media=media * m, van=van, grad_start_van=van * m,
    grad_start_sal=[inducer_ref / d * m for d in start_dilution],
  )


class Marionette:
  """The method, step by step; `say` reports each one."""

  def __init__(self, star: STARDevice, v: VenusDeck, vol: Volumes, say=print):
    self.star, self.v, self.vol, self.say = star, v, vol, say
    self.p = star.pipettes
    self.g = Gripper(star, v, say)

  # -- the shared library's helpers (GSF-IMS.shared_submethods) ------------------------------------

  async def tip_pickup(self, tips: str, n: int) -> None:
    await self.p.pick_up_tips(self.v.next_tips(tips, n), use_channels=list(range(n)))

  async def tip_eject(self, n: int) -> None:
    await self.p.discard_tips(use_channels=list(range(n)))

  async def transfer(self, source, targets, volume: float, n: int, mix: Optional[Mix] = None) -> None:
    ch = list(range(n))
    await self.p.aspirate(source, [volume] * n, use_channels=ch,
                          pre_mixes=[mix] * n if mix else None)
    await self.p.dispense(targets, [volume] * n, use_channels=ch)

  async def pipette_media(self, asp: str, disp: str, volume: float, pre_wet: bool, n: int) -> None:
    source = self.v.items(asp)
    if pre_wet:
      await self.transfer(source, source, volume, n)
    for targets in chunks(self.v.items(disp), n):
      await self.transfer(source, targets, volume, n)

  async def add_reagent_reuse_tips(self, asp: str, disp: str, volume: float, pre_wet: bool, n: int) -> None:
    await self.pipette_media(asp, disp, volume, pre_wet, n)

  async def add_reagent_replace_tips(self, asp: str, disp: str, volume: float, tips: str, n: int) -> None:
    source = self.v.items(asp)
    for targets in chunks(self.v.items(disp), n):
      await self.tip_pickup(tips, n)
      await self.transfer(source, targets, volume, n)
      await self.tip_eject(n)

  async def pipette_dil_series(self, from_seq: str, to_seq: str, volume: float, tips: str, n: int) -> None:
    sources, targets = chunks(self.v.items(from_seq), n), chunks(self.v.items(to_seq), n)
    if len(sources) != len(targets):
      raise ValueError(f"{from_seq} and {to_seq} differ in length")
    await self.tip_pickup(tips, n)
    mix = Mix(volume=volume, repetitions=2, flow_rate=250.0)
    for source, target in zip(sources, targets):
      await self.transfer(source, target, volume, n, mix=mix)
    await self.tip_eject(n)

  # -- moves ---------------------------------------------------------------------------------------

  async def move_lid_to_park(self, lid_seq: str, park_placeholder: str) -> Resource:
    return await self.g.to_placeholder(self.v.labware(lid_seq), park_placeholder)

  async def put_lid_back(self, lid: Resource, plate: Resource) -> None:
    await self.g.onto(lid, plate)

  # -- the method ----------------------------------------------------------------------------------

  async def run(self) -> None:
    v, vol = self.v, self.vol
    T1000, T300 = "Tips_1000_Channels", "Tips_300_Channels"

    # The Growth Plate, with its lid, from the handoff to its position
    plate = await self.g.to_placeholder(v.labware("Move_Growth_Plate_Handoff"), "Growth_Plate")
    gp_lid = await self.move_lid_to_park("Growth_Plate_Handoff_lid", "Lid_parking_Growth_Plate")
    media_lid = await self.move_lid_to_park("Media_source_lid", "Media_trough_lid_parking")
    media_trough = media_lid_plate = v.resource("Media_source")

    self.say("media")
    await self.tip_pickup(T1000, 4)
    media = "Media_pipette_from_4"
    await self.pipette_media(media, "regular_wells_with_tmp_sal_grad", vol.media - vol.tmp, True, 4)
    await self.pipette_media(media, "regular_wells_with_tmp_van_grad",
                             vol.media - vol.van_grad_add_sal - vol.tmp, False, 4)
    await self.pipette_media(media, "sal_1_grad_start",
                             vol.grad_start_media - vol.grad_start_sal[0] - vol.grad_start_tmp, False, 4)
    await self.pipette_media(media, "sal_2_grad_start",
                             vol.grad_start_media - vol.grad_start_sal[1] - vol.grad_start_tmp, False, 4)
    await self.pipette_media(media, "van_grad_start_wells_with_tmp",
                             vol.grad_start_media - vol.grad_start_van - vol.van_grad_start_add_sal
                             - vol.grad_start_tmp, False, 4)
    await self.pipette_media(media, "regular_wells_no_tmp_no_van", vol.media, False, 4)
    await self.pipette_media(media, "regular_wells_no_tmp_with_van", vol.media - vol.van, False, 4)
    await self.tip_eject(4)

    await self.put_lid_back(media_lid, media_lid_plate)
    stock_lid = await self.move_lid_to_park("Reagent_Stock_Plate_lid", "Reagent_Stock_lid_parking")
    stock_plate = v.resource("Reagent_Stock_Plate")

    for k, stock in ((0, "Sal_stock_1_4"), (1, "Sal_stock_2_4")):
      self.say(f"salicylate stock {k + 1}")
      await self.tip_pickup(T300, 4)
      await self.add_reagent_reuse_tips(stock, f"sal_{k + 1}_grad_start", vol.grad_start_sal[k], True, 4)
      await self.add_reagent_reuse_tips(stock, f"van_grad_start_wells_with_sal_{k + 1}",
                                        vol.van_grad_start_add_sal, False, 4)
      await self.add_reagent_reuse_tips(stock, f"regular_wells_with_sal_{k + 1}", vol.van_grad_add_sal, False, 4)
      await self.tip_eject(4)

    if vol.with_tmp:  # not gated by is_pipetting in the method
      self.say("TMP")
      await self.add_reagent_replace_tips("TMP_stock", "regular_wells_with_tmp_sal_grad", vol.tmp, T300, 8)
      await self.add_reagent_replace_tips("TMP_stock", "regular_wells_with_tmp_van_grad", vol.tmp, T300, 8)
      await self.add_reagent_replace_tips("TMP_stock", "sal_grad_start_wells_add_tmp", vol.grad_start_tmp, T300, 8)
      await self.add_reagent_replace_tips("TMP_stock", "van_grad_start_wells_with_tmp", vol.grad_start_tmp, T300, 8)

    self.say("vancomycin")
    await self.add_reagent_replace_tips("Van_stock_1", "van_grad_start_wells_with_tmp", vol.grad_start_van, T1000, 8)
    await self.add_reagent_replace_tips("Van_stock_1_4", "regular_wells_no_tmp_with_van", vol.van, T1000, 4)

    self.say("serial dilutions")  # not gated by is_pipetting in the method
    await self.pipette_dil_series("van_gradient_pipette_from", "van_gradient_pipette_to", vol.transfer, T1000, 8)
    await self.pipette_dil_series("sal_grad_pipette_from", "sal_grad_pipette_to", vol.transfer, T1000, 8)

    await self.put_lid_back(stock_lid, stock_plate)
    await self.put_lid_back(gp_lid, plate)
    del media_trough


def fill(v: VenusDeck, vol: Volumes) -> None:
  """The sources full enough for the run, the wells that take liquid able to hold it."""
  give_room(v.items("Media_pipette_from_4"), 30_000.0)
  for seq in ("Sal_stock_1_4", "Sal_stock_2_4", "TMP_stock", "Van_stock_1", "Van_stock_1_4"):
    give_room(v.items(seq), 5_000.0)
  # the dilution series end in the waste trough; the Growth Plate is not on the deck yet
  make_room(v.resource("Liquid_waste").get_all_items(), 20_000.0)


def report(v: VenusDeck, vol: Volumes) -> None:
  plate = v.resource("Growth_Plate")
  got = [round(w.tracker.get_used_volume(), 1) for w in plate.get_all_items()]
  print(f"Growth Plate: every well {vol.media:.1f} uL expected; min {min(got)}, max {max(got)}")
  by_column = {c + 1: sorted(set(got[c * 8:c * 8 + 8])) for c in range(12)}
  for c, values in by_column.items():
    print(f"  column {c:2}: {values}")


TRACE = "Marionette protease.gradient plate prep.v5.condensed.md"


async def main(corpus: pathlib.Path, view: bool, p: Parameters, trace: pathlib.Path) -> None:
  logging.disable(logging.WARNING)
  warnings.simplefilter("ignore")
  set_volume_tracking(True)
  set_tip_tracking(True)
  v = VenusDeck(corpus, LAYOUT)
  install(v)
  print("not on the deck at the start:", ", ".join(v.clear_absent(trace)))
  vol = volumes(p)
  print(f"volumes: media {vol.media:.1f}, transfer {vol.transfer:.1f}, x{vol.multiplier:.2f}, "
        f"TMP {vol.tmp:.1f}, salicylate starts {[round(x, 1) for x in vol.grad_start_sal]}, "
        f"vancomycin {vol.van:.1f} / start {vol.grad_start_van:.1f}")
  star = STARDevice(deck=v.deck, simulation=True, declared_configuration_json=RECORDING_STAR,
                    name="STAR")
  await star.setup()
  fill(v, vol)

  if view:
    from pylabrobot.hamilton.star.motion import attach_viewer_motion
    from pylabrobot.visualizer3D.server import Viewer3D

    viewer = Viewer3D(star, name="marionette_demo.py", open_browser=False)
    await viewer.start()
    attach_viewer_motion(star.driver, viewer)
    print("viewer:", getattr(viewer, "url", ""), flush=True)
    await viewer.wait_for_browser()
    await asyncio.sleep(1.0)

  await Marionette(star, v, vol).run()
  report(v, vol)
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
  ap.add_argument("--culture-volume", type=float, default=500.0)
  a = ap.parse_args()
  trace = a.trace or a.corpus.parent / "analysis" / "traces" / TRACE
  asyncio.run(main(a.corpus, a.view, Parameters(culture_volume=a.culture_volume, plate_number=a.plate), trace))
