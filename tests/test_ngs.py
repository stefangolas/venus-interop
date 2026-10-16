"""The NGS STAR layouts: lossless conversion, and the capture log on each. Needs VENUS_INTEROP_NGS
(an NGS-Protocols checkout) and pylabrobot."""
import json
import os
import pathlib

import pytest

pytest.importorskip("pylabrobot")

from pylabrobot.resources import Deck  # noqa: E402

from venus_interop.files import layout  # noqa: E402
from venus_interop.plr import plr_export, plr_import  # noqa: E402

NGS = pathlib.Path(os.environ["VENUS_INTEROP_NGS"]) if os.environ.get("VENUS_INTEROP_NGS") else None
LAYOUTS = sorted(NGS.rglob("*.lay")) if NGS else []


@pytest.fixture(scope="module")
def store_for():
  import capture_log  # tools/

  kits = [pathlib.Path(dp, d) for base in (NGS, pathlib.Path(r"C:\Program Files (x86)\HAMILTON\NGSStar"))
          if base.exists() for dp, ds, _ in os.walk(base) for d in ds if d.lower() == "labware"]
  return lambda lp: capture_log.store_for(lp, [], kits)


@pytest.mark.skipif(NGS is None, reason="VENUS_INTEROP_NGS not set")
@pytest.mark.parametrize("path", LAYOUTS, ids=lambda p: p.name)
def test_ngs_layout_round_trip_and_capture(path, store_for):
  data = path.read_bytes()
  store = store_for(path)
  deck = plr_import.lay_to_plr(layout.read_layout(data), store)
  back = Deck.deserialize(json.loads(json.dumps(deck.serialize())))
  assert layout.write_layout(plr_export.plr_to_lay(back, store)) == data
  cap = deck.metadata["venus"]["capture"]
  assert cap["summary"]["labware"] >= 80
  assert all({"labware", "field", "text"} <= set(i) for i in cap["items"])
