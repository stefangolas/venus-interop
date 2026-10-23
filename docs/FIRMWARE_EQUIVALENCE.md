# Firmware equivalence: a Venus method against its PLR translation

How to check that a translated method makes the instrument do what the Venus method does. Both run in
simulation, and the firmware commands each sends are compared field by field. Per-function port tests
(`tests/*_port.py`) are scaffolding. The acceptance check is this one, run on each shipped method.

The work is in two parts. **Configuration**: the two runs must start from the same instrument, deck,
labware, liquid classes and stored state. Most of this guide is that, because every unaligned item
turns into a firmware difference that looks like a translation bug. **Comparison**: pair the
commands and sort each difference as expected, explained by configuration, or a bug.

## 1. The run, end to end

The harness is `tools/venus_sim/`. Its README covers setup (the 32-bit Python, environment
variables, the Venus configuration) and, under "Running the 1:1 tests", the exact commands and
pass criteria for both tests. This section is why each step is there. Locations come from `paths.py`. Everything the scripts write goes
to a work folder outside the repo (`VENUS_SIM_WORK`, default `~/venus-sim`): staged copies of other
people's methods, traces, backups of Venus files.

| Step | Automated by | Manual part |
|---|---|---|
| Stage | `stage_marionette.py` (per method; copy it for a new one) | find the method's hard-coded paths and input files (§2.9) |
| Labware | `labware_closure.py --copy`, `labware_siblings.py` | files in neither the corpus nor the install: find them or skip the layout |
| Stored state | `probes/marionette_reload_tips.hsl` (staged and signed by `stage_marionette.py`) | which counters the method reads (grep `TipCount::Read2`, `GetTipCounters`) |
| Venus run | `run_probe.py` under `paths.PYTHON32` | note the ComTrace line count first (`<work>/marionette_comtrace_start.txt`) |
| PLR run | `marionette_plr_firmware.py` | the same parameters, counters and liquid classes as the Venus run |
| Compare | `compare_firmware.py --extract` | classify every difference (§3.2) |
| Spatial check | `sweep.py`, `compare_sweep.py` (§5) | read the groups; turn each into a rule |
| Probes | `stage_probe.py`, `probes/*.hsl` | write a probe for each new Venus behaviour |

1. **Stage the method** in a folder of its own (`stage_<method>.py`):
   - copy the `.hsl/.sub/.stp/.res` and the layout, under the file name the method declares
     (`global device ML_STAR ("<name>.lay", ...)`);
   - follow the `#include` closure from the method's folder, then the Venus `Library`, then the
     source repository, and copy whatever comes from the repository;
   - convert text files back to CRLF where that makes the checksum footer verify (a git checkout
     has LF line endings; Venus's checksums are over CRLF);
   - repoint hard-coded input paths and re-sign the file (`venus_interop.files.footer.rewrite`);
   - write the method's input files (§2.9).
2. **Set the stored state** (§2.8). For tip counters, run a reload method through Hamilton's API.
3. **Run Venus headless.** Use 32-bit Python, `RunHSLExecutor.dll` through pythonnet, then
   `StartMethod(path)`. The call returns once the run has started, so keep the process alive and
   poll the run trace (`HAMILTON\LogFiles\<stem>_<guid>_Trace.trc`) for `End method - complete`,
   `Abort method` or `- error;`. 64-bit HxRun waits for a manual Start button press, so it can't
   run headless.
4. **Capture Venus's firmware** from `LogFiles\ComTrace_Simulator<yyyymmdd>.trc`:
   - note the line count before the run and take the lines after it;
   - `<` lines are what Venus sent, `>` lines are the simulator's replies.
5. **Run the PLR translation** on `STARDevice(simulation=True)` with the same parameters, liquid
   classes and counters:
   - wrap the simulator's `_log_exchange` to record each assembled command;
   - use the `venus-plr` PLR worktree on `PYTHONPATH`, since other checkouts have older driver APIs.
6. **Compare** (`compare.py`):
   - pair commands of one code in order and compare each two-letter field;
   - normalize first (§3.1).
7. **Classify every difference** (§3.2). A new difference with no row in §2 is either a
   configuration item to add to §2 or a translation bug.

Never run `HxCfgFilConverter.exe`: it sends {ENTER} to whichever window has focus. Back up every
Venus file before changing it, and keep a manifest of files added to the Venus install.

## 2. Configuration map

Each row: where Venus keeps the setting, which firmware fields it reaches, where PLR keeps it, and
how to align the two for a test.

### 2.1 Instrument type and config file
- **Venus:** the layout's instrument (`ML_STAR`) together with the deck file decide the config file:
  `Config\ML_STAR.cfg`, `ML_Starlet.cfg` or `ML_FlexStar.cfg`. Each has its own `SimulateMode`
  key, and the matching `ML_*_Simulator.cfg` holds the simulator's canned replies.
- **Symptom when wrong:** "No connection, check the cable" means the config Venus actually uses
  has `SimulateMode=0`.
- **Align:** find which config the run reads (the error names the instrument; the run trace header
  names it too) and set simulation there.

### 2.2 Installed modules: 96-head, iSWAP, autoload, channel count, grippers
- **Venus asks the instrument.** At run start it sends `C0QM` (extended configuration) and `C0RM`
  (configuration), then overwrites `CoRe96Head`, `NumberOfChannels` and the rest in the `.cfg` with
  the answers. **Editing the `.cfg` is undone on the next run.**
- **In simulation the answers come from `ML_*_Simulator.cfg`**, under keys `C0QM` and `C0RM`. Edit
  those values (use `venus_interop.files.hxcfg`, which round-trips byte for byte).
- **Bits** (decoded as in PLR `master.request_device_configuration`):

  | Field | Bit | Meaning |
  |---|---|---|
  | `ka` (hex) | 0 | left X-drive large |
  | `ka` | 1 | 96-head |
  | `ka` | 2 | right X-drive large |
  | `ka` | 3, 4 | pump stations 1 and 2 |
  | `ka` | 7, 8 | left and right covers |
  | `xl` (left arm byte) | 0 | PIP channels |
  | `xl` | 1 | iSWAP |
  | `xl` | 2 | 96-head |
  | `xl` | 3 | nano pipettor |
  | `xl` | 4 | 384 head |
  | `xl` | 5 | XL channels |
  | `xl` | 6 | tube gripper |
  | `kb` | 0 | 1000 µL PIP |
  | `kb` | 1 | iSWAP |
  | `kb` | 2 | front-cover monitoring |
  | `kb` | 3 | autoload |
  | `kb` | 4, 5 | wash stations |
  | `kp` | – | channel count |

- **Symptom when missing:** "The instrument extensions for this command is not installed (CO-RE 96
  Head module)".
