"""T3: LAY -> PLR -> (JSON) -> LAY. Needs pylabrobot; skipped without it."""
import json
import logging

import pytest

pytest.importorskip("pylabrobot")

from pylabrobot.resources import Coordinate, Deck, ItemizedResource, Plate  # noqa: E402

from conftest import LAYOUTS, corpus_params  # noqa: E402
from venus_interop.files import hxcfg  # noqa: E402
from venus_interop.plr import plr_export, plr_import
from venus_interop.files.definitions import Carrier, DefinitionStore, Rack  # noqa: E402
from venus_interop.files.layout import Layout, read_layout, write_layout  # noqa: E402

logging.getLogger("pylabrobot").setLevel(logging.ERROR)


def through_json(deck):
  return Deck.deserialize(json.loads(json.dumps(deck.serialize())))


# ------------------------------------------------------------------------------ synthetic


def tiny():
  store = DefinitionStore()
  store.add("ML_STAR\\CAR.tml", Carrier("ml_star/car.tml", "TEMPLATE", {
    "Dim.Dx": "135", "Dim.Dy": "497", "Dim.Dz": "130",
    **{f"Site.{i}.{k}": v for i in range(1, 3) for k, v in
       {"Id": str(i), "X": "4", "Y": str(8.5 + 96 * (2 - i)), "Z": "86.15", "Dx": "127", "Dy": "86"}.items()},
  }))
  store.add("ML_STAR\\PLATE.rck", Rack("ml_star/plate.rck", "RECTRACK", {
    "Rows": "8", "Columns": "12", "Dx": "9", "Dy": "9", "BndryX": "14.38", "BndryY": "11.24",
    "Dim.Dx": "127.76", "Dim.Dy": "85.48", "Dim.Dz": "14.2", "IX.Index": "1", "IX.Inc": "0",
  }))
  plate_tform = (100 + 4 + 14.38, 63 + 8.5 + 96 + 11.24 + 7 * 9)  # carrier + site 1 + A1 offset
  entries = {
    "Deck": "ML_STAR2.dck", "Labware.Cnt": "2", "Seq.Cnt": "0",
    "Labware.1.Id": "car", "Labware.1.File": "ML_STAR\\CAR.tml", "Labware.1.Template": "default",
    "Labware.1.SiteId": "6T-1", "Labware.1.TForm.3.X": "100", "Labware.1.TForm.3.Y": "63",
    "Labware.1.ZTrans": "100",
    "Labware.2.Id": "plate", "Labware.2.File": "ML_STAR\\PLATE.rck", "Labware.2.Template": "car",
    "Labware.2.SiteId": "1", "Labware.2.TForm.3.X": repr(plate_tform[0]),
    "Labware.2.TForm.3.Y": repr(plate_tform[1]), "Labware.2.ZTrans": "186.15",
  }
  cfg = hxcfg.CfgFile(sections=[hxcfg.Section("DECKLAY", 5, "ML_STAR", entries=sorted(entries.items()))])
  return Layout.from_cfg(cfg), store, plate_tform


def test_tiny_geometry():
  lay, store, (ax, ay) = tiny()
  deck = plr_import.lay_to_plr(lay, store)
  plate = deck.get_resource("plate")
  assert isinstance(plate, Plate)
  a1 = plate.get_item("A1").get_absolute_location(x="c", y="c")
  assert (a1.x, a1.y, a1.z) == pytest.approx((ax, ay, 186.15))
  assert plate.parent.name == "car_site_1"


