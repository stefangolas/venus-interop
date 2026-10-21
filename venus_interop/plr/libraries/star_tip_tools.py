"""Hamilton's STAR Tip Tools (`STAR Tools\\STAR Tip Tools.hsi`, with its HelperLibrary): the tip
pick-up planner the NGSStar framework calls before every channel tip pick-up.

Optimized1mLTipPickup chooses which tips N channels take (N: the positions left in the control
sequence, at most the 1 mL channel count) and reorders the tip sequence so they come first:

  fast path   the next N tips as the sequence has them, if they share one X, each at least a raster
              (9 mm) in front of the one before, each within its channel's Y reach: no reorder.
  reorder     the tips left (from the current position on), sorted by X, then rasters, then Y down
              (`SortSequenceRaster`), grouped (a new group when X changes or a group outgrows the
              channels); the first group, scanning by labware, Y down, X, with N tips: its first N
              (X, then Y down). No such group: by X, then Y down, each tip that the next channel can
              reach. The sequence becomes the chosen tips, then the rest by labware, X, Y down,
              from position 1.

Optimized1mLTipPickup2 does the same for the channels of a given pattern (as many tips as it has
1s), with two differences: on the fast path each active channel's tip must stand a raster per
channel in front of the first tip, not of the one before; and choosing from a group, a tip read
for an inactive channel is passed over (that channel sits between the active ones, so their tips
must be a raster apart per channel). Venus tries the first group with enough tips only; a pattern
with gaps can find too few in it (7 tips left in a column for `01010101` give 3) and ask the
operator to load tips with full columns left. Repaired here: the next group with enough is tried
before giving up (`faithful=True` keeps Venus's behaviour, for the differential test).

Too few tips is the operator's (a dialog to load more): here an error. The library sorts with SQL
in a temporary workbook and reads positions from Venus's deck object; the HSL interpreter runs it
with both modelled (`tests/test_star_tip_tools_hsl.py` compares both planners with the port).

DefragTipRacks1mL moves tips out of the emptiest racks into the gaps of the fullest, a channel slice
at a time (`plan_defrag`; the library works over a temporary workbook with SQL, read here as a
table of positions and their states).

Channel Y reach (`HelperLibrary::GetChannelLimits`, 1 mL channels only, no 5 mL, handling or camera
channels): channel i (1 = back) of n reaches Y <= 614.5 - 9 i and Y >= -1 + 9 (n - i + 1), deck mm.
"""
from __future__ import annotations

from typing import Callable, Sequence

from venus_interop.methods import sequences as sq

LIBRARY = "STAR_TIP_TOOLS"  # the Venus namespace ported

RASTER = 9.0  # mm, the 1 mL channels' raster (configuration key 26)
Y_TOP, Y_BOTTOM = 614.5, -1.0  # GetChannelLimits' deck limits


def channel_limits(n: int, raster: float = RASTER) -> tuple[list[float], list[float]]:
  """(Y max, Y min) per channel, back to front."""
  return ([Y_TOP - i * raster for i in range(1, n + 1)],
          [Y_BOTTOM + (n - i + 1) * raster for i in range(1, n + 1)])


def channel_pattern(active: int, total: int) -> str:
  """BuildChannelPattern: the first `active` of `total` channels."""
  return ("1" * active + "0" * total)[:total]


def _raster_sorted(items, xy, raster):
  """SortSequenceRaster: X up, then whether a tip is a raster in front of the last one kept in its
  column, then Y down."""
  rows, cur_x, cur_y = [], None, None
  for k, item in enumerate(items):
    x, y = xy(item)
    if k == 0 or x != cur_x:
      r, cur_x, cur_y = 1, x, y
    else:
      r = 1 if round((cur_y - y) / raster, 6) >= 1.0 else 0
      if r:
        cur_y = y
    rows.append((x, -r, -y, k, item))
  return [row[-1] for row in sorted(rows)]


def _in_order(items, needed, channels, xy, raster, pattern) -> bool:
  """The fast path: the next tips serve as they are. Without a pattern, tip k goes to channel k,
  each a raster in front of the one before; with one (Optimized1mLTipPickup2), the next tip goes to
  each active channel, a raster in front of the first per channel between them."""
  y_max, y_min = channel_limits(channels, raster)
  if len(items) < needed:
    return False
  targets = ([(k, k) for k in range(needed)] if pattern is None else
             list(zip((c for c in range(channels) if pattern[c]), range(needed))))
  target_x = prev_y = None
  for c, k in targets:
    x, y = xy(items[k])
    if not (y_min[c] <= y <= y_max[c]):
      return False
    if target_x is None:
      target_x, prev_y, first_c = x, y, c
    elif x != target_x or y > (prev_y - raster if pattern is None else prev_y - (c - first_c) * raster):
      return False
    elif pattern is None:
      prev_y = y
  return True