- **PLR:** `STARDevice(declared_configuration_json=...)` declares the configuration. In simulation
  it is answered from `simulated_configuration`.
- **Align:** make the simulator's `C0QM`/`C0RM` replies match PLR's declared configuration. For
  Marionette (a STARlet with a 96-head) that means `ka000002` and `xl05`.

### 2.3 Deck and layout
- **Venus:** the `.lay` file and the `.dck` it references, which sets the tracks and the raster
  (`DeckRaster = 22.5`).
- **PLR:** `VenusDeck(corpus, layout)` builds the same deck.
- **Align:** use the same `.lay` on both sides.
- **Labware absent at start:** the demos read this from the method's real trace (`clear_absent`),
  while Venus simulation places everything in the layout. The two agree only when the trace's
  absences don't touch the compared steps; otherwise give both sides the same list.

### 2.4 Labware definitions (`.rck .ctr .lid .tml .tpl .hxx .x`)
- **Venus:** read from `HAMILTON\Labware`. A missing file stops the run.
- **Firmware fields they set:**
  - LLD search start `lp`: the container top;
  - minimum height `zx`: the bottom;
  - liquid surface without LLD `zl`;
  - second-section height and ratio `zu`/`zr`: a conical bottom;
  - tip pick-up heights `tp/tz`: rack height plus tip fitting;
  - eject heights;
  - gripper widths `yo/yg`: the plate or lid size.
- **The spatial model, from Venus's own numbers.** Positions from the sweep (§5); firmware from
  Marionette and the probes.
  - **The container floor** is what Venus reports as a position's Z
    (`ML_STAR.GetLabwarePosition`, `HSLLabwrAccess::AbsolutePositionValuesGetForLabwareID`). It
    depends on the placement's `ZTransValue`, which says what the stored `ZTrans` is measured from:

    | `ZTransValue` | Stored `ZTrans` is | Floor | Pilot (22 layouts) |
    |---|---|---|---|
    | 1 | the rack's bottom | `ZTrans` + `Cntr.1.base` + `BaseMM` | 316 of 322 labware |
    | 0 | the container base | `ZTrans` + `BaseMM` | 64 of 64 |
    | 2 | the floor itself | `ZTrans` | 112 of 131 |

    **Applied** (`plr_import.z_above_bottom`, used by `venus_corner` on import and by
    `plr_export` and `deck_export`, which write a value-2 `ZTrans` as the floor). Before, the
    importer read all three as the rack's bottom, and value-2 tip racks were 40.9 to 83.5 mm too
    low in PLR (their `Cntr.1.base` is negative). With it the pilot is 481 of 517 exact, up from
    362; with the negative-base fix below, the whole sweep's only misses are rotated labware.
  - **`BaseMM`** (`.ctr`) is material under the floor. Half the installed `.ctr` files have one
    (0.5 to 10 mm). It's carried as the well's `material_z_thickness`, so PLR's `cavity_bottom` is
    Venus's floor (import, export and generator).
  - **Minimum height** `zx` = floor + the `.ctr`'s `MaxDepth` (the deepest the channel may go).
  - **LLD search start** `lp` = floor + the `.ctr`'s `LSHt`.
  - **Fixed liquid height** `zl` (no LLD) is measured from `zx`, not from the floor.
  - **Tip pick-up:** see §2.7 (the same `MaxDepth`, with base and no `BaseMM` in Hamilton's tip
    containers).
  - These three firmware rules were exact on three plates (`Media_source`, `Reagent_Stock_Plate`,
    `Growth_Plate`). **Applied (2026-10-22)** under `PLR_VENUS_FAITHFUL_CFG`: the importer puts
    `MaxDepth` and `LSHt` on each well (`metadata["venus"]`), and `steps.venus_heights` passes
    `zx` and, with cLLD off, `zl`. Venus measures `zl` from `zx` as sent (rounded to 0.1 mm):
    dispenses at 0.3 mm read `zx` 181.0, `zl` 181.3. Marionette: `zx` matches on all 128
    aspirates and dispenses, `zl` on all 24 without LLD. `lp` waits for the faithful LLD (the
    driver sets it from the container top, with no argument for it). Test:
    `test_venus_heights_from_max_depth`.
