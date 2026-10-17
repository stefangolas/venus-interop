"""The GSF-IMS shared submethods: the Python port against the HSL library itself.

Both run the same calls on the Marionette layout's sequences: the library in the HSL interpreter
(its device steps resolved through the library's .stp records), the port with its PLR channel
calls recorded. Every step must use the same (labware, position) on every channel.

Needs VENUS_INTEROP_NIST (the NIST lmsf_hamilton repository copy), VENUS_INTEROP_CORPUS (for the
layout, 3ed5809e547e.lay, and labware definitions) and a pylabrobot with the STAR driver's
`lld_mode` (the PLR fork's venus-plr branch).
"""
import asyncio
import os
import pathlib

import pytest

pytest.importorskip("pylabrobot.hamilton.star.driver.lld_mode")

from venus_interop.files import layout  # noqa: E402
from venus_interop.files.definitions import DEFAULT_VENUS_LABWARE, DefinitionStore  # noqa: E402
from venus_interop.methods import hsl_eval, protocol, sequences as sq  # noqa: E402

NIST = pathlib.Path(os.environ["VENUS_INTEROP_NIST"]) if os.environ.get("VENUS_INTEROP_NIST") else None
CORPUS = pathlib.Path(os.environ["VENUS_INTEROP_CORPUS"]) if os.environ.get("VENUS_INTEROP_CORPUS") else None
pytestmark = pytest.mark.skipif(NIST is None or CORPUS is None,
                                reason="VENUS_INTEROP_NIST and VENUS_INTEROP_CORPUS not set")

# What this test checks against the HSL (read by tools/trace_method.py --status)
LIBRARY = "GSF_IMS_SHARED_SUBMETHODS"
COVERS = ["add_reagent_replace_tips", "add_reagent_reuse_tips", "add_reagents_reuse_tips_vol_arr",
          "pipette_cells_from_tubes", "pipette_dil_series", "pipette_media", "pipette_media_volume_arr",
          "simple_aspirate", "simple_dispense", "tip_eject", "tip_pickup"]
ARRAYS = {"VOLS4": [10, 0, 30, 40], "VOLS4B": [15, 25, 35, 45]}
# (function, arguments as the HSL call writes them, as the port takes them)
CALLS = [
  ("tip_pickup", "ML_STAR.Tips_1000_Channels, 4", ("Tips_1000_Channels", 4)),
  ("pipette_media", "ML_STAR.Media_pipette_from_4, ML_STAR.regular_wells_with_tmp_sal_grad, 100, 1, ML_STAR.Tips_1000_Channels, 4",
   ("Media_pipette_from_4", "regular_wells_with_tmp_sal_grad", 100, 1, "Tips_1000_Channels", 4)),
  ("pipette_media", "ML_STAR.Media_pipette_from_4, ML_STAR.sal_1_grad_start, 120, 0, ML_STAR.Tips_1000_Channels, 4",
   ("Media_pipette_from_4", "sal_1_grad_start", 120, 0, "Tips_1000_Channels", 4)),
  ("tip_eject", "4", (4,)),
  ("add_reagent_reuse_tips", "ML_STAR.Sal_stock_1_4, ML_STAR.sal_1_grad_start, 20, 1, 1, ML_STAR.Tips_300_Channels, 4",
   ("Sal_stock_1_4", "sal_1_grad_start", 20, 1, 1, "Tips_300_Channels", 4)),
  ("add_reagent_replace_tips", "ML_STAR.Sal_stock_1_4, ML_STAR.regular_wells_with_sal_1, 20, 2, 50, ML_STAR.Tips_300_Channels, 4",
   ("Sal_stock_1_4", "regular_wells_with_sal_1", 20, 2, 50, "Tips_300_Channels", 4)),
  ("pipette_dil_series", "ML_STAR.van_gradient_pipette_from, ML_STAR.van_gradient_pipette_to, 200, 2, 200, ML_STAR.Tips_1000_Channels, 8",
   ("van_gradient_pipette_from", "van_gradient_pipette_to", 200, 2, 200, "Tips_1000_Channels", 8)),
  ("pipette_cells_from_tubes", "ML_STAR.Van_stock_1, ML_STAR.Bacteria_dispense, 50, 3, 100, ML_STAR.Tips_1000_Channels, 8",
   ("Van_stock_1", "Bacteria_dispense", 50, 3, 100, "Tips_1000_Channels", 8)),
  ("tip_pickup", "ML_STAR.Tips_300_Channels, 4", ("Tips_300_Channels", 4)),
  ("add_reagents_reuse_tips_vol_arr", "ML_STAR.Sal_stock_2_4, ML_STAR.regular_wells_with_sal_2, VOLS4, 1, 0, ML_STAR.Tips_300_Channels, 4",
   ("Sal_stock_2_4", "regular_wells_with_sal_2", ARRAYS["VOLS4"], 1, 0, "Tips_300_Channels", 4)),
  ("pipette_media_volume_arr", "ML_STAR.Media_pipette_from_4, ML_STAR.regular_wells_with_sal_1, VOLS4B, 1, ML_STAR.Tips_300_Channels, 4",
   ("Media_pipette_from_4", "regular_wells_with_sal_1", ARRAYS["VOLS4B"], 1, "Tips_300_Channels", 4)),
  ("simple_aspirate", "ML_STAR.Sal_stock_2_4, 1, 20, ML_STAR.Tips_300_Channels, 4", ("Sal_stock_2_4", 1, 20, "Tips_300_Channels", 4)),
  ("simple_dispense", "ML_STAR.regular_wells_with_sal_2, 0, 1, 20, 0, 0, 4", ("regular_wells_with_sal_2", 0, 1, 20, 0, 0, 4)),
  ("simple_dispense", "ML_STAR.regular_wells_with_sal_2, 1, 0, 20, 0, 0, 4", ("regular_wells_with_sal_2", 1, 0, 20, 0, 0, 4)),
  ("tip_eject", "4", (4,)),
]


