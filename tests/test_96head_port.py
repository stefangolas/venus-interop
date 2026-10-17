"""NIST's Common96HeadSubMethods and culture-processing Move96HeadAndArm: the ports against the HSL.

Every entry point runs in both: the libraries in the HSL interpreter (their moves, firmware
commands and ejects recorded with their settings), the ports with their PLR calls recorded. Both
must make the same moves in the same order: the 96-head over the same sequence position, the arm
to the same X, the head to the same Z and Y, tips ejected to the same place.

Needs VENUS_INTEROP_NIST and VENUS_INTEROP_CORPUS (Marionette's layout, 3ed5809e547e.lay).
"""
import asyncio
import os
import pathlib

import pytest

from venus_interop.files import layout
from venus_interop.methods import hsl_eval, protocol, sequences as sq

NIST = pathlib.Path(os.environ["VENUS_INTEROP_NIST"]) if os.environ.get("VENUS_INTEROP_NIST") else None
CORPUS = pathlib.Path(os.environ["VENUS_INTEROP_CORPUS"]) if os.environ.get("VENUS_INTEROP_CORPUS") else None
pytestmark = pytest.mark.skipif(NIST is None or CORPUS is None,
                                reason="VENUS_INTEROP_NIST and VENUS_INTEROP_CORPUS not set")

# What this test checks against the HSL (read by tools/trace_method.py --status); the second
# library is listed in COVERS_ALSO
LIBRARY = "COMMON96HEADSUBMETHODS"
COVERS = ["Clear96HeadAndArm", "Eject96HeadTips", "Eject96HeadTipsAndShake", "Move96HeadToFront",
          "Move96HeadUp"]
CULTURE = "MOVE96HEADANDARM"
COVERS_ALSO = {"MOVE96HEADANDARM": ["Move96HeadAndArm", "Move96HeadToFront"]}

SEQ = "clear_96_head_seq"
# (library namespace, function, HSL arguments after ML_STAR, the port's arguments after ML_STAR)
CALLS = [
  (LIBRARY, "Move96HeadUp", f"ML_STAR.{SEQ}", (SEQ,)),
  (LIBRARY, "Move96HeadToFront", f"ML_STAR.{SEQ}", (SEQ,)),
  (LIBRARY, "Clear96HeadAndArm", f"ML_STAR.{SEQ}", (SEQ,)),
  (LIBRARY, "Eject96HeadTips", f"ML_STAR.{SEQ}", (SEQ,)),
  (LIBRARY, "Eject96HeadTipsAndShake", f"2, ML_STAR.{SEQ}", (2, SEQ)),
  (CULTURE, "Move96HeadToFront", "", ()),
  (CULTURE, "Move96HeadAndArm", "", ()),
]
Z_MM, Y_MM = 0.005, 0.015625  # PLR's 96-head drive resolutions, mm per increment


@pytest.fixture(scope="module")
def lay():
  return layout.read_layout(CORPUS / "raw" / "3ed5809e547e.lay")


