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

Probes in `probes/` (our own; `sign.py` adds the footer when staged):
- `marionette_reload_tips.hsl`: the operator's tip reload before each Marionette run;
- `eject_patterns.hsl`: tip eject per channel pattern;
- `empty.hsl`: an empty method;
- `pyhamilton_smoke.py`: pyhamilton's STAR_OEM path, end to end.

## A Marionette comparison

```
python tools/venus_sim/stage_marionette.py
# note the ComTrace line count into <work>/marionette_comtrace_start.txt, then:
<python32> tools/venus_sim/run_probe.py <work>/marionette/reload_tips.hsl 120
<python32> tools/venus_sim/run_probe.py "<work>/marionette/Marionette protease.gradient plate prep.v5.hsl" 1500
python tools/venus_sim/marionette_plr_firmware.py
python tools/venus_sim/compare_firmware.py --extract
```