- **A negative `Cntr.1.base` is used as it is** (resolved 2026-10-22). The containers hang below the
  rack's bottom: filter and binding plates (spouts below the skirt), the 96/384-head wastes (the chute
  below the deck). These were the pilot's 25 "exceptions", and 11 more in the wider sweep; each was
  off by exactly −base:
  - Agilent filter plates −3.0, Nunc binding plates −6.8, Varian Captiva filter plates −21.6;
  - slide wastes −22, `ver_96externalwaste`/`core96externalwaste`/`starpluscore96waste` −22.5,
    whatever the `ZTransValue`.

  The importer had clamped the wells' base at 0 (`max(base, 0)`, from the first commit, no recorded
  reason) while tip racks used it raw. Without the clamp the 73 swept layouts are 1,825 of 1,836
  exact, with no Z miss left. Test: `test_a_negative_container_base_hangs_below_the_rack`.
  - **Lesson:** two misses that "Venus treats specially" were one rule applied inconsistently in our
    code. Before calling something a Venus special case, check every place our code reads the same
    field.
- **Rotation** (`Angle` 90/180/270; resolved 2026-10-22). Venus turns a rack about its position 1
  (`TForm.3`) by the matrix in `TForm.1/2`: a position `(lx, ly)` from position 1 in the rack's own
  frame lands at `TForm.3 + lx·TForm.1 + ly·TForm.2`. `Angle` 90 is `TForm.1 = (0, −1)`: a quarter
  turn clockwise seen from above, PLR's `Rotation(z=−90)`.
  - **Import:** `plr_import.venus_corner` turns the origin about position 1, and `place` sets
    `Rotation(z = −Angle)`. Labware nested under a turned plate is placed in that plate's frame,
    with its rotation relative to the plate's (`_attach`).
  - **Position 1 with `IX.Start = 1`** is the front-left position, and rows count toward the back
    (`rules.placement.a1_offset`, `default_grid`). This was CONVENTIONS §3's open question. The
    wells take Venus's names, so a portrait plate turned 90° is the landscape plate it shows
    (`Ans_96_C18_SPE`: `A1` back-left, letters toward the front).
  - **Evidence:** all 11 rotated labware in the sweep are exact (0.000 mm), and so are the 3
    nested under them. With this, the 73 swept layouts are 1,836 of 1,836 exact. Test:
    `test_rotated_racks_turn_about_position_1`.
  - **Not measured:** rotated carriers (warned on import), and a rotated plate's lid (its stored
    corner is kept).
- **PLR:** `DefinitionStore` reads the same files.
- **Align:** give both the same files:
  - `labware_closure.py` copies a layout's missing files and everything they refer to from the
    corpus;
  - `labware_siblings.py` copies containers and lids that are named without a folder (Venus looks
    beside the referring file);
  - both scripts write a manifest so the additions can be removed later.

### 2.5 Liquid classes
- **Venus:** `Config\ML_STARLiquids.mdb` (Access).
- **What a class sets:**
  - aspirate and dispense speeds `as/ds`;
  - the volume correction curve: `av/dv` are corrected volumes;
  - transport air `ta`, blow-out `ba`, settle times `wt`;
  - swap speed, mix speed `ms`, pull-out distance `po`;
  - the dispense mode `dm` when the step says "from liquid class";
  - LLD sensitivity `ll`.
- **Venus checks** that the class matches the step's tip type and dispense mode, and errors
  otherwise.
- **PLR:** `VenusLiquidClasses.from_json`. `tools/liquid_classes.py` exports the `.mdb` to JSON.
  Without that file PLR falls back to its own STAR table, which differs.
- **Align:** swap the method's own `.mdb` into `Config` (back up the original) and export the same
  file for PLR.

### 2.6 Step settings from the `.stp`
- **Where:** each device step's `.stp` record holds the settings that aren't in the liquid class:
  - LLD mode `lm` (cLLD, pLLD, or none / "from labware");
  - submerge depth `ip`;
  - liquid following `fp`;
  - dispense position;
  - channel pattern;
  - the tip-eject target.
- **PLR:** the ports read the same `.stp` records, and must carry each setting into the PLR call.
- **Align:** nothing to configure. A difference here is a translation bug.

### 2.7 Tip types
- **Venus:** sends its whole tip-type table at run start (`C0TT`, 53 definitions) and refers to tips
  by slot (`tt05` = 1000 µL with filter, 87.1 mm).
