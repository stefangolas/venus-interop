"""STAR Tip Tools' tip pick-up planners against the HSL itself (`STAR Tools\\STAR Tip Tools.hsi`).

Optimized1mLTipPickup (tips for the positions left in a control sequence) and Optimized1mLTipPickup2
(tips for the channels of a pattern) run in the HSL interpreter and in the port on the same tip
sequence: two 96-tip racks side by side, from several start positions, one with tips missing as a
tip counter leaves them. The library sorts in a temporary workbook with SQL (the interpreter's
workbooks, SQLite) and reads positions from the deck object (here `answers["labware_position"]`, the
racks' coordinates) and the channel count and raster from the instrument configuration (keys 1
and 26). Each case must leave the same tip sequence, in the same order, at the same position, and
v1 must give the same channel pattern.

Needs VENUS_INTEROP_HAMILTON_LIBS (a folder holding `STAR Tools\\`, as pyhamilton's library does).
"""
import functools
import os
import pathlib
import types

import pytest

from venus_interop.methods import hsl_eval, protocol, sequences as sq
from venus_interop.plr.libraries import star_tip_tools as stt

LIBS = [pathlib.Path(p) for p in os.environ.get("VENUS_INTEROP_HAMILTON_LIBS", "").split(os.pathsep) if p]
TOOLS = next((p / "STAR Tools" for p in LIBS if (p / "STAR Tools" / "STAR Tip Tools.hs_").exists()), None)
pytestmark = pytest.mark.skipif(TOOLS is None, reason="VENUS_INTEROP_HAMILTON_LIBS holds no STAR Tools")

# What this test checks against the HSL (read by tools/trace_method.py --status)
LIBRARY = "STAR_TIP_TOOLS"
COVERS = ["Optimized1mLTipPickup", "Optimized1mLTipPickup2", "DefragTipRacks1mL", "Get1mLChannelCount"]

ROWS = "ABCDEFGH"
RACKS = {"T1": 100.0, "T2": 220.0}  # rack -> X of column 1; row A at Y 300, 9 mm pitch


YBACK = {"T4": 600.0}  # a rack at the back: its row A at Y 600, beyond the front channels' reach


def xy(item):
  lab, pos = item
  return RACKS[lab] + (int(pos[1:]) - 1) * 9.0, YBACK.get(lab, 300.0) - ROWS.index(pos[0]) * 9.0


def rack(lab):
  return [(lab, f"{r}{c}") for c in range(1, 13) for r in ROWS]


FULL = rack("T1") + rack("T2")
GAPPY = [it for k, it in enumerate(FULL) if k % 8 not in (2, 5)]  # rows C and F gone, every column


def layout(tips, control_count=0):
  seqs = [types.SimpleNamespace(name="Tips", items=list(tips)),
          types.SimpleNamespace(name="Ctl", items=[("P", str(k + 1)) for k in range(control_count)])]
  return types.SimpleNamespace(sequences=seqs, labware=[types.SimpleNamespace(id=n) for n in (*RACKS, "P")])


@functools.lru_cache(maxsize=1)
def program():
  """The library and a main calling either planner, parsed once; each case's inputs come from the
  TESTINPUT functions, answered per run."""
  src = ('namespace _Method { #include "HSLSeqLib.hsl" }\n'
         'namespace _Method { #include "STAR Tools\\\\STAR Tip Tools.hs_" }\n'
         'global device ML_STAR ("x.lay", "ML_STAR", hslTrue);\n'
         "namespace _Method { namespace TESTINPUT {\n"
         # bodies that are only a return would be taken for .hs_ placeholders and dropped
         "function Start() variable { variable v; return(v); }\nfunction Pattern() variable { variable v; return(v); }\n"
         "function Version() variable { variable v; return(v); }\n} }\n"
         "namespace _Method { global variable g_pattern; method main() void { variable p;\n"
         "ML_STAR.Tips.SetCurrentPosition(TESTINPUT::Start());\n"
         "if (TESTINPUT::Version() == 2) {\n"
         "STAR_TIP_TOOLS::Optimized1mLTipPickup2(ML_STAR, ML_STAR.Tips, \"c\", TESTINPUT::Pattern()); }\n"
         'else { STAR_TIP_TOOLS::Optimized1mLTipPickup(ML_STAR, ML_STAR.Tips, ML_STAR.Ctl, "c", p); g_pattern = p; }\n'
         "} }\n")
  pre = hsl_eval.Preprocessor(LIBS, lambda p: p.read_text(encoding="latin-1"))
  parser = hsl_eval.Parser(hsl_eval.lex(pre.expand(TOOLS / "probe.hsl", text=src)))
  parser.unit()
  stps = protocol.load_stps(sorted([*TOOLS.glob("*.stp"), *(TOOLS / "Resources" / "SubMethods").glob("*.stp")]))
  return parser, stps


