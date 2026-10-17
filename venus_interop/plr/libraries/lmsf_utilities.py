"""NIST LMSF's LMSF_Utilities (`Methods/Common/LMSF_Utilities.hsi`): the functions the methods call.

The methods use two of its many functions directly, both on sequence position properties
(`Sequence.set_property`, Venus's SetSequenceProperty). They carry the plate map the GSF-IMS methods
build: each Growth Plate well's inducer concentrations, strain and plasmid, which the method writes
to its output file at the end. Its SeqZShift is part of the plate moves (`plate_and_lid`, the tap).
"""
from __future__ import annotations

LIBRARY = "LMSF_UTILITIES"  # the Venus namespace ported


class LmsfUtilities:
  def __init__(self, deck):
    self.v = deck  # anything with `seq(name)`: the layout's sequences as live state

  def SeqSetPropertyByWell(self, labware_id: str, position_id: str, target_sequence: str,
                           property_str: str, property_value):
    """The property at the first position of `target_sequence` holding that well; that position,
    0 (nothing set) when it holds none."""
    t = self.v.seq(target_sequence)
    pos = t.lookup_position(labware_id, position_id, 1, True)
    if pos > 0:
      t.set_property(pos, property_str, property_value)
    return pos

  def SeqCopyPropsFromShortSeq(self, input_sequence: str, property_arr, target_sequence: str):
    """Each listed property of each position of `input_sequence` (up to its end) onto the first
    position of `target_sequence` holding the same well. Both current positions are kept; the
    input's max is left at its total, as the library's loop leaves it."""
    s, t = self.v.seq(input_sequence), self.v.seq(target_sequence)
    for i in range(1, s.end + 1):
      out = t.lookup_position(*s.items[i - 1], 1, True)
      if out > 0:
        for name in property_arr:
          t.set_property(out, name, s.get_property(i, name))
    s.set_max(s.total)

