"""T2: the measured rules, as unit tests and as regression tests over the corpus."""
import json
import pathlib

import pytest

from conftest import LAYOUTS, corpus_params
from venus_interop.rules import placement as rules
from venus_interop.files.definitions import Lid, Rack
from venus_interop.files.layout import read_layout

KNOWN = pathlib.Path(__file__).with_name("known_exceptions.json")


def rack(**fields) -> Rack:
  return Rack("test.rck", "RECTRACK", {k.replace("_", "."): str(v) for k, v in fields.items()})


PLATE_96 = rack(Rows=8, Columns=12, Dx=9, Dy=9, BndryX=14.38, BndryY=11.24, Dim_Dx=127.76, Dim_Dy=85.48,
                StackHt=14.5, IX_Index=1)


def test_rails():
  assert rules.parse_rail("6T-24") == 24
  assert rules.parse_rail("6T-M3") == -3
  assert rules.parse_rail("1") is None
  assert rules.rail_location(24) == (617.5, 63.0, 100.0)
  assert rules.rail_site_id(6, -3) == "6T-M3"


def test_a1_offset_uses_back_row():
  x, y = rules.a1_offset(PLATE_96)
  assert (x, round(y, 2)) == (14.38, 74.24)  # BndryY + 7 * Dy
  assert rules.rack_corner(rules.rack_tform((10, 20), PLATE_96), PLATE_96) == pytest.approx((10, 20))


def test_a1_offset_without_rows():
  trough = rack(BndryX=5, BndryY=7, Dy=9)
  assert rules.a1_offset(trough) == (5, 7)


def test_lid_centred():
  lid = Lid("l.lid", "COVER", {"Dim.Dx": "127", "Dim.Dy": "85"})
  assert rules.lid_corner((0, 0), PLATE_96, lid) == pytest.approx((0.38, 0.24))


def test_stack_z():
  assert rules.stack_z(100, [PLATE_96, PLATE_96, PLATE_96]) == [100, 114.5, 129]


def test_row_names():
  assert [rules.row_name(r) for r in (1, 8, 16, 26, 27, 32)] == ["A", "H", "P", "Z", "AA", "AF"]


def test_default_positions():
  assert rules.default_positions(PLATE_96)[:3] == ["A1", "B1", "C1"]
  assert rules.default_positions(PLATE_96)[8] == "A2"
  down_columns = rack(Rows=8, Columns=12, IX_Index=0, IX_Inc=1)  # e.g. HTF_L tip racks
  assert rules.default_positions(down_columns)[:3] == ["1", "2", "3"]
  assert rules.default_positions(down_columns)[8] == "9"
  across_rows = rack(Rows=8, Columns=12, IX_Index=0, IX_Inc=0)  # e.g. Nunc 1.3 ml plates
  assert rules.default_positions(across_rows)[:3] == ["1", "13", "25"]
  portrait = rack(Rows=12, Columns=8, IX_Index=1, IX_Inc=1, IX_Start=1)  # ans_96_c18_spe
  assert rules.default_positions(portrait)[:9] == ["A1", "B1", "C1", "D1", "E1", "F1", "G1", "H1", "A2"]
  assert rules.naming_confidence(portrait) == "single example"  # measured in Venus: one rack
  assert rules.naming_confidence(rack(Rows=12, Columns=8, IX_Index=1, IX_Inc=1, IX_Start=2)) == "unverified"
  assert rules.naming_confidence(across_rows) == "validated"
  with pytest.raises(rules.UnsupportedNaming):
    rules.default_positions(rack(Rows=8, Columns=12, IX_Index=1, IX_Inc=0, IX_First=0))
  assert rules.default_positions(rack(HoleCnt=3)) == ["1", "2", "3"]
  assert len(rules.default_positions(rack(Rows=16, Columns=24, IX_Index=1))) == 384


# ------------------------------------------------------------------------------ corpus


def current_failures(path, store) -> dict[str, list[str]]:
  rep = rules.rule_report(read_layout(path), store)
  return {r: sorted(lid for lid, _ in res.failures) for r, res in rep.items() if res.failures}


@pytest.mark.parametrize("path", corpus_params(LAYOUTS))
def test_t2_rules_hold_except_known(path, store):
  """Every failure must be listed in known_exceptions.json (regenerate with tools/known_exceptions.py)."""
  known = json.loads(KNOWN.read_text()).get(path.name, {}) if KNOWN.exists() else {}
  for rule, ids in current_failures(path, store).items():
    new = sorted(set(ids) - set(known.get(rule, [])))
    assert not new, f"{rule}: new failures {new}"


@pytest.mark.parametrize("path", corpus_params(LAYOUTS))
def test_t2_every_stored_position_name_is_valid(path, store):
  rep = rules.rule_report(read_layout(path), store)
  assert rep["sequence_names"].failures == []
  assert rep["carrier_on_rail"].failures == []
