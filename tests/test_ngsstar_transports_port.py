"""Hamilton's NGSStar framework, NGSStarProcesses' CO-RE transports: the port against the HSL.

Trp_MIDI and Trp_HSP run on Roche Avenio CGP's layout in the HSL interpreter and in the port, for
the destinations whose rules differ (a heater-shaker nest with or without its plate check and press,
the magnet, the waste chutes with their labware shifts, the CPAC). Every move must take the same
labware to the same place with the same grip (height, width, opening, force, speed), front channel,
plate check, press, acceleration, tool eject and the same shifts of source and destination.

Needs VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS (see test_ngsstar_processes_port.py) and
pylabrobot.
"""
import asyncio
import os
import pathlib

import pytest

pytest.importorskip("pylabrobot.resources")

from port_harness import RecordingDeck, hsl_run  # noqa: E402
from venus_interop.files import layout  # noqa: E402

NGS = pathlib.Path(os.environ["VENUS_INTEROP_NGS"]) if os.environ.get("VENUS_INTEROP_NGS") else None
LIBS = [pathlib.Path(p) for p in os.environ.get("VENUS_INTEROP_HAMILTON_LIBS", "").split(os.pathsep) if p]
pytestmark = pytest.mark.skipif(NGS is None or not LIBS,
                                reason="VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS not set")

# What this test checks against the HSL (read by tools/trace_method.py --status)
LIBRARY = "NGSSTARPROCESSES"
COVERS = ["Trp_HSP", "Trp_MIDI", "Trp_HSPFromAndToODTCwithiSWAP", "Trp_HamiltonComfortLid"]

# (function, source, destination, park)
CALLS = [
  ("Trp_MIDI", "Stack1", "HHS3_MIDI", 1), ("Trp_MIDI", "HHS4_MIDI", "MIDI_OnMagnet", 0),
  ("Trp_MIDI", "MIDI_OnMagnet", "HHS4_MIDI", 1), ("Trp_MIDI", "MIDI_Pipette", "MIDI_Waste", 1),
  ("Trp_MIDI", "HHS5_MIDI", "MIDI_Pipette", 0),
  ("Trp_HSP", "HSP_Pipette", "HSP_onCPAC", 1), ("Trp_HSP", "HSP_onCPAC", "HSP_Waste", 0),
  ("Trp_HSP", "HSP_ODTC", "HSP_Pipette2", 1),
]


@pytest.fixture(scope="module")
def avenio():
  return NGS / "assets" / "NGSStar" / "Roche" / "Avenio CGP"


@pytest.fixture(scope="module")
def lay(avenio):
  return layout.read_layout(avenio / "Methods" / "Avenio CGP.lay")


def hsl_moves(avenio, lay):
  N = "NGSSTARPROCESSES::"
  src = (
    'namespace _Method { #include "HSLSeqLib.hsl" }\n'
    'namespace _Method { #include "NGSStarProcesses.hs_" }\n'
    'global device ML_STAR ("x.lay", "ML_STAR", hslTrue);\n'
    'variable bc;\n'
    'namespace _Method { #include "HSLMECCLib.hs_" }\n'
    "namespace _Method { method main() void {\n"
    f"{N}t_intTransportTool = 2;\n{N}t_intFrontChannelCORETransport = 7;\n"
    f"{N}t_seqCOREGripper = ML_STAR.COREGripTool_OnWaste_1000ul_0001;\n"
    + "".join(f"{N}{fn}(ML_STAR, ML_STAR.{a}, ML_STAR.{b}, 0, {park}, bc, 4);\n" for fn, a, b, park in CALLS)
    + "} }\n")
  nothing = lambda run, p: 0  # noqa: E731
  run = hsl_run(src, avenio / "Library" / "port_test.hsl", [avenio / "Library", avenio / "Methods", *LIBS],
                (avenio / "Library").glob("*.stp"), {"x.lay": lay},
                answers={"functions": {"ngsstarprocesses::_data_scheduleconsumables": nothing}})
  moves, shift, get = [], {}, None
  for e in run.events:
    s = e.settings
    if e.command == "LabwareShift":
      x, y, z = shift.get(s["labware"], (0, 0, 0))
      shift[s["labware"]] = (x + s["x"], y + s["y"], z + s["z"])
    elif e.command == "ZSwapGetPlate":
      get = e
      pick_shift = shift.get(e.channels[1][0], (0, 0, 0))
    elif e.command == "ZSwapPlacePlate":
      g = get.settings
      moves.append(dict(
        thing=get.channels[1][0], to=e.channels[1][0], height=g["GripperAccessHeight"], width=g["grip width"],
        opening=g["grip opening"], force=g["grip force"], z_speed=g["z speed"], front=g["ToolUpperChannel"],
        check=s["ZSwapPlateCheck"], eject=s["ToolEject"], press=s["plate press"], x_acceleration=s["x acceleration"],
        place_z_speed=s["z speed"], pick_shift=pick_shift, drop_shift=shift.get(e.channels[1][0], (0, 0, 0))))
  return moves


