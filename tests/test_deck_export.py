"""T4: decks built in PLR -> Venus layout -> PLR, and the second trip byte-identical."""
import json
import logging

import pytest

pytest.importorskip("pylabrobot")

from pylabrobot.resources import Deck, ItemizedResource  # noqa: E402
from pylabrobot.resources.corning.plates import cor_96_wellplate_2mL_Vb, cor_96_wellplate_360uL_Fb  # noqa: E402
from pylabrobot.resources.hamilton import STARDeck, STARLetDeck  # noqa: E402
from pylabrobot.resources.hamilton.plate_carriers import PLT_CAR_L5AC_A00  # noqa: E402
from pylabrobot.resources.hamilton.tip_carriers import TIP_CAR_480BC_A00  # noqa: E402
from pylabrobot.resources.hamilton.tip_racks import (  # noqa: E402
  hamilton_96_tiprack_1000uL_filter, hamilton_96_tiprack_300uL_filter)
from pylabrobot.resources.hamilton.trough_carriers import Trough_CAR_4R200_A00  # noqa: E402
from pylabrobot.resources.hamilton.troughs import hamilton_1_trough_200mL_Vb  # noqa: E402

from venus_interop.plr import deck_export, plr_import  # noqa: E402
from venus_interop.files import layout
from venus_interop.files.definitions import DEFAULT_VENUS_LABWARE, DefinitionStore  # noqa: E402

logging.getLogger("pylabrobot").setLevel(logging.ERROR)
needs_venus = pytest.mark.skipif(not DEFAULT_VENUS_LABWARE.is_dir(), reason="stock Hamilton files not installed")



def build(deck):
  tc = TIP_CAR_480BC_A00("tip_car")
  tc[0] = hamilton_96_tiprack_300uL_filter("tips_300")
  tc[1] = hamilton_96_tiprack_1000uL_filter("tips_1000")
  deck.assign_child_resource(tc, rails=1)
  pc = PLT_CAR_L5AC_A00("plate_car")
  pc[0] = cor_96_wellplate_360uL_Fb("assay_plate", with_lid=True)
  pc[2] = cor_96_wellplate_2mL_Vb("dwp")
  deck.assign_child_resource(pc, rails=8)
  trc = Trough_CAR_4R200_A00("trough_car")
  trc[1] = hamilton_1_trough_200mL_Vb("buffer")
  deck.assign_child_resource(trc, rails=15)
  return deck


LABWARE = ["tip_car", "plate_car", "trough_car", "tips_300", "tips_1000", "assay_plate", "assay_plate_lid", "dwp",
           "buffer"]


def round_trip(deck, tmp_path):
  ex = deck_export.export(deck, DefinitionStore([DEFAULT_VENUS_LABWARE]))
  ex.write(tmp_path / "deck.lay", tmp_path / "Labware")
  store = DefinitionStore([tmp_path / "Labware", DEFAULT_VENUS_LABWARE])
  back = plr_import.lay_to_plr(layout.read_layout(tmp_path / "deck.lay"), store)
  return ex, store, Deck.deserialize(json.loads(json.dumps(back.serialize())))


