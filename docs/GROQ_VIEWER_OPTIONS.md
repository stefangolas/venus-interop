# Bringing the existing viewer options into GROQ-seq

Integrated 2026-10-23. The viewer changes are local modifications in `plr-venus`;
GROQ now requests `overlays=False, hover=False, ui=True, look="real", light=0.8`.
Use `--view --viewer-debug` for the technical view with overlays and hover readouts.
The normal printed watch URL also sets `pauses=0.5`, halving playback fixed/dwell times.
CO-RE gripper requests are played with zero Y stagger; pipetting keeps its stagger.
These adjustments leave recorded motion data and drive speeds unchanged.
The existing Venus driver and collision hooks were retained. The merge restored the
`modelOf` import used by the branch's detail-culling logic after browser verification caught it.
Validation: 21 GROQ model tests passed, 65 server/scene tests passed (one skipped),
and 30 JavaScript motion-player tests passed. The map below records the source and rationale.

## Where the options live

The current GROQ launch uses `PYTHONPATH=C:/Users/stefa/plr-venus;.`. Its imported
`pylabrobot.visualizer3D.server` serves the sibling `static` directory, so settings in another
checkout do not affect this run. `examples/groq_seq_demo.py` constructs `Viewer3D` under `--view`.

The requested options were added in the PLR repository at commit
`e8bef570d85f10a17dc751df382042c53c630f43` (Viewer options for a models-only view,
liquid levels, and smoother orbiting). It is present on local `viz3d-pr` and
`fork/viz3d-motion`, but absent from `venus-plr` and the current `plr-viz3d` checkout
(`viz3d-iswap`). The `viz3d-pr` worktree is currently
`C:/Users/stefa/AppData/Local/Temp/opencode/viz3dpr-baseline`, head `014012d75`.
Use the git ref as the source of truth rather than relying on that temporary path.

| Existing option | Effect | Suggested GROQ setting |
|---|---|---|
| `overlays=False` / `?overlays=0` | Removes box outlines, floor grid, origins, rail numbers, reference/grip marks, halos, axis gizmo, scale bar and stats; stops device panels opening automatically | Off for watching runs |
| `hover=False` / `?hover=0` | Removes hover outlines/readouts; clicking still selects | Off for watching runs |
| `ui=False` / `?ui=0` | Hides navbar, tools, tree, buttons and panels | Keep UI for playback controls |
| `bare=True` / `?bare=1` | Disables overlays, hover and UI together | Optional screenshots/presentation mode |
| `light=0.8` / `?light=0.8` | Scales lights and reflections | Starting point to compare, not a validated default |
| `look="real"` / `?look=real` | World-fixed lighting, soft shadows, Neutral tone mapping | Compare against technical mode for white plastic |
| `camera=((fx,fy,fz),(ax,ay,az))` | Initial camera and Home position, in root millimetres | Set after visually framing GROQ |
| `mesh_edits={...}` | Hides or recolors named materials, optionally selecting faces by axis/threshold | Only for identified obstructing model parts |

The options parser is `pylabrobot/visualizer3D/static/options.js`; server constructor
arguments become query parameters before the URL's `#token=` fragment. Appending these options
to the old viewer URL alone would not enable them; the integrated frontend is required.

`overlays=False` removes diagnostic outlines; it does not promise to hide every resource without
a mesh. Generic vessel geometry and fallback bodies can remain. Hiding resources through tree eyes
or `plrViewer.hide(name)` also affects descendant visibility, so hiding a carrier to remove its
placeholder can hide its contents. A separate body-only policy would need explicit implementation.

## Integration sequence

1. Bring the viewer options into the PLR checkout serving GROQ, preserving the Venus driver and
   its simulation/motion hooks. Avoid replacing the whole Python dependency with `viz3d-pr` merely
   to get its frontend. Begin with `e8bef570d` as a reviewed patch: it spans 22 files and also adds
   liquid-height publication, open vessel rendering and orbit/performance changes. Server, scene
   and frontend changes must agree; copying only `options.js` is insufficient.
2. If adding realistic lighting, start from `fb2fc37e3` and review its later fixes through
   `viz3d-pr`. The current implementation has static variance shadows, model-specific finishes,
   glass suppression (`?glass=1` restores it), and quality/performance fixes. The full viewer diff
   against `venus-plr` spans 48 files, including vendor assets, so do not blindly overwrite it.
   Preserve the current branch's collision UI and motion playback integrations during reconciliation.
3. Add explicit GROQ viewing options at its `Viewer3D(...)` construction. Suggested watch preset:
   `overlays=False, hover=False, ui=True, look="real"`; compare light 1.0 and 0.8 in the rendered
   deck. Retain a technical/debug mode with overlays enabled and an optional bare presentation mode.
   Pass only arguments supported by the integrated viewer; fail clearly if the old dependency is used.
4. Verify server URL serialization, scene/state tests and the upstream browser option tests.
   Exercise GROQ mesh serving, moving tips/plates/lids, pause/resume controls, reconnect, and resource
   identity/coordinate invariance. Inspect both technical and real views, including missing-mesh
   fallback, tube cavities and liquid surfaces. Check real mode on the user's browser for frame cost.

The newer viewer also renders liquid at the published physical height and opens vessel tops;
this is relevant to the tube appearance, but it does not supply accurate exterior tube geometry.
None of these display options should change protocol coordinates or pipetting semantics.