class _Gripper:
  def __init__(self):
    self.moves = []

  async def to_placeholder(self, thing, placeholder, front_channel, eject, grip, release):
    o, d = grip["offset"], release["offset"]
    self.moves.append(dict(
      thing=thing, to=placeholder, height=grip["pickup_distance_from_top"], width=grip["resource_size_y"],
      opening=round(grip["resource_size_y"] + 2 * grip["y_clearance"], 4), force=grip["grip_strength"],
      z_speed=grip["z_speed"], front=front_channel + 1, eject=int(eject), press=release["press_on_distance"],
      x_acceleration=release["x_acceleration_level"], place_z_speed=release["z_speed"],
      pick_shift=(o.x, o.y, o.z), drop_shift=(d.x, d.y, d.z)))


def port_moves(lay):
  from venus_interop.plr import steps
  from venus_interop.plr.libraries.ngsstar_processes import NGSStarProcesses

  gripper, checks = _Gripper(), []
  steps.OBSERVERS[:] = [lambda command, ch, grip: checks.append(grip.check) if command == "CoreGrip" else None]
  procs = NGSStarProcesses(type("Star", (), {"pipettes": None})(), RecordingDeck(lay), {}, {}, gripper=gripper,
                           say=lambda _: None)

  async def go():
    for fn, a, b, park in CALLS:
      await getattr(procs, fn)(None, a, b, 0, park)

  try:
    asyncio.run(go())
  finally:
    steps.OBSERVERS.clear()
  for move, check in zip(gripper.moves, checks):
    move["check"] = check
  return gripper.moves


def test_covers_what_it_calls():
  others = {"Trp_HSPFromAndToODTCwithiSWAP", "Trp_HamiltonComfortLid"}
  assert sorted(COVERS) == sorted({fn for fn, *_ in CALLS} | others)


def test_port_moves_plates_as_the_library_does(avenio, lay):
  hsl, port = hsl_moves(avenio, lay), port_moves(lay)
  assert len(hsl) == len(port) == len(CALLS)
  for (fn, a, b, _), x, y in zip(CALLS, hsl, port):
    assert x == y, f"{fn} {a} -> {b}: library {x}, port {y}"


# Trp_HSPFromAndToODTCwithiSWAP, as Avenio calls it: (source, destination, park)
ISWAP_CALLS = [("HSP_Pipette2", "HSP_ODTC", 0), ("HSP_ODTC", "HSP_Pipette2", 1), ("HSP_ODTC", "HSP_Pipette2", 0)]


def hsl_iswap_moves(avenio, lay, clinical):
  N = "NGSSTARPROCESSES::"
  src = (
    'namespace _Method { #include "HSLSeqLib.hsl" }\n'
    'namespace _Method { #include "NGSStarProcesses.hs_" }\n'
    'global device ML_STAR ("x.lay", "ML_STAR", hslTrue);\n'
    'variable bc;\n'
    'namespace _Method { #include "HSLMECCLib.hs_" }\n'
    "namespace _Method { method main() void {\n"
    f"{N}t_blnClinicalNGSStarlet = {int(clinical)};\n"
    + "".join(f"{N}Trp_HSPFromAndToODTCwithiSWAP(ML_STAR, ML_STAR.{a}, ML_STAR.{b}, 0, {park}, bc);\n"
              for a, b, park in ISWAP_CALLS)
    + "} }\n")
  run = hsl_run(src, avenio / "Library" / "port_test.hsl", [avenio / "Library", avenio / "Methods", *LIBS],
                (avenio / "Library").glob("*.stp"), {"x.lay": lay})
  moves = []
  for e in run.events:
    s = e.settings
    if e.command == "GetPlate":
      moves.append(dict(thing=e.channels[1][0], height=s["GripperAccessHeight"], width=s["grip width"],
                        opening=s["grip opening"], force=s["grip force"], inverse=bool(s["InversGripping"]),
                        large_side=bool(s["GrippLargeSite"]), orientation=s["LabwareOrientation"]))
    elif e.command == "PutPlate":
      moves[-1]["to"] = e.channels[1][0]
    elif e.command == "ParkISwap":
      moves[-1]["end"] = "park"
    elif e.command == "FirmwareCommand":
      moves[-1]["end"] = s["firmware command string"]
  return moves


