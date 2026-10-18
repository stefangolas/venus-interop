"""NGSStar's incubation timers and tip counters (the STAR Tip Tools kind), against their code as read.

Neither runs a device step, so there is nothing for the HSL interpreter to compare: the timers wait
on Venus's timer objects, the counters live in Venus's compiled element counter.
"""
import asyncio

import pytest

pytest.importorskip("pylabrobot")

from venus_interop.methods import sequences as sq  # noqa: E402
from venus_interop.plr.libraries.ngsstar_processes import HVFT, LVFT, SVFT, NGSStarProcesses  # noqa: E402
from venus_interop.plr.libraries.star_tip_tools import StarTipTools  # noqa: E402
from venus_interop.plr.libraries.tip_count import TipCounters  # noqa: E402

RACK = [("T", str(i)) for i in range(1, 97)]


class _Deck:
  def __init__(self):
    self.sequences = {"Tips300": list(RACK)}
    self.live = {"Tips300": sq.Sequence("Tips300", list(RACK))}

  def seq(self, name):
    return self.live[name]


def procs(deck, counters=None, **kw):
  planner = StarTipTools(deck, counters=counters)
  return NGSStarProcesses(type("Star", (), {"pipettes": None})(), deck, {SVFT: "Tips300"}, {}, planner=planner,
                          tip_counters={SVFT: "tc300"}, **kw)


def test_timers_start_wait_and_wait_for_what_is_left():
  t, slept = [0.0], []

  async def sleep(s):
    slept.append(s)
    t[0] += s

  p = procs(_Deck(), time_scale=1.0, sleep=sleep, clock=lambda: t[0])

  async def go():
    await p.DATA_IncubationTimer("beads", 120.7, 1)  # start and wait, whole seconds
    await p.DATA_IncubationTimer("dry", 300, 2)  # start only
    t[0] += 100  # other work
    await p.DATA_IncubationTimer("dry", 300, 3)  # what is left
  asyncio.run(go())
  assert slept == [120, 200]


def test_simulation_skips_the_waits():
  slept = []

  async def sleep(s):
    slept.append(s)
  asyncio.run(procs(_Deck(), sleep=sleep).DATA_IncubationTimer("x", 60, 1))
  assert slept == [0.0]


def test_a_rack_carries_over_as_the_tips_left(tmp_path):
  deck = _Deck()
  deck.seq("Tips300").set_current_position(41)  # 40 tips used
  procs(deck, TipCounters(tmp_path / "c.json")).DATA_TipCounterWrite()
  later = _Deck()
  procs(later, TipCounters(tmp_path / "c.json")).DATA_TipCounterRead(required_300=50, tip_types=2)
  s = later.seq("Tips300")
  assert (s.total, s.cur, s.items[0]) == (56, 1, ("T", "41"))


def test_too_few_tips_is_the_reload_dialog():
  deck = _Deck()
  deck.seq("Tips300").set_current_position(90)
  counters = TipCounters()
  procs(deck, counters).DATA_TipCounterWrite()
  with pytest.raises(RuntimeError, match="7 tips for 50"):
    procs(_Deck(), counters).DATA_TipCounterRead(required_300=50, tip_types=2)


def test_no_counter_stored_reads_the_layout_and_edit_keeps_what_is_left():
  deck = _Deck()
  tools = StarTipTools(deck)
  assert tools.TipCounter_Read(None, "Tips300", "none") == 96
  deck.seq("Tips300").set_current_position(11)
  tools.TipCounter_Write(None, "Tips300", "c")
  tools.TipCounter_Edit(None, "Tips300", "c")
  assert deck.seq("Tips300").total == 86 and tools.counters.counters["c"][0] == ["T", "11"]
  assert (LVFT, HVFT) == (23, 5)
