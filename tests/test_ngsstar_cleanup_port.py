"""Hamilton's NGSStar framework, NGSStarProcesses' bead clean-ups: the port against the HSL library.

Process_CleanUp, Customized_Process_CleanUp_ElutionBufferInPlate, _AvenioCGP_1xEthanol and
_2BeadAdditions run on Roche Avenio CGP's layout in the HSL interpreter and in the port, each as
Avenio calls it (its literal arguments; its volumes, which the method computes, and its sequences,
which it builds, stand in for by illustrative ones on the layout), in simulation mode and not. They
are compositions of functions checked on their own (the transfer, the supernatant removal, the
mixing, the multi-dispense, the CO-RE transport, the incubation timer; the heater shaker's in the
NGSStarPrep test): this checks the composition. One timeline per side must match step for step:
every pipetting step (tips and wells per channel, volumes, settings), each liquid search, each
plate moved (what, where to), each shaker started and stopped, each incubation timer (its mode
and time: when an air-drying timer starts is otherwise invisible); and the run report row for row.
The timers themselves are answered by a model here (the incubation timer's own test checks them),
so their report rows are on neither side.

Needs VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS, and pylabrobot.
"""
import asyncio
import time

import pytest

pytest.importorskip("pylabrobot.hamilton.star.driver.lld_mode")

from port_harness import (ALIQUOT, ARRAYTOOLS, ARRAYTOOLS_MODELS, CLOCK, CREATE_CHANNEL_PATTERN,  # noqa: E402
                          REPORT_BOOK, RecordingChannels, RecordingDeck, assert_same_steps, hsl_run, report_rows,
                          steps_of)
from test_ngsstar_processes_port import LIBS, NGS, TIPS, _planner, avenio, lay, xy  # noqa: E402,F401

pytestmark = pytest.mark.skipif(NGS is None or not LIBS,
                                reason="VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS not set")

# What this test checks against the HSL (read by tools/trace_method.py --status)
LIBRARY = "NGSSTARPROCESSES"
COVERS = ["Process_CleanUp", "Customized_Process_CleanUp_ElutionBufferInPlate",
          "Customized_Process_CleanUp_AvenioCGP_1xEthanol", "Customized_Process_CleanUp_2BeadAdditions",
          "_DATA_CalculateAndDefineBatchProcessCleanUp", "_HHS_Shake"]

# Avenio's liquid classes: tip type and dispense mode (from the kit's database: 2 is "part")
P = "Roche_AVENIO_CGP_"
CLASSES = {P + "300F_CleanupBeads_SurfaceEmpty": (1, 0), P + "1000F_CleanupBeadsMixing_SurfaceEmpty": (5, 0),
           P + "300F_CleanupBeadsMixing_SurfaceEmpty": (1, 0), P + "1000F_80Ethanol_JetPart": (5, 2),
           P + "50F_PrimerMix_SurfaceEmpty": (23, 0), P + "50F_NucleaseFreeWater_SurfaceEmpty": (23, 0),
           P + "50F_UniversalEnhancingOligos_SurfaceEmpty": (23, 0),
           P + "50F_HybridizationMasterMix_SurfaceEmpty": (23, 0), P + "300F_Supernatant_JetEmpty": (1, 0),
           P + "300F_EthanolToWaste_JetEmpty": (1, 0)}
PROBES = {"51fb1bd5", "9685e7ca", "b71da740", "3526cc04", "0a018a55", "0dadcaa2"}  # the liquid searches
HHS = 3  # t_intHHS3_HSP3_MIDI3
WELLS = 24


def S(name):  # a sequence argument
  return ("seq", name)


