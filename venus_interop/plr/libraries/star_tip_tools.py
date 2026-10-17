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

Too few tips is the operator's (a dialog to load more): here an error. The library does its sorting
with SQL over a CSV file and reads positions from Venus's deck object, so the HSL interpreter cannot
run it: this port is checked against the algorithm as read, by unit tests, not by a differential
test.

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


def plan_tips(items: Sequence[sq.Item], needed: int, channels: int,
              xy: Callable[[sq.Item], tuple[float, float]], raster: float = RASTER) -> list[sq.Item] | None:
  """The tips left (`items`, from the current position on) reordered for a pick-up of `needed`
  tips, or None when the order already serves (the fast path)."""
  y_max, y_min = channel_limits(channels, raster)
  if len(items) >= needed:
    ok, target_x, prev_y = True, None, None
    for k, item in enumerate(items[:needed]):
      x, y = xy(item)
      if not (y_min[k] <= y <= y_max[k]):
        ok = False
        break
      if k == 0:
        target_x, prev_y = x, y
      elif x != target_x or y > prev_y:
        ok = False
        break
      else:
        prev_y = y
      prev_y -= raster
    if ok:
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
  chosen_group = next((group_of[it] for it in by_place if counts[group_of[it]] >= needed), None)
  if chosen_group is not None:
    members = sorted((it for it in rest if group_of[it] == chosen_group), key=lambda it: (xy(it)[0], -xy(it)[1]))
    chosen = set(members[:needed])
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


class StarTipTools:
  def __init__(self, deck, channels: int = 8, xy: Callable[[sq.Item], tuple[float, float]] | None = None):
    """`xy`: a tip position's deck (X, Y); from the PLR deck when None."""
    self.v, self.channels = deck, channels
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
