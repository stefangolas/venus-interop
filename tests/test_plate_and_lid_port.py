"""NIST's PlateAndLidMovement: the Python port against the HSL library itself.

Every entry point runs on the Marionette layout's sequences in both: the library in the HSL
interpreter (its CO-RE gripper steps resolved through the library's .stp records, the tap's
labware shifts recorded), the port with its gripper calls recorded. Every move must take the same
labware to the same place with the same grip, front channel, plate press, tap and tool eject.

Needs VENUS_INTEROP_NIST (the NIST lmsf_hamilton repository copy), VENUS_INTEROP_CORPUS (for the
layout, 3ed5809e547e.lay) and pylabrobot.
"""
import asyncio
import os
import pathlib

import pytest

pytest.importorskip("pylabrobot")

from venus_interop.files import layout  # noqa: E402
from venus_interop.methods import hsl_eval, protocol, sequences as sq  # noqa: E402

NIST = pathlib.Path(os.environ["VENUS_INTEROP_NIST"]) if os.environ.get("VENUS_INTEROP_NIST") else None
CORPUS = pathlib.Path(os.environ["VENUS_INTEROP_CORPUS"]) if os.environ.get("VENUS_INTEROP_CORPUS") else None
pytestmark = pytest.mark.skipif(NIST is None or CORPUS is None,
                                reason="VENUS_INTEROP_NIST and VENUS_INTEROP_CORPUS not set")

# What this test checks against the HSL (read by tools/trace_method.py --status)
LIBRARY = "PLATEANDLIDMOVEMENT"
COVERS = ["MoveAbegeneFromThermoShakeNoTap", "MoveAbgenePlateFromThermoShake", "MoveAbgenePlateWithLid",
          "MoveAgarPlateFromThermoShake", "MoveAgarPlateWithLid", "MoveAgilent86mLSingleResWithLid",
          "MoveAgilentFPwithLid", "MoveBindPlateNoLid", "MoveBindPlateWithLid", "MoveCytometryPlateWithLid",
          "MoveEppendorf350uLElutionPlateWithLid", "MoveEppendorf500uLElutePlateWithLid",
          "MoveEppendorfDWPNoLidNoTap", "MoveEppendorfDWPWithLid", "MoveGreinerPlateWithLid",
          "MoveGrowthPlateFromThermoShake", "MoveGrowthPlateWithLid", "MoveGrowthPlateWithLidNoTap",
          "MoveLid", "MoveLidNoTap", "MoveN3BufferWithLid", "MoveNuncOmniTrayWithLid",
          "MoveSupportPlateNoLid", "MoveSupportPlateNoLidNoTap", "SetFrontChannel"]
GRIP = "COREGripTool_OnWaste_1000ul_0001"
PLATE = ("Move_Growth_Plate_Handoff", "Growth_Plate_Handoff_lid", "Move_Growth_Plate", "Growth_Plate_lid")
BARE = ("Move_Growth_Plate", "Growth_Plate_waste")
LIDS = ("Growth_Plate_lid", "Lid_parking_Growth_Plate")



def core_force(grip: dict) -> int:
  """The Venus grip force (0-9) a port meant: PLR is given it in firmware steps (yw = force x 5)."""
  from venus_interop.plr import steps
  return grip["grip_strength"] // steps.GRIP_FORCE_STEP

def _calls():
  """(function, its arguments as Python values, z_shift or None); the eject flag alternates."""
  from venus_interop.plr.libraries import plate_and_lid as pl

  out = [("SetFrontChannel", (7,), None)]
  names = sorted(pl.ENTRY) + sorted(pl.WITH_TAP_ARG) + ["MoveLid", "MoveLidNoTap"]
  for i, name in enumerate(names):
    eject = i % 2
    if i == len(names) // 2:
      out.append(("SetFrontChannel", (5,), None))
    if name in ("MoveLid", "MoveLidNoTap"):
      args = (*LIDS, GRIP, 0, eject)
    else:
      with_lid = (pl.ENTRY.get(name) or pl.WITH_TAP_ARG[name])[0]
      args = (*(PLATE if with_lid else BARE), GRIP, 0, eject)
    out.append((name, args, 2.5 if name in pl.WITH_TAP_ARG else None))
  return out


@pytest.fixture(scope="module")
def lay():
  return layout.read_layout(CORPUS / "raw" / "3ed5809e547e.lay")