# Avenio's four calls (Avenio CGP_v1.0.1.sub), the sequences and the computed volumes illustrative
BEADS, ETHANOL, MAGNET, SHAKER, WASTE = S("RGT_Beads"), S("RGT_Ethanol"), S("MIDI_OnMagnet"), S("HHS3_MIDI"), S("LiquidWaste")
CALLS = {
  "Customized_Process_CleanUp_ElutionBufferInPlate": [
    BEADS, BEADS, SHAKER, ETHANOL, MAGNET, WASTE, S("HSP_Pipette2"), 1, 200, 90, 20, 220,
    P + "300F_CleanupBeads_SurfaceEmpty", P + "1000F_CleanupBeadsMixing_SurfaceEmpty", P + "1000F_80Ethanol_JetPart",
    P + "50F_PrimerMix_SurfaceEmpty", P + "300F_Supernatant_JetEmpty", P + "300F_EthanolToWaste_JetEmpty",
    1800, 1200, 300, 20, 3, HHS, 0, 300, 420, 120, 300, 180],
  "Customized_Process_CleanUp_2BeadAdditions": [
    BEADS, BEADS, SHAKER, ETHANOL, MAGNET, WASTE, S("RGT_Te_Buffer"), 200, 50, 50, 30, 25, 100, 100,
    P + "300F_CleanupBeads_SurfaceEmpty", P + "1000F_CleanupBeadsMixing_SurfaceEmpty", P + "1000F_80Ethanol_JetPart",
    P + "50F_NucleaseFreeWater_SurfaceEmpty", P + "300F_Supernatant_JetEmpty", P + "300F_EthanolToWaste_JetEmpty",
    1500, 1200, 60, 60, 3, HHS, 0, 600, 500, 180, 180, 120, 180],  # Avenio: 600, 600 (the 2nd made 500 to tell them apart)
  "Customized_Process_CleanUp_AvenioCGP_1xEthanol": [
    BEADS, BEADS, SHAKER, ETHANOL, MAGNET, WASTE, S("RGT_Tris"), S("RGT_Te_Buffer"), 200, 80, 10, 40, 270,
    P + "300F_CleanupBeads_SurfaceEmpty", P + "1000F_CleanupBeadsMixing_SurfaceEmpty", P + "1000F_80Ethanol_JetPart",
    P + "50F_UniversalEnhancingOligos_SurfaceEmpty", P + "50F_HybridizationMasterMix_SurfaceEmpty",
    P + "300F_Supernatant_JetEmpty", P + "300F_EthanolToWaste_JetEmpty", 1500, 1800, 60, 60, 3, HHS, 0, 600, 180,
    180, 120, 180],
  "Process_CleanUp": [
    BEADS, BEADS, SHAKER, ETHANOL, MAGNET, WASTE, S("RGT_Te_Buffer"), 200, 90, 25, 100,
    P + "300F_CleanupBeads_SurfaceEmpty", P + "300F_CleanupBeadsMixing_SurfaceEmpty", P + "1000F_80Ethanol_JetPart",
    P + "50F_NucleaseFreeWater_SurfaceEmpty", P + "300F_Supernatant_JetEmpty", P + "300F_EthanolToWaste_JetEmpty",
    1500, 1200, 60, 60, 3, HHS, 0, 600, 180, 180, 120, 180],
}
N ="NGSSTARPROCESSES::"


def _hsl_arg(a):
  if isinstance(a, tuple):
    return f"ML_STAR.{a[1]}"
  return f'"{a}"' if isinstance(a, str) else str(a)


