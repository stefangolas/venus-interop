"""NIST LMSF "DNA Extraction" on a simulated STAR with a simulated MPE², for the 3D viewer.

The method's operational logic (docs/notes/LMSF_OPERATIONAL_LOGIC.md section 1) on its own deck,
the elution through the MPE² with the gripper doing the plate moves (`use_iSWAP`, no spin), for one
3-column set of 24 samples (`sequence_number`). The layout is imported with `plr_import.lay_to_plr`
and every step names its wells by the layout's sequences, as the method does.

  python dna_extraction_demo.py --corpus DIR            headless: runs, checks the volumes
  python dna_extraction_demo.py --corpus DIR --view     serves the viewer and plays the run

Run on the PLR fork's `nist-viz` branch (upstream main + PR 1470 + the MPE² package), with it on
PYTHONPATH; `--corpus` is the layout corpus.

What it shows, step for step with the method:
  01   supernatant off the pellets (8 channels, 1000 uL then the rest, per column)
  01A  P1 onto the pellets, resuspended and moved to the lysate plate (8 channels)
  02   P2 (96-head, 24 nozzles from the offset support), a 120 s shake; the spin plate to waste
  03   N3 (96-head), a 120 s shake
  04   the receiving and filter plates onto the MPE², the lysate onto the filter with the pre-cut
       wide-bore tips (96-head), pressed through into the receiving plate; both plates back
  05   the binding plate onto the MPE², the cleared lysate onto it (96-head), pressed to waste
  06   PB wash, 07 PE wash and a 420 s dry, each pressed to waste
  08   the binding plate onto the elution plate, elution buffer (8 channels), 300 s, both onto the
       MPE², pressed into the elution plate; both plates back to storage

Deviations from the method, and why:
  - Plates and lids are objects that move (`nist_deck.VenusDeck`); the method's re-seating moves
    (a plate lifted and put back where it was, 4 or 7 mm high) are left out, as they change nothing
    the model has.
  - "Aspirate mode 2" draws what the well holds: the method uses it exactly where it asks for more
    than is there (300 uL from ~200 resuspended, 900 uL from ~800 of lysate).
  - The MPE² is `MPE2SimulationDriver`; its liquid is moved here, well for well: the filter plate's
    into the plate under it, or to waste.
  - The heater-shakers are their waits; the handoff tip rack is refilled before each renewal, as
    the operator or scheduler does.
  - Liquid classes and grip heights are PLR's defaults; the tip redefinition (`C0TT`) is a PLR tip
    79.8 mm long, which PLR defines to the firmware itself.
"""

import argparse
import asyncio
import logging
import pathlib
import sys
import warnings
from typing import List, Optional

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from nist_deck import Gripper, VenusDeck, chunks, give_room, install, make_room  # noqa: E402

from pylabrobot.hamilton.mpe2 import MPE2SimulationDriver, SPEControlState  # noqa: E402
from pylabrobot.hamilton.star.device import RECORDING_STAR, STARDevice  # noqa: E402
from pylabrobot.lib.liquid_handling.head_alignment import get_items_under_channels  # noqa: E402
from pylabrobot.lib.liquid_handling.mix import Mix  # noqa: E402
from pylabrobot.resources import Plate, TipRack, set_tip_tracking, set_volume_tracking  # noqa: E402
from pylabrobot.resources.hamilton import HamiltonTip  # noqa: E402

LAYOUT = "ce242e85d05d.lay"  # Fitness Selection 2.With DNA Extraction.lay
WIDE_BORE_LENGTH = 79.8  # mm, the method's `wide_bore_length`: firmware length 71.8 + fitting 8
FP_ON_RP = (86.5, 86.5)  # MPE² filter / nozzle height of the filter plate stacked on the RP, mm
BP = (31.35, 38.4)  # of the Nunc binding plate
EP_HEIGHT, BP_NOZZLE_OFFSET = 14.35, 0.0
# Two labware at one site that are one plate: the P1 sequences name the spin plate this way
SAME_PLATE = {"Spin_Plate_2": "Spin_Plate"}


