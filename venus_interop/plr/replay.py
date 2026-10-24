"""Record viewer messages and their assets as a portable static replay site."""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import html
import json
import pathlib
import re
import shutil
from datetime import datetime, timezone

from pylabrobot.visualizer3D.server import STATIC_DIR, Viewer3D, _encode


# The viewer options a bundle opens with; a link's own query still wins. `ui='0'` takes away the
# viewer's navbar, rails, tree and panels as well, leaving the scene and the replay controls.
VIEW_DEFAULTS = dict(overlays='0', hover='0', look='real', light='0.8', pauses='0.5')
_DEFAULTS_START, _DEFAULTS_END = '<script id="replay-defaults">', '</script><!-- replay-defaults -->'


def _defaults_script(defaults: dict[str, str]) -> str:
  return f"""{_DEFAULTS_START}
const replayQuery = new URLSearchParams(location.search);
for (const [key,value] of Object.entries({json.dumps(defaults)})) {{
  if (!replayQuery.has(key)) replayQuery.set(key,value);
}}
history.replaceState(null,'',location.pathname+'?'+replayQuery);
{_DEFAULTS_END}"""


def set_view_defaults(directory: pathlib.Path, **options: str) -> dict[str, str]:
  """Change the options a recorded bundle opens with, in place; returns them all."""
  page_path = directory / 'index.html'
  page = page_path.read_text(encoding='utf-8')
  start, end = page.find(_DEFAULTS_START), page.find(_DEFAULTS_END)
  end_length = len(_DEFAULTS_END)
  if start < 0 or end < 0:
    # Bundles recorded before the block was marked: the first script, holding a JS object.
    start = page.find('<script>\nconst replayQuery')
    end, end_length = page.find('</script>', start), len('</script>')
    if start < 0:
      raise ValueError(f'{page_path} has no replay defaults block')
  literal = page[start:end].split('Object.entries(', 1)[1].split(')) {', 1)[0]
  current = json.loads(re.sub(r"(\w+):'([^']*)'", r'"\1":"\2"', literal))
  current.update(options)
  page = page[:start] + _defaults_script(current) + page[end + end_length:]
  page_path.write_text(page, encoding='utf-8')
  return current


def publish(bundle: pathlib.Path, output: pathlib.Path, **options: str) -> pathlib.Path:
  """Copy a finished bundle for public hosting: no zip beside it, the given view defaults."""
  shutil.copytree(bundle, output)
  set_view_defaults(output, **options)
  return output


class ReplayBundle:
  """An append-only event log with content-addressed model files."""

  def __init__(self, directory: pathlib.Path, title: str, metadata: dict,
               view_defaults: dict[str, str] | None = None):
    self.directory = directory
    directory.mkdir(parents=True, exist_ok=False)
    shutil.copytree(STATIC_DIR, directory, dirs_exist_ok=True)
    assets = pathlib.Path(__file__).with_name('replay_static')
    shutil.copyfile(assets / 'transport.js', directory / 'transport.js')
    shutil.copyfile(assets / 'replay.js', directory / 'replay.js')
    shutil.copyfile(assets / 'replay.css', directory / 'replay.css')
    page = (directory / 'index.html').read_text(encoding='utf-8')
    page = page.replace('{{ source_filename }}', html.escape(title)).replace('{{ ws_port }}', '0')
    defaults = _defaults_script({**VIEW_DEFAULTS, **(view_defaults or {})})
    page = page.replace('<head>', '<head>' + defaults)
    (directory / 'index.html').write_text(page, encoding='utf-8')
    motion = directory / 'motion.js'
    source = motion.read_text(encoding='utf-8')
    # A frame that stalls (a shadow redraw, a scene rebuilt) would hand the player its whole
    # duration at once and the parts jump; capped, a recording slows for that frame instead.
    source = source.replace('export const stepMotion = (delta) => player.step(delta);', '''let replayPaused = false;
const REPLAY_MAX_STEP = 1 / 30;
export const stepMotion = (delta) => replayPaused ? false : player.step(Math.min(delta, REPLAY_MAX_STEP));
export function replayControl({paused = false, speed = 1, finish = false} = {}) {
  replayPaused = paused;
  player.setSpeed(speed);
  if (finish) player.finishAll();
}''')
    if 'export function replayControl' not in source:
      raise RuntimeError('viewer motion API changed; replay adapter must be updated')
    motion.write_text(source, encoding='utf-8')
    boot = directory / 'boot.js'
    boot.write_text(boot.read_text(encoding='utf-8').replace(
      'function probeWebsocket(hello) {', 'function probeWebsocket(hello) { return Promise.resolve(false);'),
      encoding='utf-8')
    self.log = (directory / 'events.jsonl').open('w', encoding='utf-8')
    self.count = 0
    self.commands = []
    self.scene = 0
    self.assets: dict[str, str] = {}
    self.manifest = dict(format=1, title=title, started=datetime.now(timezone.utc).isoformat(),
                         status='recording', metadata=metadata, events='events.jsonl')
    (directory / 'README.txt').write_text(
      'Serve this directory with any static HTTP server and open index.html.\n'
      'No simulation process or WebSocket server is needed.\n'
      'Use Play/Pause, speed, Restart and the command-position slider.\n', encoding='utf-8')
    self._manifest()

  def _manifest(self):
    data = {**self.manifest, 'event_count': self.count, 'commands': self.commands,
            'assets': sorted(set(self.assets.values()))}
    temp = self.directory / 'manifest.tmp'
    temp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temp.replace(self.directory / 'manifest.json')

  def record(self, event: str, data: dict, mesh_files: dict[str, str], extra: dict | None = None):
    """Copy the wire representation so later model mutations cannot alter history.

    `extra` is added to the logged data only, never sent to a live page."""
    message = json.loads(_encode(event, data))
    message['data'].update(extra or {})
    if event == 'scene':
      self.scene = self.count
      for model in message['data']['models']:
        mesh = model.get('mesh')
        if not mesh or not mesh.get('url'):
          continue
        url = mesh['url']
        if url not in self.assets:
          source = pathlib.Path(mesh_files[url.removeprefix('mesh/')])
          content = source.read_bytes()
          target = 'assets/' + hashlib.sha256(content).hexdigest() + '.glb'
          (self.directory / 'assets').mkdir(exist_ok=True)
          (self.directory / target).write_bytes(content)
          self.assets[url] = target
        mesh['url'] = self.assets[url]
    if event in ('motion', 'command'):
      self.commands.append(dict(event=self.count, scene=self.scene,
                                label=data.get('command', data.get('kind', event))))
    self.log.write(json.dumps(message, separators=(',', ':')) + '\n')
    self.log.flush()
    self.count += 1
    if self.count % 25 == 0:
      self._manifest()

  def finish(self, status: str, error: str | None = None):
    self.log.close()
    self.manifest.update(status=status, error=error, finished=datetime.now(timezone.utc).isoformat())
    self._manifest()
    shutil.make_archive(str(self.directory), 'zip', root_dir=self.directory)


