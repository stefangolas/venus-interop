"""NIST LMSF's culture-processing Move96HeadAndArm (`Library/Culture processing/Move96HeadAndArm.hsi`).

103 lines and 2 functions in Venus, as raw firmware commands to the 96-head (`H0ZA za68500`,
`H0YA ya07500`) and a channels' arm move. `za68500` is the top of the 96-head's Z travel; `ya07500`
is near the front of its Y travel. In mm they are PLR's head drive resolutions times the increments
(342.5 mm stop disc, 117.19 mm at channel A1), so they rest on those resolutions. Not to be confused
with Common96HeadSubMethods, whose Move96HeadToFront moves to a sequence instead.
"""
from __future__ import annotations

LIBRARY = "MOVE96HEADANDARM"  # the Venus namespace ported

HEAD_Z_INCREMENTS = 68500  # H0ZA za: the top of the head's Z travel
HEAD_Y_INCREMENTS = 7500  # H0YA ya: the front of the deck
ARM_RIGHT_X = 1337.5  # mm, the channels' arm (MoveToPosition)


class Move96HeadAndArm:
  def __init__(self, star, deck=None, say=print):
    self.star, self.say = star, say

  async def Move96HeadToFront(self, ML_STAR=None):
    head = self.star.head96
    await head.move_stop_disc_to_z_position(head.configuration.z_drive_increments_to_mm(HEAD_Z_INCREMENTS))
    await head.move_to_y_position(head.configuration.y_drive_increments_to_mm(HEAD_Y_INCREMENTS))

  async def Move96HeadAndArm(self, ML_STAR=None):
    await self.Move96HeadToFront()
    await self.star.pipettes.move_to_x_position(ARM_RIGHT_X)