class DNAExtraction:
  def __init__(self, star: STARDevice, v: VenusDeck, mpe: MPE2SimulationDriver, set_no: int = 1,
               culture_volume: float = 500.0, time_scale: float = 0.0, model=None, say=print):
    self.star, self.v, self.mpe, self.n, self.say = star, v, mpe, set_no, say
    self.model = model  # an MPE2Model, when the animated model is drawn
    self.culture = min(max(culture_volume, 200.0), 500.0)
    self.time_scale = time_scale
    self.p, self.h = star.pipettes, star.head96
    self.g = Gripper(star, v, say)
    self.offset_columns: List[int] = []  # the offset support's 3-column blocks still holding tips

  # -- helpers -------------------------------------------------------------------------------------

  async def wait(self, seconds: float, what: str) -> None:
    self.say(f"{what}: {seconds:.0f} s")
    if self.time_scale:
      await asyncio.sleep(seconds * self.time_scale)

  def set_seq(self, base: str) -> str:
    return f"{base}_{self.n}"

  async def channels(self, tips: str, steps) -> None:
    """8-channel passes, new tips each: `steps(pass_index)` does the aspirates and dispenses."""
    passes = len(steps)
    for i in range(passes):
      await self.p.pick_up_tips(self.v.next_tips(tips, 8), use_channels=list(range(8)))
      await steps[i]()
      await self.p.discard_tips(use_channels=list(range(8)))

  async def move8(self, source, target, volume: Optional[float] = None, mix: Optional[Mix] = None):
    """Aspirate from 8 wells and dispense into 8; `volume` None draws what each holds."""
    vols = [w.tracker.get_used_volume() if volume is None else volume for w in source]
    ch = list(range(8))
    await self.p.aspirate(source, vols, use_channels=ch, pre_mixes=[mix] * 8 if mix else None)
    await self.p.dispense(target, vols, use_channels=ch)

  @staticmethod
  def under_head(plate: Plate, first_column: int) -> list:
    """The wells under the head's 96 channels with its column 1 over `first_column`."""
    return get_items_under_channels(plate, "A1", f"A{first_column}")

  @staticmethod
  def column_of(seq_items) -> int:
    return seq_items[0].parent.get_child_column(seq_items[0]) + 1

  async def head24(self, source_seq: str, target_seq: str, volume: Optional[float],
                   mix: Optional[Mix] = None, wide_bore: bool = False) -> None:
    """A 96-head transfer with 24 nozzles: from the offset support, or the wide-bore one."""
    v = self.v
    if wide_bore:
      rack: TipRack = v.resource("TipSupport_1000_WideBore")
      await self.h.pick_up_tips(rack, channel="A1", tip_spot="A10")
    else:
      if not self.offset_columns:
        await self.renew_offset_tips()
      column = self.offset_columns.pop(0)
      await self.h.pick_up_tips(v.resource("TipSupport_1000_offset"), channel="A1", tip_spot=f"A{column}")
    source, target = v.items(source_seq), v.items(target_seq)
    src = self.under_head(source[0].parent, self.column_of(source))
    dst = self.under_head(target[0].parent, self.column_of(target))
    draw = volume if volume is not None else min(w.tracker.get_used_volume() for w in source)
    if mix is not None and volume is None:  # the method mixes 0.75 x the draw
      mix = Mix(volume=round(0.75 * draw, 1), repetitions=mix.repetitions, flow_rate=mix.flow_rate)
    # The method's 96-head classes all end "_Empty", Hamilton's word for blowing out; its dispense
    # mode is "surface, empty". Dispensing with `empty` pushes out all the tip holds: dispensing
    # the drawn volume is refused by a rounding difference under 0.1 uL in the simulated piston.
    await self.h.aspirate(src, draw, pre_mix=mix, blow_out=True)
    await self.h.dispense(dst, draw, blow_out=True, empty=True)
    await self.h.discard_tips()

  async def renew_offset_tips(self) -> None:
    """RenewOffsetTips: what is left on the offset support to waste, a full rack onto it."""
    v = self.v
    offset: TipRack = v.resource("TipSupport_1000_offset")
    handoff: TipRack = v.resource("Tips_1000_Handoff")
    self.say("renew the offset tips")
    if any(spot.has_tip() for spot in offset.get_all_items()):
      await self.h.pick_up_tips(offset)
      await self.h.discard_tips()
    handoff.fill()  # the operator's or scheduler's fresh rack
    await self.h.pick_up_tips(handoff)
    await self.h.drop_tips(offset)
    self.offset_columns = [10, 7, 4, 1]  # Tips_1000_Offset_pickup: columns 12-10 first, then back

  async def to_mpe(self, plate: Plate, placeholder: str, collection: bool = False) -> Plate:
    """A plate onto the MPE²: into the model's carrier when it is drawn, so it rides with it."""
    carrier = None
    if self.model is not None:
      carrier = self.model.collection_carrier if collection else self.model.filter_carrier
    return await self.g.to_placeholder(plate, placeholder, into=carrier)

  def press(self, top: Plate, below: Optional[Plate]) -> None:
    """The MPE²'s liquid: each filter well's volume into the well under it, or to waste."""
    for i, well in enumerate(top.get_all_items()):
      volume = well.tracker.get_used_volume()
      if not volume:
        continue
      well.tracker.remove_liquid(volume)
      if below is not None:
        below.get_item(i).tracker.add_liquid(volume)

  async def mpe_to_waste(self, top: Plate, below: Optional[Plate], heights, points: str) -> None:
    """The method's FilterPlateToWaste: placed, pressed to waste with the plate returned, removed."""
    self.say(f"MPE2: {top.name} pressed, {points}")
    await self.mpe.filter_plate_placed(*heights)
    await self.mpe.process_filter_plate_to_waste(points)
    self.press(top, below)
    await self.mpe.filter_plate_removed()

  # -- the method ----------------------------------------------------------------------------------

  async def run(self) -> None:
    v, g = self.v, self.g
    T1000, T300 = "Tips_1000_Channels", "Tips_300_Channels"
    await self.mpe.initialize()

    spin = v.resource("Spin_Plate")
    for other, same in SAME_PLATE.items():
      v.aliases[other] = v.resource(same)
    lysate = v.resource("ABGene_LP_Shake")

    self.say("01 supernatant off")
    await g.to_placeholder(v.labware("Spin_Plate_lid"), "Spin_Plate_lid_waste")
    sup, waste = chunks(v.items("Spin_Plate_supernatant"), 8), chunks(v.items("Spin_Plate_liquid_waste"), 8)
    first = 1000.0
    await self.channels(T1000, [
      (lambda i=i: self._supernatant(sup[2 * i], waste[2 * i], sup[2 * i + 1], waste[2 * i + 1], first))
      for i in range(3)])

    self.say("01A P1, resuspend, to the lysate plate")
    lp_lid = await g.to_placeholder(v.labware("ABGene_LP_Shake_lid"), "Lid_parking_LP")
    b2_lid = await g.to_placeholder(v.labware("DNA_Buffers_2_lid"), "Lid_parking_DNA_Buffers_2")
    p1, pellets = chunks(v.items("Buffer_P1"), 8), chunks(v.items("Spin_Plate_Buffer_P1"), 8)
    lysate_cols = chunks(v.items(self.set_seq("Lysate_Plate_Buffer")), 8)
    await self.channels(T300, [
      (lambda i=i: self._resuspend(p1[i], pellets[i], lysate_cols[i])) for i in range(3)])

    self.say("02 P2")
    await self.head24("Buffer_P2", self.set_seq("Lysate_Plate_Buffer"), 250.0)
    await self.wait(120, "HHS_1 at 200 rpm")
    await g.onto(b2_lid, v.resource("DNA_Buffers_2"))
    await g.to_placeholder(spin, "Spin_Plate_waste")

    self.say("03 N3")
    n3 = v.resource("DNA_N3_Buffer")
    n3_lid = await g.to_placeholder(v.labware("DNA_N3_Buffer_lid"), "Lid_parking_N3_Buffer")
    await self.head24(self.set_seq("Buffer_N3"), self.set_seq("Lysate_Plate_Buffer"), 350.0)
    await self.wait(120, "HHS_1 at 200 rpm")
    await g.onto(n3_lid, n3)

    self.say("04 clear the lysate through the filter plate")
    rp = await self.to_mpe(v.labware("RP_Storage"), "RP_on_MPE")
    rp_lid = await g.to_placeholder(v.labware("RP_on_MPE_lid"), "Lid_parking_RP")
    fp = await self.to_mpe(v.labware("FP_Storage_1"), "FP_on_MPE")
    fp_lid = await g.to_placeholder(v.labware("FP_on_MPE_lid"), "Lid_parking_Agilent_FP")
    await self.head24(self.set_seq("Lysate_Plate_Buffer"), self.set_seq("Filter_Plate_WideBore"), None,
                      mix=Mix(volume=0, repetitions=3, flow_rate=250.0), wide_bore=True)
    await self.wait(120, "incubation on the filter")
    await g.onto(lp_lid, lysate)
    await self.mpe_to_waste(fp, rp, FP_ON_RP, "pressure,20,240;pressure,65,60;")
    await g.onto(fp_lid, fp)
    await g.to_placeholder(fp, "FP_Storage_1")
    await g.onto(rp_lid, rp)
    await g.to_placeholder(rp, "RP_Storage")

    self.say("05 bind")
    bp_lid = await g.to_placeholder(v.labware("Nunc_BP_storage_1_lid"), "Lid_parking_Numc_BP")
    bp = await self.to_mpe(v.labware("Nunc_BP_storage_1"), "Nunc_BP_MPE2")
    await g.to_placeholder(rp_lid, "Lid_parking_RP")
    await self.head24(self.set_seq("Cleared_Lysate"), self.set_seq("BP_Lysate_MPE"), None)
    await g.onto(rp_lid, rp)
    await self.mpe_to_waste(bp, None, BP, "pressure,40,60;")

    self.say("06 wash 1 (PB)")
    b1 = v.resource("DNA_Buffers_1")
    b1_lid = await g.to_placeholder(v.labware("DNA_Buffers_1_lid"), "Lid_parking_DNA_Buffers_1")
    await self.head24("Buffer_PB", self.set_seq("BP_Lysate_MPE"), 900.0)
    await self.mpe_to_waste(bp, None, BP, "pressure,40,60;")

    self.say("07 wash 2 (PE) and dry")
    await self.head24("Buffer_PE", self.set_seq("BP_Lysate_MPE"), 900.0)
    await g.onto(b1_lid, b1)
    await self.mpe_to_waste(bp, None, BP, "pressure,40,60;pressure,65,420;")

    self.say("08 elute")
    ep = await g.to_placeholder(v.labware("Eppendorf_EP_Storage"), "Eppendorf_EP_Pipetting")
    ep_lid = await g.to_placeholder(v.labware("Eppendorf_EP_Pipetting_lid"), "Lid_parking_EP_by_MPE")
    await g.to_placeholder(bp, "Nunc_BP_on_EP")
    eb = v.resource("DNA_Elute_Buffer")
    eb_lid = await g.to_placeholder(v.labware("DNA_Elute_Buffer_lid"), "Lid_parking_Elute_Buffer_lid")
    source = v.items("DNA_Elute_Buffer_from")  # the same 8 wells every pass
    bp_cols = chunks(v.items(self.set_seq("BP_EluteBuff_Storage")), 8)
    await self.channels(T300, [(lambda i=i: self.move8(source, bp_cols[i], 130.0)) for i in range(3)])
    await self.wait(300, "elution buffer on the membrane")
    await g.onto(eb_lid, eb)
    await self.to_mpe(bp, "Nunc_BP_MPE2")
    await g.onto(ep_lid, ep)
    await self.mpe.filter_plate_placed(*BP)
    await self.mpe.clamp_filter_plate()
    await self.to_mpe(ep, "Eppendorf_EP_MPE", collection=True)
    await g.to_placeholder(ep_lid, "Lid_parking_EP_by_MPE")
    await self.mpe.collection_plate_placed(EP_HEIGHT, BP_NOZZLE_OFFSET)
    self.say("MPE2: binding plate pressed into the elution plate, pressure,65,420;")
    await self.mpe.process_filter_plate_to_collection("pressure,65,420;",
                                                      return_filter_plate_to_integration_area=False)
    self.press(bp, ep)
    await g.onto(ep_lid, ep)
    await g.to_placeholder(ep, "Eppendorf_EP_Storage")
    await self.mpe.collection_plate_removed()
    await self.mpe.retrieve_filter_plate()
    await g.to_placeholder(bp, "Nunc_BP_storage_1")
    await g.onto(bp_lid, bp)
    await self.mpe.filter_plate_removed()

  async def _supernatant(self, sup1, waste1, sup2, waste2, first: float) -> None:
    await self.move8(sup1, waste1, first)
    await self.move8(sup2, waste2, None)  # the rest: 3.6 x culture - 1000

  async def _resuspend(self, p1, pellets, lysate_cols) -> None:
    await self.move8(p1, pellets, 200.0)
    have = min(w.tracker.get_used_volume() for w in pellets)
    await self.move8(pellets, lysate_cols, None, mix=Mix(volume=round(0.9 * have, 1), repetitions=10,
                                                         flow_rate=250.0))