def plan_tips(items: Sequence[sq.Item], needed: int, channels: int,
              xy: Callable[[sq.Item], tuple[float, float]], raster: float = RASTER,
              pattern: Sequence[int] | None = None, faithful: bool = False) -> list[sq.Item] | None:
  """The tips left (`items`, from the current position on) reordered for a pick-up of `needed`
  tips, or None when the order already serves (the fast path). `pattern`: the channels to fill (1
  active, per channel), as Optimized1mLTipPickup2 takes them; a group's tip read on an inactive
  channel is passed over (that channel sits between the others, a raster apart). `faithful`:
  give up on the first group as Venus does, not try the next."""
  y_max, y_min = channel_limits(channels, raster)
  if _in_order(items, needed, channels, xy, raster, pattern):
    return None
  rest = _raster_sorted(list(items), xy, raster)
  group_of, group, cur_x, index = {}, 0, None, 0
  for item in rest:
    x, _ = xy(item)
    index += 1
    if x != cur_x:
      cur_x, group, index = x, group + 1, 1
    if index > channels:
      index, group = 1, group + 1
    group_of[item] = group
  counts: dict[int, int] = {}
  for g in group_of.values():
    counts[g] = counts.get(g, 0) + 1
  by_place = sorted(rest, key=lambda it: (it[0], -xy(it)[1], xy(it)[0]))
  groups = list(dict.fromkeys(group_of[it] for it in by_place if counts[group_of[it]] >= needed))

  def pick(g):
    members = sorted((it for it in rest if group_of[it] == g), key=lambda it: (xy(it)[0], -xy(it)[1]))
    return set(members[:needed] if pattern is None else [it for it, on in zip(members, pattern) if on])

  if groups:
    # Venus tries the first group only; a pattern with gaps can then find too few in it and ask
    # for tips with others left. Repaired (not `faithful`): the first group that has enough.
    chosen = pick(groups[0])
    if len(chosen) < needed and not faithful:
      chosen = next((c for c in map(pick, groups[1:]) if len(c) >= needed), chosen)
  else:
    chosen, k = set(), 0
    for it in sorted(rest, key=lambda it: (xy(it)[0], -xy(it)[1])):
      if k >= needed:
        break
      y = xy(it)[1]
      if y_min[k] <= y <= y_max[k]:
        chosen.add(it)
        k += 1
  if len(chosen) < needed:
    raise RuntimeError(f"too few tips: {len(chosen)} for {needed} channels (Venus asks the operator to load more)")
  return sorted(rest, key=lambda it: (it not in chosen, it[0], xy(it)[0], -xy(it)[1]))


RACK = 96  # a rack counted as full (the library's "< 96": partial)
HAS_TIP, EMPTY, EMPTIED, FILLED = 1, 0, -1, 2  # the defrag's states (its sort table's USED column)


