"""Hamilton's NGSStar framework, NGSStarProcesses' multi-dispense from a trough: the port against the HSL.

PIP_ReagentsFromTubeOrTroughOrPlateToPlate with a liquid class of a "part" dispense mode (2 or 4) and
a trough or plate as the source hands over to _PIP_MultidispenseFromTroughToPlate: one aspirate
per channel, then a dispense per column. It runs on Roche Avenio CGP's layout in the HSL
interpreter and in the port, for each tip type, one pass or several, a last column part full (the
channels then aspirate and mix different volumes), in simulation mode (no trough measured) or not:
enough in the trough, the first trough short and the next one taken, every trough short and the
operator asked to refill (OK: the first trough again; Cancel: as it was), the 50 uL copy's front
cover around that dialog. Every step must use the same tips and wells per channel with the same
settings; the liquid search must be on the same trough (finding the same test value on both
sides); the dialogs and the report rows must be the same.

ALIQUOT_FOR_EASYSTEPS_V2::CalcAliquot_v2_1 is on no machine here: both sides take the port's
reading of it (`ngsstar_processes.CalcAliquot_v2_1`, through port_harness), so this checks the
library around it, not the split itself (its own tests below say what the reading is). STAR Tip
Tools' planner runs as HSL; STCC is answered with no-ops, as in test_ngsstar_processes_port.

Needs VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS, and pylabrobot.
"""
import asyncio
import dataclasses
import time

import pytest

pytest.importorskip("pylabrobot.hamilton.star.driver.lld_mode")

from port_harness import (ALIQUOT, ARRAYTOOLS, ARRAYTOOLS_MODELS, CLOCK, CREATE_CHANNEL_PATTERN,  # noqa: E402
                          REPORT_BOOK, VECTORCUSTOMDIALOGS, RecordingChannels, RecordingDeck, assert_same_steps,
                          hsl_run, report_rows, steps_of)
from test_ngsstar_processes_port import LIBS, NGS, TIPS, _planner, avenio, xy  # noqa: E402,F401
from venus_interop.files import layout  # noqa: E402

pytestmark = pytest.mark.skipif(NGS is None or not LIBS,
                                reason="VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS not set")

# What this test checks against the HSL (read by tools/trace_method.py --status)
LIBRARY = "NGSSTARPROCESSES"
COVERS = ["_PIP_MultidispenseFromTroughToPlate", "_PIP_MultidispenseBeadsFromTubesToPlate"]

