"""NIST LMSF "GROQ-Seq.2_TFs" plate 1 and plates 2-5 on a simulated STAR, for the 3D viewer.

Both methods' `main`, call for call, on the Python ports of their libraries (GSF-IMS shared
submethods, PlateAndLidMovement, Common96HeadSubMethods, tip counters, LMSF_Utilities), on their
deck (`GROQ-Seq.2_TFs.lay`) imported with `plr_import.lay_to_plr`, as `marionette_demo.py` does.

  python groq_seq_demo.py --corpus DIR --method plate_1        growth plate 1: media, then cells
  python groq_seq_demo.py --corpus DIR --method plates_2-5     a selection plate: media, TMP,
                                                                inducers, the inducer gradients
  ... --plate-map FILE    write the worklist;  --view    play it in the viewer
  ... --repair            the plate-map code with its defects fixed (below): not the method

Plate 1 fills every well with media (0.9 x culture) and cells (0.1 x culture) from two stocks, rows
A/C/E/G and B/D/F/H. Plates 2-5: column 1 media only; column 2 inducers (1 in rows A/C/E/G, 2 in
B/D/F/H); column 3 TMP; column 4 both; columns 5-11 TMP; column 12 the gradient start (inducer and
TMP), diluted column by column to column 6, column 5 the TMP-only control. TMP (the selector) from
the second gradient plate on (`grad_plate_num`).

What the method gets from its parameters file, which is not in the NIST repository, is given here as
options; the defaults are illustrative, chosen so every volume is one a channel can move (the
inducer gradient's start, culture/2 x the series multiplier, goes on 300 uL tips).

Found in the methods' own code, and what the demo does about it:
  - The plate map (CalculateOutputs) of both methods sets each plasmid on positions 1-8 of
    sequences of 12 (`plasmid_1_1` = row A, ...), then copies all 12: reading position 9's
    property, Venus's GetSequenceProperty throws "property not found" (HSL reference), so the
    method aborts there, its abort handler runs CleanUp, and no worklist is written. The demo does
    the same; `--repair` sets all 12.
  - Plates 2-5 compute the selector concentration as `tmp_conc_arr.ElementAt(inducer_number - 1)`,
    `inducer_number` not yet set (its value is "undefined", HSL reference): the demo stops there as
    a runtime error; `--repair` uses the selector's own index.
  - Plates 2-5 divide the gradient's concentration by the series factor after the loop over the
    gradient's wells, not per column: every gradient well is written at the start concentration.
    The demo writes that; `--repair` divides per column.
  - Plates 2-5 write TMP into the map for every plate, also those that get none (grad_plate_num 1).
  - Plate 1 with library stocks (isClonalTest not "true") aborts at its first cell transfer: the
    library's check_seq_lengths_and_channels raises, as `library_stock_1` has 8 positions for its 4
    channels. The demo's default is the clonal test (the tube racks, 4 positions); `--library` the other.
  - Plates 2-5's gradient start takes the inducer's volume out of the media, not the TMP's (the
    Marionette method takes both): column 12 holds the TMP volume more than the other wells.
These are the methods as committed (2025-11-23). Venus's simulation aborts both where the demo does
(docs/FIRMWARE_EQUIVALENCE.md §4b): plate 1 at position 9's "property not found", plates 2-5 at
`ElementAt(inducer_number - 1)`, "array reference out of bound".

Deviations from the methods (beyond `marionette_demo.py`'s, which apply here too):
  - TipCount::Edit2, the operator's dialog to edit each tip counter before it is read, is skipped.
  - The STAR's Initialize step in StartUp is the simulator's setup.
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

from nist_deck import VenusDeck, give_room, install, make_room, print_plate_map, write_worklist  # noqa: E402

from venus_interop.methods import sequences as sq  # noqa: E402
from venus_interop.plr.libraries.common_96head import Common96HeadSubMethods  # noqa: E402
from venus_interop.plr.libraries.gsf_ims import GsfIms, SubmethodError  # noqa: E402
from venus_interop.plr.libraries.lmsf_utilities import LmsfUtilities  # noqa: E402
from venus_interop.plr.libraries.plate_and_lid import PlateAndLidMovement  # noqa: E402
from venus_interop.plr.libraries.tip_count import TipCount, TipCounters  # noqa: E402
from venus_interop.plr.libraries.tip_handling_96 import TipHandling96  # noqa: E402
from venus_interop.plr.liquid_classes import VenusLiquidClasses  # noqa: E402

from pylabrobot.hamilton.star.device import RECORDING_STAR, STARDevice  # noqa: E402
from pylabrobot.resources import set_tip_tracking, set_volume_tracking  # noqa: E402
from venus_interop.plr import faithful  # noqa: E402

LAYOUT = "5ae1a84b57e5.lay"  # GROQ-Seq.2_TFs.lay, both methods'
GRIP = "COREGripTool_OnWaste_1000ul_0001"
T1000, T300 = "Tips_1000_Channels", "Tips_300_Channels"


class MethodError(RuntimeError):
  """A runtime error in the method's own code: Venus aborts the method, and its handler runs."""


