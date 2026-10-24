# Collecting interactive run replays

## Implemented

For setup from a fresh method checkout, including the corpus and trace needed below, see
[From a method checkout to a replay](METHOD_WORKFLOW.md).

GROQ `--view` now automatically records into a new `.local/replays/<timestamp>-<id>/`
folder. `ReplayViewer` captures once on the server, even with multiple browsers, and bundles
the viewer version, content-addressed GLBs, initial/final snapshots and ordered events.
It finalizes a manifest and a sibling ZIP, retaining aborted status and the error message.
Events are flushed as they arrive and the manifest is updated every 25 events.

To generate a replay without opening a browser:

```powershell
$env:PYTHONPATH = 'C:/Users/stefa/plr-venus;.'
$env:PLR_VENUS_FAITHFUL_CFG = 'stock'
.venv/Scripts/python examples/groq_seq_demo.py --corpus .local/session_state/corpus --record-only
```

Use `--replay-dir <new-directory>` to choose its destination. Existing directories are refused.
The current viewer dependency is the integrated local `plr-venus` checkout, as for the live demo.

Motions the driver sends together (`X0 XP` and `C0 JY` under one `asyncio.gather`) are marked
`with_previous` in the log and start together on playback, as they do live.

### Publishing

`tools/publish_replay.py <bundle> site/<name>` copies a bundle for public hosting and sets the view
options it opens with; by default `ui=0` (no navbar, tool rails, tree or panels: the scene and the
replay controls only). `--option ui=1` keeps the viewer's UI; a link's own query still overrides
(`?ui=1`). `venus_interop.plr.replay.set_view_defaults` changes an existing bundle in place.

`site/` is deployed to GitHub Pages by `.github/workflows/pages.yml` on every push to `main` that
changes it. Bundles are committed as recorded: CI has neither the NIST corpus nor the PLR fork.
`site/groq-seq/` is GROQ-Seq plates 2-5, recorded with `PLR_VENUS_FAITHFUL_CFG=stock`.