CLASSES = {"LC1000P": (5, 2), "LC300P": (1, 4), "LC50P": (23, 2)}  # tip type, dispense mode ("part")
# the 0 uL cLLD aspirates that measure the trough (or the tubes)
PROBES = {"3526cc04", "0a018a55", "0dadcaa2", "73d4fc3f", "d09db83a", "8d921894"}
FULL = 20000.0
# (wells, trough sequence, plate, volume, class, mix cycles, simulation, measured per trough, refill answer, lock)
CALLS = [
  (24, "RGT_Ethanol", "MIDI_Pipette", 180, "LC1000P", 6, 1, {}, None, 0),  # one pass: 3 columns of 5 a tip
  (96, "RGT_Ethanol", "MIDI_Pipette", 200, "LC1000P", 6, 1, {}, None, 0),  # 4 a tip: three passes
  (20, "RGT_Tris", "HSP_Pipette", 30, "LC300P", 2, 1, {}, None, 0),  # the last column half full
  (40, "RGT_Beads", "HSP_Pipette", 10, "LC50P", 0, 1, {}, None, 0),  # 4 a tip: 4 columns, then 1
  (24, "RGT_Ethanol", "MIDI_Pipette", 180, "LC1000P", 6, 0, {"RGT_01": FULL}, None, 0),  # measured: enough
  (24, "RGT_Ethanol", "MIDI_Pipette", 180, "LC1000P", 6, 0, {"RGT_01": 1500.0, "RGT_02": FULL}, None, 0),  # the next
  (16, "RGT_Ethanol", "MIDI_Pipette", 180, "LC1000P", 6, 0, {}, 1, 0),  # every trough short: refilled (OK)
  (16, "RGT_Tris", "HSP_Pipette", 30, "LC300P", 0, 0, {}, 2, 0),  # one trough, short: Cancel
  (16, "RGT_Beads", "HSP_Pipette", 10, "LC50P", 0, 0, {}, 1, 1),  # the 50 uL copy: the cover unlocked around it
  (16, "RGT_Ethanol", "MIDI_Pipette", 180, "LC1000P", 6, 0, {}, 1, 1),  # the 1000 uL copy: the cover left alone
]
# From tubes (_PIP_MultidispenseBeadsFromTubesToPlate, Avenio's wash buffers): the same fields, then
# (dispense height, tubes in the sequence, called directly, measure); the transfer passes measure FALSE
V = "CAR_VIALS_LARGE"
TUBE_CALLS = [
  (24, V, "MIDI_Pipette", 150, "LC1000P", 0, 1, {}, None, 0, 1.5, 24),  # 6 a tip: one pass; the 20 uL kept
  (3, V, "HSP_Pipette", 100, "LC1000P", 2, 1, {}, None, 0, 2.0, 3),  # three tubes: three tips
  (16, V, "MIDI_Pipette", 300, "LC1000P", 0, 0, {}, None, 0, 1.5, 12),  # 3 a tip: two passes, not measured
  (20, V, "HSP_Pipette", 30, "LC300P", 0, 1, {}, None, 0, 2.0, 12),  # the 300 uL copy is the trough's
  (16, V, "HSP_Pipette", 10, "LC50P", 0, 1, {}, None, 0, 2.0, 16),  # and the 50 uL copy
  (16, V, "MIDI_Pipette", 150, "LC1000P", 0, 0, {V: FULL}, None, 0, 1.5, 12, 1, 1),  # measured on 8 channels
  (16, V, "HSP_Pipette", 30, "LC300P", 0, 0, {}, 1, 0, 2.0, 4, 1, 1),  # measured, short: refilled
  (24, V, "MIDI_Pipette", 150, "LC1000P", 0, 1, {}, None, 0, 1.5, 3),  # 3 of 24 counted: 8 tips (the total)
  (24, "Tubes_3", "MIDI_Pipette", 150, "LC1000P", 0, 1, {}, None, 0, 1.5),  # a sequence of 3: 3 tips
]
# Illustrative: a tube sequence shorter than the channels (the tips follow its total)
TUBES_3 = layout.Sequence("Tubes_3", [(V, str(k)) for k in range(1, 4)])
CALLS += TUBE_CALLS
SOURCES = ["RGT_Ethanol", "RGT_Tris", "RGT_Beads", V, "Tubes_3"]
PLATES = ["MIDI_Pipette", "HSP_Pipette"]
INPUTS = ["Source", "Plate", "Count", "Volume", "LiquidClass", "Cycles", "Simulation", "Lock", "Height", "Tubes",
          "Direct", "Measure"]


def _opts(call):
  """A call's fields, the tube fields' defaults filled in: height, tubes, direct, measure."""
  return (*call, *(0, 0, 0, 0)[len(call) - 10:])
