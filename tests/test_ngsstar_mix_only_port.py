"""Hamilton's NGSStar framework, NGSStarProcesses' PIP_MixOnly: the port against the HSL library.

PIP_MixOnly runs on Roche Avenio CGP's layout in the HSL interpreter and in the port, for each tip
type: a trough (the mix volume measured and shared among the channels, capped), tubes (not
shared), more tubes than channels (two slices, one set of tips), ten troughs that the library
folds into one position, a fixed height, a measurement below zero. Every step must use the same
tips and wells per channel with the same settings, the mix volume included; the liquid search
(Venus: a 0 uL cLLD aspirate on channel 1, then HSLML_STAR::MeasureContainerVolume2 /
GetContainerVolume, compiled; the port: PLR's probe_liquid_volumes) must be on the same container,
and finds the same volume on both sides (a test value). STAR Tip Tools' Optimized1mLTipPickup2
runs as HSL (its positions from a synthetic geometry, the same on both sides), Create_Channel_Pattern
and ArrayTools as models (port_harness).

Needs VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS, and pylabrobot.
"""
import asyncio
import dataclasses

import pytest

pytest.importorskip("pylabrobot.hamilton.star.driver.lld_mode")

from port_harness import (ARRAYTOOLS, ARRAYTOOLS_MODELS, CREATE_CHANNEL_PATTERN, RecordingChannels,  # noqa: E402
                          RecordingDeck, assert_same_steps, hsl_run, steps_of)
from venus_interop.files import layout  # noqa: E402
from test_ngsstar_processes_port import CLASSES, LIBS, NGS, TIPS, _planner, avenio, lay, xy  # noqa: E402,F401

pytestmark = pytest.mark.skipif(NGS is None or not LIBS,
                                reason="VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS not set")

# What this test checks against the HSL (read by tools/trace_method.py --status)
LIBRARY = "NGSSTARPROCESSES"
COVERS = ["PIP_MixOnly"]
COVERS_ALSO = {"STAR_TIP_TOOLS": ["Optimized1mLTipPickup2"]}

PROBES = {"51fb1bd5", "9685e7ca", "b71da740"}  # the 0 uL cLLD aspirates that find the liquid
# (positions, sequence, height, class, mix cycles, mix volume, measured uL[, first tip])
CALLS = [
  (8, "RGT_Beads", 0, "LC1000", 10, 0, 12000.0),  # a trough: 9000 / 8, capped at 900
  (8, "RGT_Beads", 0, "LC1000", 10, 0, 2000.0),  # 1500 / 8
  (3, "CAR_VIALS_LARGE", 0, "LC300", 10, 0, 300.0),  # tubes: 225 each
  (12, "CAR_VIALS_LARGE", 0, "LC1000", 10, 0, 1000.0),  # two slices, one set of tips
  (10, "RGT50", 0, "LC50", 10, 0, 40.0),  # ten troughs, all position 1: one, on the last
  (5, "CAR_VIALS_SMALL", 2.5, "LC300", 4, 300, 0.0),  # a fixed height: 300 capped at 270
  (2, "CAR_VIALS_SMALL", 1.0, "LC50", 3, 20, 0.0),  # at 1 mm: no liquid following
  (4, "CAR_VIALS_LARGE", 0, "LC1000", 10, 0, -1.0),  # below zero: 50
  (12, "RGT_Wide", 0, "LC1000", 10, 0, 4000.0),  # a trough wider than the channels: 3000 / 8
  (3, "CAR_VIALS_LARGE", 0, "LC1000", 10, 0, 800.0, 5),  # three tips left in the column: taken there
  (3, "CAR_VIALS_LARGE", 0, "LC1000", 10, 0, 800.0, 7),  # two left: the planner moves to the next column
]
# Illustrative, for the channel cap on the share (Avenio's troughs have 8 positions): 12 on one
WIDE = layout.Sequence("RGT_Wide", [("RGT_10", str(k)) for k in range(1, 13)])