@pytest.fixture(scope="module")
def lay():
  return layout.read_layout(CORPUS / "raw" / "3ed5809e547e.lay")


def hsl_steps(lay):
  from venus_interop.plr.venus_deck import corpus_index

  nl = "\n"
  decls = nl.join(f"variable {k}[];" for k in ARRAYS)
  setup = nl.join(f"{k}.SetSize(0);" + "".join(f" {k}.AddAsLast({v});" for v in vs) for k, vs in ARRAYS.items())
  calls = nl.join(f"GSF_IMS_SHARED_SUBMETHODS::{fn}({a}, ML_STAR);" for fn, a, _ in CALLS)
  src = (
    'namespace _Method { #include "HSLSeqLib.hsl" }\n'
    'namespace _Method { #include "HSLStrLib.hsl" }\n'
    'namespace _Method { #include "HSLTrcLib.hsl" }\n'
    'namespace _Method { #include "Common\\\\LMSF_Utilities.hs_" }\n'
    'namespace _Method { #include "GSF-IMS Project\\\\GSF-IMS.shared_submethods.hs_" }\n'
    'global device ML_STAR ("x.lay", "ML_STAR", hslTrue);\n'
    f"{decls}\n"
    'namespace _Method { #include "HSLMECCLib.hs_" }\n'
    f"namespace _Method {{ method main() void {{\n{setup}\n{calls}\n}} }}\n")
  here = NIST / "Methods" / "GSF-IMS Project" / "port_test.hsl"
  roots = [NIST / "Library", NIST / "Methods"]
  stps = protocol.load_stps(sorted(here.parent.glob("*.stp")))
  pre = hsl_eval.Preprocessor(roots, lambda p: p.read_text(encoding="latin-1"))
  text = pre.expand(here, text=src)
  parser = hsl_eval.Parser(hsl_eval.lex(text))
  parser.unit()
  store = DefinitionStore([DEFAULT_VENUS_LABWARE], corpus_index(CORPUS))
  by_id = lay.by_id()

  def labware_data(lab, key):
    d = store.get(by_id[lab].file) if lab in by_id else None
    return getattr(d, "properties", {}).get(key) if d is not None else None

  run = hsl_eval.Run(parser, stps, {"x.lay": lay}, answers={"labware_data": labware_data})
  run.src = text.splitlines()
  run.run()
  assert run.stopped is None, run.stopped
  return [(e.command, e.channels) for e in run.events]


class _Deck:
  def __init__(self, lay):
    self.items = {s.name: list(s.items) for s in lay.sequences}
    self.live = {}

  def seq(self, name):
    if name not in self.live:
      self.live[name] = sq.Sequence(name, list(self.items[name]))
    return self.live[name]

  def resolve(self, item):
    return item


class _Channels:
  def __init__(self):
    self.events = []

  def _log(self, command, spots, channels):
    self.events.append((command, dict(zip([c + 1 for c in channels], spots))))

  async def pick_up_tips(self, spots, use_channels):
    self._log("TipPickUp", spots, use_channels)

  async def discard_tips(self, use_channels):
    self.events.append(("TipEject", {}))

  async def aspirate(self, wells, vols, use_channels, **kw):
    self._log("Aspirate", wells, use_channels)

  async def dispense(self, wells, vols, use_channels, **kw):
    self._log("Dispense", wells, use_channels)


def port_steps(lay):
  from venus_interop.plr.libraries import gsf_ims

  channels = _Channels()
  g = gsf_ims.GsfIms(type("Star", (), {"pipettes": channels})(), _Deck(lay))
  g._class = lambda tips: (gsf_ims.CLASS_BY_TIP[300 if "300" in tips else 1000], None)
  g._lc = lambda name: None

  async def go():
    for fn, _, args in CALLS:
      await getattr(g, fn)(*args)

  asyncio.run(go())
  return channels.events


def test_covers_what_it_calls():
  assert sorted(COVERS) == sorted({fn for fn, _, _ in CALLS})


def test_port_uses_the_wells_and_tips_the_library_does(lay):
  hsl, port = hsl_steps(lay), port_steps(lay)
  assert len(hsl) == len(port) == 111
  for i, (a, b) in enumerate(zip(hsl, port)):
    assert a == b, f"step {i}: library {a}, port {b}"
