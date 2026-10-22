"""The NGSStar kits' `Tip Present Check_5ml_1ml` library (in the kit's Library folder): which 1 mL
channels hold a tip, asked at the end of a run and in the abort handler, so the method can eject
them.

Check_Tips_Present_1ml asks each of the first `channels` channels (firmware `P<n>RW`, the tip read
from its reply) and returns 1 when any holds a tip, with the pattern of those that do ("10100000").
PLR asks the master module for all channels at once (`sense_tip_presence`, firmware `C0RT`): the
same answer, one command. In Venus's simulation mode the library asks nothing: no tips. The 5 mL
channels' copy is not ported (no NGSStar kit here uses 5 mL channels).
"""
from __future__ import annotations

LIBRARY = "TIP_PRESENT_CHECK_5ML_1ML"  # the Venus namespace ported


async def Check_Tips_Present_1ml(pipettes, channels: int, simulation: bool = False) -> tuple[int, str]:
  """(1 if any of the first `channels` holds a tip else 0, the pattern of those that do)."""
  if simulation:
    return 0, "0" * int(channels)
  held = (await pipettes.sense_tip_presence())[:int(channels)]
  pattern = "".join("1" if t else "0" for t in held)
  return int("1" in pattern), pattern
