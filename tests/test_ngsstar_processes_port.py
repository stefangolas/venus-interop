"""Hamilton's NGSStar framework, NGSStarProcesses: the port against the HSL library itself.

PIP_ReagentsFromTubeOrTroughOrPlateToPlate runs on Roche Avenio CGP's layout in the HSL interpreter
and in the port, for each tip type and the branches that matter (tips exchanged or kept, the
aspiration sequence advanced or not, cLLD or fixed heights, a last slice narrower than the
channels). Every step must use the same tips and wells per channel, and the same cLLD or
fixed-height step record.

What Venus does through compiled services is modelled on both sides alike: the liquid class's tip
type and dispense mode (a table), the tip planner (STAR Tip Tools, unit-tested on its own in
test_star_tip_tools.py, here on a synthetic rack geometry), and the sample-tracking calls (STCC,
nothing).

Needs VENUS_INTEROP_NGS (an NGS-Protocols checkout: the Avenio CGP kit) and
VENUS_INTEROP_HAMILTON_LIBS (library folders, separated by os.pathsep, for what the kit includes from
elsewhere: Venus's Library, a folder holding `STAR Tools\\`, one holding `HSL_MethodHelper.hsl`),
and pylabrobot.
"""
import asyncio
import os
import pathlib

import pytest

pytest.importorskip("pylabrobot.hamilton.star.driver.lld_mode")

from venus_interop.files import layout  # noqa: E402
from venus_interop.methods import hsl_eval, protocol, sequences as sq  # noqa: E402

NGS = pathlib.Path(os.environ["VENUS_INTEROP_NGS"]) if os.environ.get("VENUS_INTEROP_NGS") else None
LIBS = [pathlib.Path(p) for p in os.environ.get("VENUS_INTEROP_HAMILTON_LIBS", "").split(os.pathsep) if p]
pytestmark = pytest.mark.skipif(NGS is None or not LIBS,
                                reason="VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS not set")

# What this test checks against the HSL (read by tools/trace_method.py --status)
LIBRARY = "NGSSTARPROCESSES"
COVERS = ["PIP_ReagentsFromTubeOrTroughOrPlateToPlate"]

TIPS = {1: "MlStar300ulStandardVolumeTipWithFilter", 5: "MlStar1000ulHighVolumeTipWithFilter", 23: "MlStar50ulTipWithFilter"}
CLASSES = {"LC300": (1, 0), "LC1000": (5, 0), "LC50": (23, 0)}
LLD_ASPIRATES = {"3de044fd", "7438ccf5", "e3697ea4"}  # the cLLD records; the others are fixed height
LLD_DISPENSES = {"39efb96f", "9726387a", "7302ffe4"}
# (dispense count, aspiration, dispense, volume, class, mix cycles, mix asp, mix disp, asp height,
#  disp height, tip exchange, increment aspiration, liquid following at a fixed dispense)
CALLS = [
  (24, "RGT_Beads", "HSP_Pipette", 20, "LC300", 0, 0, 0, 0, 0, 0, 0, 0),
  (12, "RGT_Beads", "HSP_Pipette", 15, "LC50", 2, 10, 10, 3.0, 0, 0, 0, 0),
  (24, "HSP_onCPAC", "HSP_Pipette2", 50, "LC1000", 0, 0, 0, 1.5, 2.0, 1, 1, 1),
  (16, "RGT_Tris", "HSP_Pipette", 30, "LC300", 3, 0, 25, 0, 1.0, 1, 0, 0),
]


@pytest.fixture(scope="module")
def avenio():
  return NGS / "assets" / "NGSStar" / "Roche" / "Avenio CGP"


@pytest.fixture(scope="module")
def lay(avenio):
  return layout.read_layout(avenio / "Methods" / "Avenio CGP.lay")


def xy(item):
  """A synthetic deck: racks side by side, columns 9 mm apart in X, rows 9 mm apart in Y."""
  lab, pos = item
  rack = sum(map(ord, lab)) % 7
  return 100.0 + rack * 120.0 + (int(pos[1:]) - 1) * 9.0 if pos[1:].isdigit() else 0.0, 300.0 - "ABCDEFGH".index(pos[0]) * 9.0 if pos[0] in "ABCDEFGH" else 300.0 - int(pos) * 9.0 % 72


def _planner(seqs):
  from venus_interop.plr.libraries.star_tip_tools import StarTipTools

  class Shim:
    def seq(self, name):
      return seqs[name]
  return StarTipTools(Shim(), 8, xy=xy)