@dataclass
class Parameters:
  """The methods' parameters (GetParams); the defaults are illustrative."""

  culture_volume: float = 300.0  # uL; the methods clamp it to 200-500
  is_pipetting: bool = True
  strain_1_id: str = "strain_1"
  plasmid_1_ids: Sequence[str] = ("plasmid_1_1", "plasmid_1_2", "plasmid_1_3", "plasmid_1_4")  # rows A, C, E, G
  plasmid_2_ids: Sequence[str] = ("plasmid_2_1", "plasmid_2_2", "plasmid_2_3", "plasmid_2_4")  # rows B, D, F, H
  worklist_file: Optional[pathlib.Path] = None  # worklistFile; not written when None
  # plate 1
  is_clonal_test: bool = True  # cells from the tube racks, else the library troughs (aborts, below)
  lineage: int = 1  # which old-plate lid park takes the handoff plate's lid
  # plates 2-5
  dilution_factor: float = 10.0  # culture : cells
  grad_plate_num: int = 3  # the method's sequence_number; TMP from 2 on
  dilution_series_factor: float = 2.0
  inducer_ids: Sequence[str] = ("inducer_1", "inducer_2")
  inducer_stock_conc: Sequence[float] = (1000.0, 1000.0)
  inducer_units: Sequence[str] = ("umol/L", "umol/L")
  selector_ids: Sequence[str] = ("TMP", "TMP")
  selector_stock_conc: Sequence[float] = (1000.0, 1000.0)
  selector_units: Sequence[str] = ("ug/mL", "ug/mL")