@needs_venus
@pytest.mark.parametrize("make_deck", [STARDeck, STARLetDeck])
def test_t4_plr_lay_plr(make_deck, tmp_path):
  deck = build(make_deck())
  ex, store, back = round_trip(deck, tmp_path)
  for name in LABWARE:
    a, b = deck.get_resource(name), back.get_resource(name)
    if isinstance(a, ItemizedResource):  # A1 well / tip spot, which is what pipetting uses
      pa, pb = a.get_item(0).get_absolute_location("c", "c", "b"), b.get_item(0).get_absolute_location("c", "c", "b")
    else:
      pa, pb = a.get_absolute_location(), b.get_absolute_location()
    assert (pb.x, pb.y) == pytest.approx((pa.x, pa.y), abs=1e-3), name
    assert pb.z == pytest.approx(pa.z, abs=1e-3), name
  by_id = ex.layout.by_id()
  # Hamilton's STF_L.rck differs from pylabrobot's rack (prefer="exact" writes our own); its carrier doesn't
  assert by_id["tips_300"].file.startswith("PLR\\") and by_id["tip_car"].file == r"ML_STAR\TIP_CAR_480.tml"
  assert by_id["tips_300"].file != by_id["tips_1000"].file  # same PLR model, different tips: different files
  assert (by_id["tips_300"].template, by_id["tips_300"].site_id, by_id["tips_300"].z_mode) == ("tip_car", "5", 1)
  assert by_id["plate_car"].site_id == "6T-8"
  assert ex.layout.sequence("assay_plate").items[:2] == [("assay_plate", "A1"), ("assay_plate", "B1")]
  assert ex.layout.sequence("tips_300").items[:2] == [("tips_300", "A1"), ("tips_300", "B1")]  # our files: A1 names
  waste = by_id["WasteBlock"]  # Venus's own waste block, from the template
  assert waste.tform[0] == (1318.0 if make_deck is STARDeck else 778.0)


@needs_venus
def test_t4_second_trip_is_byte_identical(tmp_path):
  ex, store, back = round_trip(build(STARDeck()), tmp_path)
  again = deck_export.export(back, store)
  assert layout.write_layout(again.layout, binary=True) == (tmp_path / "deck.lay").read_bytes()
  assert not again.files  # nothing new to write


def differences(deck, back, name):
  """(quantity, size) for every way `name` came back different, in absolute and rack terms."""
  from venus_interop.rules.deltas import TOL, rack_differences

  a, b = deck.get_resource(name), back.get_resource(name)
  out = [(q, size) for q, _, _, size in rack_differences(a, b, sinking=getattr(a, "sinking_depth", 0.0) or 0.0)]
  if isinstance(a, ItemizedResource):  # absolute: where the robot goes, not just the shape
    pa, pb = a.get_item(0).get_absolute_location("c", "c", "b"), b.get_item(0).get_absolute_location("c", "c", "b")
    if max(abs(pa.x - pb.x), abs(pa.y - pb.y)) > TOL:
      out.append(("A1 x/y", max(abs(pa.x - pb.x), abs(pa.y - pb.y))))
    dz = abs(pa.z - pb.z)
    # an absolute height change is explained only by a rack-level height difference of the same size
    if dz > TOL and not any(q in ("position z", "tip bottom") and abs(size - dz) < TOL for q, size in out):
      out.append(("A1 z", dz))
  return out


@needs_venus
@pytest.mark.parametrize("prefer", ["exact", "stock"])
def test_every_round_trip_difference_is_in_the_ledger(prefer, tmp_path):
  deck = build(STARDeck())
  ex = deck_export.export(deck, DefinitionStore([DEFAULT_VENUS_LABWARE]), prefer=prefer)
  ex.write(tmp_path / "deck.lay", tmp_path / "Labware")
  store = DefinitionStore([tmp_path / "Labware", DEFAULT_VENUS_LABWARE])
  back = plr_import.lay_to_plr(layout.read_layout(tmp_path / "deck.lay"), store)
  unexplained = []
  for name in ["tips_300", "tips_1000", "assay_plate", "dwp", "buffer"]:
    for quantity, size in differences(deck, back, name):
      if not any(d.resource == name and d.quantity == quantity and d.size is not None and abs(d.size - size) < 1e-3
                 for d in ex.deltas):
        unexplained.append((name, quantity, round(size, 4)))
  assert not unexplained, unexplained
  diffs = {name: differences(deck, back, name) for name in ["tips_300", "tips_1000", "assay_plate", "dwp", "buffer"]}
  if prefer == "exact":
    assert all(not v for v in diffs.values()), diffs
  else:  # the stock tip racks bring Venus's numbers back with them
    assert dict(diffs["tips_1000"])["tip bottom"] == pytest.approx(2.1, abs=0.01)
  # and the import recorded its interpretations
  kinds = {(d["resource"], d["quantity"]) for d in back.metadata["venus"]["deltas"]}
  assert ("tips_300", "tip spot height") in kinds