SEQUENCES = ["RGT_Beads", "CAR_VIALS_LARGE", "RGT50", "CAR_VIALS_SMALL", "RGT_Wide"]
INPUTS = ["Sequence", "Count", "Height", "LiquidClass", "Cycles", "Volume", "TipStart"]
N = "NGSSTARPROCESSES::"
# One source for every case (parsed once): the call's inputs from TESTINPUT functions, answered per run
SRC = (
  'namespace _Method { #include "HSLSeqLib.hsl" }\n'
  'namespace _Method { #include "NGSStarProcesses.hs_" }\n'
  'global device ML_STAR ("x.lay", "ML_STAR", hslTrue);\n'
  'namespace _Method { #include "HSLMECCLib.hs_" }\n' + ARRAYTOOLS + CREATE_CHANNEL_PATTERN +
  "namespace _Method { namespace TESTINPUT {\n"
  + "".join(f"function {k}() variable {{ variable v; return(v); }}\n" for k in INPUTS) + "} }\n"
  "namespace _Method { method main() void {\n"
  + "".join(f"ML_STAR.{TIPS[t]}.SetCurrentPosition(TESTINPUT::TipStart());\n{N}t_seqTips{k} = ML_STAR.{TIPS[t]};\n"
            for k, t in (("300", 1), ("1000", 5), ("50", 23)))
  + f"{N}t_intNumberOfAllAvailableChannels = 8;\n{N}t_blnDeactivatePipettingStepsForTransportTests = 0;\n"
  + f"{N}t_blnSimulationModeON = 0;\n"
  + "".join(f"if (TESTINPUT::Sequence() == {i}) {{ ML_STAR.{s}.SetCount(TESTINPUT::Count());\n"
            f"{N}PIP_MixOnly(ML_STAR, ML_STAR.{s}, TESTINPUT::Height(), TESTINPUT::LiquidClass(), "
            "TESTINPUT::Cycles(), TESTINPUT::Volume()); }\n" for i, s in enumerate(SEQUENCES))
  + "} }\n")


@pytest.fixture(scope="module")
def mlay(lay):
  return dataclasses.replace(lay, sequences=[*lay.sequences, WIDE])


def hsl_steps(avenio, lay, call, max_steps=2_000_000):
  n, seq, height, lc, cycles, volume, measured, *first = call

  def tip_type(run, p):
    p["o_inttiptype"].value, p["o_intdispensemode"].value = CLASSES[str(p["i_strliquidclassname"].value)]
    return 0

  litres = lambda run, p: measured / 1000  # noqa: E731  Venus's container volume, in mL
  inputs = dict(zip(INPUTS, (SEQUENCES.index(seq), n, height, lc, cycles, volume, first[0] if first else 1)))
  run = hsl_run(SRC, avenio / "Library" / "port_test.hsl", [avenio / "Library", avenio / "Methods", *LIBS],
                (avenio / "Library").glob("*.stp"), {"x.lay": lay}, max_steps=max_steps, answers={
                  "cfg.1": 8, "cfg.26": 9.0, "labware_position": lambda lab, pos: (*xy((lab, pos)), 0.0),
                  "functions": {"ngsstarprocesses::_data_gettiptypeanddispensemodeofliquidclass": tip_type,
                                "hslml_star::measurecontainervolume2": litres, "hslml_star::getcontainervolume": litres,
                                **{f"testinput::{k.lower()}": (lambda v: lambda run, p: v)(v) for k, v in inputs.items()},
                                **ARRAYTOOLS_MODELS}})
  out = []
  for e, step in zip(run.events, steps_of(run)):  # one per event, in order
    if e.command == "OptimizeFollowSpeed":  # left out of the port (commented there): CONVENTIONS §11
      continue
    # the liquid search: where, not how (PLR searches its own way)
    out.append(("Probe", step[1], "", {}) if e.guid[:8] in PROBES else step)
  classes = [e.settings["LiquidName"] for e in run.events if e.command == "Aspirate"]
  return out, classes


