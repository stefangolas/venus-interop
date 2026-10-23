"""NIST LMSF's PlateAndLidMovement (`Methods/Common/PlateAndLidMovement.hsi`) on a PLR STAR.

1,732 lines and 62 functions in Venus; in effect a table of grip settings per labware and three
CO-RE gripper moves:

  plate      get, put: the labware with its lid on (WithLid) or bare (NoLid). "Tap": the
             destination is raised `z_shift` mm (LMSF_UTILITIES::SeqZShift) while the plate is put,
             so it is released that much high and drops onto its site, then lowered back.
  lid        get, put, with the lid's own grip and a 0.5 mm plate press (none for NoTap).

Every Venus entry point keeps its name and arguments (sequences by name, each naming one
labware). The front channel the grip tools go on is drawn from the clock's seconds in Venus
(GetNewFrontChannel: 2 + 7 * seconds / 59.01, rounded down) to spread wear; here it is
`front_channel`, 7 until set, as Venus's own default. Grip heights are below the labware's top
(Venus's "Grip height"), PLR's `pickup_distance_from_top`; grip width is across the jaws, the
labware's Y.
"""
from __future__ import annotations

import dataclasses
from typing import Optional

from pylabrobot.resources import Coordinate

from venus_interop.plr import steps
from venus_interop.plr.venus_deck import Gripper, VenusDeck

LIBRARY = "PLATEANDLIDMOVEMENT"  # the Venus namespace ported


@dataclasses.dataclass(frozen=True)
class Grip:
  height: float  # mm below the top
  width: float  # mm across the jaws
  force: int
  tap: float = 0.0  # z_shift, mm; 0 for the NoTap moves
  check_on_put: int = 1
  press: float = 0.0  # plate press on put, mm
  x_acceleration: int = 1
  z_speed: float = 75.0  # mm/s
  opening: float = 88.0  # mm: grip_opening in every move of the library
  speed: float = 277.0  # mm/s: grip_speed in every move of the library


_LID = Grip(4, 84.5, 5, press=0.5, x_acceleration=2)
# Each entry point: (moves a lid with the plate, its grip). From the library source.
ENTRY = {
  "MoveGrowthPlateWithLid": (True, Grip(11, 80, 5, tap=1)),
  "MoveGrowthPlateFromThermoShake": (True, Grip(11, 80, 5, tap=1)),
  "MoveGrowthPlateWithLidNoTap": (True, Grip(11, 80, 5, check_on_put=0, x_acceleration=2)),
  "MoveCytometryPlateWithLid": (True, Grip(11, 83.3, 5, tap=1)),
  "MoveEppendorfDWPWithLid": (True, Grip(10, 78.95, 5, tap=1)),
  "MoveAgarPlateWithLid": (True, Grip(13, 80, 5, tap=1)),
  "MoveAgarPlateFromThermoShake": (True, Grip(11, 80, 9, tap=1)),
  "MoveN3BufferWithLid": (True, Grip(11, 79, 9, tap=1)),
  "MoveNuncOmniTrayWithLid": (True, Grip(11, 79.5, 5, tap=1)),
  "MoveAbgenePlateWithLid": (True, Grip(11, 79.35, 4, tap=1)),
  "MoveAbgenePlateFromThermoShake": (True, Grip(11, 79.35, 4, tap=1)),  # its check_on_put 0 is unused
  "MoveAbegeneFromThermoShakeNoTap": (True, Grip(11, 79.35, 4, check_on_put=0, x_acceleration=2)),
  "MoveAgilent86mLSingleResWithLid": (True, Grip(11, 80, 5, tap=1)),
  "MoveEppendorf500uLElutePlateWithLid": (True, Grip(7, 80.8, 4, tap=1)),
  "MoveGreinerPlateWithLid": (True, Grip(11, 79.35, 4, tap=1)),
  "MoveEppendorf350uLElutionPlateWithLid": (True, Grip(8, 80, 4, tap=1)),
  "MoveBindPlateWithLid": (True, Grip(11, 78, 5, tap=1)),
  "MoveSupportPlateNoLid": (False, Grip(13, 79.5, 5, x_acceleration=2)),
  "MoveSupportPlateNoLidNoTap": (False, Grip(13, 79, 7, check_on_put=0, x_acceleration=2)),
  "MoveEppendorfDWPNoLidNoTap": (False, Grip(15, 78.95, 5, check_on_put=0, x_acceleration=2)),
}
# Entry points that take z_shift as their last argument (the tap set by the caller)
WITH_TAP_ARG = {
  "MoveAgilentFPwithLid": (True, Grip(11, 80, 5)),
  "MoveBindPlateNoLid": (False, Grip(7, 78, 5, check_on_put=0)),
}