def wide_bore_tips(rack: TipRack) -> None:
  """The pre-cut wide-bore tips: the rack's own tip, 79.8 mm long."""
  sample = rack.get_item(0).tip_for_pickup()

  def make(name: str) -> HamiltonTip:
    return HamiltonTip(name, has_filter=sample.has_filter, size_z=WIDE_BORE_LENGTH,
                       maximal_volume=sample.maximal_volume, tip_size=sample.tip_size,
                       pickup_method=sample.pickup_method, collar_height=sample.collar_height,
                       model=f"{sample.model or 'hamilton_tip_1000uL'}_cut_{WIDE_BORE_LENGTH}")

  rack.empty()
  for spot in rack.get_all_items():
    spot._make_tip_func = make
  rack.fill()


def fill(v: VenusDeck, culture_volume: float, n: int) -> None:
  """The pellets' supernatant, the buffers, room where the method pours a lot into one place."""
  culture = min(max(culture_volume, 200.0), 500.0)
  for w in v.items("Spin_Plate_supernatant"):
    w.tracker.set_volume(culture * 3.6)
  give_room(v.items("Buffer_P1"), 10_000.0)
  give_room(v.items("Buffer_P2"), 10_000.0)
  give_room(v.items(f"Buffer_N3_{n}"), 10_000.0)
  give_room(v.items("Buffer_PB"), 30_000.0)
  give_room(v.items("Buffer_PE"), 30_000.0)
  give_room(v.items("DNA_Elute_Buffer_from"), 10_000.0)
  make_room(v.items("Spin_Plate_liquid_waste"), 5_000.0)