N = "NGSSTARPROCESSES::"
SRC = (
  'namespace _Method { #include "HSLSeqLib.hsl" }\n'
  'namespace _Method { #include "NGSStarProcesses.hs_" }\n'
  'global device ML_STAR ("x.lay", "ML_STAR", hslTrue);\n'
  'namespace _Method { #include "HSLMECCLib.hs_" }\n' + ARRAYTOOLS + CREATE_CHANNEL_PATTERN + ALIQUOT
  + VECTORCUSTOMDIALOGS + "namespace _Method { namespace TESTINPUT {\n"
  + "".join(f"function {k}() variable {{ variable v; return(v); }}\n" for k in INPUTS) + "} }\n"
  "namespace _Method { method main() void {\n"
  + "".join(f"{N}t_seqTips{k} = ML_STAR.{TIPS[t]};\n" for k, t in (("300", 1), ("1000", 5), ("50", 23)))
  + f"{N}t_intNumberOfAllAvailableChannels = 8;\n{N}t_blnDeactivatePipettingStepsForTransportTests = 0;\n"
  + f"{N}t_blnSimulationModeON = TESTINPUT::Simulation();\n{N}t_blnLockUnlockSystem = TESTINPUT::Lock();\n"
  + f'{N}t_strFullPathReportFile = "{REPORT_BOOK}";\n'
  + "".join(f"if (TESTINPUT::Source() == {i}) {{ if (TESTINPUT::Plate() == {j}) {{\n"
            f"ML_STAR.{d}.SetCount(TESTINPUT::Count());\n"
            f"if (TESTINPUT::Tubes() > 0) {{ ML_STAR.{s}.SetCount(TESTINPUT::Tubes()); }}\n"
            f"if (TESTINPUT::Direct() == 1) {{ {N}_PIP_MultidispenseBeadsFromTubesToPlate(ML_STAR, ML_STAR.{s}, "
            f"ML_STAR.{d}, TESTINPUT::Volume(), TESTINPUT::LiquidClass(), TESTINPUT::Cycles(), TESTINPUT::Height(), "
            "TESTINPUT::Measure()); }\n"
            f"else {{ {N}PIP_ReagentsFromTubeOrTroughOrPlateToPlate(ML_STAR, ML_STAR.{s}, ML_STAR.{d}, "
            "TESTINPUT::Volume(), TESTINPUT::LiquidClass(), TESTINPUT::Cycles(), 0, 0, 0, TESTINPUT::Height(), 0, 0, "
            "0); } } }\n"
            for i, s in enumerate(SOURCES) for j, d in enumerate(PLATES))
  + "} }\n")


# A plate not of whole columns: the library's report analysis raises after the part-full column's
# dispense (ngsstar_processes repairs it; faithful, the port raises there too)
STOP = "GetLabwareId"


@pytest.fixture(scope="module")
def lay(avenio):
  base = layout.read_layout(avenio / "Methods" / "Avenio CGP.lay")
  return dataclasses.replace(base, sequences=[*base.sequences, TUBES_3])


def _measured(volumes, lab):
  return volumes.get(lab, 500.0)  # a trough not named: short


def hsl_steps(avenio, lay, call, stops=False):
  n, src, plate, vol, lc, cyc, sim, volumes, answer, lock, height, tubes, direct, measure = _opts(call)
  measured, dialogs = [], []

  def tip_type(run, p):
    p["o_inttiptype"].value, p["o_intdispensemode"].value = CLASSES[str(p["i_strliquidclassname"].value)]
    return 0

  def measure_model(run, p):  # Venus's MeasureContainerVolume2 at the trough's current position, in mL
    measured.append(_measured(volumes, p["targetsequence"].value.current_item()[0]) / 1000)
    return measured[-1]

  def error_dialog(run, p):
    dialogs.append(f'{p["i_text"].value}\n{p["i_bottom"].value}')
    return answer

  nothing = lambda run, p: 0  # noqa: E731
  inputs = dict(zip(INPUTS, (SOURCES.index(src), PLATES.index(plate), n, vol, lc, cyc, sim, lock, height, tubes,
                             direct, measure)))
  run = hsl_run(SRC, avenio / "Library" / "port_test.hsl", [avenio / "Library", avenio / "Methods", *LIBS],
                (avenio / "Library").glob("*.stp"), {"x.lay": lay}, answers={
                  "clock": time.struct_time(CLOCK), "cfg.1": 8, "cfg.26": 9.0,
                  "labware_position": lambda lab, pos: (*xy((lab, pos)), 0.0),
                  "functions": {"ngsstarprocesses::_data_gettiptypeanddispensemodeofliquidclass": tip_type,
                                "hslml_star::measurecontainervolume2": measure_model,
                                "hslml_star::getcontainervolume": lambda run, p: measured[-1],
                                "vectorcustomdialogs::errordialog": error_dialog,
                                "stcc::resetfiltersequences": nothing, "stcc::addfiltersequence": nothing,
                                "stcc::generatemappingfilev43ex1": nothing,
                                **{f"testinput::{k.lower()}": (lambda v: lambda run, p: v)(v) for k, v in inputs.items()},
                                **ARRAYTOOLS_MODELS}}, stops=STOP if stops else None)
  out = []
  for e, step in zip(run.events, steps_of(run)):
    if e.command == "FirmwareCommand":  # the cover monitoring, off and on
      out.append(({"C0CD": "disable_control", "C0CE": "enable_control"}[e.settings["firmware command string"]],
                  {}, "", {}))
    elif e.command == "LockFrontCover":  # PLR has no cover lock (ngsstar_loading.cover_unlocked)
      continue
    else:  # the liquid search: where, not how
      out.append(("Probe", step[1], "", {}) if e.guid[:8] in PROBES else step)
  return out, dialogs, report_rows(run)