class PlateAndLidMovement:
  def __init__(self, star, deck: VenusDeck, gripper: Optional[Gripper] = None, say=print):
    self.v = deck
    self.g = gripper or Gripper(star, deck, say)
    self.front_channel = 7  # Venus's: 1 = back ... 8 = front

  def _labware(self, seq: str) -> str:
    """The one labware a move's sequence names."""
    return self.v.seq(seq).items[0][0]

  def _front(self, new_front_gripper) -> int:
    # PLR counts channels from 0 at the back
    return self.front_channel - 1

  async def move_plate(self, move_from_seq: str, move_to_seq: str, grip: Grip, new_front_gripper=0,
                       eject_gripper=0):
    """Get and place, the grip tools kept on unless `eject_gripper` is 1. The tap is the release
    `tap` mm above the site: the plate drops onto it. Venus's plate check on put
    (`grip.check_on_put`) has no PLR counterpart."""
    plate = self.v.resource(self._labware(move_from_seq))  # the object now standing for it
    destination = self._labware(move_to_seq)  # a placeholder: where it goes
    await self.g.to_placeholder(
      plate, destination, front_channel=self._front(new_front_gripper), eject=int(eject_gripper) == 1,
      grip=dict(pickup_distance_from_top=grip.height, z_speed=grip.z_speed,
                **steps.venus_grip(grip.width, grip.opening, grip.force, grip.speed)),
      release=dict(offset=Coordinate(0, 0, grip.tap), press_on_distance=grip.press,
                   x_acceleration_level=grip.x_acceleration, z_speed=grip.z_speed,
                   **steps.venus_release(grip.width, grip.opening)))
    return plate

  async def MoveLid(self, lid_from_seq, lid_to_seq, gripper_sequence=None, new_front_gripper=0,
                    eject_gripper=0, grip: Grip = _LID):
    await self.move_plate(lid_from_seq, lid_to_seq, grip, new_front_gripper, eject_gripper)

  async def MoveLidNoTap(self, lid_from_seq, lid_to_seq, gripper_sequence=None, new_front_gripper=0,
                         eject_gripper=0):
    await self.MoveLid(lid_from_seq, lid_to_seq, gripper_sequence, new_front_gripper, eject_gripper,
                       grip=dataclasses.replace(_LID, press=0.0, check_on_put=0))

  def SetFrontChannel(self, i_front):
    self.front_channel = int(i_front)

  def __getattr__(self, name):
    """The plate entry points, by their Venus names and arguments."""
    if name in ENTRY:
      with_lid, grip = ENTRY[name]

      async def move(*args):
        return await self._entry(with_lid, grip, args)
      return move
    if name in WITH_TAP_ARG:
      with_lid, grip = WITH_TAP_ARG[name]

      async def move_tap(*args):
        return await self._entry(with_lid, dataclasses.replace(grip, tap=float(args[-1])), args[:-1])
      return move_tap
    raise AttributeError(name)

  async def _entry(self, with_lid: bool, grip: Grip, args):
    """A plate entry point's arguments: (move_from, lid_from, move_to, lid_to, gripper, new_front,
    eject) with the lid, (move_from, move_to, gripper, new_front, eject) without."""
    if with_lid:
      args = (args[0], args[2], *args[4:])
    move_from, move_to, *rest = args
    new_front, eject = (list(rest[1:3]) + [0, 0])[:2]
    return await self.move_plate(move_from, move_to, grip, new_front, eject)
