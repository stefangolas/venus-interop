"""Venus sequences as state over indexes: what a pipetting step's sequence actually is.

A sequence is an ordered list of (labware id, position id) items and four integers. Every
operation Venus defines on it is a small rule over those integers, collected here from Hamilton's
own documentation (CONVENTIONS.md §12 "Sequences", with the sources):

- HSL Standard Language reference, "Element functions" of type sequence (HxStandardLanguageEnu.chm);
- the step help "Sequence counting", "Channel Use" (HxGruCommandEnu.chm) and the Method Editor's
  Loop, Set Current / End Position and Adjust Sequences commands (HxMetEdCompCmdEnu.chm), whose
  worked example table `align` reproduces;
- Hamilton's HSLSeqLib.hsl, which wraps the element functions;
- the step dialog enums in Venus's string table (Bin\\HxGruCommandEnu.dll): counting `(0) Manually`,
  `(1) Automatic`; channel use `(1) All sequence positions`, `(2) Channel pattern`.

Positions are 1-based; 0 is Venus's invalid position (the sequence is disabled or completed).
Standard library only.
"""
from __future__ import annotations

import dataclasses
from typing import Optional

Item = tuple[str, str]  # (labware id, position id)

MANUAL, AUTOMATIC = 0, 1  # SequenceCounting
ALL_POSITIONS, CHANNEL_PATTERN = 1, 2  # "Optimizing channel use"


class SequenceError(ValueError):
  """What Venus reports as a step error: not enough positions, no valid current position."""


@dataclasses.dataclass
class Sequence:
  """One sequence object's state.

  `end` is Venus's "count" (the end position, "current total number of positions"); `total` is
  the number of items; `max` the most positions one step may take; `used` how many the last step
  took. A layout sequence starts at cur 1, end = max = total.
  """
  name: str
  items: list[Item]
  cur: int = 1
  end: int = -1  # -1: total, set in __post_init__
  max: int = -1
  used: int = 0

  def __post_init__(self):
    if self.end < 0:
      self.end = len(self.items)
    if self.max < 0:
      self.max = len(self.items)
    if not self.items:
      self.cur = 0

  @property
  def total(self) -> int:
    return len(self.items)

  def copy(self, name: Optional[str] = None) -> "Sequence":
    """`a = b` and `a.CopySequence(b)`: the whole state."""
    return Sequence(name or self.name, list(self.items), self.cur, self.end, self.max, self.used)

  def assign(self, other: "Sequence") -> None:
    """Overwrite this object's state with another's, keeping the object (references see it)."""
    self.items, self.cur, self.end, self.max, self.used = (
      list(other.items), other.cur, other.end, other.max, other.used)

  # -- element functions (HSL reference) ------------------------------------------------------

  def set_current_position(self, pos: int) -> int:
    self.cur = pos if 0 < pos <= self.end else 0
    return self.cur

  def increment(self, inc: int) -> int:
    """Increment(inc); also seq++ (inc = used) and seq-- (inc = -used)."""
    n = self.cur + inc
    self.cur = n if 0 < n <= self.end else 0
    return self.cur

  def get_next(self) -> int:
    if 0 < self.cur < self.end:
      self.cur += 1
    else:
      self.cur = 0
    return self.cur

  def set_count(self, n: int) -> int:
    """SetCount: the end position; shrinks, never grows past total."""
    self.end = min(max(n, 0), self.total)
    return self.end

  def set_max(self, m: int) -> int:
    self.max = min(max(m, 0), self.end)
    return self.max

  def set_used(self, n: int) -> None:
    self.used = n

  def reset(self) -> None:
    """HSLSeqLib's SeqResetSequenceIndexes: end and max to total, the current position to 1."""
    self.set_count(self.total)
    self.set_current_position(1)
    self.set_max(self.total)

  def valid(self) -> int:
    """Positions left from the current one to the end; 0 when disabled."""
    return self.end - self.cur + 1 if self.cur > 0 else 0

  def current_item(self) -> Optional[Item]:
    return self.items[self.cur - 1] if 0 < self.cur <= self.total else None

  # -- content ---------------------------------------------------------------------------------

  def add(self, labware: str, position: str) -> None:
    """Add at the end; end and max follow when they were at total ("Max and Count will be
    maintained if Max and Count was equal to Total")."""
    follow_end, follow_max = self.end == self.total, self.max == self.total
    self.items.append((labware, position))
    if follow_end:
      self.end = self.total
    if follow_max:
      self.max = self.total

  def insert_at(self, pos: int, labware: str, position: str) -> None:
    """InsertAt(pos): 0 inserts at the beginning (HSL reference), else before item pos."""
    self.items.insert(max(pos - 1, 0), (labware, position))

  def remove_at(self, pos: int) -> None:
    if 1 <= pos <= self.total:
      del self.items[pos - 1]
      self.end = min(self.end, self.total)
      self.max = min(self.max, self.end)

  def delete_labware(self, labware: str) -> None:
    self.items = [it for it in self.items if it[0] != labware]
    self.end = min(self.end, self.total)
    self.max = min(self.max, self.end)

  def lookup_position(self, labware: str, position: str, start: int, forward: bool) -> int:
    rng = range(max(start, 1), self.total + 1) if forward else range(min(start, self.total), 0, -1)
    for i in rng:
      lab, pos = self.items[i - 1]
      if lab == labware and (position == "" or pos == position):
        return i
    return 0


