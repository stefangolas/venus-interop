# Venus simulation harness

Runs Venus methods and probes headless in Venus's simulation mode, and compares them with their
PyLabRobot translations: firmware command by command, and labware positions placement by
placement. The method, the rules found and the open questions are in
[docs/FIRMWARE_EQUIVALENCE.md](../../docs/FIRMWARE_EQUIVALENCE.md). This file is setup and commands.

## Setup (once per machine)

- **Venus** (Hamilton Venus 4) installed, its database off (`Config\HxVectorDb.cfg`).
- **A 32-bit Python with pythonnet** at `<work>/python32` (`paths.PYTHON32`). Venus's run service
  is driven through Hamilton's `RunHSLExecutor.dll` (in pyhamilton's `star-oem` folder); the
  64-bit HxRun route waits for a Start button press.
- **Simulation on** in the instrument config the layouts use: `SimulateMode=1` in
  `Config\ML_Starlet.cfg` (or `ML_STAR.cfg` for STAR decks).
- **Modules declared in the simulator's replies**, not in the `.cfg` (Venus overwrites that from
  the instrument). For a 96-head: `C0QM` in `Config\ML_Starlet_Simulator.cfg` with `ka000002` and
  `xl05` (FIRMWARE_EQUIVALENCE §2.2).
- **The method's liquid-class database** swapped into `Config\ML_STARLiquids.mdb`, original backed
  up.
- **Back up every Venus file before changing it**, into `<work>/backup`. Never run
  `HxCfgFilConverter.exe` (it sends {ENTER} to the focused window).

Environment variables (`paths.py`): `VENUS_SIM_WORK` (default `~/venus-sim`), `HAMILTON_DIR`,
`VENUS_INTEROP_CORPUS`, `VENUS_INTEROP_NIST`, `PYHAMILTON_DIR`. The PLR-side scripts need the
`venus-plr` PyLabRobot worktree first on `PYTHONPATH`.

## Commands

Run the PLR-side scripts with the repo's Python, and `run_probe.py` with `paths.PYTHON32`.

| Script | What it does |
|---|---|
| `run_probe.py METHOD.hsl [TIMEOUT]` | runs one method headless, waits for its trace, prints it |
| `sign.py FILE.hsl` | gives an HSL file a valid Venus checksum footer |
| `stage_probe.py PROBE.hsl` | copies a probe into `<work>/oem` with the pyhamilton files its includes reach |
| `stage_marionette.py` | stages NIST's Marionette, its parameters CSV and the tip-reload probe |
| `labware_closure.py LAYOUT.lay [--copy]` | the layout's labware missing from Venus, from the corpus |
| `labware_siblings.py` | containers and lids that added labware names without a folder |
| `marionette_plr_firmware.py` | the PLR translation's firmware for the same run |
| `compare_firmware.py [--extract] [CODES]` | Venus's against PLR's firmware, field by field |
| `where.py X Y [NAME]` | what PLR has at a deck point of Marionette's deck |
| `sweep.py HASH ...` | Venus's position of every labware and position, for corpus layouts |
| `compare_sweep.py [HASH ...]` | those positions against the importer's; writes `deltas.tsv` |
| `select_sweep.py [HASH ...]` | the fewest layouts that cover the labware combinations not yet swept |
| `trim_sweep.py HASH TAG PATTERN ...` | sweeps a layout with labware taken out (file substrings, or `id:<Id>`): to find what makes it fail |

Probes in `probes/` (our own; `sign.py` adds the footer when staged):
- `marionette_reload_tips.hsl`: the operator's tip reload before each Marionette run;
- `eject_patterns.hsl`: tip eject per channel pattern;
- `marionette_volume_repeat.hsl`: one 440 µL then 431 µL aspirate/dispense repeated, on Marionette's
  staged method folder (copy it there, `sign.py` it, run `reload_tips.hsl` first): what Venus sends
  as `av/dv` from constant inputs (FIRMWARE_EQUIVALENCE §4);
- `empty.hsl`: an empty method;
- `pyhamilton_smoke.py`: pyhamilton's STAR_OEM path, end to end.

## Running the 1:1 tests (Venus ↔ PLR)

A 1:1 test runs the same thing in Venus's simulation and in PyLabRobot and compares Venus's own
numbers with PLR's. There are two. The `tests/` suite (pytest) is not one of them: it checks our
code against our reading of the files, and those readings have been wrong about what Venus does
(FIRMWARE_EQUIVALENCE §5).

