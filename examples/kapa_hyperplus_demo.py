"""KAPA HyperPlus library prep, the whole protocol, on a simulated STAR, for the 3D viewer.

From `NGS-Protocols/protocols/KAPA_HyperPrep/HyperPrep_HyperPlus.py` (pyhamilton), step for step,
on its own layout (`KAPA_HyperPlus_Deck.lay`) imported with `plr_import.lay_to_plr`. Each step
names the labware the method names; pyhamilton's helpers are re-implemented here with their own
rules (below), so the tips, columns and volumes are the method's.

  python kapa_hyperplus_demo.py --corpus DIR --ngs DIR            headless: runs, checks the volumes
  python kapa_hyperplus_demo.py --corpus DIR --ngs DIR --view     serves the viewer and plays the run

Run on the PLR fork's `nist-viz` branch, with it on PYTHONPATH. `--ngs` is an NGS-Protocols
checkout (the layout, and the NGS kits' labware next to it); `--corpus` is the layout corpus, for
the definitions the kits lack.

The steps:
  1  fragmentation      master mix from the CPAC plate (8 channels, 50 uL tips, a column at a
                        time), a 96-head mix, the plate into the ODTC under a ComfortLid, 37 C
  2  end repair, A-tail the samples to HSP 2 (96-head), master mix (8 channels), mix, ODTC
  3  ligation           back to HSP 1, adapters and ligation mix (8 channels), mix, 15 min
  4  post-ligation      to the MIDI plate, beads (8-channel multi-dispense), mix, 5 min, onto the
     cleanup            magnet, supernatant off, two ethanol washes, dry, off the magnet, water,
                        mix, 2 min, onto the magnet, 20 uL of eluate to HSP 2
  5  amplification      HiFi mix from the CPAC plate (8 channels), index primers (96-head), mix,
                        ODTC
  6  final cleanup      as 4, with 0.9X beads (8 channels); 20 uL of library back to HSP 1

pyhamilton's helpers, as here:
  pip_transfer     per column of 8 targets: 8 new tips; one channel at a time from a source with
                   fewer positions than channels (a tube), all at once from one with 8 (a trough);
                   dispense the column; tips to waste.
  multi_dispense   as many columns per draw as the class's volume holds (300 uL: 3 x 88 uL).
  transfer_96 /    96-head, n = samples / 8 columns from the CO-RE II tip support: the support's
  mix_plate        right-most n full columns, on the head's first n, so they work plate columns
                   1 to n. When the support holds another tip size, or too few full columns, the
                   head takes what is left back to its rack and moves a whole rack with enough
                   columns onto the support (`TipSupportTracker`). Tips to the 96-head waste.
  TrackedTips      racks in layout order, spots column by column; `reset_all` refills them, where
                   the method calls it.

Deviations from the method, and why (each printed when it happens):
  - Supernatant and ethanol go to the 96-head waste trough (`LiquidWaste_MPH`): the method
    dispenses them to MIDI_OffMagnet, the nest the plate has just left (in pyhamilton, two
    positions with one plate between them; here one plate that moves).
  - Index primers: the method declares them on HSP 2, which holds the libraries, and pipettes them
    from HSP 1, empty since step 4. Here the operator loads them into HSP 1 at step 5.
  - Water for elution: the method passes the trough itself where it wants positions; its 8 are used.
  - Step 6's volumes are the method's 53 + beads, from 25 - 2 + 25 + 5 uL; 20 + 25 + 5 = 50 are in
    the wells (step 4 moves 20 of the 25 uL eluate). Where the method asks for more than a well
    holds, what it holds is drawn, and the difference printed.
  - The cold reagents: one PCR-plate well each, as the method has them, holds the 0.96 mL and
    2.4 mL the run needs, as its reagent tracker counts them.
  - Tips run out with 96 samples where the method has no `reset_all`: the operator refills that
    tracker's racks (printed).
  - The ODTC and CPAC are timed waits and messages: their PLR resources are not on this branch.
    Run times: fragmentation 37 C for `--fragmentation-min`; end repair 20 C 30 min + 65 C 30
    min (the method's comments); PCR 45 s + cycles x 75 s + 60 s (KAPA's manual; the method only
    names its ODTC file).
  - The four ComfortLids the method counts are on the stack; the layout's fifth is not loaded.
  - The ODTC moves are the iSWAP's (gripped from the right, the first elbow stop that clears): the
    method's CO-RE gripper cannot reach the ODTC, which stands left of the deck past the channels'
    X travel (95 mm on the recorded STAR).
  - The MIDI plate goes back off the magnet at the end of step 4: step 6 pipettes into
    MIDI_OffMagnet, which in the method is the nest the plate left at the end of step 4.
  - Dispense modes: the classes' own ("_Empty": empty the tip), which pyhamilton leaves to the
    class by sending none (unverified); multi_dispense's part dispenses, the last one emptying.
  - Liquid classes, heights where the method uses cLLD, and grip heights are PLR's defaults.
  - Layout definitions not on this machine: the tip support (`TipSupport_CORE II.rck`) is
    Hamilton's CO-RE II ST-filter support, whose tip type the method rewrites at run time anyway;
    the 60 mL troughs are PLR's `hamilton_1_trough_60mL_Vb` (the Venus rack lists 8 positions,
    which the importer does not read); the CO-RE grip tools are PLR's, where its STAR deck puts
    them.
"""

