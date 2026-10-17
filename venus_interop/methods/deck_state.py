"""What stands on a Venus deck when a method starts, read from the method itself.

A Venus layout places labware at every position a method uses, including positions that only ever
receive something: a lid park, a device's plate position, a waste spot. Those are placeholders, not
objects; a PyLabRobot deck built for the start of the run should not have them. The method shows
which they are: a labware whose first appearance is as where a move puts something (`move_to_seq`,
`lid_to_seq`, ...) is not there yet.

Read from a method trace (`protocol.trace_method`'s lines, or a saved `.condensed.md`): the order
references appear in, with both branches of each `if` in the order written. A sequence put into an
array (`arr.AddAsLast(ML_STAR.X)`) is bookkeeping, not a use: methods build their arrays up front
and reach the sequences through them later. Standard library only.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

# A sequence argument, e.g. `move_to_seq = ML_STAR.RP_on_MPE`; its name says what it is for.
_ARG = re.compile(r"(\w+)\s*=\s*ML_STAR\.(\w+)")
_REF = re.compile(r"ML_STAR\.(\w+)")
_BOOKKEEPING = re.compile(r"\.(AddAsLast|AddAsFirst|InsertAt|SetAt)\(\s*ML_STAR\.")


def is_destination(argument: str) -> bool:
  """Whether a library argument names where a move puts something (`move_to_seq`, `lid_to_seq`).

  Only a move's: a pipetting helper's `to_seq` (a dilution series' targets) names wells that are
  there, liquid or not.
  """
  return re.fullmatch(r"(move|lid|plate)_to_seq", argument.lower()) is not None


def first_roles(trace: Iterable[str],
                sequences: Mapping[str, Sequence[Tuple[str, str]]]) -> Dict[str, str]:
  """Each labware's first role in the method: "destination" or "used".

  Args:
    trace: the method's lines, in order.
    sequences: the layout's sequences, name -> [(labware, position), ...].
  """
  roles: Dict[str, str] = {}
  for line in trace:
    if _BOOKKEEPING.search(line):
      continue
    named = {m.start(2): m.group(1) for m in _ARG.finditer(line)}
    for m in _REF.finditer(line):
      items = sequences.get(m.group(1))
      if not items:
        continue
      role = "destination" if is_destination(named.get(m.start(1), "")) else "used"
      for labware, _ in items:
        roles.setdefault(labware, role)
  return roles


def absent_at_start(trace: Iterable[str],
                    sequences: Mapping[str, Sequence[Tuple[str, str]]]) -> List[str]:
  """The labware a method first names as a move's destination: placeholders, not there at start."""
  return sorted(lw for lw, role in first_roles(trace, sequences).items() if role == "destination")