class _Channels(RecordingChannels):
  def __init__(self, volumes):
    super().__init__()
    self.volumes = volumes

  async def probe_liquid_volumes(self, containers, use_channels, **kw):
    self._log("Probe", containers, use_channels)
    return [_measured(self.volumes, c[0]) for c in containers]


class _Cover:
  def __init__(self, events):
    self.events = events

  async def request_state(self):
    return "closed"

  async def disable_control(self):
    self.events.append(("disable_control", {}, "", {}))

  async def enable_control(self):
    self.events.append(("enable_control", {}, "", {}))


def port_steps(lay, call, faithful=True):
  from venus_interop.plr.libraries.ngsstar_processes import NGSStarProcesses
  from venus_interop.plr.libraries.ngsstar_report import RunReport
  from venus_interop.plr.operator import ScriptedOperator

  n, src, plate, vol, lc, cyc, sim, volumes, answer, lock, height, tubes, direct, measure = _opts(call)
  deck = RecordingDeck(lay)
  deck.seq(plate).set_count(n)
  if tubes:
    deck.seq(src).set_count(tubes)
  operator = ScriptedOperator({"Insufficient liquid": answer == 1})
  with _Channels(volumes) as ch:
    star = type("Star", (), {"pipettes": ch, "front_cover": _Cover(ch.events)})()
    procs = NGSStarProcesses(star, deck, TIPS, CLASSES, planner=_planner(deck.live), simulation=bool(sim),
                             faithful=faithful,
                             lock_unlock=bool(lock), operator=operator,
                             report=RunReport(clock=lambda: time.struct_time(CLOCK)))
    procs._lc = lambda name: None
    try:
      if direct:
        asyncio.run(procs._PIP_MultidispenseBeadsFromTubesToPlate(None, src, plate, vol, lc, cyc, height, measure))
      else:
        asyncio.run(procs.PIP_ReagentsFromTubeOrTroughOrPlateToPlate(None, src, plate, vol, lc, cyc, 0, 0, 0, height,
                                                                     0, 0, 0))
    except RuntimeError as e:
      if not (faithful and STOP in str(e)):
        raise
      stopped = True
    else:
      stopped = False
  dialogs = [text for kind, text, _ in operator.asked if kind == "confirm"]
  return ch.events, dialogs, procs.report.rows, stopped


def _id(c):
  return f"{c[4]}-{c[1]}-n{c[0]}-{c[3]}uL" + ("-sim" if c[6] else f"-{'-'.join(f'{v:g}' for v in c[7].values()) or 'short'}") + \
    (f"-answer{c[8]}" if c[8] else "") + ("-lock" if c[9] else "")


@pytest.mark.parametrize("call", CALLS, ids=[_id(c) for c in CALLS])
def test_port_multidispenses_as_the_library_does(avenio, lay, call):
  # where a round dispenses on fewer channels than the aspirate (a column part full), the faithful
  # port stops after that dispense, and the HSL must stop there too (hsl_run's `stops`)
  port, port_dialogs, port_report, stopped = port_steps(lay, call)
  hsl, hsl_dialogs, hsl_report = hsl_steps(avenio, lay, call, stops=stopped)
  measured = not call[6] and (len(call) <= 10 or _opts(call)[13])
  assert [e[0] for e in hsl][:2] == ["TipPickUp", "Probe" if measured else "Aspirate"]
  if stopped:
    assert hsl[-1][0] == "Dispense" and len(hsl[-1][1]) < 8
  assert_same_steps(hsl, port)
  assert hsl_dialogs == port_dialogs
  assert hsl_report == port_report
  assert hsl_report or _opts(call)[12]  # a direct call with 50 or 300 uL tips writes none


