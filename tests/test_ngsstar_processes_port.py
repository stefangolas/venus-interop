"""Hamilton's NGSStar framework, NGSStarProcesses: the port against the HSL library itself.

PIP_ReagentsFromTubeOrTroughOrPlateToPlate runs on Roche Avenio CGP's layout in the HSL interpreter
and in the port, for each tip type and the branches that matter (tips exchanged or kept, the
aspiration sequence advanced or not, cLLD or fixed heights, a last slice narrower than the
channels). Every step must use the same tips and wells per channel, the same cLLD or fixed-height
step record, the same settings (port_harness: the record's against the PLR arguments and the Venus
settings the port meant), and the record's liquid class.

What Venus does through compiled services is modelled on both sides alike: the liquid class's tip
type and dispense mode (a table), the tip positions STAR Tip Tools' planner reads (a synthetic rack
geometry; the planner itself runs as HSL), and the sample-tracking calls (STCC, nothing).

Needs VENUS_INTEROP_NGS (an NGS-Protocols checkout: the Avenio CGP kit) and
VENUS_INTEROP_HAMILTON_LIBS (library folders, separated by os.pathsep, for what the kit includes from
elsewhere: Venus's Library, a folder holding `STAR Tools\\`, one holding `HSL_MethodHelper.hsl`),
and pylabrobot.
"""
import asyncio
import os
import pathlib
import time

import pytest

pytest.importorskip("pylabrobot.hamilton.star.driver.lld_mode")

from pylabrobot.hamilton.star.driver.lld_mode import LLDMode  # noqa: E402

from port_harness import (CLOCK, REPORT_BOOK, RecordingChannels, RecordingDeck, assert_same_steps,  # noqa: E402
                          hsl_run, report_rows, steps_of)
from venus_interop.files import layout  # noqa: E402

NGS = pathlib.Path(os.environ["VENUS_INTEROP_NGS"]) if os.environ.get("VENUS_INTEROP_NGS") else None
LIBS = [pathlib.Path(p) for p in os.environ.get("VENUS_INTEROP_HAMILTON_LIBS", "").split(os.pathsep) if p]
pytestmark = pytest.mark.skipif(NGS is None or not LIBS,
                                reason="VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS not set")

# What this test checks against the HSL (read by tools/trace_method.py --status)
LIBRARY = "NGSSTARPROCESSES"
COVERS = ["PIP_ReagentsFromTubeOrTroughOrPlateToPlate", "PIP_Supernatant_SVFTSingleDispenseFromPlateToLiquidWaste"]

TIPS = {1: "MlStar300ulStandardVolumeTipWithFilter", 5: "MlStar1000ulHighVolumeTipWithFilter", 23: "MlStar50ulTipWithFilter"}
CLASSES = {"LC300": (1, 0), "LC1000": (5, 0), "LC50": (23, 0)}
LLD_RECORDS = {"3de044fd", "7438ccf5", "e3697ea4", "39efb96f", "9726387a", "7302ffe4", "0b2ad228"}  # the others: fixed height
# (dispense count, aspiration, dispense, volume, class, mix cycles, mix asp, mix disp, asp height,
#  disp height, tip exchange, increment aspiration, liquid following at a fixed dispense)
CALLS = [
  (24, "RGT_Beads", "HSP_Pipette", 20, "LC300", 0, 0, 0, 0, 0, 0, 0, 0),
  (12, "RGT_Beads", "HSP_Pipette", 15, "LC50", 2, 10, 10, 3.0, 0, 0, 0, 0),
  (24, "HSP_onCPAC", "HSP_Pipette2", 50, "LC1000", 0, 0, 0, 1.5, 2.0, 1, 1, 1),
  (16, "RGT_Tris", "HSP_Pipette", 30, "LC300", 3, 0, 25, 0, 1.0, 1, 0, 0),
  (16, "RGT_Te_Buffer", "HSP_Pipette2", 100, "LC1000", 2, 80, 0, 0, 0, 0, 0, 0),
]
ROWS = "ABCDEFGH"


@pytest.fixture(scope="module")
def avenio():
  return NGS / "assets" / "NGSStar" / "Roche" / "Avenio CGP"


