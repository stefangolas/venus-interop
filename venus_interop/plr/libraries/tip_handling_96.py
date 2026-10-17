"""NIST LMSF's "Tip Handling with 96-Head" (`Methods/Common/Tip Handling/With 96-Head/`): the
functions the methods call.

GetTipCounters gives the names of the tip counters a method reads its tip sequences from and writes
them back to (`tip_count.TipCount`): for the 1000, 300 and 50 uL channel racks, automatic or manual
set, and the offset pick-up rack. GetTipStatusFile is where the LMSF scheduler keeps its tip status
file. TipHandlingParameters only sets those names; AddTipsToDoubleSupp is not called by any method.
"""
from __future__ import annotations

LIBRARY = "TIP_HANDLING_WITH_96_HEAD"  # the Venus namespace ported

AUTO = ["Tips_for_ch_1000_auto", "Tips_for_ch_300_auto", "Tips_for_ch_50_auto"]
MANUAL = ["Tips_for_channels_1000", "Tips_for_channels_300", "Tips_for_channels_50"]
OFFSET = "Tips_for_offset_pickup"
TIP_STATUS_FILE = "C:\\Shared Files\\LMSF Scheduler\\Hamilton\\tip_status.csv"


class TipHandling96:
  def GetTipCounters(self, is_auto) -> list[str]:
    return (AUTO if int(is_auto) == 1 else MANUAL) + [OFFSET]

  def GetTipStatusFile(self) -> str:
    return TIP_STATUS_FILE