- **PLR:** defines only the tips it uses, starting from slot `01`.
- **Compare** the definition fields (`tf tl tv tg tu`), not the slot number.
- **Tip pick-up heights.** Venus takes them from the rack's container, not from the tip:
  - `tp` (where the pick-up begins) = rack Z + `Cntr.1.base` + the `.ctr`'s `Depth`, which is the
    tip's top;
  - `tz` (where it ends) = rack Z + `Cntr.1.base` + the `.ctr`'s `MaxDepth`;
  - so the stroke into the collar is `Depth − MaxDepth`: 10 mm for 1000 µL tips (95/85), 8 mm for
    300 µL tips (60/52).
  - Verified on Marionette's CO-RE II supports: 231.0/241.0 and 231.5/239.5.
  - **PLR** puts `tz` at the tip spot and `tp` at `tz` + the tip's `collar_height` (10).
  - **Fixed:** the converter put the spot at `base + tip length − fitting depth (8)`, 2.1 mm high on
    1000 µL tips. It now sets the spot at `base + MaxDepth` (`plr_import.build_rack`, `generate.py`),
    and the export writes `MaxDepth` (`to_venus`). PLR's own 1000 µL rack now round-trips through
    Venus's `HT_L.rck` exactly.
  - Still different: `tp` on 300 µL tips, PLR's collar (10) against Venus's `Depth − MaxDepth` (8).
- `td` is the pick-up method: 0 = the tip type's own (`C0TT`'s `tu`), 1 = out of rack, 2 = out of
  wash liquid (Hamilton's firmware spec, quoted in PLR's legacy backend). Venus sends 1; PLR sends
  `TipPickupMethod.value`, whose 0 (out of rack) means "the tip type's" in `td`. **PLR bug:** the one
  enum serves `tu` (0 rack, 1 wash) and `td`, so `OUT_OF_WASH_LIQUID` sends `td1`, out of rack.
- **One command per pick-up.** Venus sends one `C0TP` for a step, whatever columns its channels'
  tips are in; the firmware works through them. PLR's planner (`plan_batches`) splits a pick-up
  whose channels cross in Y, even across columns. `PLR_VENUS_FAITHFUL_CFG` makes it one command per
  call and tip model (`faithful._one_command`).

### 2.8 Stored state: tip counters, sequences, files
- **Tip counters**
  - **Where:** `HAMILTON\System\HxElementCounter.mdb`. Simulation counters are stored apart from the
    instrument's (`SimulationPositions` vs `Positions`), so simulation never changes production
    counts.
  - **Venus API:** the method reads with `TipCount::Read2` and writes back with `TipCount::Write2`
    at its end and on abort. **Counts carry over between runs**, so a second run starts where the
    first one stopped.
  - **How production refills them:**
    - the **Edit Tip Count** dialog (`TipCount::Edit2` → `EditSequences`), where the operator marks
      reloaded racks;
    - or a loading step that calls `Write2` with full racks. NIST's scheduler owns its `_auto`
      counters this way, and Marionette's `Edit2` is compiled out (`if(0)`).
- **Test procedure:**
  - before each Venus run, run a reload method (`reload_tips.hsl`) on the method's layout. It calls
    `CopyResetSequence` and then `TipCount::Write2` for each counter the method reads. This is
    Hamilton's own API, the same thing an operator's reload does.
  - give PLR the matching state (`TipCounters`; "no counter stored" reads as the layout's full
    racks).
  - don't delete rows from the database.
- **Other carried state:**
  - sequence and counter files the method writes;
  - append-mode output files, which Venus reads back from the start;
  - the HxVectorDb (kept off: `Config\HxVectorDb.cfg`).

### 2.9 Method inputs
- **Front-end parameter files:** reproduce the exact text the front end writes. Marionette compares
  `isPipetting == "true"`, and writing `1` silently skips the pipetting.
- **Key names built at run time** (`"inducer2_" + n + "StockConc"`) have to be present in the file.
- **Paths:** use absolute paths without `\v` (a Venus `schema.ini` quirk).
- **Dialogs:** answer them with a timeout or a default on both sides, and use the same answers.
  - **Decided (user, 2026-10-22):** two configurations.
    - **Headless**, for rapid tests: a staged method copy whose dialogs return fixed answers, the
      same answers the interpreter tests use. A documented, mechanical edit, like the parameters
      path.
    - **Headful**, for live production runs: the real dialogs.
  - Not built yet. Avenio needs it first (worklist, mastermix, process selection, loading dialogs).

### 2.10 Traverse heights and moves between steps
- **Venus** reads these from the instrument `.cfg`: `TraverseHeight = 245.0`,
  `Head96TraverseHeight`, `ZSwapTraverseHeight = 275.0` (the gripper), and others. They become `th/te`.