def report(v: VenusDeck, n: int) -> None:
  ep = v.resource("Eppendorf_EP_Storage")
  cols = [ep.get_item(f"{r}{c}") for c in range(1, 4) for r in "ABCDEFGH"]
  got = sorted({round(w.tracker.get_used_volume(), 1) for w in cols})
  print(f"elution plate, set {n} (columns 1-3): {got} uL per well (130 expected)")
  bp, rp = v.resource("Nunc_BP_storage_1"), v.resource("RP_Storage")
  print("binding plate left holding", round(sum(w.tracker.get_used_volume() for w in bp.get_all_items()), 1),
        "uL; receiving plate", round(sum(w.tracker.get_used_volume() for w in rp.get_all_items()), 1), "uL")


TRACE = "DNA Extraction.condensed.md"


async def main(corpus: pathlib.Path, view: bool, culture_volume: float, time_scale: float,
               trace: pathlib.Path, models: Optional[pathlib.Path] = None) -> None:
  logging.disable(logging.WARNING)
  warnings.simplefilter("ignore")
  set_volume_tracking(True)
  set_tip_tracking(True)
  v = VenusDeck(corpus, LAYOUT)
  install(v, slide_waste="core96slidewaste_0001")
  print("not on the deck at the start:", ", ".join(v.clear_absent(trace)))
  v.clear(list(SAME_PLATE))
  wide_bore_tips(v.resource("TipSupport_1000_WideBore"))
  # The method picks 24 tips from these with the rest of the head hanging past their edge: the
  # CO-RE II tip supports have no frame there. PLR asks for that to be declared.
  for name in ("TipSupport_1000_offset", "TipSupport_1000_WideBore"):
    v.resource(name)._frame_height = 0.0
  star = STARDevice(deck=v.deck, simulation=True, declared_configuration_json=RECORDING_STAR, name="STAR")
  await star.setup()
  fill(v, culture_volume, 1)
  model = None
  if models is not None:  # the animated MPE² where the layout has its unit, seated under its plates
    from mpe2_model import MPE2Model

    box = v.deck.get_resource("__MPE_2_0001")
    site = box.parent  # the base's MPE_1 site, where the layout has its unit
    site.unassign_child_resource(box)
    model = MPE2Model("MPE2", models / "hamilton_mpe2_animated.glb")
    seat = v.spots["Nunc_BP_MPE2"]
    site.assign_child_resource(
      model, location=MPE2Model.location_for_seat(seat) - site.get_location_wrt(v.deck))
  mpe = MPE2SimulationDriver(time_scale=time_scale)
  if model is not None:
    mpe.add_state_observer(model.on_state)
  mpe.add_state_observer(lambda s: s in (SPEControlState.PROCESS_FILTER_PLATE_TO_WASTE,
                                         SPEControlState.PROCESS_FILTER_PLATE_TO_COLLECTION)
                         and print(f"  MPE2 state: {s.name}"))

  if view:
    from pylabrobot.hamilton.star.motion import attach_viewer_motion
    from pylabrobot.visualizer3D.server import Viewer3D

    viewer = Viewer3D(star, name="dna_extraction_demo.py", open_browser=False)
    await viewer.start()
    attach_viewer_motion(star.driver, viewer)
    print("viewer:", getattr(viewer, "url", ""), flush=True)
    await viewer.wait_for_browser()
    await asyncio.sleep(1.0)

  await DNAExtraction(star, v, mpe, 1, culture_volume, time_scale, model).run()
  report(v, 1)
  if view:
    print("done", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
  ap = argparse.ArgumentParser()
  ap.add_argument("--corpus", type=pathlib.Path, required=True)
  ap.add_argument("--trace", type=pathlib.Path,
                  help="the method's trace; the corpus's sibling analysis/traces/the method's .condensed.md when not given")
  ap.add_argument("--view", action="store_true")
  ap.add_argument("--culture-volume", type=float, default=500.0)
  ap.add_argument("--models", type=pathlib.Path,
                  help="plr-models' models/ directory: draw the MPE² from its animated model")
  ap.add_argument("--time-scale", type=float, default=0.0,
                  help="how long the shakes, incubations and presses really wait, per second of the method's")
  a = ap.parse_args()
  trace = a.trace or a.corpus.parent / "analysis" / "traces" / TRACE
  asyncio.run(main(a.corpus, a.view, a.culture_volume, a.time_scale, trace, a.models))
