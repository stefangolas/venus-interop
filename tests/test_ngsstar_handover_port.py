"""Hamilton's NGSStar framework, NGSStarProcesses' DATA_HandoverSequencesAndDataToSMT: the port
against the HSL.

The framework's set-up runs in the HSL interpreter and in the port on Roche Avenio CGP's layout, as
Avenio calls it and with 4 channels, a Clinical NGS STARlet, the cover unlocked and tip counters
holding used racks. Both must leave the same state: the channel count and patterns, the CO-RE
transport's front channel, the platform, the cover locking, the transport tool, each tip sequence
(as its counter left it) and the counter names written to after, and the report's name. Venus's
deck-layout object, which lists the deck's labware and sequences, is answered from the layout
(`_DATA_GetLabwareIDAndSequenceNamesFromDeck`).

Needs VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS.
"""
import time

import pytest

pytest.importorskip("pylabrobot.hamilton.star.driver.lld_mode")

from port_harness import CLOCK, RecordingDeck, hsl_eval, hsl_run  # noqa: E402
from test_ngsstar_processes_port import LIBS, NGS, TIPS, _planner, avenio, lay  # noqa: E402,F401

pytestmark = pytest.mark.skipif(NGS is None or not LIBS,
                                reason="VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS not set")

# What this test checks against the HSL (read by tools/trace_method.py --status)
LIBRARY = "NGSSTARPROCESSES"
COVERS = ["DATA_HandoverSequencesAndDataToSMT", "DATA_TrackDataFromLoadingSMT"]

N = "NGSSTARPROCESSES::"
INPUTS = ["Tool", "Reduce", "Lock", "Platform"]
SRC = (
  'namespace _Method { #include "HSLSeqLib.hsl" }\n'
  'namespace _Method { #include "NGSStarProcesses.hs_" }\n'
  'global device ML_STAR ("x.lay", "ML_STAR", hslTrue);\n'
  'namespace _Method { #include "HSLMECCLib.hs_" }\n'
  "namespace _Method { namespace TESTINPUT {\n"
  + "".join(f"function {k}() variable {{ variable v; return(v); }}\n" for k in INPUTS) + "} }\n"
  "namespace _Method { global variable g_path; method main() void { variable path; sequence a; sequence b; sequence c;\n"
  f'{N}DATA_HandoverSequencesAndDataToSMT(ML_STAR, TESTINPUT::Tool(), "Roche", "Avenio CGP", 0, TESTINPUT::Reduce(), '
  '"", TESTINPUT::Lock(), path, 0, TESTINPUT::Platform(), "50F_Counter", "SVF_Counter", "1000F_Counter", a, b, c);\n'
  f"{N}DATA_TrackDataFromLoadingSMT(0, 40, 96, 24);\n"
  "g_path = path; } }\n")
# (transport tool, reduce to 4 channels, lock the cover, platform, tip counters: name -> first position left)
CASES = [(2, 0, 1, 1, {}), (1, 1, 0, 2, {})]
SEQ_OF = {"50F_Counter": TIPS[23], "SVF_Counter": TIPS[1], "1000F_Counter": TIPS[5]}
GLOBALS = ["t_intNumberOfAllAvailableChannels", "t_strChannelpattern", "t_strTransportChannelpattern",
           "t_intFrontChannelCORETransport", "t_blnClinicalNGSStarlet", "t_blnLockUnlockSystem", "t_intTransportTool",
           "t_strTipCounterNameTip50", "t_strTipCounterNameTip300", "t_strTipCounterNameTip1000"]


def hsl_state(avenio, lay, case):
  tool, reduce, lock, platform, counters = case
  layout_names = ([p.id for p in lay.labware], [s.name for s in lay.sequences])

  def deck_names(run, p):  # Venus's deck-layout object: the layout's labware and sequence names
    p["o_arraylabwarenames"].value = hsl_eval.HArray(list(layout_names[0]))
    p["o_arrayseqnames"].value = hsl_eval.HArray(list(layout_names[1]))
    return 0

  stored = dict(counters)  # the interpreter takes a counter as its first position left
  inputs = dict(zip(INPUTS, (tool, reduce, lock, platform)))
  run = hsl_run(SRC, avenio / "Library" / "port_test.hsl", [avenio / "Library", avenio / "Methods", *LIBS],
                (avenio / "Library").glob("*.stp"), {"x.lay": lay},
                # STAR Tip Tools calls it; its body is empty, which the parser takes for a header placeholder
                allow_unresolved=["TIP_OFFSET_GLOBAL::INIT::InitializeVariables"], answers={
                  "clock": time.struct_time(CLOCK), "cfg.1": 8, "cfg.26": 9.0, "tip_counters": stored,
                  "functions": {"ngsstarprocesses::_data_getlabwareidandsequencenamesfromdeck": deck_names,
                                **{f"testinput::{k.lower()}": (lambda v: lambda run, p: v)(v) for k, v in inputs.items()}}})
  cells = {k.lower(): c.value for ns, sc in run.globals.items() if ns.lower().endswith("ngsstarprocesses")
           for k, c in sc.items()}
  state = {g: cells[g.lower()] for g in GLOBALS}
  for k in ("50", "300", "1000"):
    s = cells[f"t_seqtips{k}"]
    state[f"tips{k}"] = (s.items[s.cur - 1:s.end] if s.cur > 0 else [])
  path = next(c.value for sc in run.globals.values() for k, c in sc.items() if k == "g_path")
  state["report"] = str(path).rsplit("\\", 1)[-1].rsplit(".", 1)[0]
  return state


