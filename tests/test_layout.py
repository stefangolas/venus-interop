"""T1 for the layout model."""
import pytest

from conftest import LAYOUTS, corpus_params
from venus_interop.files import hxcfg
from venus_interop.files.layout import Layout, Placement, Sequence, fmt, read_layout, write_layout


def tiny_layout() -> Layout:
  entries = {
    "Deck": "ML_STAR2.dck",
    "Labware.Cnt": "2",
    "Labware.1.Id": "PLT_CAR_L5AC_A00_0001", "Labware.1.File": "ML_STAR\\PLT_CAR_L5AC_A00.tml",
    "Labware.1.Template": "default", "Labware.1.SiteId": "6T-1",
    "Labware.1.TForm.3.X": "100", "Labware.1.TForm.3.Y": "63", "Labware.1.ZTrans": "100",
    "Labware.2.Id": "plate", "Labware.2.File": "ML_STAR\\Cos_96_DW_1mL.rck",
    "Labware.2.Template": "PLT_CAR_L5AC_A00_0001", "Labware.2.SiteId": "1", "Labware.2.DefSeqValid": "1",
    "Seq.Cnt": "1", "Seq.1.Name": "plate", "Seq.1.Cnt": "2", "Seq.1.ReadOnly": "0",
    "Seq.1.Item.1.ObjId": "plate", "Seq.1.Item.1.PosId": "A1",
    "Seq.1.Item.2.ObjId": "plate", "Seq.1.Item.2.PosId": "B1",
    "dataVersion": "3",
  }
  cover = {"Labware.2.Id": "plate_lid", "Labware.2.File": "ML_STAR\\lid.lid"}
  cfg = hxcfg.CfgFile(sections=[
    hxcfg.Section("DECKLAY", 5, "ML_STAR", entries=sorted(entries.items())),
    hxcfg.Section("DECKLAY", 5, "ML_STAR_COVER", entries=sorted(cover.items())),
    hxcfg.Section("DEVICE", 2, "ML_STAR", entries=[("TYPE", "1")]),
  ])
  return Layout.from_cfg(cfg)


def test_parse_tiny():
  lay = tiny_layout()
  assert [p.id for p in lay.labware] == ["PLT_CAR_L5AC_A00_0001", "plate"]
  assert lay.labware[0].kind == "carrier" and lay.labware[1].kind == "rack"
  assert lay.labware[1].lid.id == "plate_lid"
  assert lay.sequence("plate").items == [("plate", "A1"), ("plate", "B1")]
  assert lay.layers is None
  assert lay.header == {"Deck": "ML_STAR2.dck", "dataVersion": "3"}


def test_tiny_round_trip():
  lay = tiny_layout()
  assert lay.to_cfg() == lay.cfg


def test_edit_renumbers_lids_with_their_plate():
  lay = tiny_layout()
  lay.labware.reverse()  # plate becomes Labware.1, so its lid must move to cover Labware.1
  cover = lay.to_cfg().section("DECKLAY", "ML_STAR_COVER").as_dict()
  assert cover == {"Labware.1.Id": "plate_lid", "Labware.1.File": "ML_STAR\\lid.lid"}


def test_add_placement_and_sequence():
  lay = tiny_layout()
  lay.labware.append(Placement({"Id": "tips", "File": "ML_STAR\\HT_L.rck", "Template": "default"}))
  lay.sequences.append(Sequence("tips", [("tips", "1")]))
  again = Layout.from_cfg(hxcfg.read(write_layout(lay)))
  assert again.by_id()["tips"].file == "ML_STAR\\HT_L.rck"
  assert again.sequence("tips").items == [("tips", "1")]


def test_fmt_matches_venus():
  assert [fmt(x) for x in (617.5, 63, 187.15, -47)] == ["617.5", "63", "187.15", "-47"]


@pytest.mark.parametrize("path", corpus_params(LAYOUTS))
def test_t1_layout_model_is_lossless(path):
  data = path.read_bytes()
  assert write_layout(read_layout(data)) == data
