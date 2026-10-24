import { invalidate } from './frame.js';
import { playMotion, replayControl } from './motion.js';
import { setGlideSeconds } from './live.js';

export async function startReplay(handlers) {
  // A recording has no server to wait for: said at once, or the viewer's own check reports the
  // server unreachable while a large log is still downloading.
  window.dispatchEvent(new CustomEvent('plr:status', {detail: {connected: true}}));
  document.getElementById('status-label').textContent = 'Loading recorded run…';
  const stylesheet = document.createElement('link');
  stylesheet.rel = 'stylesheet'; stylesheet.href = './replay.css'; document.head.append(stylesheet);
  const loading = document.createElement('div');
  loading.className = 'replay-controls replay-loading';
  loading.textContent = 'Loading recorded run…';
  document.body.append(loading);
  const [manifestResponse, logResponse] = await Promise.all([
    fetch('./manifest.json'), fetch('./events.jsonl'),
  ]);
  if (!manifestResponse.ok || !logResponse.ok) throw new Error('Run files could not be loaded');
  const manifest = await manifestResponse.json();
  if (manifest.format !== 1) throw new Error('Unsupported replay format');
  const events = (await logResponse.text()).trim().split('\n').filter(Boolean).map(JSON.parse);
  loading.remove();
  if (!events.length || events[0].event !== 'scene') throw new Error('Recording has no initial scene');
  const boundaries = manifest.commands.length ? [...manifest.commands.map(c => c.event), events.length] : [0, events.length];
  let cursor = 0, playing = false, speed = 1, active = null, seeking = false;
  let seekVersion = 0;
  setGlideSeconds(0);
  handlers.connecting();
  document.getElementById('status-label').textContent = `Recorded run · ${manifest.status}`;
  document.getElementById('status-label').title = manifest.error ?? '';
  window.dispatchEvent(new CustomEvent('plr:status', {detail: {connected: true}}));
  const bar = document.createElement('div');
  bar.className = 'replay-controls';
  const playIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13L19 12Z" fill="currentColor"/></svg>';
  const pauseIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 5h4v14H7zm6 0h4v14h-4z" fill="currentColor"/></svg>';
  bar.innerHTML = `<button data-play class="replay-play" aria-label="Play" title="Play">${playIcon}</button><button data-restart aria-label="Restart" title="Restart"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 8a8 8 0 1 1-1 8M5 3v5h5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></button><div class="replay-timeline"><div class="replay-caption"><span class="replay-heading">RECORDED RUN</span><span data-label></span></div><input data-seek type="range" min="0" value="0" aria-label="Command position"></div><div class="replay-speed"><select data-speed aria-label="Playback speed"><option value="0.5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option><option value="4">4×</option><option value="8">8×</option></select></div>`;
  document.body.append(bar);
  const play = bar.querySelector('[data-play]'), slider = bar.querySelector('[data-seek]');
  const label = bar.querySelector('[data-label]');
  slider.max = boundaries.length - 1;
  function update() {
    play.innerHTML = playing ? pauseIcon : playIcon;
    play.setAttribute('aria-label', playing ? 'Pause' : 'Play');
    play.title = playing ? 'Pause' : 'Play';
    const position = boundaries.findLastIndex(b => b <= cursor);
    slider.value = position;
    slider.style.setProperty('--progress', `${100 * position / Math.max(1, boundaries.length - 1)}%`);
    const command = manifest.commands[Math.max(0, position)];
    label.textContent = cursor >= events.length ? `End · ${manifest.status}` : `${position}/${boundaries.length - 1} ${command?.label ?? 'Start'}`;
    label.title = manifest.error ?? '';
    slider.setAttribute('aria-valuetext', label.textContent);
  }
  async function dispatch(message, instant = false) {
    // The viewer keeps parts of a message as its live state (a scene's parent array becomes the
    // tree that moves re-parent), so each dispatch gets a fresh copy, as a socket would deliver.
    // Handing over the logged object let a seek back rebuild a scene with tips already on shafts.
    const {event, data} = structuredClone(message);
    if (event === 'motion') {
      replayControl({speed: instant ? 0 : speed});
      await playMotion(data, () => {});
    } else if (event === 'moves') handlers.moves(data.moves);
    else if (handlers[event]) handlers[event](data);
    invalidate();
  }
  // A motion the recorder marked `with_previous` was sent alongside the one before it (the arm's X
  // and the channels' Y under one gather), so the two start together and are awaited as a group.
  const joinsNext = i => events[i + 1]?.event === 'motion' && events[i + 1].data.with_previous;
  async function pump() {
    if (active || seeking || !playing) return;
    active = (async () => {
      let group = [];
      // A group is sent whole even if paused part-way: its members then wait, paused, together.
      while ((playing || group.length) && !seeking && cursor < events.length) {
        const step = dispatch(events[cursor]);
        if (events[cursor].event === 'motion' && joinsNext(cursor)) group.push(step);
        else { await Promise.all([...group, step]); group = []; }
        cursor++;
        update();
      }
      await Promise.all(group);
      if (cursor === events.length) playing = false;
    })();
    try { await active; } finally { active = null; update(); }
  }
  async function seek(position) {
    position = Math.max(0, Math.min(boundaries.length - 1, Math.round(position)));
    const version = ++seekVersion;
    playing = false;
    seeking = true;
    replayControl({speed: 0, finish: true});
    if (active) await active;
    if (version !== seekVersion) return;
    const target = boundaries[position];
    // Every full scene is followed by a complete state snapshot. Restore the nearest one,
    // then fast-forward its small suffix using the same handovers and motion player.
    let start = 0;
    for (let i = 0; i < target; i++) if (events[i].event === 'scene') start = i;
    cursor = start;
    const end = target === 0 ? Math.min(2, events.length) : target;
    while (cursor < end) {
      if (version !== seekVersion) return;
      await dispatch(events[cursor++], true);
    }
    replayControl({paused: true, speed});
    seeking = false;
    update();
    invalidate();
  }
  play.onclick = () => {
    if (seeking) return;
    playing = !playing;
    replayControl({paused: !playing, speed});
    invalidate(); update(); pump();
  };
  bar.querySelector('[data-restart]').onclick = () => seek(0);
  slider.oninput = () => seek(Number(slider.value));
  bar.querySelector('[data-speed]').onchange = event => {
    speed = Number(event.target.value);
    replayControl({paused: !playing, speed}); invalidate();
  };
  window.plrReplay = {seek, play: () => { if (!playing) play.click(); },
    pause: () => { if (playing) play.click(); },
    status: () => ({cursor, total:events.length, playing, seeking, commands:manifest.commands.length})};
  await seek(0);
}