import argparse
import asyncio
import logging
import math
import os
import pathlib
import sys
import warnings
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from nist_deck import Gripper, VenusDeck, corpus_index, give_room, install, make_room  # noqa: E402

from venus_interop.files.definitions import DEFAULT_VENUS_LABWARE, DefinitionStore, normalize  # noqa: E402

from pylabrobot.hamilton.star.device import RECORDING_STAR, STARDevice  # noqa: E402
from pylabrobot.hamilton.star.driver.features.iswap_transport import iSWAPTransport  # noqa: E402
from pylabrobot.lib.liquid_handling.mix import Mix  # noqa: E402
from pylabrobot.resources import Coordinate, Lid, Plate, TipRack, set_tip_tracking, set_volume_tracking  # noqa: E402
from pylabrobot.resources.hamilton import hamilton_1_trough_60mL_Vb  # noqa: E402
from pylabrobot.resources.hamilton.core_grippers import hamilton_core_gripper_1000ul_at_waste  # noqa: E402
from venus_interop.plr import faithful  # noqa: E402

LAYOUT = pathlib.Path("protocols", "KAPA_HyperPrep", "KAPA_HyperPlus_Deck.lay")
# The layout's tip support file, missing here; Hamilton's CO-RE II ST-filter support in the corpus
TIP_SUPPORT_FILE = r"C:\Program Files (x86)\HAMILTON\Library\STAR Tools\TipSupport_CORE II.rck"
TIP_SUPPORT_STAND_IN = "tipsupport co-re ii/core2_96_tipsupport_st_filter_l.rck"
# Move destinations only: not on the deck when the method starts. The fifth lid is not loaded.
ABSENT = ["HSP_ODTC", "Ham_ComfortLid_ODTC", "MIDI_OnMagnet", "Ham_ComfortLid_Stack_0005"]
LIDS = [f"Ham_ComfortLid_Stack_{i:04d}" for i in range(4, 0, -1)]  # top first, as pyhamilton
# How far a ComfortLid comes down a plate: the layout's ODTC lid site (209.1) is 3.5 below the top
# of the plate in the ODTC (197.1 + 15.5)
COMFORT_LID_NESTING = 3.5
CLASS_VOLUME_300 = 300.0  # uL, StandardVolumeFilter_Water_*: multi_dispense's volume per draw