- **PLR (the `venus-plr` driver)** is driven by the same 245.0 default
  (`default_minimum_traverse_height`), but `th` doesn't always show it:
  - **Aspirate and dispense with capacitive LLD.** The driver doesn't hand LLD to the firmware. It
    raises the channels and moves the arm itself, runs each channel's liquid search itself, then
    sends `C0AS/C0DS` with LLD off (`lm0`), starting at the surface it found (`th` = `zl` = that
    surface, 146.0 here).
    - This accounts for most of PLR's extra traffic: `P?RZ/RD/ZA/ZL`, `C0RY/RZ/JY`, `X0XP`.
    - Venus sends one `C0AS` with `lm1` and lets the firmware search.
    - The firmware streams can't match until the driver can leave LLD to the firmware. That would
      be a driver option; this driver has none (any `CAPACITIVE` mode is searched in software).
    - **Built (2026-10-22), as a driver option** (the user's choice over a wrapper on private
      APIs): `firmware_lld` on `aspirate`/`dispense` in the `venus-plr` fork
      (`default_firmware_lld` on the pipettes). It skips the driver's search, sends the LLD mode
      in the command, draws the blow-out air in it, takes `lld_search_heights` (`lp`) and a
      liquid height beside an LLD mode (`zl`). The tracker books the volumes as given.
      `PLR_VENUS_FAITHFUL_CFG` turns it on (`faithful.apply`), and `steps.venus_heights` passes
      `lp` = floor + `LSHt` and `zl` = `zx` as sent + the step's height, with LLD or without.
    - **Result on Marionette:** `lm`, `lp`, `th`, `zl` match on all 64 aspirates and 64
      dispenses; PLR sends 4,424 commands, down from 6,352 (no search traffic).
  - **Tip pick-up and eject.** The driver travels as high as the mounted tips allow
    (`_tip_traverse_height` with no height given: Z range top − tip overhang = 247.6 for 1000 µL
    tips), never below 245.0. Venus uses 245.0.
  - **Gripper:** 280.0 against Venus's 275.0 (`ZSwapTraverseHeight`) for gripping and placing. Taking
    and returning the tools (`C0ZT/ZS`) is a channel move: Venus travels at `TraverseHeight`, 245.0.
  - **Align:** `PLR_VENUS_FAITHFUL_CFG` (AGENTS.md; `venus_interop.plr.faithful`) set to the Venus
    run's instrument `.cfg` fills `TraverseHeight`, `ZSwapTraverseHeight` and `Head96TraverseHeight`
    wherever a port passes none. The same variable will carry the faithful LLD.

### 2.11 Waste and tip eject
- **Venus:** `DefaultWaste = Waste` in the `.cfg` names the layout's `Waste` labware
  (`ML_STAR\CORE\waste2.rck`: 16 positions 12.5 mm apart, flagged `MlStarIsSpecialEject`).
  Ejecting to it:
  - spreads the 8 channels over the whole waste: `yp` 405.0 → 217.5, 26.8 mm apart, from the first
    position to the last;
  - ejects low into the chute: `tp` 197.0, `tz` 187.0 with the waste at Z 186, the same for both
    tip sizes.