def port_steps(lay, call, faithful=True):
  from venus_interop.plr.libraries.ngsstar_processes import NGSStarProcesses

  n, seq, height, lc, cycles, volume, measured, *first = call
  deck = RecordingDeck(lay)
  deck.seq(seq).set_count(n)
  for tips in TIPS.values():
    deck.seq(tips).set_current_position(first[0] if first else 1)
  with RecordingChannels(measured=measured) as ch:
    procs = NGSStarProcesses(type("Star", (), {"pipettes": ch})(), deck, TIPS, CLASSES, planner=_planner(deck.live),
                             faithful=faithful)
    classes = []
    procs._lc = lambda name: classes.append(name)  # the class asked for; none given to the recorder
    asyncio.run(procs.PIP_MixOnly(None, seq, height, lc, cycles, volume))
  return ch.events, classes


@pytest.mark.parametrize("call", CALLS, ids=[f"{c[3]}-{c[1]}-n{c[0]}-h{c[2]}-{c[6]:g}uL" + (f"-tip{c[7]}" if len(c) > 7 else "")
                                  for c in CALLS])
def test_port_mixes_as_the_library_does(avenio, mlay, call):
  (hsl, hsl_classes), (port, _) = hsl_steps(avenio, mlay, call), port_steps(mlay, call)
  assert [e[0] for e in hsl][:2] == ["TipPickUp", "Probe" if call[2] == 0 else "Aspirate"]
  assert_same_steps(hsl, port)
  assert set(hsl_classes) == {call[3]}


def test_the_mix_volume_is_what_the_library_works_out(avenio, lay):
  """The numbers themselves, from the library's arithmetic: a trough shares 75 % of what it holds."""
  port, _ = port_steps(lay, CALLS[1])
  mixes = [e[3]["venus"].mix_volume for e in port if e[0] == "Aspirate"]
  assert mixes == [2000.0 * 0.75 / 8]
  port, _ = port_steps(lay, CALLS[0])
  assert [e[3]["venus"].mix_volume for e in port if e[0] == "Aspirate"] == [900.0]


def test_a_trough_shares_among_the_channels_not_the_positions(mlay):
  port, _ = port_steps(mlay, CALLS[8])
  assert [e[3]["venus"].mix_volume for e in port if e[0] == "Aspirate"] == [4000.0 * 0.75 / 8] * 2


def test_ten_troughs_at_position_1_mix_one_position_on_the_last(lay):
  port, _ = port_steps(lay, CALLS[4])
  assert [e[1] for e in port if e[0] == "Aspirate"] == [{1: ("RGT_10", "1")}]


def test_repaired_ten_troughs_are_ten_containers(lay):
  """Repaired (the default): each (labware, position) of the sequence, two slices on one set of tips."""
  port, _ = port_steps(lay, CALLS[4], faithful=False)
  mixed = [it for e in port if e[0] == "Aspirate" for it in e[1].values()]
  assert mixed == [(f"RGT_{k:02}", "1") for k in range(1, 11)]
  assert [e[0] for e in port].count("TipPickUp") == 1


def test_repaired_300_uL_tips_mix_every_slice(lay):
  call = (12, "CAR_VIALS_LARGE", 0, "LC300", 10, 0, 300.0)
  port, _ = port_steps(lay, call, faithful=False)
  assert [e[0] for e in port] == ["TipPickUp", "Probe", "Aspirate", "Probe", "Aspirate", "TipEject"]
  assert [len(e[1]) for e in port if e[0] == "Aspirate"] == [8, 4]
  assert [e[3]["venus"].mix_volume for e in port if e[0] == "Aspirate"] == [225.0, 225.0]


def test_more_tubes_than_channels_with_300_uL_tips_never_ends(avenio, lay):
  """The library mixes the first slice only with 300 uL tips (its mix inside the first pass's
  block) and loops on: the interpreter runs out of steps; the port says so."""
  call = (12, "CAR_VIALS_LARGE", 0, "LC300", 10, 0, 300.0)
  with pytest.raises(AssertionError, match="step budget"):
    hsl_steps(avenio, lay, call, max_steps=100_000)  # the calls that finish take under 13,000
  with pytest.raises(RuntimeError, match="without end"):
    port_steps(lay, call)