def kapa_store(corpus: pathlib.Path, ngs: pathlib.Path) -> DefinitionStore:
  """The NGS kits' labware folders (the one nearest the layout first, as `tools/capture_log`
  orders them), over the corpus's definitions, with the tip support's stand-in."""
  layout = ngs / LAYOUT
  kits = [pathlib.Path(dp, d) for base in (ngs, pathlib.Path(r"C:\Program Files (x86)\HAMILTON\NGSStar"))
          if base.exists() for dp, ds, _ in os.walk(base) for d in ds if d.lower() == "labware"]

  def shared(kit: pathlib.Path) -> int:
    return len(set(kit.parts) & set(layout.parts))

  kits.sort(key=lambda k: -shared(k))
  index = corpus_index(corpus)
  index[TIP_SUPPORT_FILE] = index[TIP_SUPPORT_STAND_IN]
  store = DefinitionStore(kits[:1] + [DEFAULT_VENUS_LABWARE] + kits[1:], index, by_name=True)
  assert normalize(TIP_SUPPORT_FILE) in store.index
  return store


class TrackedTips:
  """pyhamilton's TrackedTips: racks in order, spots column by column."""

  def __init__(self, name: str, racks: Sequence[TipRack], say=print):
    self.name, self.racks, self.say = name, list(racks), say

  def next_spots(self, n: int) -> list:
    spots = [s for r in self.racks for s in r.get_all_items() if s.has_tip()][:n]
    if len(spots) < n:
      self.refill("8-channel pick-up")
      return self.next_spots(n)
    return spots

  def rack_with_columns(self, n: int) -> TipRack:
    for rack in self.racks:
      if sum(all(s.has_tip() for s in rack.get_all_items()[c * 8:c * 8 + 8]) for c in range(12)) >= n:
        return rack
    self.refill(f"no rack with {n} full columns")
    return self.rack_with_columns(n)

  def refill(self, why: str) -> None:
    self.say(f"  operator: {self.name} racks refilled ({why}; the method has no reset_all here)")
    self.reset_all()

  def reset_all(self) -> None:
    for rack in self.racks:
      rack.fill()


class TipSupport:
  """pyhamilton's TipSupportTracker on the CO-RE II tip support."""

  def __init__(self, star: STARDevice, rack: TipRack, say=print):
    self.h, self.rack, self.say = star.head96, rack, say
    self.source: Optional[TrackedTips] = None
    self.source_rack: Optional[TipRack] = None

  def full_columns(self) -> List[int]:
    return [c for c in range(12) if all(s.has_tip() for s in self.rack.get_all_items()[c * 8:c * 8 + 8])]

  async def pick_up_columns(self, tips: TrackedTips, n: int) -> None:
    if self.source is not tips or len(self.full_columns()) < n:
      await self.load(tips, n)
    first = self.full_columns()[-n]  # the right-most n
    await self.h.pick_up_tips(self.rack, channel="A1", tip_spot=f"A{first + 1}")

  async def load(self, tips: TrackedTips, n: int) -> None:
    rack = tips.rack_with_columns(n)
    if self.source_rack is not None and any(s.has_tip() for s in self.rack.get_all_items()):
      self.say(f"  support: what is left back to {self.source_rack.name}")
      await self.h.pick_up_tips(self.rack)
      await self.h.drop_tips(self.source_rack)
    self.say(f"  support: {rack.name} onto it")
    await self.h.pick_up_tips(rack)
    await self.h.drop_tips(self.rack)
    self.source, self.source_rack = tips, rack