- **Rule, probed with the STAR_OEM toolkit** (channel patterns 1, 2, 4 and 8 channels, sparse;
  the waste moved and re-heighted):
  - channel *n* always goes to the *n*-th of 8 points spread evenly from the waste's first position
    Y to its last (405.0 … 217.5, step −26.79), whatever the pattern; only `tm` changes;
  - `xp` = the waste's X;
  - `tz` = the waste's container floor (rack Z + `Cntr.1.base` + `BaseMM`; with `ZTransValue` 2,
    the stored Z itself), and `tp` = `tz` + 10;
  - `th` = `te` = 245.0, `ti0` (PLR's `PLACE_SHIFT`).
- **Ejecting into a rack** (`UseDefaultWaste=0`, back to the tips' own positions): `tz` = the
  container base, 85.0 below the pick-up, and `tp` = `tz` + 10.
- **NGSStar ejects into a sequence its caller passes** (`UseDefaultWaste=0`), not the default
  waste. That case is not yet probed.
- **PLR:** `discard_tips` uses the same place (the trash area is the layout's `WasteBlock` site,
  y 207.5–415, z 186). But it spreads the channels tight (9 mm) around the centre and lets go
  49 mm higher (`PLACE_SHIFT`). That's a policy difference, not geometry.
- **Done:** `steps.eject_to_waste` does this. The demos' `install()` records the waste's first and
  last positions and its floor on the trash, and GSF-IMS's `tip_eject` uses it. Marionette's 18
  ejects now match Venus field for field.

### 2.12 CO-RE gripper
- **Fields:**
  - the channels used `pa/pb`. Venus uses 7 and 8; NIST's library moves the front channel. PLR's
    indices are 0-based in its API, so check the off-by-one;
  - grip widths `yo/yg`: from the labware;
  - grip speed `yv`, grip strength `yw`;
  - heights `zj`, traverse `th/te`;
  - the gripper tool's position on the waste.

### 2.13 Initialization and queries
- **Venus at start:**
  - queries `RQ QB RI QM RM RF` and each channel's `RF/RJ/RV`;
  - defines tip types (`C0TT`);
  - initializes the 96-head (`C0EI`) and the channels (`C0DI`).
- **PLR** has its own discovery sequence.
- **Compare from the method's first action**, not from setup.

### 2.14 Simulation answers
- The simulator answers sensing from canned values in `ML_*_Simulator.cfg`:
  - liquid heights (`C0RL`);
  - tip presence (`C0RT`);
  - barcodes (`Barcode01`, ...).
- Branches that depend on what was sensed take the canned path on the Venus side. Give PLR the same
  answers.

### 2.15 Not yet exercised by a compared method
Check each of these when a method first uses it:
- **iSWAP:** `kb` bit 1, the `R0` module, `C0PP/PR`. Grip directions and arm stops; see the iSWAP
  notes.
- **Autoload and carrier barcodes:** `C0CI/CL/CR`, with canned barcodes.
- **384 head, XL channels, tube or puncher grippers:** `xl` bits.
- **pLLD, dual LLD, TADM:** TADM curves live in a separate `.mdb`; pLLD is `lm2`.
- **Wash stations, pump stations, temperature-controlled carriers:** `ka`/`kb` bits and their
  `.cfg` keys.
- **Devices not on the STAR link:** heater-shakers, ODTC, readers. They talk over USB or TCP, are
  absent from the ComTrace, and need their own capture.
- **CO-RE II and 96-head tip supports, offset pick-up.**
- **Runtime deck edits:** `SetLabwarePosition`, moving labware IDs, `CopyResetSequence` on edited
  sequences.
- **Instrument-specific `.cfg` keys:** channel spacing, Y limits, and
  `Head96MinYPos/MaxYPos/MaxZPos`.

## 3. Comparing

### 3.1 Normalize before comparing
- **Drop the `id` field.**
- **Expand shortened lists:**
  - Venus ends a per-channel list early when the remaining values repeat the last one
    (`as2500&` means 2500 on every channel, `tm1&` means all 8 channels);
  - PLR writes every channel;
  - expand both lists to the channel count.
- **Compare only channels on in `tm`.** Inactive channels carry 0 on one side and defaults on the
  other.
- **Pair commands by code, in order.** For codes whose count differs, read the commands around the
  first mismatch.

### 3.2 Classes of difference
- **Configuration:** a §2 row explains the difference. Align the item, or record it as a known
  difference.
- **Expected:** PLR does something Venus doesn't, and the method doesn't depend on it, such as PLR's
  safe-travel queries or slot numbering.
- **Bug:** anything else. Fix the port and rerun.

## 4. Marionette (NIST, plate 3): first full comparison, 2026-10-22

Venus completed the run in simulation: 181 device steps, 379 commands sent. PLR sent 6,363 at
first, most of them position queries and its own liquid searches; 4,424 now, with
`PLR_VENUS_FAITHFUL_CFG` set (`marionette_plr_firmware.py` sets it).

**State (end of 2026-10-22):** every count, position, height, channel pattern and tip command
matches, and every pipetting field except those in the second table. Tip eject `C0TR` matches field
for field.

**Fixed, with what fixed it:**

| Fields | Venus | PLR was | Fix |
|---|---|---|---|
| `C0TP` count 18 vs 19 | one command, channels 1-4 at X 770.5 (rows E-H), 5-8 at X 779.5 (rows A-D) | two: the planner splits channels that cross in Y | one `C0TP` per call and tip model (§2.7) |
| `tp/tz` on pick-up (+2.1 mm, 1000 µL) | rack + `MaxDepth` / `Depth` | rack + tip length − 8, + 10 | the spot at base + `MaxDepth` (§2.7) |
| `th/te`, tips and tools | 245.0 (`TraverseHeight`) | 247.6 / 280.0 | the profile (§2.10) |
| `th/te`, gripping | 275.0 (`ZSwapTraverseHeight`) | 280.0 | the profile (§2.10) |
| `C0TR` | spread over the waste, `tz` 187.0, `yp` cut to 0.1 mm | tight at the centre, `tz` 235.9; then `yp` rounded | `steps.eject_to_waste` (§2.11) |
| `lm`, `th`, `zl`, `P?Z*` traffic | firmware cLLD (`lm1`) | the driver's own search, then `lm0` | `firmware_lld` (§2.10) |
| `zx` | floor + `MaxDepth` | the cavity bottom | `steps.venus_heights` (§2.4) |
| `lp` | floor + `LSHt`, LLD or not | the container top | the same |
| `zl` | `zx` as sent + the step's height | from the cavity bottom | the same |
| `zu zr` | 0 / 0 (one-segment containers) | a 3.2 mm cone, PLR's default | the same; several segments unmeasured |
| `as` in 25 of 64, `av/dv` in 22 of 37 | the 300 µL class (100 µL/s) | the 1000 µL class: a 300 µL filter tip's 360 µL rounded to 400 | **port bug**, `gsf_ims._class`: the nearest tip size, from the rack's type even when the spot is empty |
| `po`, `zo` | 5.0, 0.5: the step record's `-534183622`, `-534183700` | 10.0, 0.0 | `Pipetting.pull_out/touch_off`, sent under the profile; the keys named in `stp_pars` (one value each measured) |
| `ms` with no mix | the class's mix flow (500) | 100.0 / 1.0 | a zero-cycle `Mix` at the class's rate, under the profile |
| `dm` | 3 (blow-out at the surface: Venus's "Empty") | 4 (PLR's `empty`, the tip emptied where it stands) | **port bug**: `blow_out` for the class's "Empty" |
| `av/dv`, one tie | 11.25 → 11.3 | 11.2 (`round`, half to even) | the fork rounds a half up |

**Left:**

| Fields | Venus | PLR | What is known |
|---|---|---|---|
| `av/dv` ±0.1, 15 of 64 | 456.8 or 456.9 for one nominal 440 µL, the same class | 456.8 | **Partly explained (probe `volume_probe.hsl`, 2026-10-22):** Venus carries the rounding remainder from one aspirate to the next at 0.1 µL (error diffusion); a dispense sends what its aspirate did. 12 × 440 µL then 8 × 431 µL, constant inputs: .8 .9 .8 .9 .8 .8 .9 .8 .9 .8 .8 .9, then .6 .6 .7 .6 .6 .6 .7 .6. A carry reset at the volume change gets 18 of 20 with PLR's corrected values; all 20 need Venus's 431 µL value at 447.6215–447.6249 against linear 447.621 (440 µL: 456.8389–456.8409, PLR 456.84), so Venus's curve departs from linear by about 0.002 µL there (a smoothed interpolation, the user's reading). Not a drive-increment carry (0.046876 µL). Open: the curve, and when the remainder resets (on Marionette the carry rules score below plain rounding, 98 vs 113 of 128) |
| `fp`, 39 + 42 of 64 | round(volume / container area, 0.1) where the area is the well's (`Growth_Plate`: all) | 0.1 (PLR's following) | Rule holds on `Growth_Plate`. `Media_source` and the liquid waste read a larger area (about 2,300 mm²): the reservoir's connected cavity, to check in its `.rck` |
| `mh`, 12 of 64 | the mix volume / the area (7.6 = 450 / 59.29) | 0 | The same rule, for the mix's following |
| `il`, `in` | sent, 0 | not sent | Expected: the firmware's default |
| `tt`, `td` | slot 05, `td1` | slot 01, `td0` | Expected: the same tip; both out of rack (§2.7) |
| `C0TT` | 53 | 2 | Expected (§2.7) |
| `C0Z*` widths, speed, force, `zj` | `yo` 88.0, `yg` 80.0, `yv` 277.0, `yw` 25, `zj` 187.3 | 83.0, 77.0, 5.0, 5, 186.7 | Gripper (§2.12). `yv` is likely `ZSwapGrippYSpeed` (277.8) in the `.cfg` |
| `C0ZR` `te` | 150.4 to 220.3, one per place | 275.0 | Open: per placed plate |
| `C0ZS/ZT` `tp/tz`, `pa/pb` | 215.0 / 205.0, channels 7/8 | 219.5 / 209.5, 6/7 (none on `ZS`) | Gripper tools: 4.5 mm, and the channel numbering |
| `C0ZA` | 1 | 5 | The 96-head and arm move: to compare |
| 96-head | `C0EI/EM/EV` | `H0` module commands | Command family: check the move targets |

