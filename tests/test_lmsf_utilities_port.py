"""NIST's LMSF_Utilities, the functions the methods call: the port against the HSL library.

Both sides set properties on the positions of a short sequence, copy them onto the Growth Plate's
sequence (SeqCopyPropsFromShortSeq) and set some by well (SeqSetPropertyByWell, one well not in the
sequence). The plate's properties, the values returned and both sequences' state must match.

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
LIBRARY = "LMSF_UTILITIES"
COVERS = ["SeqCopyPropsFromShortSeq", "SeqSetPropertyByWell"]

SHORT, PLATE = "calc_wells_with_tmp", "Growth_Plate"
PROPS = ["tmp_conc", "strain"]
BY_WELL = [("Growth_Plate", "A1", "inducer_1_conc", 2.5), ("Growth_Plate", "H12", "inducer_1_conc", 7),
           ("Growth_Plate", "C5", "strain", "MG1655"), ("Not_On_Deck", "A1", "inducer_1_conc", 1)]


@pytest.fixture(scope="module")
def lay():
  return layout.read_layout(CORPUS / "raw" / "3ed5809e547e.lay")


def _value(i: int, name: str):
  return i * 1.5 if name == "tmp_conc" else f"strain {i}"


def hsl_state(lay):
  n = next(len(s.items) for s in lay.sequences if s.name == SHORT)
  sets = "\n".join(f'ML_STAR.{SHORT}.SetSequenceProperty({i}, "{p}", {_hsl(_value(i, p))});'
                   for i in range(1, n + 1) for p in PROPS)
  props = "\n".join(f'props.AddAsLast("{p}");' for p in PROPS)
  by_well = "\n".join(f'ret.AddAsLast(LMSF_UTILITIES::SeqSetPropertyByWell("{lab}", "{pos}", ML_STAR.{PLATE}, '
                      f'"{p}", {_hsl(v)}));' for lab, pos, p, v in BY_WELL)
  src = (
    'namespace _Method { #include "HSLSeqLib.hsl" }\n'
    'namespace _Method { #include "Common\\\\LMSF_Utilities.hs_" }\n'
    'global device ML_STAR ("x.lay", "ML_STAR", hslTrue);\n'
    'variable props[];\nvariable ret[];\n'
    'namespace _Method { #include "HSLMECCLib.hs_" }\n'
    "namespace _Method { method main() void {\n"
    f"{sets}\n{props}\nML_STAR.{SHORT}.SetCurrentPosition(2);\n"
    f"LMSF_UTILITIES::SeqCopyPropsFromShortSeq(ML_STAR.{SHORT}, props, ML_STAR.{PLATE});\n{by_well}\n"
    "} }\n")
  here = NIST / "Methods" / "Common" / "port_test.hsl"
  pre = hsl_eval.Preprocessor([NIST / "Library", NIST / "Methods"], lambda p: p.read_text(encoding="latin-1"))
  text = pre.expand(here, text=src)
  parser = hsl_eval.Parser(hsl_eval.lex(text))
  parser.unit()
  run = hsl_eval.Run(parser, protocol.load_stps([]), {"x.lay": lay}, answers={})
  run.src = text.splitlines()
  run.run()
  assert run.stopped is None, run.stopped
  cells = [c.value for scope in run.globals.values() for c in scope.values()]
  dev = next(v for v in cells if isinstance(v, hsl_eval.Device))
  ret = next(v for scope in run.globals.values() for k, c in scope.items() if k.lower() == "ret"
             for v in [c.value])
  return dev.sequences[SHORT.lower()], dev.sequences[PLATE.lower()], [hsl_eval._num(x) for x in ret.items]


def _hsl(v):
  return f'"{v}"' if isinstance(v, str) else str(v)


class _Deck:
  def __init__(self, lay):
    self.live = {s.name: sq.Sequence(s.name, list(s.items)) for s in lay.sequences}

  def seq(self, name):
    return self.live[name]


def port_state(lay):
  from venus_interop.plr.libraries.lmsf_utilities import LmsfUtilities

  deck = _Deck(lay)
  short = deck.seq(SHORT)
  for i in range(1, short.total + 1):
    for p in PROPS:
      short.set_property(i, p, _value(i, p))
  short.set_current_position(2)
  u = LmsfUtilities(deck)
  u.SeqCopyPropsFromShortSeq(SHORT, PROPS, PLATE)
  ret = [u.SeqSetPropertyByWell(lab, pos, PLATE, p, v) for lab, pos, p, v in BY_WELL]
  return short, deck.seq(PLATE), ret


def test_covers_what_it_calls():
  assert COVERS == ["SeqCopyPropsFromShortSeq", "SeqSetPropertyByWell"]


def test_port_sets_the_properties_the_library_does(lay):
  (h_short, h_plate, h_ret), (p_short, p_plate, p_ret) = hsl_state(lay), port_state(lay)
  assert h_plate.properties and h_plate.properties == p_plate.properties
  assert h_ret == p_ret and h_ret[-1] == 0
  for a, b in ((h_short, p_short), (h_plate, p_plate)):
    assert (a.cur, a.end, a.max) == (b.cur, b.end, b.max)