def test_the_split_is_a_column_a_round():
  """The reading of CalcAliquot_v2_1: 20 wells of 30 uL with 300 uL tips are three columns, the
  third half full; 9 dispenses fit a tip (280 / 30), so one pass."""
  from venus_interop.plr.libraries.ngsstar_processes import CalcAliquot_v2_1

  a = CalcAliquot_v2_1(20, 30.0, 10.0, 10.0, 300.0, 8)
  assert a.loops == 3
  assert a.dispense_patterns == ["11111111", "11111111", "11110000"]
  assert a.aspirate == [110.0] * 4 + [80.0] * 4 and a.aspirate_pattern == "11111111"
  a = CalcAliquot_v2_1(96, 200.0, 50.0, 50.0, 1000.0, 8)
  assert a.loops == 4 and a.aspirate == [900.0] * 8
  a = CalcAliquot_v2_1(3, 50.0, 50.0, 50.0, 1000.0, 8)
  assert a.dispense_patterns == ["11100000"] and a.aspirate == [150.0] * 3 + [0.0] * 5
  with pytest.raises(ValueError):
    CalcAliquot_v2_1(8, 950.0, 50.0, 50.0, 1000.0, 8)


def test_every_well_gets_the_volume_once(lay):
  port, _, _, _ = port_steps(lay, CALLS[1])
  plate = [it for e in port if e[0] == "Dispense" for it in e[1].values() if it[0] == "MIDI_Pipette"]
  assert sorted(plate) == sorted(set(plate)) and len(plate) == 96
  assert [e[0] for e in port].count("TipPickUp") == 1 and port[-1][0] == "TipEject"
  drains = [e[3]["volumes"] for e in port if e[0] == "Dispense" and e[3]["venus"].fluid_height == 50.0]
  assert drains[1::2] == [[50.0] * 8] * 3  # each pass: the pre-dispense back, then the reserve drained


def test_a_short_trough_moves_to_the_next(lay):
  port, dialogs, _, _ = port_steps(lay, CALLS[5])
  assert [e[1] for e in port if e[0] == "Probe"] == [{1: ("RGT_01", "1")}, {1: ("RGT_02", "1")}]
  assert {it[0] for e in port if e[0] == "Aspirate" for it in e[1].values()} == {"RGT_02"}
  assert not dialogs


def test_repaired_a_part_full_column_carries_on(lay):
  """Repaired (the default): the 20 wells all filled, the tips drained and dropped."""
  port, _, _, _ = port_steps(lay, CALLS[2], faithful=False)
  plate = [it for e in port if e[0] == "Dispense" for it in e[1].values() if it[0] == "HSP_Pipette"]
  assert len(plate) == 20 == len(set(plate))
  assert [e[0] for e in port][-2:] == ["Dispense", "TipEject"]
  aspirate = next(e for e in port if e[0] == "Aspirate")
  assert aspirate[3]["volumes"] == [110.0] * 4 + [80.0] * 4
  assert aspirate[3]["venus"].mix_volume == (110.0,) * 4 + (80.0,) * 4


def test_from_tubes_the_1000_uL_copy_keeps_its_20_uL(lay):
  """The bead copy at 1000 uL: no pre-dispense back and no drain, the plate at the height given."""
  port, _, _, _ = port_steps(lay, TUBE_CALLS[0])
  assert [e[0] for e in port] == ["TipPickUp", "Aspirate", "Dispense", "Dispense", "Dispense", "TipEject"]
  assert next(e for e in port if e[0] == "Aspirate")[3]["volumes"] == [3 * 150.0 + 20] * 8
  assert {e[3]["venus"].fluid_height for e in port if e[0] == "Dispense"} == {1.5}


def test_from_tubes_three_tubes_three_tips(lay):
  port, _, _, _ = port_steps(lay, TUBE_CALLS[1])
  assert sorted(port[0][1]) == [1, 2, 3]