## 5. The position sweep: checking the spatial layer against Venus

The spatial layer is the import of Venus layouts and labware into PLR geometry. It matters most,
because its errors crash real hardware. Check it against Venus itself, not against our reading of
the files: the tip-seat, `BaseMM` and `ZTransValue` rules all looked right from the files and were
wrong about what Venus does.

- **What it does:** for each corpus layout, `sweep.py` generates a probe that asks Venus, in
  headless simulation, for every labware's position and every position in it. `compare_sweep.py`
  builds the same layout with `lay_to_plr` and compares, per position, X/Y (centre) and Z (the
  container floor; for tips, the container base). It writes `<work>/sweep/deltas.tsv`, one row per
  labware with its file, carrier, site, `ZTransValue`, angle, `Cntr.1.base` and `BaseMM`, and prints
  the differences grouped.
- **How to read it:** labware sharing one Z difference and one `ZTransValue` are one rule. Test a
  candidate rule against every row (predicted − measured, as in §2.4's table) before changing the
  importer. An X/Y miss so far has always been rotation.
- **What it covers:** placement only, before any step runs. It does not cover:
  - heights that exist only in firmware (`MaxDepth`, `LSHt`, the pick-up stroke, gripper widths):
    use firmware probes;
  - runtime deck changes (transports, `HSLLabwrAccess` position edits): snapshot those during a
    method run (§7).
- **Position names** come from `rules.placement.default_positions`. Venus's own default-sequence
  call needs a sorting COM component (`Hamilton.ASW.SequenceSorting.Controller`) that a plain
  install lacks. A wrong name shows as an `ERR|` line, so the naming rule is tested too. The pilot
  had no naming errors.
- **Pilot (22 layouts chosen for coverage, 2026-10-22):** 16 ran, 517 labware measured, 362 exact.
  The rest:
  - `ZTransValue` 0 and 2 (§2.4's rule explains all but 25);
  - rotation (11);
  - the slide-waste and filter-plate "exceptions" (a negative container base, since fixed: §2.4).
- **Layouts that failed to run, and why:**
  - **missing labware** in both the corpus and the install ("Invalid file name ... .tml"). The
    pyhamilton test layouts, an Allen `ReaderLocations.tml`, a MultiFlex `.tml`. Skip and list them,
    or find the files;
  - **"The instrument configuration ... does not match the configuration reported by the
    instrument"**: the layout expects modules the simulated STARlet doesn't report. Declare them in
    the simulator config (§2.2), per layout;
  - **an empty output: Venus crashed while analysing the probe, with no error.** Two causes, both
    found by bisecting with `trim_sweep.py` (2026-10-22):
    - **a cover `.lid` missing from the install** (`Nunc binding ontop ... supporting plate.lid`).
      `labware_closure.py` copied only the placements' files, not their covers'. It now copies
      both;
    - **a probe too large:** 16,759 position calls (860 KB) crash, 8,932 run. `sweep.py` splits a
      probe into parts of `MAX_CALLS` (8,000) on the whole layout.
    Bisect with the wastes always kept: without the 96-head's waste the run stops at the
    configuration check, which hides the crash.
- **Beyond the pilot (2026-10-22):** the corpus has 149 STAR-family layouts, but it repeats
  itself. 20 more layouts in corpus order added 543 labware, 523 exact and 20 slide wastes: nothing
  new. So the sweep now runs on a covering set (`select_sweep.py`): the fewest layouts that hold
  every (rack, `ZTransValue`, angle, carrier) not yet measured. 105 layouts were left, 46 of them
  added anything, and 27 cover it all. None of those is rotated: rotation needs its own probes.
  These STAR2-deck layouts ran with simulation set in `ML_Starlet.cfg` only; `ML_STAR.cfg` stayed
  at `SimulateMode=0`.

## 6. Heuristics and lessons

- **Ask Venus rather than infer.** Write a probe for any rule that a coordinate depends on. Probes
  are cheap: a headless run takes 15–30 s. Use several data points: one sample fits several rules
  (the waste's +1 mm was `BaseMM`, not a constant).
- **Look for the number in the definition files.** An unexplained offset has so far always been a
  field: `MaxDepth`, `BaseMM`, `LSHt`, `Cntr.1.base`. Dump the `.rck` and `.ctr` and search for the
  value.
- **Watch for coincidences.** `Media_source`'s `zx` matched after the `BaseMM` fix only because its
  `ZTransValue` 0 offset equals its `MaxDepth` (both 4). Check a rule on labware where those fields
  differ.
- **Fix a rule in every converter at once:** the import (`plr_import`), the code generator
  (`generate.py`) and the export (`to_venus`). Also update CONVENTIONS and the delta ledger. A
  round-trip test that records a difference as expected can hide a bug: the 2.1 mm tip difference
  was in the ledger as "stock disagrees".
- **Separate geometry from policy from driver design.** Waste eject looked like a geometry error
  and was a policy (how channels are spread). LLD looked like a port bug and was the driver's
  design. Read the driver code for the field before blaming the port.
- **Configuration first.** Most first-run differences are configuration (§2), not translation:
  modules, parameter text, liquid classes, tip counters, labware files.
- **Venus rewrites some files on every run:** instrument `.cfg` module keys (from `C0QM`), tip
  counters (`Write2` at the end and on abort). Change them through what Venus reads (the simulator
  replies, a reload method), not by editing the result.
- **Production equivalents, not shortcuts.** To set state, do what an operator does, through
  Hamilton's API: the tip reload is `TipCount::Write2`, not a row deletion. That keeps the test
  setup meaningful and keeps the Venus install consistent.
- **Normalize firmware before comparing** (§3.1), or Venus's shortened lists show up as hundreds of
  false differences.
- **Keep Venus reversible:** a backup of every changed file in `<work>/backup`, a manifest of added
  labware, and a list of changes in HANDOFF. Simulation counters are separate from the
  instrument's.
- **Traps:**
  - `HxCfgFilConverter.exe` sends {ENTER} to the focused window;
  - a `\v` in a data path breaks Venus's `schema.ini`;
  - footers need CRLF, with the length field equal to the footer line's own length;
  - 64-bit HxRun needs a button press;
  - the `plr-viz3d` checkout is on another branch: put `plr-venus` on `PYTHONPATH`;
  - Venus's `Analyze` errors name the first missing file only.

## 7. Decisions and open work

- **Decided (user, 2026-10-22):**
  - a Venus-faithful LLD (§2.10): built as a driver option, `firmware_lld` (user, 2026-10-22);
  - headless and headful configurations for operator dialogs (§2.9);
  - the harness lives in this repository (`tools/venus_sim`);
  - labware may be added to the Venus install as tests need it (with the manifest).
- **Next, spatial:**
  1. ~~apply the `ZTransValue` floor rule in `venus_corner` and the export~~ (done, 2026-10-22);
  2. ~~carry `MaxDepth` and `LSHt` and use them for `zx`, `lp` and `zl`~~ (done 2026-10-22, with the faithful LLD);
  3. ~~derive and implement rotation~~ (done 2026-10-22: 1,836 of 1,836 exact);
  4. ~~explain the slide-waste and filter-plate exceptions~~ (a negative base, done 2026-10-22);
  5. ~~run the full corpus sweep~~ (done 2026-10-22, a covering set: 73 layouts, **2,065 of 2,065
     labware exact**; `select_sweep.py` finds nothing left). Two layouts still don't run and add
     nothing new: `f51e8a63c748` (no 96-head waste: the configuration check) and `dbeb40b4b449`
     (Venus rejects `Nunc_8WellDish_0001`; the rest measured);
  6. firmware probes per labware family for the derived heights;
  7. runtime snapshots: position dumps inserted after each transport and `HSLLabwrAccess` edit in a
     staged method, against the PLR deck after the same port call.
- **Next, firmware:**
  - the liquid-class fields (`as/ms/po/dm`, `av` ±0.1);
  - gripper `pa/pb` and widths;
  - the 96-head's command families;
  - NGSStar's eject into a sequence (`UseDefaultWaste=0`);
  - Avenio (headless dialogs, its own liquid-class `.mdb`).