class KAPAHyperPlus:
  def __init__(self, star: STARDevice, v: VenusDeck, samples: int = 96, dna_input_ng: float = 100,
               fragmentation_min: float = 15, pcr_cycles: int = 8, time_scale: float = 0.0,
               say=print):
    self.star, self.v, self.say = star, v, say
    self.p, self.h = star.pipettes, star.head96
    self.n = samples
    self.columns = math.ceil(samples / 8)
    self.fragmentation_min, self.pcr_cycles, self.time_scale = fragmentation_min, pcr_cycles, time_scale
    self.g = Gripper(star, v, say)
    self.iswap = iSWAPTransport(star.iswap)
    self.tips50 = TrackedTips("TIP_50uLF_L", [v.resource(f"TIP_50uLF_L_{i:04d}") for i in range(1, 9)], say)
    self.tips300 = TrackedTips("STF_L", [v.resource(f"STF_L_{i:04d}") for i in range(1, 9)], say)
    self.support = TipSupport(star, v.resource("TipSupport_0001"), say)
    self.lids = list(LIDS)  # on the stack, top first
    self.lids_back: List[str] = []  # where each lid taken goes back: the stack position it left

    # _setup_volumes
    self.dna_input_volume = min(dna_input_ng, 50)
    self.fragmentation_mastermix_volume = 10
    self.end_repair_mastermix_volume = 10
    self.ligation_mastermix_volume = 20
    self.adapter_volume = 2.5
    self.pcr_mix_volume = 25
    self.index_primer_volume = 5
    self.post_ligation_bead_volume = 88
    self.final_cleanup_bead_volume = 50
    self.ethanol_wash_volume = 200
    self.post_ligation_elution_volume = 25
    self.final_elution_volume = 22

    # _setup_deck_layout: the method's labware, by its names
    self.hsp, self.hsp2 = v.resource("HSP_Pipette"), v.resource("HSP_Pipette2")
    self.midi = v.resource("MIDI_Pipette")
    self.ethanol = v.resource("RGT_Ethanol")
    self.beads, self.water = v.resource("rgt_cont_60ml_BC_A00_0002"), v.resource("rgt_cont_60ml_BC_A00_0003")
    self.waste = v.resource("LiquidWaste_MPH")
    tubes = "SMP_CAR_24_15x75_A00_0001"  # pyhamilton's index i is Venus position i + 1
    self.end_repair_mix, self.ligation_mix, self.adapters = (v.at(tubes, p) for p in ("2", "3", "4"))
    cold = v.resource("CPAC_HSP_0001")
    self.hifi_mix, self.fragmentation_mix = cold.get_item(0), cold.get_item(1)

  # -- helpers -------------------------------------------------------------------------------------

  async def wait(self, seconds: float, what: str) -> None:
    self.say(f"  {what}: {seconds:.0f} s")
    if self.time_scale:
      await asyncio.sleep(seconds * self.time_scale)

  def wells(self, plate: Plate) -> list:
    return [plate.get_item(i) for i in range(self.n)]

  def drawn(self, wells: list, volume: float, what: str) -> float:
    """The method's volume, or what the wells hold where that is less (printed)."""
    have = min(w.tracker.get_used_volume() for w in wells)
    if volume > have + 1e-6:
      self.say(f"  ! {what}: the method draws {volume:g} uL, the wells hold {have:g}; drawing {have:g}")
      return have
    return volume

  # The method's liquid classes all end "_Empty": Hamilton's dispense mode "empty tip", with the
  # blow-out. pyhamilton sends no dispense mode, so the class's is taken (unverified).
  async def pip_transfer(self, tips: TrackedTips, source: list, targets: list, volume: float) -> None:
    for c in range(0, len(targets), 8):
      column = targets[c:c + 8]
      ch = list(range(len(column)))
      await self.p.pick_up_tips(tips.next_spots(len(column)), use_channels=ch)
      if len(source) >= len(column):  # one position per channel
        await self.p.aspirate(source[:len(column)], [volume] * len(column), use_channels=ch,
                              blow_out=[True] * len(ch))
      else:  # fewer positions than channels: one channel at a time
        for k in ch:
          await self.p.aspirate([source[k % len(source)]], [volume], use_channels=[k], blow_out=[True])
      await self.p.dispense(column, [volume] * len(column), use_channels=ch, blow_out=[True] * len(ch),
                            empty=[True] * len(ch))
      await self.p.discard_tips(use_channels=ch)

  async def multi_dispense(self, tips: TrackedTips, source: list, targets: list, volume: float) -> None:
    per_draw = int(CLASS_VOLUME_300 // volume)  # columns
    columns = [targets[c:c + 8] for c in range(0, len(targets), 8)]
    for b in range(0, len(columns), per_draw):
      batch = columns[b:b + per_draw]
      ch = list(range(8))
      await self.p.pick_up_tips(tips.next_spots(8), use_channels=ch)
      draw = [volume * sum(1 for col in batch if k < len(col)) for k in ch]
      await self.p.aspirate(source[:8], draw, use_channels=ch, blow_out=[True] * 8)
      for i, col in enumerate(batch):  # part dispenses; the last empties the tips
        last = i == len(batch) - 1
        await self.p.dispense(col, [volume] * len(col), use_channels=list(range(len(col))),
                              blow_out=[last] * len(col), empty=[last] * len(col))
      await self.p.discard_tips(use_channels=ch)

  async def transfer_96(self, tips: TrackedTips, source: Plate, target, volume: float,
                        aspiration_height: float = 0, what: str = "") -> None:
    await self.support.pick_up_columns(tips, self.columns)
    volume = self.drawn(self.wells(source), volume, what or f"{source.name} -> {target.name}")
    await self.h.aspirate(source, volume, liquid_height=aspiration_height or None, blow_out=True)
    # "_Empty" classes blow out; dispensing with `empty` avoids PLR's <0.1 uL piston rounding refusal
    await self.h.dispense(target, volume, blow_out=True, empty=True)
    await self.h.discard_tips()

  async def mix_plate(self, tips: TrackedTips, plate: Plate, volume: float, cycles: int,
                      liquid_height: float = 1.0) -> None:
    await self.support.pick_up_columns(tips, self.columns)
    await self.h.mix(plate, Mix(volume=volume, repetitions=cycles, flow_rate=100.0),
                     offset=Coordinate(0, 0, liquid_height))
    await self.h.discard_tips()

  async def odtc(self, plate: Plate, home: str, program: str, seconds: float) -> None:
    """Into the ODTC under a lid from the stack, the program, and back. With the iSWAP: the ODTC
    stands left of the deck, past the channels' X travel, so the method's CO-RE gripper moves cannot
    be made. Gripped from the right: from the front or left the jaws meet the tube carriers beside
    the pipetting carrier. The right elbow stop first: with the others the arm mostly sweeps over
    the 96-head waste trough behind the ODTC."""
    arm = dict(iswap=self.iswap, direction="right", elbows=("right", None, "front", "left"))
    self.say("  ODTC: door open")
    await self.g.to_placeholder(plate, "HSP_ODTC", **arm)
    lid_name = self.lids.pop(0)
    lid = self.v.resource(lid_name)
    await self.g.to_placeholder(lid, "Ham_ComfortLid_ODTC", into=plate, **arm)  # on the plate
    self.say("  ODTC: door closed")
    await self.wait(seconds, f"ODTC {program}")
    self.say("  ODTC: door open")
    below = self.v.resource(self.lids[0]) if self.lids else None
    await self.g.to_placeholder(lid, lid_name, into=below, **arm)  # put_back: onto the stack
    self.lids.insert(0, lid_name)
    await self.g.to_placeholder(plate, home, **arm)
    await self.star.iswap.park(traverse_height=280.0)
    self.say("  ODTC: door closed")

  async def to_magnet(self) -> None:
    await self.g.to_placeholder(self.midi, "MIDI_OnMagnet")

  async def off_magnet(self) -> None:
    await self.g.to_placeholder(self.midi, "MIDI_Pipette")

  async def bead_cleanup(self, sample_volume: float, beads: float, add_beads, elution: float,
                         target: Plate, supernatant_height: float) -> None:
    """Steps 4 and 6 from the beads on: they differ in how beads go in and the heights."""
    midi = self.wells(self.midi)
    await add_beads()
    await self.mix_plate(self.tips300, self.midi, 80, 15)
    await self.wait(300, "incubate")
    await self.to_magnet()
    await self.wait(120, "beads settle")
    self.say("  supernatant off (to the 96-head waste trough; the method: MIDI_OffMagnet)")
    await self.transfer_96(self.tips300, self.midi, self.waste, sample_volume + beads,
                           aspiration_height=supernatant_height, what="supernatant")
    for wash in (1, 2):
      self.say(f"  ethanol wash {wash}")
      await self.transfer_96(self.tips300, self.ethanol, self.midi, self.ethanol_wash_volume,
                             aspiration_height=0.8)
      await self.wait(30, "ethanol on the beads")
      await self.transfer_96(self.tips300, self.midi, self.waste, self.ethanol_wash_volume,
                             aspiration_height=0.8, what="ethanol off")
    await self.wait(180, "air dry")
    await self.off_magnet()
    await self.pip_transfer(self.tips50, self.water_positions(), midi, elution)
    await self.mix_plate(self.tips50, self.midi, 20, 15)
    await self.wait(120, "incubate")
    await self.to_magnet()
    await self.wait(120, "beads settle")
    await self.transfer_96(self.tips50, self.midi, target, 20, aspiration_height=0.8)

  def water_positions(self) -> list:
    return [self.water] * 8  # the trough's 8 positions

  # -- the method ----------------------------------------------------------------------------------

  async def run(self) -> None:
    self.say("initialize: CPAC 1 to 4 C; ODTC connected and initialized")

    self.say("1 enzymatic fragmentation")
    await self.pip_transfer(self.tips50, [self.fragmentation_mix], self.wells(self.hsp),
                            self.fragmentation_mastermix_volume)
    await self.mix_plate(self.tips50, self.hsp, 15, 10)
    await self.odtc(self.hsp, "HSP_Pipette", "Enzymatic_Fragmentation", self.fragmentation_min * 60)

    self.say("2 end repair and A-tailing")
    volume = self.dna_input_volume + self.fragmentation_mastermix_volume
    await self.transfer_96(self.tips300, self.hsp, self.hsp2, volume)
    await self.pip_transfer(self.tips50, [self.end_repair_mix], self.wells(self.hsp2),
                            self.end_repair_mastermix_volume)
    await self.mix_plate(self.tips50, self.hsp2, 25, 10)
    await self.odtc(self.hsp2, "HSP_Pipette2", "End_Repair_A_Tailing", 3600)

    self.say("3 adapter ligation")
    volume += self.end_repair_mastermix_volume
    await self.transfer_96(self.tips300, self.hsp2, self.hsp, volume)
    await self.pip_transfer(self.tips50, [self.adapters], self.wells(self.hsp), self.adapter_volume)
    await self.pip_transfer(self.tips50, [self.ligation_mix], self.wells(self.hsp),
                            self.ligation_mastermix_volume)
    self.say("  reset_all: TIP_50uLF_L racks refilled (the method's)")
    self.tips50.reset_all()
    await self.mix_plate(self.tips50, self.hsp, 40, 10)
    await self.wait(900, "ligation at room temperature")

    self.say("4 post-ligation cleanup")
    volume += self.adapter_volume + self.ligation_mastermix_volume
    await self.transfer_96(self.tips300, self.hsp, self.midi, volume)
    beads = [self.beads] * 8
    await self.bead_cleanup(
      volume, self.post_ligation_bead_volume,
      lambda: self.multi_dispense(self.tips300, beads, self.wells(self.midi), self.post_ligation_bead_volume),
      self.post_ligation_elution_volume, self.hsp2, supernatant_height=0.3)
    await self.off_magnet()  # the plate back in its nest for step 6 (the method moves it there then)

    self.say("5 library amplification")
    await self.pip_transfer(self.tips50, [self.hifi_mix], self.wells(self.hsp2), self.pcr_mix_volume)
    self.say("  operator: index primers into HSP_Pipette (the method's source; see the notes)")
    for w in self.wells(self.hsp):
      w.tracker.add_liquid(self.index_primer_volume)
      w.tracker.commit()
    await self.transfer_96(self.tips50, self.hsp, self.hsp2, self.index_primer_volume)
    await self.mix_plate(self.tips50, self.hsp2, 40, 5)
    pcr = 45 + self.pcr_cycles * (15 + 30 + 30) + 60
    await self.odtc(self.hsp2, "HSP_Pipette2", "Library_Amplification_PCR.xml", pcr)

    self.say("6 final cleanup and size selection")
    pcr_volume = self.post_ligation_elution_volume - 2 + self.pcr_mix_volume + self.index_primer_volume
    self.say("  reset_all: STF_L racks refilled (the method's)")
    self.tips300.reset_all()
    await self.transfer_96(self.tips300, self.hsp2, self.midi, pcr_volume, what="PCR products")
    await self.bead_cleanup(
      pcr_volume, self.final_cleanup_bead_volume,
      lambda: self.pip_transfer(self.tips300, beads, self.wells(self.midi), self.final_cleanup_bead_volume),
      self.final_elution_volume, self.hsp, supernatant_height=0.75)


def prepare(v: VenusDeck, samples: int, dna_input_volume: float) -> None:
  """The deck as the method finds it: samples, reagents, room in the waste, empty tip support."""
  # PLR's wastes; the CO-RE grip tools where PLR's STAR deck has its 1000 uL tools at waste
  install(v, slide_waste="core96externalwaste_0001", grip_tools=None)
  v.clear(["CORE_Grip_Tool_1000uL_0001"])
  tools = hamilton_core_gripper_1000ul_at_waste(name=v.deck.get_component_name("core_grippers"))
  v.deck.assign_child_resource(
    tools, location=Coordinate(1338 - tools.get_size_x() / 2, 105.550 - 26 - 9.5, 205))
  for name in ("rgt_cont_60ml_BC_A00_0002", "rgt_cont_60ml_BC_A00_0003"):
    v.replace(name, lambda name=name: hamilton_1_trough_60mL_Vb(name))
  support: TipRack = v.resource("TipSupport_0001")
  support.empty()
  support._frame_height = 0.0  # the head hangs past its edge when it takes the right-most columns
  v.clear(ABSENT)
  # The ComfortLids: Venus labware (a plate) each; here PLR lids, which is what seats on a plate,
  # nesting COMFORT_LID_NESTING onto it. They nest 1.8 mm into each other on the stack too, so the
  # import puts some on the deck beside it: each stands on the one below, at the layout's place.
  bottom = v.resource(LIDS[-1])
  base, at = bottom.parent, {name: v.resource(name).get_absolute_location() for name in LIDS}
  size = (bottom.get_size_x(), bottom.get_size_y(), bottom.get_size_z())
  base.unassign_child_resource(bottom)  # and the lids on it
  for name in LIDS[:-1]:
    if v.deck.has_resource(name):
      r = v.deck.get_resource(name)
      r.parent.unassign_child_resource(r)
  lower = None
  for name in reversed(LIDS):  # bottom first
    lid = Lid(name, *size, nesting_z_height=COMFORT_LID_NESTING)
    if lower is None:
      base.assign_child_resource(lid, location=at[name] - base.get_absolute_location())
    else:
      lower.assign_child_resource(lid, location=at[name] - at[lower.name])
    lower = lid

  hsp = v.resource("HSP_Pipette")
  for i in range(samples):
    hsp.get_item(i).tracker.set_volume(dna_input_volume)
  cold = v.resource("CPAC_HSP_0001")
  give_room([cold.get_item(0)], 25 * samples * 1.1)  # KAPA HiFi HotStart ReadyMix
  give_room([cold.get_item(1)], 10 * samples * 1.1)  # fragmentation master mix
  for pos, per in (("2", 10), ("3", 20), ("4", 2.5)):  # end repair mix, ligation mix, adapters
    v.at("SMP_CAR_24_15x75_A00_0001", pos).tracker.set_volume(per * samples * 1.1)
  v.resource("rgt_cont_60ml_BC_A00_0002").tracker.set_volume((88 + 50) * samples * 1.1)  # beads
  v.resource("rgt_cont_60ml_BC_A00_0003").tracker.set_volume((25 + 22) * samples * 1.1)  # water
  give_room(v.resource("RGT_Ethanol").get_all_items(), 4 * 200 * 1.1)  # one cavity: 4 washes
  make_room(v.resource("LiquidWaste_MPH").get_all_items(), 2_000.0)


def report(v: VenusDeck, samples: int) -> None:
  hsp = v.resource("HSP_Pipette")
  got = sorted({round(hsp.get_item(i).tracker.get_used_volume(), 2) for i in range(samples)})
  print(f"final libraries in HSP_Pipette, {samples} wells: {got} uL (20 expected)")
  midi = v.resource("MIDI_Pipette")
  left = sorted({round(midi.get_item(i).tracker.get_used_volume(), 2) for i in range(samples)})
  print(f"left in the MIDI plate (on {midi.parent.name}): {left} uL")


async def main(corpus: pathlib.Path, ngs: pathlib.Path, view: bool, samples: int, dna_input_ng: float,
               fragmentation_min: float, pcr_cycles: int, time_scale: float) -> None:
  logging.disable(logging.WARNING)
  warnings.simplefilter("ignore")
  set_volume_tracking(True)
  set_tip_tracking(True)
  v = VenusDeck(corpus, ngs / LAYOUT, store=kapa_store(corpus, ngs))
  prepare(v, samples, min(dna_input_ng, 50))
  star = STARDevice(deck=v.deck, simulation=True, declared_configuration_json=RECORDING_STAR, name="STAR")
  await star.setup()
  faithful.apply(star)  # Venus's defaults when PLR_VENUS_FAITHFUL_CFG is set

  if view:
    from pylabrobot.hamilton.star.motion import attach_viewer_motion
    from pylabrobot.visualizer3D.server import Viewer3D

    viewer = Viewer3D(star, name="kapa_hyperplus_demo.py", open_browser=False)
    await viewer.start()
    attach_viewer_motion(star.driver, viewer)
    print("viewer:", getattr(viewer, "url", ""), flush=True)
    await viewer.wait_for_browser()
    await asyncio.sleep(1.0)

  await KAPAHyperPlus(star, v, samples, dna_input_ng, fragmentation_min, pcr_cycles, time_scale).run()
  report(v, samples)
  if view:
    print("done", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
  ap = argparse.ArgumentParser()
  ap.add_argument("--corpus", type=pathlib.Path, required=True)
  ap.add_argument("--ngs", type=pathlib.Path, required=True, help="an NGS-Protocols checkout")
  ap.add_argument("--view", action="store_true")
  ap.add_argument("--samples", type=int, default=96)
  ap.add_argument("--dna-input-ng", type=float, default=100)
  ap.add_argument("--fragmentation-min", type=float, default=15)
  ap.add_argument("--pcr-cycles", type=int, default=8)
  ap.add_argument("--time-scale", type=float, default=0.0,
                  help="how long the incubations and ODTC runs really wait, per second of the method's")
  a = ap.parse_args()
  asyncio.run(main(a.corpus, a.ngs, a.view, a.samples, a.dna_input_ng, a.fragmentation_min,
                   a.pcr_cycles, a.time_scale))