def plan_defrag(remaining: Sequence[sq.Item], racks: dict[str, Sequence[sq.Item]], channels: int, xy,
                faithful: bool = False):
  """DefragTipRacks1mL's plan: (rounds, the tip sequence after). The table is the tips left, in
  order, then each rack's empty positions in its default order. A round: the racks with tips, the
  fewest first (fewer than 96; ties by labware id, as the interpreter's SQL gives them: Jet's order
  is open, CONVENTIONS §11), all but the fullest give tips: channel by channel, the first tip it can
  reach, X up then Y down, on the first of them that has one; the racks with gaps, the fewest first,
  all but the emptiest take them: each channel that holds a tip, the first gap it can reach, X down
  then Y down, else the channel is dropped. Stops when one rack (or none) is left on either side.
  Moved tips and the gaps they leave are marked apart (FILLED, EMPTIED) and no longer counted. A
  round yields (pattern, pick-up items, put-down items) as the library builds them: the pick-ups of
  dropped channels stay in the list (its steps then take them in order for the channels left).
  After: the positions holding tips, in table order. Repaired (`faithful` raises): a round that can
  move nothing would repeat for ever."""
  have = {tuple(it) for it in remaining}
  table = [tuple(it) for it in remaining] + [tuple(it) for lab in dict.fromkeys(it[0] for it in remaining)
                                              for it in racks[lab] if tuple(it) not in have]
  state = [HAS_TIP] * len(remaining) + [EMPTY] * (len(table) - len(remaining))
  ymax, ymin = channel_limits(channels)
  where = {it: xy(it) for it in table}
  rounds = []

  def partial(kind):
    counts: dict[str, int] = {}
    for it, s in zip(table, state):
      if s == kind:
        counts[it[0]] = counts.get(it[0], 0) + 1
    return [lab for lab, n in sorted(sorted(counts.items()), key=lambda kv: kv[1]) if n < RACK][:-1]

  def first(c, labs, kind, used, x_sign):
    for lab in labs:
      found = sorted((i for i, it in enumerate(table) if it[0] == lab and state[i] == kind
                      and ymin[c] <= where[it][1] <= ymax[c]),
                     key=lambda i: (x_sign * where[table[i]][0], -where[table[i]][1]))
      for i in found:
        if i not in used:
          return i
    return None

  while True:
    givers = partial(HAS_TIP)
    if not givers:
      break
    used, picks, pattern = set(), [], []
    for c in range(channels):
      i = first(c, givers, HAS_TIP, used, 1)
      pattern.append(i is not None)
      if i is not None:
        picks.append(i)
        used.add(i)
        if len(picks) == channels:
          break
    pattern += [False] * (channels - len(pattern))
    takers = partial(EMPTY)
    if not takers:
      break
    puts = []
    for c in range(channels):
      if pattern[c]:
        i = first(c, takers, EMPTY, used, -1)
        if i is None:
          pattern[c] = False
        else:
          puts.append(i)
          used.add(i)
          if len(puts) == channels:
            break
    if not any(pattern):
      if faithful:
        raise RuntimeError("DefragTipRacks1mL: no tip can be moved, and the library tries again for ever")
      break
    active = sum(pattern)
    for i in picks[:active]:  # the library marks the first picks, one per active channel
      state[i] = EMPTIED
    for i in puts[:active]:
      state[i] = FILLED
    rounds.append(("".join("1" if c else "0" for c in pattern), [table[i] for i in picks], [table[i] for i in puts]))
  return rounds, [it for it, s in zip(table, state) if s > 0]


