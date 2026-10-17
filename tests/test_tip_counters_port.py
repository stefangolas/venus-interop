"""Tip counters: NIST's "Tip Handling with 96-Head" and Hamilton's TipCount::Read2, ports against the HSL.

The HSL side runs GetTipCounters, GetTipStatusFile and Read2 on Marionette's tip sequences with
counters supplied to the interpreter's element counter; the port reads the same counters from a
TipCounters store. Returns and the tip sequences' state must match: a stored counter restores the
sequence's position, a missing one leaves it as it is (-1), an empty rack ends at position 0.
Write2 then Read2 on the port carries a sequence's position over.

Needs VENUS_INTEROP_NIST and VENUS_INTEROP_CORPUS (Marionette's layout, 3ed5809e547e.lay).
"""
import os
import pathlib

import pytest

from venus_interop.files import layout
from venus_interop.methods import hsl_eval, protocol, sequences as sq

NIST = pathlib.Path(os.environ["VENUS_INTEROP_NIST"]) if os.environ.get("VENUS_INTEROP_NIST") else None
CORPUS = pathlib.Path(os.environ["VENUS_INTEROP_CORPUS"]) if os.environ.get("VENUS_INTEROP_CORPUS") else None
pytestmark = pytest.mark.skipif(NIST is None or CORPUS is None,
                                reason="VENUS_INTEROP_NIST and VENUS_INTEROP_CORPUS not set")

# What this test checks against the HSL (read by tools/trace_method.py --status)
LIBRARY = "TIP_HANDLING_WITH_96_HEAD"
COVERS = ["GetTipCounters", "GetTipStatusFile"]
COVERS_ALSO = {"TIPCOUNT": ["Read2"]}

STORED = {"Tips_for_ch_1000_auto": 17, "Tips_for_ch_300_auto": 0}
# (tip sequence, counter): stored at 17, stored empty, not stored
READS = [("Tips_1000_Channels", "Tips_for_ch_1000_auto"), ("Tips_300_Channels", "Tips_for_ch_300_auto"),
         ("Tips_50_Channels", "Tips_for_ch_50_auto")]


@pytest.fixture(scope="module")
def lay():
  return layout.read_layout(CORPUS / "raw" / "3ed5809e547e.lay")


def hsl_state(lay):
  reads = "\n".join(f'ret.AddAsLast(TipCount::Read2(ML_STAR.{s}, c{i}, ML_STAR));' for i, (s, _) in enumerate(READS))
  names = "\n".join(f'c{i} = "{c}";' for i, (_, c) in enumerate(READS))
  src = (
    'namespace _Method { #include "HSLSeqLib.hsl" }\n'
    'namespace _Method { #include "HSLTipCountingLib.hsl" }\n'
    'namespace _Method { #include "Common\\\\Tip Handling\\\\With 96-Head\\\\Tip Handling with 96-Head.hs_" }\n'
    'global device ML_STAR ("x.lay", "ML_STAR", hslTrue);\n'
    'variable auto_names[];\nvariable manual_names[];\nvariable ret[];\nvariable status_file;\n'
    + "".join(f"variable c{i};\n" for i in range(len(READS))) +
    'namespace _Method { #include "HSLMECCLib.hs_" }\n'
    "namespace _Method { method main() void {\n"
    "TIP_HANDLING_WITH_96_HEAD::GetTipCounters(auto_names, 1);\n"
    "TIP_HANDLING_WITH_96_HEAD::GetTipCounters(manual_names, 0);\n"
    "status_file = TIP_HANDLING_WITH_96_HEAD::GetTipStatusFile();\n"
    f"{names}\n{reads}\n" "} }\n")
  here = NIST / "Methods" / "Common" / "port_test.hsl"
  pre = hsl_eval.Preprocessor([NIST / "Library", NIST / "Methods"], lambda p: p.read_text(encoding="latin-1"))
  text = pre.expand(here, text=src)
  parser = hsl_eval.Parser(hsl_eval.lex(text))
  parser.unit()
  run = hsl_eval.Run(parser, protocol.load_stps([]), {"x.lay": lay}, answers={"tip_counters": STORED})
  run.src = text.splitlines()
  run.run()
  assert run.stopped is None, run.stopped
  cells = {k.lower(): c.value for scope in run.globals.values() for k, c in scope.items()}
  dev = next(v for v in cells.values() if isinstance(v, hsl_eval.Device))
  seqs = {s: dev.sequences[s.lower()] for s, _ in READS}
  return (list(cells["auto_names"].items), list(cells["manual_names"].items), cells["status_file"],
          [hsl_eval._num(x) for x in cells["ret"].items], seqs)


class _Deck:
  def __init__(self, lay):
    self.sequences = {s.name: list(s.items) for s in lay.sequences}
    self.live = {}

  def seq(self, name):
    if name not in self.live:
      self.live[name] = sq.Sequence(name, list(self.sequences[name]))
    return self.live[name]


def port_state(lay):
  from venus_interop.plr.libraries.tip_count import TipCount, TipCounters
  from venus_interop.plr.libraries.tip_handling_96 import TipHandling96

  deck, counters = _Deck(lay), TipCounters()
  counters.counters.update(STORED)
  t96, tc = TipHandling96(), TipCount(deck, counters)
  ret = [tc.Read2(s, c) for s, c in READS]
  return (t96.GetTipCounters(1), t96.GetTipCounters(0), t96.GetTipStatusFile(), ret,
          {s: deck.seq(s) for s, _ in READS})


def test_covers_what_it_calls():
  assert COVERS == ["GetTipCounters", "GetTipStatusFile"] and COVERS_ALSO == {"TIPCOUNT": ["Read2"]}


def test_port_reads_the_counters_as_the_library_does(lay):
  h, p = hsl_state(lay), port_state(lay)
  assert h[:4] == p[:4]
  assert h[3] == [1, 1, -1]
  for name in h[4]:
    a, b = h[4][name], p[4][name]
    assert (a.cur, a.end, a.max) == (b.cur, b.end, b.max), name
  assert h[4]["Tips_1000_Channels"].cur == 17 and h[4]["Tips_300_Channels"].cur == 0


def test_a_written_counter_carries_over(lay, tmp_path):
  from venus_interop.plr.libraries.tip_count import TipCount, TipCounters

  deck = _Deck(lay)
  deck.seq("Tips_1000_Channels").set_current_position(42)
  TipCount(deck, TipCounters(tmp_path / "c.json")).Write2("Tips_1000_Channels", "Tips_for_ch_1000_auto")
  later = _Deck(lay)
  assert TipCount(later, TipCounters(tmp_path / "c.json")).Read2("Tips_1000_Channels", "Tips_for_ch_1000_auto") == 1
  assert later.seq("Tips_1000_Channels").cur == 42