def _source(fn):
  return (
    'namespace _Method { #include "HSLSeqLib.hsl" }\n'
    'namespace _Method { #include "NGSStarProcesses.hs_" }\n'
    'global device ML_STAR ("x.lay", "ML_STAR", hslTrue);\n'
    'namespace _Method { #include "HSLMECCLib.hs_" }\n' + ARRAYTOOLS + CREATE_CHANNEL_PATTERN + ALIQUOT
    + "namespace _Method { namespace TESTINPUT { function Simulation() variable { variable v; return(v); } } }\n"
    "namespace _Method { method main() void {\n"
    + "".join(f"{N}t_seqTips{k} = ML_STAR.{TIPS[t]};\n" for k, t in (("300", 1), ("1000", 5), ("50", 23)))
    + f"{N}t_intNumberOfAllAvailableChannels = 8;\n{N}t_blnDeactivatePipettingStepsForTransportTests = 0;\n"
    + f"{N}t_blnSimulationModeON = TESTINPUT::Simulation();\n"
    + f'{N}t_strFullPathReportFile = "{REPORT_BOOK}";\n'
    + f"{N}t_intTransportTool = 2;\n{N}t_intFrontChannelCORETransport = 7;\n"
    + f"{N}t_seqCOREGripper = ML_STAR.COREGripTool_OnWaste_1000ul_0001;\n"
    + f"ML_STAR.HHS3_MIDI.SetCount({WELLS});\nML_STAR.MIDI_OnMagnet.SetCount({WELLS});\n"
    + f"{N}{fn}(ML_STAR, " + ", ".join(_hsl_arg(a) for a in CALLS[fn]) + ");\n"
    + "} }\n")


MEASURED = 20000.0  # what every liquid search finds, uL


def hsl_steps(avenio, lay, fn, sim):
  shaker = []  # (index into the run's events, event)

  def tip_type(run, p):
    p["o_inttiptype"].value, p["o_intdispensemode"].value = CLASSES[str(p["i_strliquidclassname"].value)]
    return 0

  def hhs(event):
    def model(run, p):
      h = int(p["devicenumber"].value)
      shaker.append((len(run.events), ("Shaker", {1: (h, event)},
                                       f"{p['shakingspeed'].value}" if event == "shake" else "", {})))
      if event == "stop":  # StopShaker: "stop shaking and unlock plate"
        shaker.append((len(run.events), ("Shaker", {1: (h, "unlock")}, "", {})))
      return 0
    return model

  def timer(run, p):
    shaker.append((len(run.events), ("Timer", {}, f"{p['i_inttimermode'].value}:{p['i_inttime'].value}", {})))
    return 0

  nothing = lambda run, p: 0  # noqa: E731
  litres = lambda run, p: MEASURED / 1000  # noqa: E731
  run = hsl_run(_source(fn), avenio / "Library" / "port_test.hsl", [avenio / "Library", avenio / "Methods", *LIBS],
                (avenio / "Library").glob("*.stp"), {"x.lay": lay}, answers={
                  "clock": time.struct_time(CLOCK), "cfg.1": 8, "cfg.26": 9.0,
                  "labware_position": lambda lab, pos: (*xy((lab, pos)), 0.0),
                  "functions": {"ngsstarprocesses::_data_gettiptypeanddispensemodeofliquidclass": tip_type,
                                "ngsstarprocesses::_data_scheduleconsumables": nothing,
                                "ngsstarprocesses::data_incubationtimer": timer,
                                "hslml_star::measurecontainervolume2": litres, "hslml_star::getcontainervolume": litres,
                                "hslml_star::aspirationmonitoring_1000ulchannel_off": nothing,
                                "hslml_star::aspirationmonitoring_1000ulchannel_on": nothing,
                                "hslhamheatershaker::startshaker": hhs("shake"),
                                "hslhamheatershaker::stopshaker": hhs("stop"),
                                "stcc::resetfiltersequences": nothing, "stcc::addfiltersequence": nothing,
                                "stcc::generatemappingfilev43ex1": nothing,
                                "testinput::simulation": lambda run, p: sim, **ARRAYTOOLS_MODELS}})
  out, get = [], None
  for i, (e, step) in enumerate(zip(run.events, steps_of(run))):
    out += [s for at, s in shaker if at == i]
    if e.command == "OptimizeFollowSpeed":  # left out of the port (CONVENTIONS §11)
      continue
    if e.command == "ZSwapGetPlate":
      get = e.channels[1][0]
    elif e.command == "ZSwapPlacePlate":
      out.append(("Move", {1: (get, e.channels[1][0])}, "", {}))
    elif e.command in ("LabwareShift", "Move96Head", "MoveToPosition"):
      continue
    else:
      out.append(("Probe", step[1], "", {}) if e.guid[:8] in PROBES else step)
  out += [s for at, s in shaker if at == len(run.events)]
  return out, report_rows(run)


