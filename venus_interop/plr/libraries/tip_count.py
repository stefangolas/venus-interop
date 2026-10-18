"""Hamilton's HSLTipCountingLib (`TipCount::Read2` / `Write2`): tip racks that carry over between runs.

A Venus tip counter is a named, persisted record of which positions of a tip rack are used. A
method reads its counters into its tip sequences at the start (`Read2`) and writes them back at
the end (`Write2`), so the next run starts where this one stopped. Read2: no counter stored, -1
and the sequence untouched; else the sequence reset to the layout's and set from the counter, and a
rack with no tips left gets end and current position 0. Write2: the sequence into the counter,
created if new.

The counter itself is Venus's compiled element counter, which keeps a status per position. Here
it is the sequence's current position (tips before it used), which is the same while tips are
taken in order, as the methods take them (unverified beyond that, CONVENTIONS §11). The counters
live in a JSON file (`TipCounters`), name -> current position (0 for an empty rack), or, as STAR
Tip Tools writes them (`star_tip_tools`), the list of positions still holding tips.
"""
from __future__ import annotations

import json
import pathlib
from typing import Optional

from venus_interop.methods import sequences as sq

LIBRARY = "TIPCOUNT"  # the Venus namespace ported


class TipCounters:
  """Persisted tip counters: name -> the current position of the tip sequence written, or the
  [labware, position] items still holding tips."""

  def __init__(self, path: Optional[pathlib.Path] = None):
    self.path = path
    self.counters: dict = {}
    if path is not None and path.exists():
      self.counters = json.loads(path.read_text(encoding="utf-8"))

  def save(self) -> None:
    if self.path is not None:
      self.path.write_text(json.dumps(self.counters, indent=2, sort_keys=True), encoding="utf-8")


class TipCount:
  def __init__(self, deck, counters: TipCounters):
    self.v, self.counters = deck, counters  # deck: `seq(name)` live, `sequences[name]` the layout's

  def Read2(self, sequence: str, tip_counter: str, device=None) -> int:
    if tip_counter not in self.counters.counters:
      return -1
    s = self.v.seq(sequence)
    s.assign(sq.Sequence(sequence, list(self.v.sequences[sequence])))
    cur = self.counters.counters[tip_counter]
    if cur > 0:
      s.set_current_position(cur)
    else:
      s.set_count(0)
      s.set_current_position(0)
    self._mark_used(s, cur - 1 if cur > 0 else s.total)
    return 1

  def Write2(self, sequence: str, tip_counter: str, device=None) -> int:
    self.counters.counters[tip_counter] = self.v.seq(sequence).cur
    self.counters.save()
    return 1

  def _mark_used(self, s: sq.Sequence, n: int) -> None:
    """The first `n` positions' tips gone, where the deck tracks tips."""
    resolve = getattr(self.v, "resolve", None)
    if resolve is None:
      return
    for item in s.items[:n]:
      spot = resolve(item)
      if getattr(spot, "has_tip", lambda: False)():
        spot.tracker.remove_tip()