def _hsl_arg(a):
  return f"ML_STAR.{a}" if isinstance(a, str) else str(a)


def hsl_moves(lay):
  lines = []
  for fn, args, z_shift in _calls():
    a = [_hsl_arg(x) for x in args]
    if fn != "SetFrontChannel":
      a.append("ML_STAR")
    if z_shift is not None:
      a.append(str(z_shift))
    lines.append(f"PLATEANDLIDMOVEMENT::{fn}({', '.join(a)});")
  src = (
    'namespace _Method { #include "HSLSeqLib.hsl" }\n'
    'namespace _Method { #include "Common\\\\PlateAndLidMovement.hs_" }\n'
    'global device ML_STAR ("x.lay", "ML_STAR", hslTrue);\n'
    'namespace _Method { #include "HSLMECCLib.hs_" }\n'
    "namespace _Method { method main() void {\n" + "\n".join(lines) + "\n} }\n")
  here = NIST / "Methods" / "Common" / "port_test.hsl"
  stps = protocol.load_stps(sorted(here.parent.glob("*.stp")))
  pre = hsl_eval.Preprocessor([NIST / "Library", NIST / "Methods"], lambda p: p.read_text(encoding="latin-1"))
  text = pre.expand(here, text=src)
  parser = hsl_eval.Parser(hsl_eval.lex(text))
  parser.unit()
  run = hsl_eval.Run(parser, stps, {"x.lay": lay}, answers={})
  run.src = text.splitlines()
  run.run()
  assert run.stopped is None, run.stopped

  moves, get, tap = [], None, 0.0
  for e in run.events:
    s = e.settings
    if e.command == "ZSwapGetPlate":
      get, tap = e, 0.0
    elif e.command == "LabwareShift":
      if s["z"] > 0:
        tap = float(s["z"])
    elif e.command == "ZSwapPlacePlate":
      g = get.settings
      moves.append(dict(
        thing=get.channels[1][0], to=e.channels[1][0], height=g["GripperAccessHeight"],
        width=g["grip width"], force=g["grip force"], front=g["ToolUpperChannel"],
        z_speed=g["z speed"], press=s["plate press"], x_acceleration=s["x acceleration"],
        check_on_put=s["ZSwapPlateCheck"], tap=tap, eject=s["ToolEject"]))
  return moves


class _Gripper:
  def __init__(self):
    self.moves = []

  async def to_placeholder(self, thing, placeholder, front_channel, eject, grip, release):
    self.moves.append(dict(
      thing=thing, to=placeholder, height=grip["pickup_distance_from_top"],
      width=grip["resource_size_y"], force=core_force(grip), front=front_channel + 1,
      z_speed=grip["z_speed"], press=release["press_on_distance"],
      x_acceleration=release["x_acceleration_level"], tap=release["offset"].z, eject=int(eject)))


class _Deck:
  def __init__(self, lay):
    self.items = {s.name: list(s.items) for s in lay.sequences}

  def seq(self, name):
    return sq.Sequence(name, list(self.items[name]))

  def resource(self, name):
    return name


def port_moves(lay):
  from venus_interop.plr.libraries import plate_and_lid as pl

  gripper = _Gripper()
  plm = pl.PlateAndLidMovement(None, _Deck(lay), gripper=gripper)
  checks = []
  move_plate = plm.move_plate

  async def spy(move_from, move_to, grip, *rest):
    checks.append(grip.check_on_put)
    return await move_plate(move_from, move_to, grip, *rest)

  plm.move_plate = spy

  async def go():
    for fn, args, z_shift in _calls():
      result = getattr(plm, fn)(*args, *(() if z_shift is None else (z_shift,)))
      if asyncio.iscoroutine(result):
        await result

  asyncio.run(go())
  for move, check in zip(gripper.moves, checks):
    move["check_on_put"] = check
  return gripper.moves


def test_covers_what_it_calls():
  assert sorted(COVERS) == sorted({fn for fn, _, _ in _calls()})


def test_port_moves_what_the_library_moves_as_it_does(lay):
  hsl, port = hsl_moves(lay), port_moves(lay)
  names = [fn for fn, _, _ in _calls() if fn != "SetFrontChannel"]
  assert len(hsl) == len(port) == len(names) == 24
  for name, a, b in zip(names, hsl, port):
    assert a == b, f"{name}: library {a}, port {b}"