class _Gripper:
  def __init__(self, events):
    self.events = events

  async def to_placeholder(self, thing, placeholder, **kw):
    self.events.append(("Move", {1: (thing, placeholder)}, "", {}))


class _Shaker:
  def __init__(self, events):
    self.events = events

  async def shake(self, speed):
    self.events.append(("Shaker", {1: (HHS, "shake")}, f"{speed}", {}))

  async def stop_shaking(self):
    self.events.append(("Shaker", {1: (HHS, "stop")}, "", {}))

  async def unlock_plate(self):
    self.events.append(("Shaker", {1: (HHS, "unlock")}, "", {}))


def port_steps(lay, fn, sim, faithful=True):
  from venus_interop.plr.libraries.ngsstar_prep import NGSStarPrep
  from venus_interop.plr.libraries.ngsstar_processes import NGSStarProcesses
  from venus_interop.plr.libraries.ngsstar_report import RunReport

  deck = RecordingDeck(lay)
  for name in ("HHS3_MIDI", "MIDI_OnMagnet"):
    deck.seq(name).set_count(WELLS)
  with RecordingChannels(measured=MEASURED) as ch:
    prep = NGSStarPrep({HHS: _Shaker(ch.events)}, simulation=bool(sim), time_scale=0.0)
    procs = NGSStarProcesses(type("Star", (), {"pipettes": ch})(), deck, TIPS, CLASSES, planner=_planner(deck.live),
                             gripper=_Gripper(ch.events), simulation=bool(sim), prep=prep, faithful=faithful,
                             report=RunReport(clock=lambda: time.struct_time(CLOCK)), say=lambda _: None)
    procs._lc = lambda name: None

    async def timer(name, seconds, mode):
      ch.events.append(("Timer", {}, f"{mode}:{seconds}", {}))
    procs.DATA_IncubationTimer = timer
    args = [a[1] if isinstance(a, tuple) else a for a in CALLS[fn]]
    asyncio.run(getattr(procs, fn)(None, *args))
  return ch.events, procs.report.rows


@pytest.mark.parametrize("sim", [1, 0], ids=["simulation", "run"])
@pytest.mark.parametrize("fn", list(CALLS))
def test_port_cleans_up_as_the_library_does(avenio, lay, fn, sim):
  (hsl, hsl_report), (port, port_report) = hsl_steps(avenio, lay, fn, sim), port_steps(lay, fn, sim)
  assert len(hsl) > 20
  assert_same_steps(hsl, port)
  assert hsl_report == port_report
  shakes = [e for e in port if e[0] == "Shaker"]
  assert (not shakes) if sim else shakes


def test_batches(lay):
  """_DATA_CalculateAndDefineBatchProcessCleanUp: 24 wells in batches of one column, with scale-up,
  are three; without, one (repaired; faithful, the count says three and the second GetAt fails)."""
  from venus_interop.plr.libraries.ngsstar_processes import NGSStarProcesses

  for faithful, scale_up, want in ((False, 1, [8, 8, 8]), (False, 0, [24]), (True, 0, [24])):
    deck = RecordingDeck(lay)
    deck.seq("MIDI_OnMagnet").set_count(WELLS)
    procs = NGSStarProcesses(type("Star", (), {"pipettes": None})(), deck, TIPS, CLASSES, faithful=faithful)
    batches, count = procs._DATA_CalculateAndDefineBatchProcessCleanUp(1, scale_up, "MIDI_OnMagnet")
    assert [len(b.items[:b.end]) for b in batches] == want
    assert count == (3 if faithful else len(want))
    assert deck.seq("MIDI_OnMagnet").cur == 1
    if faithful:
      with pytest.raises(RuntimeError, match="GetAt"):
        list(procs._batches(batches, count, "MIDI_OnMagnet"))