@pytest.fixture(scope="module")
def lay(avenio):
  return layout.read_layout(avenio / "Methods" / "Avenio CGP.lay")


def xy(item):
  """A synthetic deck: each rack 120 mm from the next by its name, columns 9 mm apart in X from
  the left, rows 9 mm apart in Y from the back; positions 1..96 column by column, or A1..H12."""
  lab, pos = item
  if pos.isdigit():
    col, row = divmod(int(pos) - 1, 8)
  else:
    col, row = int(pos[1:]) - 1, ROWS.index(pos[0])
  return 100.0 + (sum(map(ord, lab)) % 7) * 120.0 + col * 9.0, 300.0 - row * 9.0


def _planner(seqs):
  from venus_interop.plr.libraries.star_tip_tools import StarTipTools

  class Shim:
    def seq(self, name):  # a sequence the method built is itself (VenusDeck's way)
      return name if not isinstance(name, str) else seqs[name]
  return StarTipTools(Shim(), 8, xy=xy)


def _call(call):
  """A transfer call's 13 fields; a supernatant call's 5, the rest None."""
  return (*call, *[None] * (13 - len(call)))


def hsl_steps(avenio, lay, call):
  n, asp, disp, vol, lc, cyc, mva, mvd, ha, hd, ex, inc, lf = _call(call)
  N = "NGSSTARPROCESSES::"
  run_it = (f"ML_STAR.{disp}.SetCount({n});\n"
            f'{N}PIP_ReagentsFromTubeOrTroughOrPlateToPlate(ML_STAR, ML_STAR.{asp}, ML_STAR.{disp}, {vol}, "{lc}", '
            f"{cyc}, {mva}, {mvd}, {ha}, {hd}, {ex}, {inc}, {lf});\n" if cyc is not None else
            f"ML_STAR.{asp}.SetCount({n});\n"
            f'{N}PIP_Supernatant_SVFTSingleDispenseFromPlateToLiquidWaste(ML_STAR, ML_STAR.{asp}, ML_STAR.{disp}, '
            f'{vol}, "{lc}");\n')
  src = (
    'namespace _Method { #include "HSLSeqLib.hsl" }\n'
    'namespace _Method { #include "NGSStarProcesses.hs_" }\n'
    'global device ML_STAR ("x.lay", "ML_STAR", hslTrue);\n'
    'namespace _Method { #include "HSLMECCLib.hs_" }\n'
    "namespace _Method { method main() void {\n"
    + "".join(f"{N}t_seqTips{k} = ML_STAR.{TIPS[t]};\n" for k, t in (("300", 1), ("1000", 5), ("50", 23)))
    + f'{N}t_strFullPathReportFile = "{REPORT_BOOK}";\n'
    + f"{N}t_intNumberOfAllAvailableChannels = 8;\n{N}t_blnDeactivatePipettingStepsForTransportTests = 0;\n"
    + run_it + "} }\n")

  def tip_type(run, p):
    p["o_inttiptype"].value, p["o_intdispensemode"].value = CLASSES[str(p["i_strliquidclassname"].value)]
    return 0

  nothing = lambda run, p: 0  # noqa: E731
  # STCC (sample tracking) answered with no-ops: the mapping files are in scope but not ported yet;
  # the test is to compare them once they are
  run = hsl_run(src, avenio / "Library" / "port_test.hsl", [avenio / "Library", avenio / "Methods", *LIBS],
                (avenio / "Library").glob("*.stp"), {"x.lay": lay}, answers={
                  # STAR Tip Tools' planner runs as HSL: the channels and raster (configuration keys
                  # 1, 26) and the tips' positions (the synthetic geometry the port's planner has)
                  "clock": time.struct_time(CLOCK), "cfg.1": 8, "cfg.26": 9.0, "labware_position": lambda lab, pos: (*xy((lab, pos)), 0.0),
                  "functions": {
                  "ngsstarprocesses::_data_gettiptypeanddispensemodeofliquidclass": tip_type,
                  "stcc::resetfiltersequences": nothing, "stcc::addfiltersequence": nothing,
                  "stcc::generatemappingfilev43ex1": nothing,
                  # out (no PLR counterpart; commented in the port): asks the instrument its channels
                  "hslml_star::aspirationmonitoring_1000ulchannel_off": nothing,
                  "hslml_star::aspirationmonitoring_1000ulchannel_on": nothing}})
  classes = [e.settings["LiquidName"] for e in run.events if e.command == "Aspirate"]
  label = lambda e: ("lld" if e.guid[:8] in LLD_RECORDS else "fixed") if e.command in ("Aspirate", "Dispense") else ""  # noqa: E731
  return steps_of(run, label), classes, report_rows(run)