class GroqSeq:
  """What both methods share: StartUp, CleanUp (also their abort handler), the strain and plasmid map."""

  TIP_SEQUENCES = ["Tips_1000_Channels", "Tips_300_Channels", "Tips_50_Channels", "Tips_1000_Offset_pickup"]
  FIELDS: list = []

  def __init__(self, star: STARDevice, v: VenusDeck, p: Parameters, say=print, repair: bool = False,
               counters: Optional[TipCounters] = None, liquid_classes: Optional[VenusLiquidClasses] = None):
    self.v, self.par, self.say, self.repair = v, p, say, repair
    self.gsf = GsfIms(star, v, say, liquid_classes=liquid_classes)
    self.plm = PlateAndLidMovement(star, v, say=say)
    self.c96 = Common96HeadSubMethods(star, v, say)
    self.util = LmsfUtilities(v)
    self.tips = TipCount(v, counters or TipCounters())
    self.culture = min(max(p.culture_volume, 200.0), 500.0)  # GetParams clamps it
    self.plate_map: list = []
    self.aborted: Optional[str] = None

  async def run(self) -> None:
    self.StartUp()
    try:
      await self.main()
    except (sq.SequenceError, SubmethodError, MethodError) as e:  # OnAbort: CleanUp
      self.aborted = str(e)
      self.say(f"method aborted: {e}")
    await self.CleanUp()
    if self.gsf.missing_classes:
      self.say("liquid classes PLR lacks (its default used): " + ", ".join(sorted(self.gsf.missing_classes)))

  def StartUp(self) -> None:
    self.counters = TipHandling96().GetTipCounters(1)
    for tips, counter in zip(self.TIP_SEQUENCES, self.counters):
      self.tips.Read2(tips, counter)

  async def CleanUp(self) -> None:
    for tips, counter in zip(self.TIP_SEQUENCES, self.counters):
      self.tips.Write2(tips, counter)
    await self.c96.Clear96HeadAndArm(None, "clear_96_head_seq")

  def strain_and_plasmids(self) -> None:
    """Strain on all 96 wells; each row's plasmid, from its 12-well sequence."""
    p, seq = self.par, self.v.seq
    seq("Growth_Plate").set_property_range(1, 96, "strain", p.strain_1_id)
    for k in range(1, 5):
      for group, ids in ((1, p.plasmid_1_ids), (2, p.plasmid_2_ids)):
        s = seq(f"plasmid_{group}_{k}")
        s.set_property_range(1, s.total if self.repair else 8, "plasmid", ids[k - 1])  # the method: 1-8
        self.util.SeqCopyPropsFromShortSeq(s.name, ["plasmid"], "Growth_Plate")

  def SaveWorklistAndMetadata(self, row) -> None:
    """A row per Growth Plate position, `row(position, well)` giving the fields after the column."""
    plate = self.v.seq("Growth_Plate")
    for _ in sq.loop(plate, rewind=False):
      pos, well = plate.cur, plate.current_item()[1]
      self.plate_map.append([pos, well, well[0], int(well[1:]), *row(pos)])
      plate.increment(1)
    if self.par.worklist_file:
      write_worklist(self.par.worklist_file, self.FIELDS, self.plate_map)
      self.say(f"worklist: {self.par.worklist_file}")

  def prop(self, pos: int, name: str):
    return self.v.seq("Growth_Plate").get_property(pos, name)


class Plate1(GroqSeq):
  """GROQ-Seq.2_TFs.plate_1: media and bacteria in every well, for growth to stationary phase."""

  TRACE = "GROQ-Seq.2_TFs.plate_1.condensed.md"
  FIELDS = ["position", "well", "row", "column", "inducerId", "inducerConcentration", "inducerUnits",
            "selectorId", "selectorConc", "selectorUnits", "strain", "plasmid"]

  async def main(self) -> None:
    p, gsf, plm = self.par, self.gsf, self.plm
    old_lid_parks = ["Lid_parking_Old_Growth_Plate", "Lid_parking_Old_Growth_Plate_2"]
    stocks = ["bacteria_stocks_1", "bacteria_stocks_2"] if p.is_clonal_test else ["library_stock_1", "library_stock_2"]
    dispense = ["bacteria_dispense_1", "bacteria_dispense_2"]

    await plm.MoveGrowthPlateWithLid("Move_Growth_Plate_Handoff", "Growth_Plate_Handoff_lid",
                                     "Move_Growth_Plate", "Growth_Plate_lid", GRIP, 1, 0)
    await plm.MoveLid("Growth_Plate_lid", "Lid_parking_Growth_Plate", GRIP, 0, 0)
    await plm.MoveLid("Media_source_lid", "Lid_parking_Media_trough", GRIP, 0, 1)
    if p.is_pipetting:
      await gsf.tip_pickup(T1000, 8)
      await gsf.pipette_media("Media_pipette_from", "Media_dispense_all", self.culture * 0.9, 1, T1000, 8)
      await gsf.tip_eject(8)
    await plm.MoveLid("Lid_parking_Media_trough", "Media_source_lid", GRIP, 1, 1)
    if p.is_pipetting:
      for stock, wells in zip(stocks, dispense):
        await gsf.pipette_cells_from_tubes(stock, wells, self.culture * 0.1, 2, 800, T1000, 4)
    await plm.MoveLid("Lid_parking_Growth_Plate", "Growth_Plate_lid", GRIP, 1, 0)
    await plm.MoveGrowthPlateWithLid("Move_Growth_Plate", "Growth_Plate_lid", "Move_Growth_Plate_Handoff",
                                     "Growth_Plate_Handoff_lid", GRIP, 0, 0)
    await plm.MoveLid("Growth_Plate_Handoff_lid", old_lid_parks[p.lineage - 1], GRIP, 0, 1)
    self.CalculateOutputs()
    self.SaveWorklistAndMetadata(lambda pos: ["none", float(self.prop(pos, "inducer_conc")), "none", "none",
                                              float(self.prop(pos, "additive_conc")), "none",
                                              self.prop(pos, "strain"), self.prop(pos, "plasmid")])

  def CalculateOutputs(self) -> None:
    plate = self.v.seq("Growth_Plate")
    plate.set_property_range(1, 96, "inducer_conc", 0)
    plate.set_property_range(1, 96, "additive_conc", 0)
    self.strain_and_plasmids()

  def expected_volumes(self) -> dict:
    return {f"{r}{c}": self.culture for r in "ABCDEFGH" for c in range(1, 13)}


