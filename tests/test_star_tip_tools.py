"""STAR Tip Tools' tip pick-up planner, against the algorithm as read from the HSL.

The library sorts with SQL over a CSV file and reads deck positions from Venus's deck object, so it
cannot run in the HSL interpreter; these cases follow its code (see the module docstring).
"""
import pytest

from venus_interop.methods import sequences as sq
from venus_interop.plr.libraries import star_tip_tools as stt

ROWS = "ABCDEFGH"


def rack(name: str, x0: float = 100.0, y0: float = 300.0):
  """A 96-tip rack as a Venus sequence orders it: column by column, A (back) to H; 9 mm pitch."""
  items = [(name, f"{r}{c}") for c in range(1, 13) for r in ROWS]
  pos = {(name, f"{r}{c}"): (x0 + (c - 1) * 9.0, y0 - ROWS.index(r) * 9.0) for c in range(1, 13) for r in ROWS}
  return items, pos


def test_channel_limits_are_getchannellimits_for_eight_1ml_channels():
  y_max, y_min = stt.channel_limits(8)
  assert y_max == [605.5, 596.5, 587.5, 578.5, 569.5, 560.5, 551.5, 542.5]
  assert y_min == [71.0, 62.0, 53.0, 44.0, 35.0, 26.0, 17.0, 8.0]


def test_a_full_column_in_order_takes_the_fast_path():
  items, pos = rack("T")
  assert stt.plan_tips(items, 8, 8, pos.get) is None


def test_part_of_a_column_left_with_fewer_needed_takes_the_fast_path():
  items, pos = rack("T")
  assert stt.plan_tips(items[4:], 4, 8, pos.get) is None  # E1..H1 for 4 channels


def test_a_pick_up_across_columns_moves_to_the_next_full_column():
  items, pos = rack("T")
  order = stt.plan_tips(items[4:], 8, 8, pos.get)  # E1..H1 left in column 1
  assert order[:8] == [("T", f"{r}2") for r in ROWS]  # column 2 first
  assert order[8:12] == [("T", f"{r}1") for r in "EFGH"]  # the partial column kept, then the rest
  assert order[12] == ("T", "A3") and len(order) == len(items) - 4


def test_no_group_big_enough_takes_reachable_tips_by_x_then_y():
  items, pos = rack("T")
  left = [it for it in items if it[1][1:] in ("1", "2", "3") and it[1][0] in "FGH"]  # 3 tips in 3 columns
  order = stt.plan_tips(left, 8, 8, pos.get)  # 9 tips, no group of 8: channels take what they reach
  assert len(order) == 9
  y_max, y_min = stt.channel_limits(8)
  for k, it in enumerate(order[:8]):
    assert y_min[k] <= pos[it][1] <= y_max[k]


def test_too_few_tips_is_an_error():
  items, pos = rack("T")
  with pytest.raises(RuntimeError):
    stt.plan_tips(items[-3:], 8, 8, pos.get)


class _Deck:
  def __init__(self, seqs, pos):
    self.live = {k: sq.Sequence(k, v) for k, v in seqs.items()}
    self.pos = pos
    self.deck = None

  def seq(self, name):
    return self.live[name]

  def resolve(self, item):
    deck = self

    class Spot:
      def get_location_wrt(self, _deck, *_):
        x, y = deck.pos[item]
        return type("C", (), {"x": x, "y": y})()
    return Spot()


def test_the_entry_point_reorders_the_tip_sequence_and_gives_the_pattern():
  items, pos = rack("T")
  plate = [("P", f"{r}{c}") for c in range(1, 13) for r in ROWS]
  d = _Deck({"Tips": items, "Plate": plate}, pos)
  d.seq("Tips").set_current_position(5)
  d.seq("Plate").set_current_position(93)  # 4 positions left: 4 channels
  tools = stt.StarTipTools(d)
  assert tools.Optimized1mLTipPickup(None, "Tips", "Plate") == "11110000"
  assert d.seq("Tips").cur == 5  # fast path: untouched
  d.seq("Plate").set_current_position(1)
  assert tools.Optimized1mLTipPickup(None, "Tips", "Plate") == "11111111"
  t = d.seq("Tips")
  assert (t.cur, t.total) == (1, 92) and t.items[0] == ("T", "A2")