def test_a_rack_listing_its_positions_gets_a_well_at_each():
  # rgt_cont_60ml_BC_A00.rck: no Rows/Columns, eight positions listed from the first's centre
  # (BndryX/Y), a gap between 4 and 5; no container file here, so the wells take the pitch
  ys = [0, -9, -18, -27, -41.5, -50.5, -59.5, -68.5]
  rack = Rack("ml_star/reagent/trough.rck", "RECTRACK", {
    "BndryX": "10", "BndryY": "79.25", "Dim.Dx": "20", "Dim.Dy": "89.9", "Dim.Dz": "65", "HoleCnt": "8",
    "ConnectedCtr": "1", **{f"{i + 1}.{k}": str(v) for i, y in enumerate(ys) for k, v in (("ID", i + 1), ("X", 0), ("Y", y))}})
  plate = plr_import.build_rack("trough", rack, DefinitionStore())
  assert isinstance(plate, Plate) and plate.num_items == 8
  centres = [plate.get_item(i).get_location_wrt(plate, "c", "c") for i in range(8)]
  assert [(round(c.x, 4), round(c.y, 4)) for c in centres] == [(10.0, 79.25 + y) for y in ys]
  assert [w.name for w in plate.get_all_items()] == [f"trough_well_{r}1" for r in "ABCDEFGH"]
  # a tip rack listing its positions (the CO-RE grip tools) stays a box
  tools = Rack("ml_star/tools.rck", "RECTRACK", {**rack.fields, "Property.1": "MlStarTipRack", "PropertyValue.1": "14"})
  assert not isinstance(plr_import.build_rack("tools", tools, DefinitionStore()), ItemizedResource)


def test_tiny_round_trip_is_identical():
  lay, store, _ = tiny()
  data = write_layout(lay)
  assert write_layout(plr_export.plr_to_lay(through_json(plr_import.lay_to_plr(lay, store)), store)) == data


def test_moving_a_carrier_moves_its_plates():
  lay, store, (ax, ay) = tiny()
  deck = plr_import.lay_to_plr(lay, store)
  car = deck.get_resource("car")
  car.location = car.location + Coordinate(22.5, 0, 0)  # one track right
  out = plr_export.plr_to_lay(through_json(deck), store).by_id()
  assert out["car"].tform[:2] == pytest.approx((122.5, 63))
  assert out["plate"].tform[:2] == pytest.approx((ax + 22.5, ay))
  assert out["car"].fields["TForm.3.X"] == "122.5"


def test_resource_added_in_plr_is_reported():
  lay, store, _ = tiny()
  deck = plr_import.lay_to_plr(lay, store)
  from pylabrobot.resources import Resource
  deck.assign_child_resource(Resource("new", 10, 10, 10), location=Coordinate(600, 100, 100))
  with pytest.raises(plr_export.UnmappedResources):
    plr_export.plr_to_lay(deck, store)


# ------------------------------------------------------------------------------ corpus


def _import(path, store):
  lay = read_layout(path)
  try:
    return lay, plr_import.lay_to_plr(lay, store)
  except plr_import.UnsupportedLayout as e:
    pytest.skip(str(e))


@pytest.mark.parametrize("path", corpus_params(LAYOUTS))
def test_t3_lay_plr_json_lay_is_identical(path, store):
  _, deck = _import(path, store)
  assert write_layout(plr_export.plr_to_lay(through_json(deck), store)) == path.read_bytes()


@pytest.mark.parametrize("path", corpus_params(LAYOUTS))
def test_t3_plr_a1_matches_venus(path, store):
  """Independent of the raw fields: PLR's A1 centre, built from the definitions, equals Venus's TForm.3."""
  lay, deck = _import(path, store)
  for p in lay.labware:
    r = deck.get_resource(p.id)
    if p.angle == 0 and isinstance(r, ItemizedResource):
      a1 = r.get_item("A1").get_absolute_location(x="c", y="c")
      assert (a1.x, a1.y) == pytest.approx(p.tform[:2], abs=1e-3), p.id


@pytest.mark.parametrize("path", corpus_params(LAYOUTS))
def test_t3_moving_every_carrier_shifts_its_tree(path, store):
  lay, deck = _import(path, store)
  moved = {r.name for r in deck.children if isinstance(r, plr_import.Carrier)}
  for name in moved:
    r = deck.get_resource(name)
    r.location = r.location + Coordinate(0, 1.5, 0)
  shifted = {d.name for name in moved for d in deck.get_resource(name).get_all_children()} | moved
  before = lay.by_id()
  after = plr_export.plr_to_lay(through_json(deck), store).by_id()
  for lid, p in after.items():
    dy = 1.5 if lid in shifted else 0
    assert p.tform[1] == pytest.approx(before[lid].tform[1] + dy, abs=2e-4), lid