# -- steps -------------------------------------------------------------------------------------


@dataclasses.dataclass
class Taken:
  """What one step took from a sequence: per channel (1-based), its item; and the state change."""
  channels: dict[int, Item]
  first: int  # the sequence position of the first item taken
  used: int
  cur_after: int


def take(seq: Sequence, pattern: str, counting: int = AUTOMATIC,
         channel_use: int = ALL_POSITIONS) -> Taken:
  """A pipetting step on `seq` with a channel `pattern` ("11110000"; '1' = used).

  The step takes positions from the current one: `k = min(active, max, end - cur + 1)` of them
  under "All sequence positions", given to the active channels in order. Under "Channel pattern"
  every channel up to the last active one consumes a position, the inactive ones skipping theirs
  (how many an all-trailing-inactive pattern consumes is open, CONVENTIONS §11; here, up to the
  last active channel). `used` is set to what was consumed; automatic counting then increments the
  current position by it, manual counting leaves it.
  """
  active = [i + 1 for i, c in enumerate(pattern) if c == "1"]
  if not active:
    seq.used = 0
    return Taken({}, seq.cur, 0, seq.cur)
  if seq.cur <= 0 or seq.valid() <= 0:
    raise SequenceError(f"{seq.name}: no valid current position (cur {seq.cur}, end {seq.end})")
  room = min(seq.max, seq.valid()) if seq.max > 0 else 0
  if room <= 0:
    seq.used = 0
    return Taken({}, seq.cur, 0, seq.cur)  # max 0: "will not perform any action on such sequences"
  first = seq.cur
  channels: dict[int, Item] = {}
  if channel_use == CHANNEL_PATTERN:
    span = min(active[-1], room)
    for ch in active:
      if ch <= span:
        channels[ch] = seq.items[first - 1 + ch - 1]
    consumed = span
  else:
    k = min(len(active), room)
    for j, ch in enumerate(active[:k]):
      channels[ch] = seq.items[first - 1 + j]
    consumed = k
  seq.used = consumed
  if counting == AUTOMATIC:
    seq.increment(consumed)
  return Taken(channels, first, consumed, seq.cur)


def take_head96(seq: Sequence, counting: int = AUTOMATIC, positions: int = 96) -> Taken:
  """A 96-head step: `positions` items from the current one (96, or n x 8 / n x 12 in a reduced
  pattern), head position k (1 = A1, 2 = B1, ..., 96 = H12) taking item cur + k - 1."""
  if seq.cur <= 0:
    raise SequenceError(f"{seq.name}: no valid current position")
  room = min(seq.max if seq.max > 0 else 0, seq.valid())
  k = min(positions, room)
  if k <= 0:
    seq.used = 0
    return Taken({}, seq.cur, 0, seq.cur)
  first = seq.cur
  channels = {j + 1: seq.items[first - 1 + j] for j in range(k)}
  seq.used = k
  if counting == AUTOMATIC:
    seq.increment(k)
  return Taken(channels, first, k, seq.cur)


def align(pairs: list[tuple[Sequence, int]], max_only: bool = True) -> int:
  """AlignSequences / Adjust Sequences / a Loop's "Consumed": every sequence's max becomes
  floor(min over the sequences of valid / consumed). With max_only False the end positions are
  aligned too, the smallest sequence driving (the exact rule there is open, CONVENTIONS §11; here
  each end is cut to cur + n * consumed - 1). Returns the n set."""
  n = min(s.valid() // c for s, c in pairs) if pairs else 0
  for s, c in pairs:
    s.max = n
    if not max_only and s.cur > 0:
      s.end = min(s.end, s.cur + n * c - 1)
  return n
