"""Replay logs preserve wire data and capture without a browser."""
import asyncio
import hashlib
import json

import pytest

pytest.importorskip('pylabrobot')
from pylabrobot.resources import Coordinate, Resource
from venus_interop.plr.replay import ReplayBundle, ReplayViewer, publish, set_view_defaults


def test_bundle_copies_assets_and_does_not_mutate_scene(tmp_path):
  source = tmp_path / 'source.glb'
  source.write_bytes(b'test mesh content')
  bundle = ReplayBundle(tmp_path / 'replay', 'Test', {'method': 'test'})
  scene = {'models': [{'mesh': {'url': 'mesh/example'}}]}
  bundle.record('scene', scene, {'example': str(source)})
  bundle.record('motion', {'kind': 'core_move', 'fixed': 2, 'command': 'C0ZM'}, {})
  bundle.finish('aborted', 'known protocol error')
  events = [json.loads(line) for line in (bundle.directory / 'events.jsonl').read_text().splitlines()]
  assert scene['models'][0]['mesh']['url'] == 'mesh/example'
  asset = events[0]['data']['models'][0]['mesh']['url']
  assert asset == 'assets/' + hashlib.sha256(source.read_bytes()).hexdigest() + '.glb'
  assert (bundle.directory / asset).read_bytes() == source.read_bytes()
  assert events[1]['data']['fixed'] == 2
  manifest = json.loads((bundle.directory / 'manifest.json').read_text())
  assert manifest['status'] == 'aborted'
  assert manifest['commands'] == [{'event': 1, 'scene': 0, 'label': 'C0ZM'}]
  assert str(tmp_path) not in (bundle.directory / 'events.jsonl').read_text()
  assert 'new WebSocket' not in (bundle.directory / 'transport.js').read_text()
  assert bundle.directory.with_suffix('.zip').is_file()


def test_capture_without_browser_has_initial_and_final_snapshots(tmp_path):
  async def run():
    root = Resource('deck', 100, 100, 100)
    child = Resource('plate', 10, 10, 10)
    root.assign_child_resource(child, Coordinate(1, 2, 3))
    viewer = ReplayViewer(root, bundle=tmp_path / 'run', metadata={}, open_browser=False,
                          fs_port=0, ws_port=0)
    await viewer.start()
    try:
      await asyncio.wait_for(viewer.act_out('test', {'kind': 'core_move', 'fixed': 2,
                                                    'dwell': 4, 'channels': []}), 2)
      child.location = Coordinate(7, 8, 9)
      await viewer.finish_recording()
    finally:
      await viewer.stop()
    events = [json.loads(line) for line in (tmp_path / 'run/events.jsonl').read_text().splitlines()]
    assert [e['event'] for e in events[:2]] == ['scene', 'state']
    assert [e['event'] for e in events[-2:]] == ['scene', 'state']
    assert sum(e['event'] == 'motion' for e in events) == 1
    assert events[0]['data'] != events[-2]['data']
    assert json.loads((tmp_path / 'run/manifest.json').read_text())['status'] == 'complete'
  asyncio.run(run())


def test_motions_sent_together_are_marked_and_sequential_ones_are_not(tmp_path):
  async def run():
    root = Resource('deck', 100, 100, 100)
    viewer = ReplayViewer(root, bundle=tmp_path / 'run', metadata={}, open_browser=False,
                          fs_port=0, ws_port=0)
    await viewer.start()
    move = lambda kind: {'kind': kind, 'fixed': 0, 'dwell': 0, 'channels': []}
    try:
      await asyncio.gather(viewer.act_out('XP', move('move_x')), viewer.act_out('JY', move('move_y')))
      await viewer.act_out('AS', move('aspirate'))
      await viewer.finish_recording()
    finally:
      await viewer.stop()
    events = [json.loads(line) for line in (tmp_path / 'run/events.jsonl').read_text().splitlines()]
    marks = {e['data']['kind']: e['data'].get('with_previous', False)
             for e in events if e['event'] == 'motion'}
    assert marks == {'move_x': False, 'move_y': True, 'aspirate': False}
  asyncio.run(run())


def test_published_copy_opens_with_the_given_defaults(tmp_path):
  bundle = ReplayBundle(tmp_path / 'replay', 'Test', {})
  bundle.finish('complete')
  out = publish(bundle.directory, tmp_path / 'site', ui='0')
  page = (out / 'index.html').read_text(encoding='utf-8')
  assert '"ui": "0"' in page and '"look": "real"' in page
  assert page.count('replay-defaults') == 2  # one block, opened and closed
  assert set_view_defaults(out, ui='1')['ui'] == '1'
  assert '"ui": "0"' not in (bundle.directory / 'index.html').read_text(encoding='utf-8')
