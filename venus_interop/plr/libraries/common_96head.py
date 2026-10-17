"""NIST LMSF's Common96HeadSubMethods (`Library/Common/Common96HeadSubMethods.hsi`) on a PLR STAR.

187 lines and 5 functions in Venus, which clear the 96-head and the channels' arm out of the way and
eject the 96-head's tips. With the library's disabled steps left out (its firmware moves of the head
to the front and up sit in `if(0)` blocks), they are three moves:

  head over  the 96-head over `move_seq`'s current position at traverse height, then at max height
             (Head96Move: mode 2, Z end mode 0). Move96HeadUp and Move96HeadToFront are only this.
  arm right  the channels' arm to X 1337.5 mm (MoveToPosition: absolute, X).
  eject      the 96-head's tips to the default waste (Head96TipEject, UsePickUpPosition 2; the help
             lists Off, pick-up position, default waste, so 2 is read as default waste, unverified).

Eject96HeadTipsAndShake then shakes the waste chute for `shake_time` s (WasteChute library; skipped
in simulation). PLR has no waste-chute shaker, so the shake is said, not done.
"""
from __future__ import annotations

from venus_interop.plr.venus_deck import VenusDeck

LIBRARY = "COMMON96HEADSUBMETHODS"  # the Venus namespace ported

ARM_RIGHT_X = 1337.5  # mm, the channels' arm (MoveToPosition)


class Common96HeadSubMethods:
  def __init__(self, star, deck: VenusDeck, say=print):
    self.star, self.v, self.say = star, deck, say

  async def _head_over(self, move_seq: str):
    """Head channel A1 over the sequence's current position, then the head at max height."""
    spot = self.v.resolve(self.v.seq(move_seq).current_item())
    c = spot.get_location_wrt(self.v.deck, "c", "c", "t")
    await self.star.head96.move_to_xy_position(c.x, c.y)
    await self.star.head96.move_to_safe_z()

  async def Move96HeadUp(self, ML_STAR=None, move_seq: str = ""):
    await self._head_over(move_seq)

  async def Move96HeadToFront(self, ML_STAR=None, move_seq: str = ""):
    await self._head_over(move_seq)

  async def Clear96HeadAndArm(self, ML_STAR=None, move_seq: str = ""):
    await self._head_over(move_seq)
    await self.star.pipettes.move_to_x_position(ARM_RIGHT_X)

  async def Eject96HeadTips(self, ML_STAR=None, move_seq: str = ""):
    await self.Eject96HeadTipsAndShake(ML_STAR, 5, move_seq)

  async def Eject96HeadTipsAndShake(self, ML_STAR=None, shake_time: float = 5, move_seq: str = ""):
    await self._head_over(move_seq)
    await self.star.head96.discard_tips()
    self.say(f"waste chute shake, {shake_time} s (not modelled)")