class Plates2to5(GroqSeq):
  """GROQ-Seq.2_TFs.plates_2-5: a selection plate with two inducer gradients."""

  TRACE = "GROQ-Seq.2_TFs.plates_2-5.condensed.md"
  FIELDS = Plate1.FIELDS

  async def main(self) -> None:
    p, gsf, plm = self.par, self.gsf, self.plm
    await plm.MoveGrowthPlateWithLid("Move_Growth_Plate_Handoff", "Growth_Plate_Handoff_lid",
                                     "Move_Growth_Plate", "Growth_Plate_lid", GRIP, 1, 0)
    await plm.MoveLid("Growth_Plate_lid", "Lid_parking_Growth_Plate", GRIP, 0, 0)
    await plm.MoveLid("Media_source_lid", "Lid_parking_Media_trough", GRIP, 0, 1)

    # main's volume model
    m = p.dilution_series_factor / (p.dilution_series_factor - 1.0)
    cell = self.culture / p.dilution_factor
    media = self.culture - cell
    transfer = media * m - media
    first_tmp_seq = 2
    with_tmp = p.grad_plate_num >= first_tmp_seq
    inducer_ref = self.culture if not with_tmp else media
    tmp_ref = media if p.grad_plate_num > first_tmp_seq else self.culture
    add_inducer = inducer_ref / 2
    add_tmp = tmp_ref / 10 if with_tmp else 0.0
    grad_start_tmp = add_tmp * m
    grad_start_inducer = inducer_ref / 2 * m
    grad_start_media = media * m - grad_start_inducer  # the TMP's volume is not taken out
    self.say(f"volumes: media {media:.1f}, inducer {add_inducer:.1f} / start {grad_start_inducer:.1f}, "
             f"TMP {add_tmp:.1f} / start {grad_start_tmp:.1f}, transfer {transfer:.1f}")

    if p.is_pipetting:
      await gsf.tip_pickup(T1000, 8)
      await gsf.pipette_media("Media_pipette_from", "media_grad_start", grad_start_media, 1, T1000, 8)
      await gsf.pipette_media("Media_pipette_from", "media_w_nothing", media, 0, T1000, 8)
      await gsf.pipette_media("Media_pipette_from", "media_w_tmp", media - add_tmp, 0, T1000, 8)
      await gsf.pipette_media("Media_pipette_from", "media_w_ind", media - add_inducer, 0, T1000, 8)
      await gsf.pipette_media("Media_pipette_from", "media_w_tmp_ind", media - add_tmp - add_inducer, 0, T1000, 8)
      await gsf.tip_eject(8)
    await plm.MoveLid("Lid_parking_Media_trough", "Media_source_lid", GRIP, 1, 0)
    await plm.MoveLid("Reagent_Stock_Plate_lid", "Lid_parking_Reagent_Stock", GRIP, 0, 1)

    if p.is_pipetting and with_tmp:
      await gsf.add_reagent_reuse_tips("tmp_stock_1", "add_tmp_1", add_tmp, 1, 1, T300, 8)
      await gsf.tip_pickup(T300, 8)
      await gsf.add_reagent_reuse_tips("tmp_stock_2", "grad_start_tmp_2", grad_start_tmp, 1, 0, T300, 8)
      await gsf.add_reagent_reuse_tips("tmp_stock_2", "add_tmp_2", add_tmp, 0, 0, T300, 8)
      await gsf.tip_eject(8)
    if p.is_pipetting:
      for k in (1, 2):
        await gsf.add_reagent_replace_tips(f"inducer_stock_{k}", f"add_ind_{k}", add_inducer, 0, 0, T300, 8)
        await gsf.add_reagent_replace_tips(f"inducer_stock_{k}_4", f"grad_start_ind_{k}", grad_start_inducer, 0, 0, T300, 4)
    await plm.MoveLid("Lid_parking_Reagent_Stock", "Reagent_Stock_Plate_lid", GRIP, 1, 1)
    if p.is_pipetting:
      await gsf.pipette_dil_series("inducer_grad_from", "inducer_grad_to", transfer, 2, media, T1000, 8)
    await plm.MoveLid("Lid_parking_Growth_Plate", "Growth_Plate_lid", GRIP, 1, 1)
    self.volumes = dict(media=media, start_extra=grad_start_tmp)
    self.CalculateOutputs()
    self.SaveWorklistAndMetadata(lambda pos: [self.prop(pos, "inducer_id"), float(self.prop(pos, "inducer_conc")),
                                              self.prop(pos, "inducer_units"), self.prop(pos, "additive_id"),
                                              float(self.prop(pos, "additive_conc")), self.prop(pos, "additive_units"),
                                              self.prop(pos, "strain"), self.prop(pos, "plasmid")])

  def CalculateOutputs(self) -> None:
    p, seq, util = self.par, self.v.seq, self.util
    plate = seq("Growth_Plate")
    for name, value in (("inducer_conc", 0), ("inducer_id", "none"), ("inducer_units", "none"),
                        ("additive_conc", 0), ("additive_id", "none"), ("additive_units", "none")):
      plate.set_property_range(1, 96, name, value)

    for k in (1, 2):  # TMP, whatever the plate number
      s = seq(f"calc_tmp_{k}")
      s.set_property_range(1, s.total, "additive_id", p.selector_ids[k - 1])
      if not self.repair:
        raise MethodError("CalculateOutputs: tmp_conc_arr.ElementAt(inducer_number - 1), inducer_number not set")
      s.set_property_range(1, s.total, "additive_conc", p.selector_stock_conc[k - 1] / 10)
      s.set_property_range(1, s.total, "additive_units", p.selector_units[k - 1])
      util.SeqCopyPropsFromShortSeq(s.name, ["additive_id", "additive_conc", "additive_units"], "Growth_Plate")

    props = ["inducer_id", "inducer_conc", "inducer_units"]
    for k in (1, 2):
      add, grad = seq(f"add_ind_{k}"), seq(f"calc_ind_grad_{k}")
      ind_id, units, conc = p.inducer_ids[k - 1], p.inducer_units[k - 1], p.inducer_stock_conc[k - 1] / 2
      for name, value in zip(props, (ind_id, conc, units)):
        add.set_property_range(1, add.total, name, value)
      util.SeqCopyPropsFromShortSeq(add.name, props, "Growth_Plate")
      # again on add_ind_k, to calc_ind_grad_k's 28 positions of its 8: nothing reaches the plate
      add.set_property_range(1, grad.total, "inducer_id", ind_id)
      add.set_property_range(1, grad.total, "inducer_units", units)

      d = grad.copy()  # ind_dill_n = ind_grad_seq_arr.GetAt(k - 1): a copy, from its current position
      labware = d.current_item()[0]
      while d.cur > 0:
        sq.align([(d, 1)])
        for _ in range(4):  # a column of the gradient
          well = d.current_item()[1]
          for name, value in zip(props, (ind_id, conc, units)):
            util.SeqSetPropertyByWell(labware, well, "Growth_Plate", name, value)
          d.increment(1)
        if self.repair:
          conc /= p.dilution_series_factor
      d.set_max(d.total)
      d.set_current_position(1)
      conc /= p.dilution_series_factor  # the method's, after the loop: no effect on the map

    self.strain_and_plasmids()

  def expected_volumes(self) -> dict:
    v = self.volumes
    return {f"{r}{c}": v["media"] + (v["start_extra"] if c == 12 else 0.0) for r in "ABCDEFGH" for c in range(1, 13)}