def port_steps(lay, call):
  from venus_interop.plr.libraries.ngsstar_processes import NGSStarProcesses
  from venus_interop.plr.libraries.ngsstar_report import RunReport

  n, asp, disp, vol, lc, cyc, mva, mvd, ha, hd, ex, inc, lf = _call(call)
  deck = RecordingDeck(lay)
  deck.seq(disp if cyc is not None else asp).set_count(n)
  label = lambda command, kw: "lld" if kw.get("lld_mode") not in (None, LLDMode.OFF) else "fixed"  # noqa: E731
  with RecordingChannels(label) as ch:
    procs = NGSStarProcesses(type("Star", (), {"pipettes": ch})(), deck, TIPS, CLASSES, planner=_planner(deck.live),
                             report=RunReport(clock=lambda: time.struct_time(CLOCK)))
    classes = []
    procs._lc = lambda name: classes.append(name)  # the class asked for; none given to the recorder
    if cyc is not None:
      asyncio.run(procs.PIP_ReagentsFromTubeOrTroughOrPlateToPlate(None, asp, disp, vol, lc, cyc, mva, mvd, ha, hd,
                                                                     ex, inc, lf))
    else:
      asyncio.run(procs.PIP_Supernatant_SVFTSingleDispenseFromPlateToLiquidWaste(None, asp, disp, vol, lc))
  return ch.events, classes, procs.report.rows


def test_covers_what_it_calls():
  assert COVERS[0] == "PIP_ReagentsFromTubeOrTroughOrPlateToPlate"


@pytest.mark.parametrize("call", CALLS, ids=[f"{c[4]}-{c[2]}-n{c[0]}" for c in CALLS])
def test_port_pipettes_as_the_library_does(avenio, lay, call):
  (hsl, hsl_classes, hsl_report), (port, port_classes, port_report) = hsl_steps(avenio, lay, call), port_steps(lay, call)
  assert len(hsl) > 3
  assert_same_steps(hsl, port)
  assert set(hsl_classes) == set(port_classes) == {call[4]}
  assert hsl_report and hsl_report == port_report


# supernatant removal: (positions, aspiration, dispense, volume, class); 160 uL: 110 + 50, 290 uL: 250 + 50
SUPERNATANT = [(24, "MIDI_OnMagnet", "LiquidWaste", 160, "LC300"), (12, "MIDI_OnMagnet", "LiquidWaste", 290, "LC300")]


@pytest.mark.parametrize("call", SUPERNATANT, ids=[f"n{c[0]}-{c[3]}uL" for c in SUPERNATANT])
def test_supernatant_removal_as_the_library_does(avenio, lay, call):
  (hsl, _, hsl_report), (port, _, port_report) = hsl_steps(avenio, lay, call), port_steps(lay, call)
  assert hsl_report and hsl_report == port_report
  assert [e[0] for e in hsl[:5]] == ["TipPickUp", "Aspirate", "Aspirate", "Dispense", "TipEject"]
  assert_same_steps(hsl, port)
  first, second = (250.0, 50.0) if call[3] > 280 else (call[3] - 50.0, 50.0)
  for i, e in enumerate(port):
    if e[0] == "Dispense":  # the tips drained: what the two draws took
      assert e[3]["volumes"] == [first + second] * len(e[1]), i
      assert port[i - 2][3]["volumes"][0] == first and port[i - 1][3]["volumes"][0] == second


def test_supernatant_removal_takes_300_uL_tips_only(lay):
  with pytest.raises(RuntimeError, match="300 uL only"):
    port_steps(lay, (8, "MIDI_OnMagnet", "LiquidWaste", 100, "LC50"))