def hsl(tips, start, pattern=None, control_count=0):
  """Optimized1mLTipPickup2 with `pattern`, or Optimized1mLTipPickup for `control_count` positions:
  (the tip sequence, v1's pattern), or ("reload", None) where the library asks for more tips."""
  parser, stps = program()

  def reload(run, p):  # the operator asked to load more tips (a dialog, then the counter edited)
    raise hsl_eval.Stop("reload")

  run = hsl_eval.Run(parser, stps, {"x.lay": layout(tips, control_count)},
                     answers={"cfg.1": 8, "cfg.26": 9.0, "labware_position": lambda lab, pos: (*xy((lab, pos)), 0.0),
                              "functions": {"star_tip_tools::tipcounter_edit": reload,
                                            "testinput::start": lambda run, p: start,
                                            "testinput::pattern": lambda run, p: pattern,
                                            "testinput::version": lambda run, p: 1 if pattern is None else 2}})
  run.run()
  if run.stopped == "reload":
    return "reload", None
  assert run.stopped is None, run.stopped
  assert not run.unresolved, run.unresolved
  dev = next(c.value for sc in run.globals.values() for c in sc.values() if isinstance(c.value, hsl_eval.Device))
  pattern = next((c.value for sc in run.globals.values() for k, c in sc.items() if k == "g_pattern"), None)
  return dev.sequences["tips"], pattern


def port(tips, start, control_count=0, faithful=True):
  deck = types.SimpleNamespace(live={"Tips": sq.Sequence("Tips", list(tips)),
                                     "Ctl": sq.Sequence("Ctl", [("P", str(k + 1)) for k in range(control_count)])})
  deck.seq = lambda name: deck.live[name]
  deck.live["Tips"].set_current_position(start)
  return stt.StarTipTools(deck, 8, xy=xy, faithful=faithful), deck.live["Tips"]


PATTERNS = ["11111111", "11100000", "10100000", "00111000", "01010101", "00000011"]
CASES2 = [(tips, start, p) for tips, starts in (("FULL", (1, 3, 5, 9, 90)), ("GAPPY", (1, 4, 70)))
          for start in starts for p in PATTERNS]


@pytest.mark.parametrize("tips,start,pattern", CASES2, ids=[f"{t}-{s}-{p}" for t, s, p in CASES2])
def test_pickup2_reorders_tips_as_the_library_does(tips, start, pattern):
  items = {"FULL": FULL, "GAPPY": GAPPY}[tips]
  seq, _ = hsl(items, start, pattern)
  tools, mine = port(items, start)
  if seq == "reload":  # an inactive channel passes over a tip of the group: too few, though tips are left
    with pytest.raises(RuntimeError, match="too few tips"):
      tools.Optimized1mLTipPickup2(None, "Tips", "c", pattern)
    return
  tools.Optimized1mLTipPickup2(None, "Tips", "c", pattern)
  assert (mine.items, mine.cur) == (seq.items, seq.cur)


def test_the_reload_cases_are_the_ones_expected():
  """The library asks for tips with tips left: a pattern with gaps on a group of fewer than eight."""
  assert hsl(FULL, 90, "01010101")[0] == "reload"
  assert hsl(FULL, 1, "01010101")[0] != "reload"


CASES1 = [(tips, start, n) for tips, starts in (("FULL", (1, 5, 90)), ("GAPPY", (1, 4))) for start in starts
          for n in (8, 5, 3, 1)]