def hsl_steps(avenio, lay, call):
  n, asp, disp, vol, lc, cyc, mva, mvd, ha, hd, ex, inc, lf = call
  N = "NGSSTARPROCESSES::"
  src = (
    'namespace _Method { #include "HSLSeqLib.hsl" }\n'
    'namespace _Method { #include "NGSStarProcesses.hs_" }\n'
    'global device ML_STAR ("x.lay", "ML_STAR", hslTrue);\n'
    'namespace _Method { #include "HSLMECCLib.hs_" }\n'
    "namespace _Method { method main() void {\n"
    + "".join(f"{N}t_seqTips{k} = ML_STAR.{v};\n" for k, v in (("300", TIPS[1]), ("1000", TIPS[5]), ("50", TIPS[23])))
    + f"{N}t_intNumberOfAllAvailableChannels = 8;\n{N}t_blnDeactivatePipettingStepsForTransportTests = 0;\n"
    f"ML_STAR.{disp}.SetCount({n});\n"
    f'{N}PIP_ReagentsFromTubeOrTroughOrPlateToPlate(ML_STAR, ML_STAR.{asp}, ML_STAR.{disp}, {vol}, "{lc}", {cyc}, '
    f"{mva}, {mvd}, {ha}, {hd}, {ex}, {inc}, {lf});\n" "} }\n")
  roots = [avenio / "Library", avenio / "Methods", *LIBS]
  stps = protocol.load_stps(sorted((avenio / "Library").glob("*.stp")))
  pre = hsl_eval.Preprocessor(roots, lambda p: p.read_text(encoding="latin-1"))
  text = pre.expand(avenio / "Library" / "port_test.hsl", text=src)
  parser = hsl_eval.Parser(hsl_eval.lex(text))
  parser.unit()

  def tip_type(run, p):
    p["o_inttiptype"].value, p["o_intdispensemode"].value = CLASSES[str(p["i_strliquidclassname"].value)]
    return 0

  def planner(run, p):
    tips, ctl = p["io_seq_tipsequence"].value, p["i_seq_controlsequence"].value
    p["o_str_channelpattern"].value = _planner({tips.name: tips, ctl.name: ctl}).Optimized1mLTipPickup(
      None, tips.name, ctl.name)
    return 0

  nothing = lambda run, p: 0  # noqa: E731
  run = hsl_eval.Run(parser, stps, {"x.lay": lay}, answers={"functions": {
    "ngsstarprocesses::_data_gettiptypeanddispensemodeofliquidclass": tip_type,
    "star_tip_tools::optimized1mltippickup": planner,
    "stcc::resetfiltersequences": nothing, "stcc::addfiltersequence": nothing,
    "stcc::generatemappingfilev43ex1": nothing}})
  run.src = text.splitlines()
  run.run()
  assert run.stopped is None, run.stopped
  out = []
  for e in run.events:
    variant = ""
    if e.command == "Aspirate":
      variant = "lld" if e.guid[:8] in LLD_ASPIRATES else "fixed"
    elif e.command == "Dispense":
      variant = "lld" if e.guid[:8] in LLD_DISPENSES else "fixed"
    out.append((e.command, dict(e.channels) if e.command != "TipEject" else {}, variant))
  return out


class _Channels:
  def __init__(self):
    self.events = []

  async def pick_up_tips(self, spots, use_channels):
    self.events.append(("TipPickUp", dict(zip([c + 1 for c in use_channels], spots)), ""))

  async def aspirate(self, wells, vols, use_channels, **kw):
    self.events.append(("Aspirate", dict(zip([c + 1 for c in use_channels], wells)),
                        "lld" if kw.get("lld_mode") else "fixed"))

  async def dispense(self, wells, vols, use_channels, **kw):
    self.events.append(("Dispense", dict(zip([c + 1 for c in use_channels], wells)),
                        "lld" if kw.get("lld_mode") else "fixed"))

  async def discard_tips(self, use_channels):
    self.events.append(("TipEject", {}, ""))


class _Deck:
  def __init__(self, lay):
    self.live = {s.name: sq.Sequence(s.name, list(s.items)) for s in lay.sequences}

  def seq(self, name):
    return self.live[name]

  def resolve(self, item):
    return item


def port_steps(lay, call):
  from venus_interop.plr.libraries.ngsstar_processes import NGSStarProcesses

  n, asp, disp, vol, lc, cyc, mva, mvd, ha, hd, ex, inc, lf = call
  deck, ch = _Deck(lay), _Channels()
  deck.seq(disp).set_count(n)
  procs = NGSStarProcesses(type("Star", (), {"pipettes": ch})(), deck, TIPS, CLASSES, planner=_planner(deck.live))
  procs._lc = lambda name: None
  asyncio.run(procs.PIP_ReagentsFromTubeOrTroughOrPlateToPlate(None, asp, disp, vol, lc, cyc, mva, mvd, ha, hd,
                                                                 ex, inc, lf))
  return ch.events


def test_covers_what_it_calls():
  assert COVERS == ["PIP_ReagentsFromTubeOrTroughOrPlateToPlate"]


@pytest.mark.parametrize("call", CALLS, ids=[f"{c[4]}-{c[2]}-n{c[0]}" for c in CALLS])
def test_port_pipettes_as_the_library_does(avenio, lay, call):
  hsl, port = hsl_steps(avenio, lay, call), port_steps(lay, call)
  assert len(hsl) == len(port) and len(hsl) > 3
  for i, (a, b) in enumerate(zip(hsl, port)):
    assert a == b, f"step {i}: library {a}, port {b}"