METHODS = {"plate_1": Plate1, "plates_2-5": Plates2to5}


def fill(v: VenusDeck) -> None:
  """The sources full enough for the run, the wells that take liquid able to hold it."""
  give_room(v.items("Media_pipette_from"), 30_000.0)
  for seq in ("library_stock_1", "library_stock_2", "bacteria_stocks_1", "bacteria_stocks_2",
              "inducer_stock_1", "inducer_stock_2", "tmp_stock_1", "tmp_stock_2"):
    give_room(v.items(seq), 5_000.0)
  # The gradient ends in the waste trough, dispensing to the liquid (cLLD): a heel, as Marionette's.
  waste = v.resource("Liquid_waste").get_all_items()
  give_room(waste, 1_000.0)
  make_room(waste, 20_000.0)


def report(v: VenusDeck, method: GroqSeq) -> None:
  if method.aborted:
    print(f"aborted: {method.aborted}; no worklist")
  expected = method.expected_volumes()
  plate = v.resource("Growth_Plate")
  off = {w.get_identifier(): round(w.tracker.get_used_volume() - expected[w.get_identifier()], 1)
         for w in plate.get_all_items()}
  # cLLD reads hand the tracker the volume measured to 0.1 mm: a few uL either side
  print(f"Growth Plate: each well's volume against the method's model; differences "
        f"min {min(off.values())}, max {max(off.values())} uL")
  for c in range(1, 13):
    col = [f"{r}{c}" for r in "ABCDEFGH"]
    print(f"  column {c:2}: expected {sorted({round(expected[w], 1) for w in col})}, "
          f"off by {sorted({off[w] for w in col})}")
  if method.plate_map:
    print_plate_map(method.FIELDS, method.plate_map, ("inducerConcentration", "selectorConc", "plasmid"))


