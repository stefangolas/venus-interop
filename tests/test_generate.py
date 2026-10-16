"""Generating PLR resources and models from Venus definitions. Needs pylabrobot and trimesh."""
import importlib.util
import math

import pytest

pytest.importorskip("pylabrobot")
trimesh = pytest.importorskip("trimesh")

from venus_interop.plr import generate, name_match  # noqa: E402
from venus_interop.files.definitions import Definition, DefinitionStore, Rack  # noqa: E402


def store_with(**defs) -> DefinitionStore:
  s = DefinitionStore()
  for rel, d in defs.items():
    s.add(rel, d)
  return s


# Hamilton 1.2 mL deep-well plate, as Venus defines it (ham_dw_12_ml.rck / ham_12_ml.ctr)
CTR = Definition("hamilton/ham_12_ml.ctr", "CONTAINER", {
  "Depth": "36.8", "Dim.Dx": "6.9", "Dim.Dy": "6.9",
  "1.Shape": "3", "1.DX": "6.9", "1.DY": "6.4", "1.Min": "0.8", "1.Max": "36.8", "1.EqnOfVol": "h*34.7486",
  "2.Shape": "4", "2.DZ": "6.4", "2.Min": "0", "2.Max": "0.8", "2.EqnOfVol": "h*h*(10.0531 - 1.0472*h)",
})
RCK = Rack("hamilton/ham_dw_12_ml.rck", "RECTRACK", {
  "Rows": "8", "Columns": "12", "Dx": "9", "Dy": "9", "BndryX": "14", "BndryY": "11.5",
  "Dim.Dx": "127", "Dim.Dy": "86", "Dim.Dz": "41", "IX.Index": "1", "IX.Inc": "0",
  "Cntr.1.file": "HAMILTON\\ham_12_ml.ctr", "Cntr.1.base": "3.6",
})


def build(spec):
  src = generate.HEADER + generate.emit(spec)
  mod = type(importlib)("generated")
  exec(compile(src, "<generated>", "exec"), mod.__dict__)  # noqa: S102 - our own generated source
  return getattr(mod, spec.name)("p")


def test_container_segments_and_volume():
  c = generate.container(CTR)
  assert [s.shape for s in c.segments] == [4, 3]  # bottom first
  assert c.bottom == "U"
  cap = math.pi * 0.8 ** 2 * (3.2 - 0.8 / 3)  # spherical cap of radius 3.2, 0.8 deep
  assert c.volume(0.8) == pytest.approx(cap, rel=1e-3)
  assert c.max_volume == pytest.approx(cap + 36 * 34.7486, rel=1e-3)


def test_plate_spec_snaps_to_sbs_and_keeps_positions_centred():
  spec = generate.spec_for(RCK, store_with(**{"HAMILTON\\ham_12_ml.ctr": CTR}))
  assert spec.kind == "plate" and spec.size[:2] == generate.SBS
  # A1 is 14 / 74.5 from the corner of a 127 x 86 plate: the same offset from the centre on SBS
  a1 = next(p for p in spec.positions if p[0] == "A1")
  assert (a1[1] - 127.76 / 2, a1[2] - 85.48 / 2) == pytest.approx((14 - 63.5, 74.5 - 43))


def test_generated_plate_builds_and_matches_venus_fingerprint():
  store = store_with(**{"HAMILTON\\ham_12_ml.ctr": CTR})
  plate = build(generate.spec_for(RCK, store))
  venus = name_match.venus_fingerprint(RCK, store)
  mine = name_match.fingerprint(plate)
  assert mine.count == 96
  assert name_match._rms(venus.positions, mine.positions) < 1e-6
  well = plate.get_item("A1")
  assert well.get_absolute_location(z="b").z == pytest.approx(3.6)
  assert well.compute_height_from_volume(well.compute_volume_from_height(20)) == pytest.approx(20, abs=1e-6)


def test_model_has_every_well_cut_out():
  spec = generate.spec_for(RCK, store_with(**{"HAMILTON\\ham_12_ml.ctr": CTR}))
  scene, info = generate.model_for(spec)
  mesh = trimesh.util.concatenate(list(scene.geometry.values()))
  assert mesh.is_watertight
  assert mesh.bounds[1] * 1000 == pytest.approx((127.76, 85.48, 41), abs=1e-3)  # manifold3d is float32
  # a horizontal section halfway down the wells: the outline plus one hole per well
  section = mesh.section(plane_origin=(0, 0, 0.0036 + 0.018), plane_normal=(0, 0, 1))
  assert len(section.to_planar()[0].polygons_full[0].interiors) == 96
  assert info["kind"] == "generated" and info["source"] == RCK.path


def test_trough_and_tip_rack_kinds():
  trough = Rack("x/trough.rck", "RECTRACK", {**RCK.fields, "ConnectedCtr": "1"})
  assert generate.spec_for(trough, store_with(**{"HAMILTON\\ham_12_ml.ctr": CTR})).kind == "trough"
  tips = Rack("ml_star/stf_l.rck", "RECTRACK", {
    **RCK.fields, "Property.1": "MlStarTipRack", "PropertyValue.1": "1",
    "Property.2": "managedSequenceName", "PropertyValue.2": "MlStar300ulStandardVolumeTipWithFilter"})
  spec = generate.spec_for(tips, store_with(**{"HAMILTON\\ham_12_ml.ctr": CTR}))
  assert (spec.kind, spec.tip_creator, spec.tip_filter) == ("tip_rack", "hamilton_tip_300uL_filter", True)