# The `act_out` call the current task is inside, if any.
_ACTING: contextvars.ContextVar = contextvars.ContextVar('replay_acting')


class _RecordingClient:
  """A capture sink acknowledges motion without making the simulation wait for rendering."""

  def __init__(self, viewer):
    self.viewer = viewer

  async def send(self, message):
    payload = json.loads(message)
    if payload['event'] == 'motion':
      # On the next turn of the loop, as a page's answer would come: a command sent alongside this
      # one then reaches the recording while this one is still open, and is marked as overlapping.
      asyncio.get_running_loop().call_soon(self.viewer._on_motion_played, self, json.dumps(
        {'event': 'motion_done', 'data': {'id': payload['data']['id']}}))


class ReplayViewer(Viewer3D):
  """Viewer with one server-side recording, independent of connected browser tabs."""

  def __init__(self, *args, bundle: pathlib.Path, metadata: dict,
               view_defaults: dict[str, str] | None = None, **kwargs):
    super().__init__(*args, **kwargs)
    self.bundle = ReplayBundle(bundle, self.name, metadata, view_defaults)
    self.capture = _RecordingClient(self)
    self.recording = True
    self._acting: list[dict] = []

  async def act_out(self, command, motion):
    # Each command's motion runs in its own task context; one sent while another's is still being
    # played was sent alongside it (`X0 XP` and `C0 JY` under one gather), and plays with it.
    acting = {'sent': False}
    token = _ACTING.set(acting)
    self._acting.append(acting)
    try:
      await super().act_out(command, motion)
    finally:
      self._acting.remove(acting)
      _ACTING.reset(token)

  async def _broadcast(self, event, data):
    if self.recording:
      extra = {}
      if event == 'motion':
        mine = _ACTING.get(None)
        if any(other['sent'] for other in self._acting if other is not mine):
          extra['with_previous'] = True
        if mine is not None:
          mine['sent'] = True
      self.bundle.record(event, data, self._mesh_files, extra)
    await super()._broadcast(event, data)

  async def start(self):
    await super().start()
    self._clients.add(self.capture)
    await self._send_scene_to_all()

  async def finish_recording(self, status='complete', error=None):
    if not self.recording:
      return
    await asyncio.sleep(0)
    if self._scene_timer is not None:
      self._scene_timer.cancel()
      await self._flush_scene()
    if self._pending:
      await self._flush()
    # A final authoritative snapshot makes the end of the scrubber exact.
    await self._send_scene_to_all()
    self.bundle.finish(status, error)
    self.recording = False
    self._clients.discard(self.capture)

  async def stop(self):
    await self.finish_recording('interrupted', 'Viewer stopped before the run was finalized')
    await super().stop()