@pytest.mark.parametrize("tips,start,n", CASES1, ids=[f"{t}-{s}-n{n}" for t, s, n in CASES1])
def test_pickup_reorders_tips_as_the_library_does(tips, start, n):
  items = {"FULL": FULL, "GAPPY": GAPPY}[tips]
  seq, pattern = hsl(items, start, control_count=n)
  tools, mine = port(items, start, n)
  assert tools.Optimized1mLTipPickup(None, "Tips", "Ctl") == pattern
  assert (mine.items, mine.cur) == (seq.items, seq.cur)


def test_repaired_the_next_column_serves_a_pattern_with_gaps():
  """Repaired (the default): where Venus asks for tips (7 left in T1's last column give 3 for
  01010101), the next group with enough is used: T2's first column, a raster apart per channel."""
  tools, mine = port(FULL, 90, faithful=False)
  tools.Optimized1mLTipPickup2(None, "Tips", "c", "01010101")
  assert mine.items[:4] == [("T2", "B1"), ("T2", "D1"), ("T2", "F1"), ("T2", "H1")]
  assert mine.cur == 1


# -- DefragTipRacks1mL ---------------------------------------------------------------------------
# Tips left (the sequence from position 1), the racks as the layout has them. A third rack for
# moves over several rounds.
RACKS["T3"], RACKS["T4"] = 340.0, 460.0
T1, T2, T3, T4 = rack("T1"), rack("T2"), rack("T3"), rack("T4")
DEFRAG = {
  "full": FULL,  # whole racks: nothing to move
  "one-partial": T1[30:] + T2,  # one rack partly used: nothing to move
  "T1-into-T2": T1[60:] + [it for k, it in enumerate(T2) if k % 8 not in (2, 5)],  # T1's 36 into T2's 24 gaps
  "gaps-alike": GAPPY,  # two racks with the same gaps: T1 gives to T1 (the library's order on a tie)
  "three": T1[80:] + T2[40:] + [it for k, it in enumerate(T3) if k % 4],  # several rounds
  "scattered": [it for k, it in enumerate(T1 + T2) if k % 3 == 0],
  "nearly-full": T1[1:] + T2[50:],  # 95 tips: still partial, so it gives
  # T4's gaps (rows A-G of columns 7-12) are beyond channel 8's reach (Y <= 542.5): it is dropped
  "back-rack": T1[60:] + [it for it in T4 if it[1][0] == "H" or int(it[1][1:]) <= 6],
}


@functools.lru_cache(maxsize=1)
def defrag_program():
  src = ('namespace _Method { #include "HSLSeqLib.hsl" }\n'
         'namespace _Method { #include "STAR Tools\\STAR Tip Tools.hs_" }\n'
         'global device ML_STAR ("x.lay", "ML_STAR", hslTrue);\n'
         "namespace _Method { method main() void {\n"
         "STAR_TIP_TOOLS::DefragTipRacks1mL(ML_STAR, ML_STAR.Tips);\n} }\n")
  pre = hsl_eval.Preprocessor(LIBS, lambda p: p.read_text(encoding="latin-1"))
  parser = hsl_eval.Parser(hsl_eval.lex(pre.expand(TOOLS / "probe.hsl", text=src)))
  parser.unit()
  stps = protocol.load_stps(sorted([*TOOLS.glob("*.stp"), *(TOOLS / "Resources" / "SubMethods").glob("*.stp")]))
  return parser, stps


def _racks_layout(tips):
  lay = layout(tips)
  lay.sequences.append(types.SimpleNamespace(name="AllRacks", items=T1 + T2 + T3 + T4))
  lay.labware += [types.SimpleNamespace(id="T3"), types.SimpleNamespace(id="T4")]
  return lay