class _IswapGripper:
  def __init__(self, log):
    self.log = log

  async def to_placeholder(self, thing, placeholder, iswap=None, direction=None, elbows=None, grip=None,
                           release=None, front_channel=None, eject=None):
    if iswap is None:  # the CO-RE gripper
      self.log.append(dict(thing=thing, to=placeholder, core=True, height=grip["pickup_distance_from_top"],
                           width=grip["resource_size_y"], force=grip["grip_strength"], end=int(eject)))
      return
    move = dict(thing=thing, to=placeholder, height=grip["pickup_distance_from_top"], width=grip["width"],
                opening=round(grip["width"] + grip["open_margin"], 4), force=grip["grip_strength"],
                direction=direction)
    if release is not None:
      move["release"] = round(grip["width"] + release["open_margin"], 4)
    self.log.append(move)


class _Iswap:
  def __init__(self, log):
    self.log = log

  async def park(self, traverse_height=None):
    self.log[-1]["end"] = "park"

  async def elbow_move_to_safe_z_height(self):
    self.log[-1]["end"] = "R0ZI"  # homing the iSWAP's Z: the firmware command Venus sends


def port_iswap_moves(lay, clinical):
  from venus_interop.plr import steps
  from venus_interop.plr.libraries.ngsstar_processes import NGSStarProcesses

  log, grips = [], []
  steps.OBSERVERS[:] = [lambda command, ch, grip: grips.append(grip) if command == "IswapGrip" else None]
  star = type("Star", (), {"pipettes": None, "iswap": _Iswap(log)})()
  procs = NGSStarProcesses(star, RecordingDeck(lay), {}, {}, gripper=_IswapGripper(log), say=lambda _: None,
                           iswap=object(), clinical_starlet=clinical)

  async def go():
    for a, b, park in ISWAP_CALLS:
      await procs.Trp_HSPFromAndToODTCwithiSWAP(None, a, b, 0, park)

  try:
    asyncio.run(go())
  finally:
    steps.OBSERVERS.clear()
  for move, grip in zip(log, grips):
    assert move.pop("direction") == grip.direction
    move.update(inverse=grip.inverse, large_side=grip.large_side, orientation=grip.orientation)
  return log


@pytest.mark.parametrize("clinical", [False, True], ids=["NGS STAR", "Clinical NGS STARlet"])
def test_port_moves_plates_into_and_out_of_the_odtc_as_the_library_does(avenio, lay, clinical):
  hsl, port = hsl_iswap_moves(avenio, lay, clinical), port_iswap_moves(lay, clinical)
  assert len(hsl) == len(port) == len(ISWAP_CALLS)
  assert any(m["inverse"] for m in hsl) == clinical
  for call, x, y in zip(ISWAP_CALLS, hsl, port):
    assert x == y, f"{call}: library {x}, port {y}"


# Trp_HamiltonComfortLid: Avenio's calls (source, destination, park, reachable with the CO-RE
# gripper: FALSE, or 4, which is not TRUE), and the CO-RE branch either way
LID_CALLS = [("Ham_ComfortLid_ODTC", "Ham_ComfortLid_Stack_ParkPos", 0, 0),
             ("Ham_ComfortLid_ODTC", "Ham_ComfortLid_Waste", 0, 0),
             ("Ham_ComfortLid_Stack_ParkPos", "Ham_ComfortLid_ODTC", 1, 0),
             ("Ham_ComfortLid_Stack_ParkPos", "Ham_ComfortLid_ODTC", 1, 4),
             ("Ham_ComfortLid_Stack_ParkPos", "Ham_ComfortLid_ODTC", 1, 1),
             ("Ham_ComfortLid_ODTC", "Ham_ComfortLid_Stack_ParkPos", 0, 1)]


