# From a method checkout to a replay

Run these PowerShell commands from the repository root after the README's installation steps.
The corpus builder and trace reader use only the standard library. The GROQ demo additionally
needs the integrated `venus-plr` PyLabRobot checkout (STARDevice, simulation driver, firmware
motion and visualizer3D APIs); the pinned upstream `plr` extra alone does not provide these.
Set `PYTHONPATH` to your compatible checkout before running the demo.

## Build a corpus

```powershell
git clone --branch S-Cell_STAR-2 --single-branch https://github.com/djross22/lmsf_hamilton.git .local/lmsf_hamilton
.venv/Scripts/python tools/build_corpus.py .local/corpus --name lmsf_hamilton --layouts .local/lmsf_hamilton/Methods --labware .local/lmsf_hamilton/LabWare
$env:VENUS_INTEROP_CORPUS = "$PWD/.local/corpus"
$env:VENUS_INTEROP_NIST = "$PWD/.local/lmsf_hamilton"
```

`raw/<sha1[:12]>.lay` contains unchanged layout bytes. `index.tsv` records the hash, source,
original path relative to the searched folder's parent, and byte count. Identical contents share
one file and index row (the last source wins). `defs_raw/` and `defs_index.tsv` hold labware
definitions and their Labware-relative names. Rebuilding adds or replaces entries; it does not
remove stale files from older corpora. Use a fresh output directory when migrating from path hashes.

The GROQ layout is `raw/5ae1a84b57e5.lay`. This name depends on its bytes, not the checkout location.
This source alone is not the complete multi-source test corpus. Stock definitions absent from the
checkout may also need a local Venus Labware folder; the demo's resolver uses it when available.

## Generate a method trace

```powershell
$method = Get-ChildItem .local/lmsf_hamilton/Methods -Recurse -Filter 'GROQ-Seq.2_TFs.plates_2-5.hsl' | Select-Object -First 1
.venv/Scripts/python tools/trace_method.py --roots .local/lmsf_hamilton/Library .local/lmsf_hamilton/Methods --out .local/traces $method.FullName
```

Keep the method's sibling `.sub` and `.stp` files and included libraries in the checkout. The tool
writes full and condensed Markdown traces. Missing includes or incompatible library versions must
be resolved before treating the trace as complete. `--calls` and `--status` inspect library calls
and port coverage. [PORTING.md](PORTING.md) explains testing ports with the HSL interpreter;
this does not replace running the method in Venus.

## Record GROQ

```powershell
$env:PYTHONPATH = 'C:/path/to/plr-venus;.'
$env:PLR_VENUS_FAITHFUL_CFG = 'stock'
.venv/Scripts/python examples/groq_seq_demo.py --corpus .local/corpus --trace .local/traces/GROQ-Seq.2_TFs.plates_2-5.condensed.md --record-only --replay-dir .local/replays/groq-new
.venv/Scripts/python -m http.server 18941 --bind 127.0.0.1 --directory .local/replays/groq-new
```

Open `http://127.0.0.1:18941`. Choose a new replay directory for each recording. The committed
method has a known plate-map error: the faithful replay ends with **aborted** status. `--repair`
changes that method logic to produce its intended output and must be identified as a repaired run.
Use `--view` for live viewing. [GROQ_REPLAYS.md](GROQ_REPLAYS.md) covers playback and publishing.

The demo reports liquid classes missing from PLR and falls back to PLR defaults. Supply the
method's liquid-class database with `--liquid-classes` for comparisons that require those values;
`stock` selects instrument defaults but does not supply missing liquid classes.

The chassis visual and left extension cabinet use the imported deck's coordinate frame.
`viewer_models.attach_star_base` shifts the cabinet from the chassis frame by
`-STAR_DECK_LOCATION`, matching stock PLR `STAR()` relative to its deck. Protocol labware stays
in place. This is a viewer registration check, not a physical cabinet measurement.

For firmware capture, comparison and position sweeps against Venus, follow the
[simulation harness README](../tools/venus_sim/README.md). Use the instrument's `.cfg` instead
of `stock` when comparing its defaults. The harness needs its separate Windows/Venus setup.

## Verification on 2026-10-24

A fresh checkout at `99364a82fd0ffe8b4b1396ea65d07b82d14df0aa` produced 141 layouts and
1,144 definitions. The GROQ trace resolved 85 files and 135 step records. With the local
integrated PLR checkout and stock Venus definitions available, recording produced 630 events,
the expected plate-map abort, and the cabinet corner (-381.215, -91, -32.5) mm in its saved scene.
Two FastMixing liquid classes fell back to PLR defaults, so this run validates the workflow and
viewer registration, not firmware equivalence. The focused corpus, viewer and replay suite passed
10 tests. No Venus-side simulation or browser interaction was run for this check.
