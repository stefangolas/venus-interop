"""Generated visual cavities must line up with the protocol's positions and stay open."""
import json
from pathlib import Path

import pytest
np = pytest.importorskip('numpy')
trimesh = pytest.importorskip('trimesh')
pytest.importorskip('rtree')

MODELS = Path(__file__).resolve().parents[1] / 'models'
NAMES = ('fourtitude_4ti_0255', 'agilent_201250_100', 'agilent_204284_100',
         'fourtitude_growth_lid', 'agilent_201250_lid', 'agilent_6_column_lid',
         'core2_support_ht', 'core2_support_st', 'core2_support_50')


def asset(name):
  scene = trimesh.load(MODELS / (name+'.glb'), force='scene')
  mesh = scene.to_geometry()
  mesh.merge_vertices()  # GLB material/normal seams are not holes
  mesh.apply_scale(1000)
  return mesh, json.loads((MODELS / (name+'.geometry.json')).read_text())


@pytest.mark.parametrize('name', NAMES)
def test_closed_mesh_and_round_trip_bounds_match_ledger(name):
  mesh, info = asset(name)
  assert mesh.is_watertight and mesh.is_volume
  assert mesh.bounds[0] == pytest.approx([0,0,0], abs=1e-4)
  assert mesh.bounds[1] == pytest.approx(info['size_mm'], abs=1e-4)
  interpretation, units = info['deltas'][:2]
  assert interpretation['plr'] == info['choices']
  assert units['venus'] == 'mm' and units['plr'] == 'm'


@pytest.mark.parametrize('name', ('fourtitude_4ti_0255','core2_support_ht','core2_support_st','core2_support_50'))
def test_all_96_openings_are_clear_at_the_venus_centres(name):
  mesh, info = asset(name)
  assert len(info['positions_mm']) == 96
  probes = [(x,y,info['size_mm'][2]-.2) for x,y in info['positions_mm']]
  assert not mesh.contains(probes).any()
  # Between two neighbouring openings is actual material, not an invisible grid.
  x,y = info['positions_mm'][0]
  assert mesh.contains([[x+4.5,y,info['size_mm'][2]-.2]])[0]


@pytest.mark.parametrize('name,count', [('agilent_201250_100',4),('agilent_204284_100',14)])
def test_reservoir_has_one_or_six_cavities_not_a_well_per_pipetting_position(name,count):
  mesh, info = asset(name)
  hits, _, _ = mesh.ray.intersects_location([[-1,43.17,20]], [[1,0,0]])
  assert len(hits) == count  # two outer surfaces plus two walls per physical cavity
  assert not mesh.contains([(x,y,20) for x,y in info['positions_mm']]).any()


@pytest.mark.parametrize('name', NAMES[3:6])
def test_lid_is_open_underneath_and_closed_above(name):
  mesh, info = asset(name)
  sx,sy,sz = info['size_mm']
  assert not mesh.contains([[sx/2,sy/2,sz/2]])[0]
  assert mesh.contains([[sx/2,sy/2,sz-.5]])[0]
