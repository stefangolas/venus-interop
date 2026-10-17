"""Venus sequence rules, checked against Hamilton's documented examples."""
import pytest

from venus_interop.methods import sequences as sq


def plate(name="MySample", n=96):
  rows = "ABCDEFGH"
  return sq.Sequence(name, [("Plate", f"{rows[i % 8]}{i // 8 + 1}") for i in range(n)])


def test_layout_initial_state():
  s = plate()
  assert (s.cur, s.end, s.max, s.total, s.used) == (1, 96, 96, 96, 0)


def test_step_from_41_with_8_channels_ends_at_49():
  # "Sequence counting": current position 41, aspirate with 8 channels -> 49
  s = plate()
  s.set_current_position(41)
  t = sq.take(s, "11111111")
  assert t.first == 41 and t.used == 8 and s.cur == 49
  assert t.channels[1] == s.items[40] and t.channels[8] == s.items[47]


def test_end_position_limits_a_step_and_completes_the_sequence():
  # current 93, end 96, 8 channels: only 93..96, then the sequence is completed
  s = plate()
  s.set_current_position(93)
  t = sq.take(s, "11111111")
  assert sorted(t.channels) == [1, 2, 3, 4] and t.used == 4
  assert s.cur == 0
  with pytest.raises(sq.SequenceError):
    sq.take(s, "11111111")


def test_end_position_below_total():
  s = plate()
  s.set_count(20)
  s.set_current_position(17)
  t = sq.take(s, "11111111")
  assert t.used == 4 and s.cur == 0


def test_manual_counting_leaves_the_current_position():
  s = plate()
  t = sq.take(s, "11111111", counting=sq.MANUAL)
  assert t.used == 8 and s.cur == 1
  s.increment(s.used)  # seq++ in the method
  assert s.cur == 9


def test_set_current_position_out_of_range_disables():
  s = plate()
  s.set_count(50)
  assert s.set_current_position(50) == 50
  assert s.set_current_position(51) == 0
  assert s.set_current_position(0) == 0


def test_set_count_clamps_to_total_and_zero():
  s = plate()
  assert s.set_count(120) == 96
  assert s.set_count(-3) == 0
  assert s.set_count(40) == 40


def test_set_max_clamps_to_count():
  s = plate()
  s.set_count(10)
  assert s.set_max(20) == 10
  assert s.set_max(-1) == 0


def test_get_next_and_increment():
  s = plate(n=3)
  assert s.get_next() == 2 and s.get_next() == 3 and s.get_next() == 0 and s.get_next() == 0
  s.set_current_position(1)
  assert s.increment(2) == 3
  assert s.increment(1) == 0
  s.set_current_position(3)
  assert s.increment(-2) == 1
  assert s.increment(-1) == 0


def test_operator_plus_plus_uses_used():
  s = plate()
  sq.take(s, "11110000", counting=sq.MANUAL)
  assert s.used == 4
  s.increment(s.used)
  assert s.cur == 5
  s.increment(-s.used)
  assert s.cur == 1


# Hamilton's "Adjust Sequences Example" table: (cur, end, consumed) per sequence -> max of both
ADJUST_EXAMPLES = [
  ((1, 96, 1), (1, 20, 1), 20),
  ((1, 96, 1), (16, 20, 1), 5),
  ((1, 96, 1), (1, 20, 2), 10),
  ((1, 96, 1), (16, 20, 2), 2),
  ((1, 96, 1), (20, 20, 2), 0),
  ((1, 96, 1), (16, 20, 4), 1),
  ((1, 96, 1), (19, 20, 4), 0),
]


@pytest.mark.parametrize("one,two,expected", ADJUST_EXAMPLES)
def test_adjust_sequences_matches_hamiltons_table(one, two, expected):
  a, b = plate("one"), plate("two")
  for s, (cur, end, _) in ((a, one), (b, two)):
    s.set_count(end)
    s.set_current_position(cur)
  assert sq.align([(a, one[2]), (b, two[2])]) == expected
  assert a.max == b.max == expected


def test_max_zero_step_does_nothing():
  # examples 5 and 7: "a following instrument step will not perform any action on such sequences"
  s = plate()
  s.max = 0
  t = sq.take(s, "11111111")
  assert t.channels == {} and s.cur == 1


def test_max_limits_positions_per_step():
  s = plate()
  s.set_max(3)
  t = sq.take(s, "11111111")
  assert sorted(t.channels) == [1, 2, 3] and s.cur == 4


def test_all_positions_gives_items_to_active_channels_in_order():
  s = plate()
  t = sq.take(s, "10100000")
  assert t.channels == {1: ("Plate", "A1"), 3: ("Plate", "B1")} and s.cur == 3


def test_channel_pattern_mode_skipped_channels_consume_positions():
  s = plate()
  t = sq.take(s, "10100000", channel_use=sq.CHANNEL_PATTERN)
  assert t.channels == {1: ("Plate", "A1"), 3: ("Plate", "C1")} and s.cur == 4


def test_add_keeps_end_and_max_following_total():
  s = sq.Sequence("s", [])
  assert s.cur == 0
  s.add("P", "A1")
  s.add("P", "B1")
  assert (s.end, s.max, s.total) == (2, 2, 2)
  s.set_count(1)
  s.add("P", "C1")
  assert s.end == 1 and s.total == 3


def test_copy_is_independent_and_assign_keeps_the_object():
  a = plate()
  b = a.copy("b")
  a.set_current_position(10)
  assert b.cur == 1
  ref = b
  b.assign(a)
  assert ref.cur == 10


def test_head96_takes_96_from_the_current_position():
  s = plate(n=192)
  t = sq.take_head96(s)
  assert t.used == 96 and t.channels[1] == s.items[0] and t.channels[96] == s.items[95] and s.cur == 97
  sq.take_head96(s, counting=sq.MANUAL)
  assert s.cur == 97


def test_lookup_position():
  s = plate()
  assert s.lookup_position("Plate", "C1", 1, True) == 3
  assert s.lookup_position("Plate", "", 5, True) == 5
  assert s.lookup_position("Plate", "A1", 96, False) == 1
  assert s.lookup_position("Other", "", 1, True) == 0


def test_properties_are_set_per_position_and_a_missing_one_raises():
  # HSL reference, SetSequenceProperty / GetSequenceProperty: setting creates; getting one not
  # there throws 'property not found'
  s = sq.Sequence("s", [("P", "A1"), ("P", "B1")])
  s.set_property(2, "conc", 1.5)
  s.set_property_range(1, 2, "strain", "x")
  assert s.get_property(2, "conc") == 1.5 and s.get_property(1, "strain") == "x"
  with pytest.raises(sq.SequenceError):
    s.get_property(1, "conc")
  s.remove_all_properties(2)
  with pytest.raises(sq.SequenceError):
    s.get_property(2, "strain")


def test_a_copy_carries_its_own_properties():
  s = sq.Sequence("s", [("P", "A1")])
  s.set_property(1, "conc", 1)
  c = s.copy()
  c.set_property(1, "conc", 2)
  assert s.get_property(1, "conc") == 1 and c.get_property(1, "conc") == 2