class StarTipTools:
  def __init__(self, deck, channels: int = 8, xy: Callable[[sq.Item], tuple[float, float]] | None = None,
               counters=None, faithful: bool = False):
    """`xy`: a tip position's deck (X, Y); from the PLR deck when None. `counters`: the tip counters
    (a tip_count.TipCounters), in memory when None. `faithful`: keep the library's defect the port
    repairs (Optimized1mLTipPickup2 asking for tips with tips left; see the module docstring)."""
    from venus_interop.plr.libraries.tip_count import TipCounters

    self.v, self.channels, self.faithful = deck, channels, faithful
    self.counters = counters if counters is not None else TipCounters()
    if xy is not None:
      self._xy = xy

  def _xy(self, item: sq.Item) -> tuple[float, float]:
    c = self.v.resolve(item).get_location_wrt(self.v.deck, "c", "c", "b")
    return round(c.x, 4), round(c.y, 4)

  def Optimized1mLTipPickup(self, ML_STAR, tip_sequence: str, control_sequence: str, tip_counter: str = "") -> str:
    """The channel pattern for the next pick-up; the tip sequence reordered when needed."""
    ctl = self.v.seq(control_sequence)
    needed = min(ctl.total - ctl.cur + 1 if ctl.cur > 0 else 0, self.channels)
    if needed <= 0:
      return ""
    tips = self.v.seq(tip_sequence)
    if (tips.end - tips.cur + 1 if tips.cur > 0 else 0) < needed:  # TipCheck: against the end
      raise RuntimeError(f"{tip_sequence}: too few tips for {needed} channels (Venus asks the operator to load more)")
    left = tips.items[tips.cur - 1:] if tips.cur > 0 else []
    order = plan_tips(left, needed, self.channels, self._xy)
    if order is not None:
      tips.assign(sq.Sequence(tips.name, order))
    return channel_pattern(needed, self.channels)

  def Optimized1mLTipPickup2(self, ML_STAR, tip_sequence: str, tip_counter: str, channel_pattern: str) -> None:
    """The tip sequence reordered, when needed, for a pick-up on the channels the pattern gives
    (as many tips as it has 1s; the pick-up step takes the pattern itself)."""
    pattern = [int(c) for c in (str(channel_pattern) + "0" * self.channels)[:self.channels]]
    needed = sum(pattern)
    if needed == 0:
      return
    tips = self.v.seq(tip_sequence)
    if (tips.end - tips.cur + 1 if tips.cur > 0 else 0) < needed:  # TipCheck: against the end
      raise RuntimeError(f"{tip_sequence}: too few tips for {needed} channels (Venus asks the operator to load more)")
    left = tips.items[tips.cur - 1:] if tips.cur > 0 else []
    order = plan_tips(left, needed, self.channels, self._xy, pattern=pattern, faithful=self.faithful)
    if order is not None:
      tips.assign(sq.Sequence(tips.name, order))

  def Get1mLChannelCount(self, ML_STAR=None) -> int:
    """The instrument's 1 mL channels (configuration key 1)."""
    return self.channels

  def _rack(self, lab: str) -> list[sq.Item]:
    """HelperLibrary::GetDefaultSequence: every position of a rack, by column (it reads the rack's
    rows and columns from Venus's deck object): here as the layout sequence listing most of them
    has them, which is that order for tip racks."""
    best = max((items for items in self.v.sequences.values()), key=lambda items: sum(it[0] == lab for it in items),
               default=[])
    return [tuple(it) for it in best if it[0] == lab]

  async def DefragTipRacks1mL(self, ML_STAR, tip_sequence, pipettes) -> None:
    """Tips moved from the emptiest racks into the gaps of the fullest (`plan_defrag`), a slice of
    channels at a time on `pipettes` (PLR's channels): picked up and put down into the rack. The
    tip sequence then lists what holds tips, from position 1. Its tips from the current position
    on (HelperLibrary::RemoveTruncatedSequencePositions). Left out: the deck view's used/empty
    marks (DeckVisualize)."""
    s = self.v.seq(tip_sequence)
    left = s.items[s.cur - 1:] if s.cur > 0 else []
    racks = {lab: self._rack(lab) for lab in dict.fromkeys(it[0] for it in left)}
    rounds, after = plan_defrag(left, racks, self.channels, self._xy, self.faithful)
    for pattern, picks, puts in rounds:
      up = sq.take(sq.Sequence("seq_TipsPickUp", picks), pattern, sq.AUTOMATIC, sq.ALL_POSITIONS)
      down = sq.take(sq.Sequence("seq_TipsPutDown", puts), pattern, sq.MANUAL, sq.ALL_POSITIONS)
      on = sorted(up.channels)
      await pipettes.pick_up_tips([self.v.resolve(up.channels[c]) for c in on], use_channels=[c - 1 for c in on])
      held = sorted(down.channels)
      await pipettes.drop_tips([self.v.resolve(down.channels[c]) for c in held], use_channels=[c - 1 for c in held])
    s.assign(sq.Sequence(s.name, after))

  # -- tip counters: the positions still holding tips, carried between runs -------------------

  def TipCounter_Read(self, ML_STAR, tip_sequence: str, tip_counter: str, counters=None):
    """The tip sequence as the counter left it: only the positions still holding tips, from 1; as
    the layout has it when nothing is stored (`counters`: a tip_count.TipCounters)."""
    from venus_interop.plr.libraries.tip_count import OCCUPIED

    counters = counters if counters is not None else self.counters
    stored = counters.read(tip_counter)
    s = self.v.seq(tip_sequence)
    items = ([it for it, status in stored if status == OCCUPIED] if stored is not None
             else list(self.v.sequences[s.name]))
    s.assign(sq.Sequence(s.name, items))
    return s.total

  def TipCounter_Write(self, ML_STAR, tip_sequence: str, tip_counter: str, counters=None):
    """The positions from the current one on (RemoveUsedPositions; none when the rack is used up)."""
    from venus_interop.plr.libraries.tip_count import OCCUPIED

    counters = counters if counters is not None else self.counters
    s = self.v.seq(tip_sequence)
    counters.write(tip_counter, [(tuple(it), OCCUPIED) for it in (s.items[s.cur - 1:] if s.cur > 0 else [])])

  def TipCounter_Edit(self, ML_STAR, tip_sequence: str, tip_counter: str, timeout=None, counters=None):
    """Venus shows the operator the tips left to confirm or change (the loading dialog): here the
    counter is read, the used positions dropped and written back, as confirmed unchanged."""
    self.TipCounter_Read(ML_STAR, tip_sequence, tip_counter, counters)
    self.TipCounter_Write(ML_STAR, tip_sequence, tip_counter, counters)
