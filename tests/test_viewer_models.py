"""Viewer assets must not move protocol labware or duplicate MultiFlex assemblies."""
import json
import pathlib
import struct
import sys

import pytest

pytest.importorskip('pylabrobot')
from venus_interop.plr import viewer_models  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'examples'))
from mpe2_model import attach_visual, SEAT  # noqa: E402


def test_star_base_translation_preserves_compressed_geometry():
  from pylabrobot.hamilton.star import device
  source = (pathlib.Path(device.__file__).parent / 'resource_model/star_base.glb').read_bytes()
  converted = (viewer_models.MODELS / 'star_base_deck_frame.glb').read_bytes()
  source_size = struct.unpack_from('<I', source, 12)[0]
  converted_size = struct.unpack_from('<I', converted, 12)[0]
  before = json.loads(source[20:20 + source_size])
  after = json.loads(converted[20:20 + converted_size])
  assert source[20 + source_size:] == converted[20 + converted_size:]
  assert after['nodes'][:len(before['nodes'])] == before['nodes']
  origin = device.STAR_DECK_LOCATION
  expected = [-origin.x / 1000, -origin.y / 1000, -origin.z / 1000]
  ledger = json.loads((viewer_models.MODELS / 'star_base_deck_frame.geometry.json').read_text())
  assert ledger['deltas'][0]['plr'] == expected
  assert after['meshes'][0]['primitives'] == [
    before['meshes'][0]['primitives'][i] for i in ledger['retained_primitives']]
  for i, scene in enumerate(after['scenes']):
    wrapper = after['nodes'][scene['nodes'][0]]
    assert wrapper['translation'] == expected
    assert wrapper['children'] == before['scenes'][i]['nodes']


def test_converted_bounds_round_trip_matches_ledger():
  trimesh = pytest.importorskip('trimesh')
  np = pytest.importorskip('numpy')
  paths = list(viewer_models.MODELS.glob('MFX_CAR_*.geometry.json'))
  paths.append(viewer_models.MODELS / 'Culture_Processing_STAR_MPE2_Base_Back.geometry.json')
  paths.append(viewer_models.MODELS / 'rgt_cont_60ml_BC_A00.geometry.json')
  paths.extend(viewer_models.MODELS / (name + '.geometry.json') for name in
               ('WasteBlock', 'Verification', 'TeachingNeedle5ml', 'TeachingNeedleBlock', 'core96SlideWasteRack'))
  assert len(paths) == 13
  for path in paths:
    info = json.loads(path.read_text())
    scene = trimesh.load(path.with_suffix('').with_suffix('.glb'), force='scene')
    source = np.array(info['source_bounds_mm'])
    origin, units = info['deltas']
    assert origin['kind'] == 'interpretation' and units['kind'] == 'convention'
    translation = np.array(origin['plr']) - np.array(origin['venus'])
    # Every change in the round-tripped bounds is the ledger's translation and unit conversion.
    assert scene.bounds / info['scale'] - translation == pytest.approx(source, abs=1e-4)
    assert scene.extents / info['scale'] == pytest.approx(source[1] - source[0], abs=1e-4)


def test_groq_assets_preserve_labware_and_register_with_viewer(store):
  from conftest import CORPUS
  from nist_deck import VenusDeck, install
  from groq_seq_demo import LAYOUT
  from pylabrobot.visualizer3D.server import Viewer3D

  v = VenusDeck(CORPUS, LAYOUT, store=store)
  install(v)
  original = list(v.deck.get_all_resources())
  def position(r):
    return (r.parent, r.location, r.get_size_x(), r.get_size_y(), r.get_size_z())
  before = {r.name: position(r) for r in original}
  root = viewer_models.attach(v.deck)
  assert attach_visual(v, pathlib.Path(root) / 'hamilton_mpe2_animated.glb') == 1
  for r in original:
    assert v.deck.get_resource(r.name) is r
    assert position(r) == before[r.name]
  count = len(v.deck.get_all_resources())
  viewer_models.attach(v.deck)
  assert len(v.deck.get_all_resources()) == count

  assembled = [r for r in original if '/multiflexcarrier/' in viewer_models.venus_file(r)
               and getattr(r, 'reference_glb', None)]
  assert len(assembled) == 5
  for r in assembled:
    assert not any(c.category == 'mfx_module' for c in r.children)
  unit = v.deck.get_resource('__MPE_2_0001')
  data = pathlib.Path(unit.mesh['path']).read_bytes()
  gltf = json.loads(data[20:20 + struct.unpack_from('<I', data, 12)[0]])
  world = next(n for n in gltf['nodes'] if n.get('name') == 'world')
  site = next(s for s in unit.parent.parent.children if s.name.endswith('_site_Filter_1'))
  target = site.get_location_wrt(v.deck, 'c', 'c', 'b') - unit.get_location_wrt(v.deck)
  assert [1000 * world['translation'][i] + x for i, x in enumerate((SEAT.x, SEAT.y, SEAT.z))] == pytest.approx(
    [target.x, target.y, target.z], abs=1e-4)
  viewer = Viewer3D(v.deck, open_browser=False, models_root=root)
  viewer._scene_message(rebuild=True)
  served = {pathlib.Path(p).name for p in viewer._mesh_files.values()}
  assert 'hamilton_mpe2_nested.glb' in served
  assert 'Culture_Processing_STAR_MPE2_Base_Back.glb' in served
  assert all(pathlib.Path(r.reference_glb).name in served for r in assembled)
  assert {'WasteBlock.glb', 'Verification.glb', 'TeachingNeedle5ml.glb',
          'TeachingNeedleBlock.glb', 'core96SlideWasteRack.glb'} <= served
  for r in original:
    path = viewer_models.venus_file(r)
    if any(part in path for part in ('fourtitude', '/agilent/', '/tipsupport co-re ii/', 'rgt_cont_60ml_bc_a00')):
      assert pathlib.Path(r.reference_glb).name in served
      if hasattr(r, 'get_all_items') and r.num_items == 96:
        info_path = pathlib.Path(root) / pathlib.Path(r.reference_glb).with_suffix('.geometry.json')
        info = json.loads(info_path.read_text())
        if 'positions_mm' in info:
          centres = sorted((round(w.get_location_wrt(r, 'c','c','b').x,4),
                            round(w.get_location_wrt(r, 'c','c','b').y,4)) for w in r.get_all_items())
          assert centres == sorted((round(x,4),round(y,4)) for x,y in info['positions_mm'])


def test_teaching_meshes_keep_negative_offsets_and_waste_keeps_overhang():
  for name, z in [('TeachingNeedle5ml', -94.9), ('TeachingNeedleBlock', -52.0)]:
    info = json.loads((viewer_models.MODELS / (name + '.geometry.json')).read_text())
    assert info['output_bounds_m'][0][2] * 1000 == pytest.approx(z)
  info = json.loads((viewer_models.MODELS / 'WasteBlock.geometry.json').read_text())
  assert (info['output_bounds_m'][1][0] - info['output_bounds_m'][0][0]) * 1000 == pytest.approx(186)