def hsl_moves(lay):
  calls = "\n".join(f"{ns}::{fn}(ML_STAR{', ' + a if a else ''});" for ns, fn, a, _ in CALLS)
  src = (
    'namespace _Method { #include "HSLSeqLib.hsl" }\n'
    'namespace _Method { #include "Common\\\\Common96HeadSubMethods.hs_" }\n'
    'namespace _Method { #include "Culture processing\\\\Move96HeadAndArm.hs_" }\n'
    'global device ML_STAR ("x.lay", "ML_STAR", hslTrue);\n'
    'namespace _Method { #include "HSLMECCLib.hs_" }\n'
    f"namespace _Method {{ method main() void {{\n{calls}\n}} }}\n")
  here = NIST / "Library" / "port_test.hsl"
  stps = protocol.load_stps([NIST / "Library" / "Common" / "Common96HeadSubMethods.stp",
                             NIST / "Library" / "Culture processing" / "Move96HeadAndArm.stp"])
  pre = hsl_eval.Preprocessor([NIST / "Library", NIST / "Methods"], lambda p: p.read_text(encoding="latin-1"))
  text = pre.expand(here, text=src)
  parser = hsl_eval.Parser(hsl_eval.lex(text))
  parser.unit()
  run = hsl_eval.Run(parser, stps, {"x.lay": lay}, answers={})
  run.src = text.splitlines()
  run.run()
  assert run.stopped is None, run.stopped

  out = []
  for e in run.events:
    s = e.settings
    if e.command == "Head96Move":
      assert (s["MoveType"], s["MoveZEndMode"]) == (2, 0)  # to a sequence position, then max height
      out.append(("head over", e.channels[1]))
    elif e.command == "MoveToPosition":
      assert (s["MoveType"], s["MoveDirection"]) == (0, 0)  # absolute, X
      out.append(("arm x", s["MoveAbsDistance"]))
    elif e.command == "Head96TipEject":
      out.append(("eject", {2: "default waste"}[s["UsePickUpPosition"]]))
    elif e.command == "FirmwareCommand":
      cmd, par = s["firmware command string"], s["firmware parameter string"]
      scale = {"H0ZA": Z_MM, "H0YA": Y_MM}[cmd]
      out.append(({"H0ZA": "head z", "H0YA": "head y"}[cmd], round(int(par[2:]) * scale, 2)))
    else:
      out.append((e.command,))
  return out


class _Spot:
  """A sequence item standing in for its resource: its location's x is the item."""

  def __init__(self, item):
    self.x, self.y = item, 0

  def get_location_wrt(self, deck, *_):
    return self


class _Deck:
  deck = None

  def __init__(self, lay):
    self.items = {s.name: list(s.items) for s in lay.sequences}

  def seq(self, name):
    return sq.Sequence(name, list(self.items[name]))

  def resolve(self, item):
    return _Spot(item)


class _Star:
  def __init__(self):
    self.moves = []
    star = self

    class Config:
      z_drive_increments_to_mm = staticmethod(lambda n: round(n * Z_MM, 2))
      y_drive_increments_to_mm = staticmethod(lambda n: round(n * Y_MM, 2))

    class Head96:
      configuration = Config

      async def move_to_xy_position(self, x, _y):
        star.last = ("head over", x)

      async def move_to_safe_z(self):
        star.moves.append(star.last)  # the move to a position ends at max height

      async def discard_tips(self):
        star.moves.append(("eject", "default waste"))

      async def move_stop_disc_to_z_position(self, z):
        star.moves.append(("head z", z))

      async def move_to_y_position(self, y):
        star.moves.append(("head y", y))

    class Pipettes:
      async def move_to_x_position(self, x):
        star.moves.append(("arm x", x))

    self.head96, self.pipettes = Head96(), Pipettes()


def port_moves(lay):
  from venus_interop.plr.libraries.common_96head import Common96HeadSubMethods
  from venus_interop.plr.libraries.move_96head_and_arm import Move96HeadAndArm

  star = _Star()
  ports = {LIBRARY: Common96HeadSubMethods(star, _Deck(lay), say=lambda _: None),
           CULTURE: Move96HeadAndArm(star)}

  async def go():
    for ns, fn, _, args in CALLS:
      await getattr(ports[ns], fn)(None, *args)

  asyncio.run(go())
  return star.moves


def test_covers_what_it_calls():
  assert sorted(COVERS) == sorted(fn for ns, fn, _, _ in CALLS if ns == LIBRARY)
  assert sorted(COVERS_ALSO[CULTURE]) == sorted(fn for ns, fn, _, _ in CALLS if ns == CULTURE)


def test_ports_move_as_the_libraries_do(lay):
  hsl, port = hsl_moves(lay), port_moves(lay)
  assert hsl == port
  assert len(hsl) == 13