def hsl_defrag(tips):
  """The pick-ups and put-downs (channel -> position) and the tip sequence after."""
  parser, stps = defrag_program()

  def default_sequence(run, p):  # GetDefaultSequence reads the rack's rows and columns from the deck object
    p["o_seq_defaultsequence"].value.assign(sq.Sequence("d", rack(str(p["i_str_labid"].value))))
    return 0

  run = hsl_eval.Run(parser, stps, {"x.lay": _racks_layout(tips)},
                     answers={"cfg.1": 8, "cfg.26": 9.0, "labware_position": lambda lab, pos: (*xy((lab, pos)), 0.0),
                              "functions": {"helperlibrary::getdefaultsequence": default_sequence,
                                            "deckvisualize::updateusedpositions": lambda run, p: 0}},
                     max_steps=5_000_000)
  run.run()
  assert run.stopped is None, run.stopped
  assert not run.unresolved, run.unresolved
  moves = [(e.command, dict(e.channels)) for e in run.events if e.command in ("TipPickUp", "TipEject")]
  dev = next(c.value for sc in run.globals.values() for c in sc.values() if isinstance(c.value, hsl_eval.Device))
  return moves, dev.sequences["tips"]


class _Pipettes:
  def __init__(self):
    self.moves = []

  async def pick_up_tips(self, spots, use_channels):
    self.moves.append(("TipPickUp", {c + 1: s for c, s in zip(use_channels, spots)}))

  async def drop_tips(self, spots, use_channels):
    self.moves.append(("TipEject", {c + 1: s for c, s in zip(use_channels, spots)}))


def port_defrag(tips, faithful=True):
  import asyncio

  tools, mine = port(tips, 1, faithful=faithful)
  tools.v.sequences = {s.name: s.items for s in _racks_layout(tips).sequences}
  tools.v.resolve = lambda item: tuple(item)
  pipettes = _Pipettes()
  asyncio.run(tools.DefragTipRacks1mL(None, "Tips", pipettes))
  return pipettes.moves, mine


@pytest.mark.parametrize("case", list(DEFRAG))
def test_defrag_moves_tips_as_the_library_does(case):
  moves, seq = hsl_defrag(DEFRAG[case])
  mine_moves, mine = port_defrag(DEFRAG[case])
  assert mine_moves == moves
  assert (mine.items, mine.cur) == (seq.items, seq.cur)
  if case in ("full", "one-partial"):
    assert not moves


def test_defrag_fills_the_fullest_rack_first():
  moves, _ = port_defrag(DEFRAG["T1-into-T2"])
  picked = [s for c, m in moves if c == "TipPickUp" for s in m.values()]
  put = [s for c, m in moves if c == "TipEject" for s in m.values()]
  assert {lab for lab, _ in picked} == {"T1"} and {lab for lab, _ in put} == {"T2"}
  assert len(put) == 24  # T2's gaps all filled


def test_defrag_drops_a_channel_that_reaches_no_gap():
  moves, _ = port_defrag(DEFRAG["back-rack"])
  assert moves and all(8 not in m for c, m in moves if c == "TipEject")


def test_defrag_with_no_reachable_gap_never_ends():
  """Gaps only in a rack's rows A and B at the back (Y 620, 611: beyond every channel), tips to give
  elsewhere: no channel can move a tip, and the library tries again for ever (the interpreter runs
  out of steps). Repaired (the default): nothing moved; faithful, an error."""
  YBACK["T5"], RACKS["T5"] = 620.0, 580.0
  try:
    tips = T1[60:] + [it for it in rack("T5") if it[1][0] not in "AB"]
    global T4
    old = T4
    T4 = old + rack("T5")  # the layout lists T5 too (_racks_layout)
    moves, _ = port_defrag(tips, faithful=False)
    assert moves == []
    with pytest.raises(RuntimeError, match="for ever"):
      port_defrag(tips)
    parser, stps = defrag_program()
    run = hsl_eval.Run(parser, stps, {"x.lay": _racks_layout(tips)}, max_steps=300_000,
                       answers={"cfg.1": 8, "cfg.26": 9.0, "labware_position": lambda lab, pos: (*xy((lab, pos)), 0.0),
                                "functions": {"helperlibrary::getdefaultsequence": lambda run, p: p[
                                  "o_seq_defaultsequence"].value.assign(sq.Sequence("d", rack(str(p["i_str_labid"].value)))) or 0,
                                  "deckvisualize::updateusedpositions": lambda run, p: 0}})
    run.run()
    assert run.stopped and "step" in run.stopped
  finally:
    T4 = old
    del YBACK["T5"], RACKS["T5"]