def _items(lay, name):
  return [tuple(it) for it in next(s for s in lay.sequences if s.name == name).items]


def port_state(lay, case):
  from venus_interop.plr.libraries import ngsstar_processes as npm
  from venus_interop.plr.libraries.ngsstar_report import RunReport
  from venus_interop.plr.libraries.tip_count import OCCUPIED

  tool, reduce, lock, platform, counters = case
  deck = RecordingDeck(lay)
  procs = npm.NGSStarProcesses(type("Star", (), {"pipettes": None})(), deck, {}, {}, planner=_planner(deck.live),
                               report=RunReport(clock=lambda: time.struct_time(CLOCK)))
  procs.planner.v.sequences = deck.sequences
  types = {"SVF_Counter": npm.SVFT, "1000F_Counter": npm.HVFT, "50F_Counter": npm.LVFT}
  for name, pos in counters.items():
    seq = npm.NGSStarProcesses.TIP_SEQUENCES[types[name]]
    procs.planner.counters.write(name, [(it, OCCUPIED) for it in _items(lay, seq)[pos - 1:]])
  path, *_ = procs.DATA_HandoverSequencesAndDataToSMT(None, tool, "Roche", "Avenio CGP", 0, reduce, "", lock, 0,
                                                      platform, "50F_Counter", "SVF_Counter", "1000F_Counter")
  procs.DATA_TrackDataFromLoadingSMT(0, 40, 96, 24)
  state = {
    "t_intNumberOfAllAvailableChannels": procs.channels, "t_strChannelpattern": procs.channel_pattern,
    "t_strTransportChannelpattern": procs.transport_pattern, "t_intFrontChannelCORETransport": procs.front_channel,
    "t_blnClinicalNGSStarlet": int(procs.clinical_starlet), "t_blnLockUnlockSystem": int(procs.lock_unlock),
    "t_intTransportTool": procs.transport_tool,
    **{f"t_strTipCounterNameTip{k}": procs.tip_counters[t] for k, t in (("50", npm.LVFT), ("300", npm.SVFT),
                                                                       ("1000", npm.HVFT))}}
  for k, t in (("50", npm.LVFT), ("300", npm.SVFT), ("1000", npm.HVFT)):
    s = deck.seq(procs.tips[t])
    state[f"tips{k}"] = s.items[s.cur - 1:s.end] if s.cur > 0 else []
  stamp = time.strftime("%Y%m%d_%H%M%S", time.struct_time(CLOCK))
  state["report"] = f"{stamp}_NGSStarReport_Avenio CGP"
  assert path is None and procs.max_tips_after_edit == {npm.SVFT: 40, npm.HVFT: 96} and procs.samples == 24
  return state


@pytest.mark.parametrize("case", CASES, ids=["avenio", "4-channels-clinical-iswap"])
def test_port_sets_up_as_the_library_does(avenio, lay, case):
  hsl, port = hsl_state(avenio, lay, case), port_state(lay, case)
  assert {k: (list(map(tuple, v)) if k.startswith("tips") else v) for k, v in hsl.items()} == port


def test_the_counters_are_read(lay):
  """Port only: STAR Tip Tools' TipCounter_Read in the HSL needs the tip type from Venus's labware
  data (_GetTipType), which the interpreter doesn't answer, so there it reads no counter. The port
  reads each under the name given and goes on under the framework's own."""
  state = port_state(lay, (2, 0, 1, 1, {"SVF_Counter": 30, "1000F_Counter": 90}))
  assert state["tips300"][0] == ("stf_l_0001", "30") and state["tips1000"][0] == ("HTF_L_0001", "90")
  assert state["tips50"][0] == ("TIP_50ulF_L_0001", "1")