| Test | What it proves | Compares | Passes when |
|---|---|---|---|
| **Position test** | a Venus layout imports to the right PLR geometry | Venus's position of every labware and position (`GetLabwarePosition`) with `lay_to_plr`'s | every position within 0.05 mm in X/Y and Z (`compare_sweep.py`'s "exact"), or its difference is a listed exception (FIRMWARE_EQUIVALENCE §2.4) |
| **Firmware test** | a translated method moves the instrument as the Venus method does | the firmware commands of both runs, field by field | every difference has a class in FIRMWARE_EQUIVALENCE §3.2 and a row in §4 (or the method's own section) |

### Before either test

1. **Two Pythons.**
   - The repo's Python, with the `venus-plr` PyLabRobot worktree first on `PYTHONPATH` (other
     checkouts have older driver APIs). Runs every script except `run_probe.py`.
   - `paths.PYTHON32` (32-bit, pythonnet). Runs `run_probe.py`, which drives Venus.
2. **Environment** (PowerShell; the defaults in `paths.py` fit the original machine):
   ```
   $env:PYTHONPATH = "<venus-plr worktree>;."
   $env:VENUS_INTEROP_CORPUS = "<corpus folder>"      # position test
   $env:VENUS_INTEROP_NIST = "<lmsf_hamilton checkout>"  # Marionette
   $env:PLR_VENUS_FAITHFUL_CFG = "<HAMILTON>\Config\ML_Starlet.cfg"  # firmware test: Venus's defaults
   ```
   `PLR_VENUS_FAITHFUL_CFG` (AGENTS.md) makes PLR use the Venus run's defaults where a port gives
   none: the instrument `.cfg` that run used, or `stock`. `marionette_plr_firmware.py` sets it to
   `ML_Starlet.cfg` when it isn't set.
   Run from the repo root.
3. **Venus in simulation:** the Setup section above. The STAR2-deck layouts in the corpus ran with
   simulation set only in `ML_Starlet.cfg`. If a run reports "No connection, check the cable", set
   `SimulateMode` in the config its trace names (FIRMWARE_EQUIVALENCE §2.1).
4. **Back up first:** every Venus file you change goes to `<work>/backup` before you change it.

### Position test

```
python tools/venus_sim/select_sweep.py > <work>/sweep/todo.txt     # layouts that add something new
python tools/venus_sim/sweep.py (Get-Content <work>/sweep/todo.txt)   # ~20 s per layout, unattended
python tools/venus_sim/compare_sweep.py                                # all of <work>/sweep/out
```
- **One layout:** `python tools/venus_sim/sweep.py <hash>`, then `compare_sweep.py <hash>`. The
  hashes are the corpus's `raw/<hash>.lay` names.
- **Choosing layouts:** the corpus repeats itself (copies of the same decks), so sweeping it in
  order mostly re-measures labware already checked: 20 layouts past the pilot added 543 labware
  and nothing new. `select_sweep.py` picks the fewest layouts that cover every (rack, `ZTransValue`,
  angle, carrier) not yet in `<work>/sweep/out`. Rerun it after each sweep; an empty answer means
  the corpus is covered.
- **What `sweep.py` does per layout:** copies the layout, adds its missing labware to the Venus
  install (new files only, listed in the manifest), generates and signs a probe, runs it, and
  keeps the trace in `out/<hash>.out`. Its line per layout is `ok`, or `NOT COMPLETE` (see the
  failure classes in FIRMWARE_EQUIVALENCE §5).
- **Reading the result:** `compare_sweep.py` prints the exact count, then the Z differences grouped
  by (`ZTransValue`, PLR − Venus, tip rack), then the X/Y misses. Per-labware rows go to
  `<work>/sweep/deltas.tsv`. A group is a candidate rule: test it against every row before
  changing the importer, then add a test with Venus's numbers (as
  `tests/test_plr.py::test_ztrans_value_says_what_ztrans_measures` does).
- **When a layout fails** (`NOT COMPLETE`), read `<work>/sweep/out/<hash>.out`:
  - **empty** (the 32-bit Python crashed, no Venus error): a missing cover `.lid` (the closure now
    copies covers), or a probe too large (`sweep.MAX_CALLS` splits it). For anything else, bisect
    with `trim_sweep.py`, always keeping the wastes, or the next class hides the crash;
  - **"The instrument configuration ... does not match"**: modules or wastes the simulator config
    and the layout disagree on (FIRMWARE_EQUIVALENCE §2.2), e.g. a layout without the 96-head's
    waste;
  - **`ERR|<labware>|...` lines** with the rest measured: Venus rejects that one labware.
- **Not covered:** heights that exist only in firmware (`MaxDepth`, `LSHt`, the pick-up stroke,
  gripper widths) need the firmware test or a probe. Decks built in PLR and exported
  (`deck_export`) aren't swept yet: `sweep.py` takes corpus layouts only.

### Firmware test (Marionette)

```
python tools/venus_sim/stage_marionette.py
# the ComTrace's line count now -> <work>/marionette_comtrace_start.txt:
(Get-Content "<HAMILTON>\LogFiles\ComTrace_Simulator<yyyymmdd>.trc").Count
<python32> tools/venus_sim/run_probe.py <work>/marionette/reload_tips.hsl 120     # tip counters persist: every run
<python32> tools/venus_sim/run_probe.py "<work>/marionette/Marionette protease.gradient plate prep.v5.hsl" 1500
python tools/venus_sim/marionette_plr_firmware.py      # PLR's run -> <work>/phase3/marionette_plr.fw
python tools/venus_sim/compare_firmware.py --extract   # Venus's commands from the ComTrace, then the comparison
```
- **Same inputs on both sides:** the parameters CSV (`stage_marionette.py` writes it from the
  demo's `Parameters`), NIST's liquid classes in `Config\ML_STARLiquids.mdb`, and full tip racks.
- **Reading the result:** per command code, the counts, then each field that differs, paired in
  order. Classify each difference against FIRMWARE_EQUIVALENCE §4's table. A difference with no
  row there is a configuration item to add to §2, or a translation bug.
- **Another method:** copy `stage_marionette.py` and `marionette_plr_firmware.py` for it.
  `compare_firmware.py` reads the fixed file names `marionette_venus.fw` and `marionette_plr.fw`
  in `<work>/phase3`; generalize it when the second method arrives.

### After

- Put back what was swapped in for the test: the liquid-class `.mdb` from
  `<work>/backup/ML_STARLiquids.mdb.orig`; config files from their `.orig`.
- Labware the sweep added stays (decided) and is listed in `paths.LABWARE_MANIFEST`.
- Record new rules and exceptions in FIRMWARE_EQUIVALENCE (§2.4 spatial, §4 per method, §7 open
  work), each with the Venus numbers it rests on.