async def main(corpus: pathlib.Path, which: str, view: bool, p: Parameters, trace: Optional[pathlib.Path],
               repair: bool, tip_counters: Optional[pathlib.Path], liquid_classes: Optional[pathlib.Path],
               viewer_debug: bool = False, record_only: bool = False,
               replay_dir: Optional[pathlib.Path] = None) -> None:
  logging.disable(logging.WARNING)
  warnings.simplefilter("ignore")
  set_volume_tracking(True)
  set_tip_tracking(True)
  cls = METHODS[which]
  v = VenusDeck(corpus, LAYOUT)
  install(v)
  trace = trace or corpus.parent / "analysis" / "traces" / cls.TRACE
  print("not on the deck at the start:", ", ".join(v.clear_absent(trace)))
  star = STARDevice(deck=v.deck, simulation=True, declared_configuration_json=RECORDING_STAR, name="STAR")
  await star.setup()
  faithful.apply(star)  # Venus's defaults when PLR_VENUS_FAITHFUL_CFG is set
  fill(v)

  viewer = None
  if view or record_only:
    from pylabrobot.hamilton.star.motion import attach_viewer_motion
    from venus_interop.plr.replay import ReplayViewer
    from datetime import datetime
    from uuid import uuid4

    from venus_interop.plr import viewer_models
    from mpe2_model import attach_visual

    models_root = viewer_models.attach(v.deck)
    viewer_models.attach_star_base(star)
    print(f"viewer models: {attach_visual(v, pathlib.Path(models_root) / 'hamilton_mpe2_animated.glb')} MPE2 units drawn")
    replay_dir = replay_dir or pathlib.Path('.local/replays') / (
      datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8])
    viewer = ReplayViewer(star, bundle=replay_dir,
                      metadata=dict(method=which, grad_plate=p.grad_plate_num,
                                    culture_volume=p.culture_volume, repair=repair),
                      name="groq_seq_demo.py", open_browser=False, models_root=models_root,
                      overlays=viewer_debug, hover=viewer_debug, ui=True,
                      look="technical" if viewer_debug else "real", light=1.0 if viewer_debug else 0.8)
    await viewer.start()
    attach_viewer_motion(star.driver, viewer)
    viewer_url = viewer.url
    if not viewer_debug:
      separator = "&" if "?" in viewer_url else "?"
      viewer_url = viewer_url.replace("#", f"{separator}pauses=0.5#", 1)
    print("viewer:", viewer_url, flush=True)
    if not record_only:
      await viewer.wait_for_browser()
      await asyncio.sleep(1.0)

  method = cls(star, v, p, repair=repair, counters=TipCounters(tip_counters),
               liquid_classes=VenusLiquidClasses.from_json(liquid_classes) if liquid_classes else None)
  failure = None
  try:
    await method.run()
    report(v, method)
  except BaseException as error:
    failure = str(error) or type(error).__name__
    raise
  finally:
    if viewer is not None:
      error = failure or (str(method.aborted) if method.aborted else None)
      await viewer.finish_recording('aborted' if error else 'complete', error)
      print('replay bundle:', replay_dir.resolve(), flush=True)
      if record_only or failure:
        await viewer.stop()
  if view and not record_only:
    print("done", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
  ap = argparse.ArgumentParser()
  ap.add_argument("--corpus", type=pathlib.Path, required=True)
  ap.add_argument("--method", choices=sorted(METHODS), default="plates_2-5")
  ap.add_argument("--trace", type=pathlib.Path,
                  help="the method's trace; the corpus's sibling analysis/traces/<method>.condensed.md when not given")
  ap.add_argument("--view", action="store_true")
  ap.add_argument("--viewer-debug", action="store_true",
                  help="show viewer overlays and hover readouts with technical lighting")
  ap.add_argument("--record-only", action="store_true",
                  help="generate a static interactive replay without waiting for a browser")
  ap.add_argument("--replay-dir", type=pathlib.Path,
                  help="new replay bundle directory; --view automatically records into .local/replays")
  ap.add_argument("--repair", action="store_true",
                  help="fix the plate-map code's defects (see the module docstring); not the method as written")
  ap.add_argument("--grad-plate", type=int, default=3, help="plates 2-5: gradient plate number (TMP from 2 on)")
  ap.add_argument("--culture-volume", type=float, default=300.0)
  ap.add_argument("--library", action="store_true",
                  help="plate 1: cells from the library troughs (isClonalTest false), not the tube racks")
  ap.add_argument("--plate-map", type=pathlib.Path, help="write the worklist (SaveWorklistAndMetadata) here")
  ap.add_argument("--liquid-classes", type=pathlib.Path,
                  help="the methods' liquid classes as JSON (tools/liquid_classes.py on NIST's Config/ML_STARLiquids.mdb)")
  ap.add_argument("--tip-counters", type=pathlib.Path,
                  help="a SQLite file of tip counters (Venus element-counter tables), read at the start and written at the end")
  a = ap.parse_args()
  par = Parameters(culture_volume=a.culture_volume, grad_plate_num=a.grad_plate, is_clonal_test=not a.library,
                   worklist_file=a.plate_map)
  asyncio.run(main(a.corpus, a.method, a.view, par, a.trace, a.repair, a.tip_counters, a.liquid_classes,
                   a.viewer_debug, a.record_only, a.replay_dir))