The published bundle's extension cabinet was corrected on 2026-10-24 in all ten scene snapshots.
The previous code fix had only reached newly recorded bundles, leaving the published cabinet
487.8 mm too low and 116.215 mm too far right. The correction is recorded in the manifest's
`visual_corrections` ledger; other resource transforms and protocol events are unchanged.
Browser inspection against a [photo of a STAR with the extension installed](https://bimedis.com/a-item/liquid-handling-hamilton-medical-microlab-star-2540100)
and [Hamilton's housing brochure](https://info.hamiltoncompany.com/view/449349329/14-15/)
checks the overall alignment: roof level with the instrument, lower frame above the bench.
The photo is qualitative evidence, not a source of millimetre measurements. A regression test
checks every published snapshot so a seek cannot restore the old position.

Serve the generated directory using any static HTTP server, or deploy its contents to GitHub
Pages. Opening `index.html` directly as a `file://` URL is not supported by browser module/fetch
security rules. No simulation or WebSocket service is needed:

```powershell
.venv/Scripts/python -m http.server 18941 --bind 127.0.0.1 --directory .local/replays/groq-demo
```

The page has Play/Pause, Restart, 0.5–8× speed and a **command-boundary scrubber**. Seeking restores
the nearest full scene snapshot and fast-forwards its suffix, including attachments and liquid
state. It is not yet a continuous within-command time scrubber. Camera orbit and inspection remain
interactive. Refreshing the page resets to the start; it never re-executes Python.

Replay controls use a floating dark toolbar with SVG icons, a styled progress track, speed picker
and keyboard focus states (`replay_static/replay.css`). Clean mode hides only the logical carrier
site bodies, retaining their child meshes and picking. The saved GROQ bundle also includes the
registered lower STAR chassis mesh. These visual updates can be applied to an existing recording
without rerunning its simulation.

Validated bundle: `.local/replays/groq-demo`, 593 events, 328 command markers, about 17 MB before
ZIP compression. Browser checks exercised play/pause, forward/backward seeks, and A1 returning
from its final 270 µL / 4.6 mm to 0 µL / 0 mm at the start. The known GROQ plate-map error is
labelled aborted. Python replay/model tests: 23 passed. Preview:
`.local/session_state/groq-replay-preview.png`.

The collection catalogue, automatic thumbnails, IndexedDB cache and continuous time seeking
below remain follow-up work. The architecture notes describe the broader design.

## Existing pieces

The viewer already receives a scene, state changes, resource moves, and motion requests over a
WebSocket. Motion requests contain drive profiles, waits, handovers and command identity. Its
browser player can animate them without re-executing the protocol. The transport currently routes
these messages to handlers in `static/app.js`; motion completion is acknowledged to Python.

There is an earlier local prototype at
`C:/Users/stefa/plr-collision/pylabrobot/visualizer3D/static/replay.js`. It stores messages in
sessionStorage, keyed by the live server token, and caps recording at 600 messages. This is useful
as a dispatch example, but unsuitable as a durable archive: it drops other tokens, lives only in
that tab's session, and does not package model files. Do not port that persistence policy.

## Recommended artifact

Save each simulation as an immutable directory, with a ZIP download of the same contents:

```
runs/<run-id>/
  manifest.json
  events.jsonl
  assets/<sha256>.glb
  thumbnail.png
```

The manifest should version the format and record protocol/parameters, source revision, viewer
revision, labware/model hashes, faithful configuration identity, start/end times, event count,
completion/abort status and error. Include the viewing preset separately from the original motion
requests. Never archive the server token, browser cookies or machine-local paths in public bundles.
Use a timestamp plus content digest as the run ID, and a human-readable title for the catalogue.

Capture the initial scene AND initial state, then every ordered scene/state/moves/motion message,
including epoch IDs and resource handovers. Include command markers for a timeline. Resolve each
mesh referenced by any scene into the asset store and rewrite its URL relative to the bundle.
Deduplicate by content hash across runs. Store both original and replay-visible source versions
when mesh edits are applied; do not silently lose material-edit metadata.

Record once per server run, before sending to clients, so reconnecting or opening a second tab
does not duplicate the recording. Add an explicit start/end lifecycle and flush final pending state
before marking complete. An aborted run remains replayable and visibly labelled aborted; the
current GROQ plate-map failure must not be presented as successful completion.

## Playback

Add a file-backed transport feeding the same handlers as WebSocket messages. Play each motion to
completion before dispatching its following state/scene changes. Do not use browser/network
wall-clock arrival delays as the animation timeline: they include rendering stalls and idle tabs.
Apply playback timing preferences at playback time (currently pauses 0.5); retain the source times
in the recording so viewers can choose original timing later. Keep CO-RE gripper channels paired
and preserve pipetting stagger.

Provide a run picker, restart, pause/resume, speed, and command-step controls. Start with seeking
only to command boundaries; later add periodic full scene/state checkpoints, with resolved
attachments and transforms, to avoid replaying the entire prefix when seeking. Camera orbit and
resource inspection stay live and independent of recorded robot motion.

Use IndexedDB for a browser cache and optional offline viewing, with explicit export/import; it
is not the sole durable copy. Maintain a small catalogue (`runs/index.json`) listing title, method,
parameters, status, duration, thumbnail and bundle URL. Bundle the matching viewer version or
declare a supported format range so an upgrade cannot silently break old runs.

## Rollout and checks

1. Add server-side capture and a finalizer to the demo's run lifecycle; save normal, aborted and
   interrupted runs without a browser being responsible for persistence.
2. Add static file playback and a catalogue page. Use one saved GROQ run repeatedly for frontend
   iteration; Python runs only when protocol inputs or simulation logic change.
3. Verify final resource transforms, attachments, tip occupancy and liquid volumes match live
   execution. Check restart, pause, reconnect during capture, aborted logs, missing assets and
   command-boundary seek. Model and protocol coordinate changes remain outside replay controls.
4. Publish the static catalogue, viewer and bundles to GitHub Pages once reviewed. The public
   replay path makes no WebSocket connection and requires no Python server. Shared assets can be
   kept once per deployment; measure total bundle size before choosing retention limits.

The core recorder and static command-boundary playback are implemented above; the broader
catalogue/cache features remain proposed.