def hsl_lid_moves(avenio, lay):
  N = "NGSSTARPROCESSES::"
  src = (
    'namespace _Method { #include "HSLSeqLib.hsl" }\n'
    'namespace _Method { #include "NGSStarProcesses.hs_" }\n'
    'global device ML_STAR ("x.lay", "ML_STAR", hslTrue);\n'
    'namespace _Method { #include "HSLMECCLib.hs_" }\n'
    "namespace _Method { method main() void {\n"
    f"{N}t_intFrontChannelCORETransport = 7;\n{N}t_seqCOREGripper = ML_STAR.COREGripTool_OnWaste_1000ul_0001;\n"
    + "".join(f"{N}Trp_HamiltonComfortLid(ML_STAR, ML_STAR.{a}, ML_STAR.{b}, {park}, {core});\n"
              for a, b, park, core in LID_CALLS)
    + "} }\n")
  nothing = lambda run, p: 0  # noqa: E731
  run = hsl_run(src, avenio / "Library" / "port_test.hsl", [avenio / "Library", avenio / "Methods", *LIBS],
                (avenio / "Library").glob("*.stp"), {"x.lay": lay},
                answers={"functions": {"ngsstarprocesses::_data_scheduleconsumables": nothing}})
  moves = []
  for e in run.events:
    s = e.settings
    if e.command == "GetPlate":
      moves.append(dict(thing=e.channels[1][0], height=s["GripperAccessHeight"], width=s["grip width"],
                        opening=s["grip opening"], force=s["grip force"], inverse=bool(s["InversGripping"]),
                        large_side=bool(s["GrippLargeSite"]), orientation=s["LabwareOrientation"]))
    elif e.command == "MovePlate":
      moves[-1]["to"] = e.channels[1][0]
    elif e.command == "OpenGripper":
      moves[-1]["release"] = s["grip opening"]
    elif e.command == "ParkISwap":
      moves[-1]["end"] = "park"
    elif e.command == "FirmwareCommand":
      moves[-1]["end"] = s["firmware command string"]
    elif e.command == "ZSwapGetPlate":
      moves.append(dict(thing=e.channels[1][0], core=True, height=s["GripperAccessHeight"], width=s["grip width"],
                        force=s["grip force"]))
    elif e.command == "ZSwapPlacePlate":
      moves[-1].update(to=e.channels[1][0], end=s["ToolEject"])
  return moves


def port_lid_moves(lay):
  from venus_interop.plr import steps
  from venus_interop.plr.libraries.ngsstar_processes import NGSStarProcesses

  log, grips = [], []
  steps.OBSERVERS[:] = [lambda command, ch, grip: grips.append(grip) if command == "IswapGrip" else None]
  star = type("Star", (), {"pipettes": None, "iswap": _Iswap(log)})()
  procs = NGSStarProcesses(star, RecordingDeck(lay), {}, {}, gripper=_IswapGripper(log), say=lambda _: None,
                           iswap=object())

  async def go():
    for a, b, park, core in LID_CALLS:
      await procs.Trp_HamiltonComfortLid(None, a, b, park, core)

  try:
    asyncio.run(go())
  finally:
    steps.OBSERVERS.clear()
  for move, grip in zip([m for m in log if not m.get("core")], grips):
    assert move.pop("direction") == grip.direction
    move.update(inverse=grip.inverse, large_side=grip.large_side, orientation=grip.orientation)
  return log


def test_port_moves_comfortlids_as_the_library_does(avenio, lay):
  hsl, port = hsl_lid_moves(avenio, lay), port_lid_moves(lay)
  assert len(hsl) == len(port) == len(LID_CALLS)
  assert [bool(m.get("core")) for m in hsl] == [False] * 4 + [True] * 2
  for call, x, y in zip(LID_CALLS, hsl, port):
    assert x == y, f"{call}: library {x}, port {y}"
