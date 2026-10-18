# Porting Venus libraries to PyLabRobot

How to turn a Venus method into Python on PLR that keeps its logic: port the **libraries** it calls,
one module each under `venus_interop/plr/libraries/`, then translate the method's own `main` call for
call. This file is the workflow, the toolkit it uses ([The toolkit](#the-toolkit)), how a method's
own code is translated ([Translating a method](#translating-a-method)), and what each port so far
needed ([Ports so far](#ports-so-far)). `plr/libraries/gsf_ims.py` and `plr/libraries/plate_and_lid.py`
are the clearest worked examples, with their checks in `tests/test_gsf_ims_port.py` and
`tests/test_plate_and_lid_port.py`; `examples/marionette_demo.py` and `examples/groq_seq_demo.py`
are the method translations.

## Why

Labs and companies that automate on Hamilton STARs often have hundreds of Venus methods, and that is
what keeps them from moving to PyLabRobot. The aim is to make migrating such a collection feasible:
each method becomes a readable PLR protocol its owners can change, with evidence that its logic
survived. Running Venus code on PLR unchanged is not the aim.

## What "equivalent" means

A port is checked to make the same protocol decisions as the HSL: which labware, wells and tips each
step uses, in what order, with the volumes and the step settings the test compares. It does not
reproduce how Venus executes a step. Motion planning (traverse heights, Z order, channel spacing)
and pipetting physics (liquid-class correction, how LLD settings become firmware fields) are PLR's
own. Settings whose meaning is still open (CONVENTIONS §11) are a best reading. Say so wherever a
port is described as matching Venus.

## What a port is

- One Python module per Venus library. Entry points keep their **Venus names and arguments**
  (sequences by name), so a method's `main` translates line by line.
- Not a line-by-line translation. Venus libraries are verbose: a local per setting, generated
  step markers, channel-pattern tables, trace calls. Find the few patterns they repeat and write
  those once. For example, GSF-IMS's 40 functions (1,281 lines) are one "fill" pattern plus a
  dilution series (242 lines), and PlateAndLidMovement's 62 functions (1,732 lines) are a grip table
  plus one plate move (135 lines).
- The state is where the real logic is: sequence positions, tip counters, tip supports, volumes.
  Sequence state is `methods/sequences.py`. Reuse PLR's trackers and pyhamilton's managed resources
  rather than writing new ones.
- **Protocol logic only.** Error-recovery branches, operator dialogs, trace output and the
  scheduler's file handshake become notes or stubs, not code. Output the method computes, such as a
  plate map and the worklist written from it, is logic and is translated (Marionette, GROQ-Seq).

## The workflow

1. **Find what is called.** Before reading a library, count which of its functions the methods
   actually call: whole families are often never called.

   ```
   python tools/trace_method.py --roots <Library> <Methods> --calls METHOD.hsl [...]
   python tools/trace_method.py --roots <Library> <Methods> --status METHOD.hsl [...]
   ```

   `--status` shows what the ports already cover. It walks each method's call tree and marks
   every library call:
   - `checked`: a port test runs it against the HSL;
   - `ported`: ported, not yet checked;
   - `out` or `method`: scope notes in `tools/function_notes.json`;
   - `open`: still to do.

   A call inside a covered one counts as part of it. Then it lists the open functions by how
   often they are called: that is the work queue. Count from these, not by grepping a trace: the
   condensed trace drops calls. `--status` sees library function calls only; it does not see:
   - PTL smart steps (folded into single steps);
   - device steps of other instruments (MPE², heater-shakers);
   - the method's own code.

   "0 open" therefore means the libraries are done, not the method.

   Calls into libraries the trace leaves unexpanded (hand-written HSL with no Method Editor
   steps, devices' COM wrappers such as `HSLThermoCytomat::` or `HSLMPELib::`) are counted from
   `Namespace::Function(` in code lines. Hamilton's own plumbing (`MECC`, `HSLExtensions`, ...) is
   excluded through `_system_namespaces` in `tools/function_notes.json`; extend that list when a
   new corpus brings more.

2. **Read the function as it runs.** `tools/trace_method.py --out DIR` writes each method's trace:
   `main` with every library function inlined, arguments bound and device steps shown with their
   settings (`methods.protocol`). Read the `.condensed.md`; the `.trace.md` has everything,
   including each step's error policies. Read the library's `.hsi` alongside it for the control
   flow.

3. **Read what each device step does.** A step's code is only
   `ML_STAR._<CLSID>("<guid>"); // StepName`. Its settings are in the library's `.stp` file:

   ```
   python tools/stp_dump.py LIBRARY.stp                  # every step, one line each
   python tools/stp_dump.py LIBRARY.stp GUID --errors    # one step in full, with its error policies
   ```

   `<name>` is a setting bound to a variable. Inside blocks such as `/gripper`, the bound
   variable is written bare (`grip width = grip_width`).

4. **Look up what the codes mean** (`MoveType 2`, `Z end mode 0`, `UsePickUpPosition 2`) in
   Venus's step help. The help ships with Venus as `.chm` files: decompile one with
   `hh.exe -decompile <dir> <file>` from a path without spaces, then search the HTML. Anything the
   help leaves open goes in CONVENTIONS §11, not into code as fact.

5. **Write the port.** Map settings to PLR's arguments (examples: CO-RE grip height →
   `pickup_distance_from_top`, grip width → `resource_size_y`, plate press →
   `press_on_distance`). Say in the module's docstring what has no PLR counterpart.

6. **Check it against the HSL** with the interpreter, `methods.hsl_eval`. The test runs the same
   calls through the real library and through the port, on a real layout's sequences, and compares
   every step: command, (labware, position) per channel, and the settings that matter. Build it on
   `tests/port_harness.py` (`hsl_run`, `steps_of`, `RecordingDeck`, `RecordingChannels`,
   `assert_same_steps`); `tests/test_gsf_ims_port.py` is the model. The HSL side is a small `main`
   that `#include`s the library and calls it; the port side gets the recording stand-ins for the PLR
   device.

   Declare in the test what it checks, `LIBRARY = "<NAMESPACE>"` and `COVERS = [...]` (literals:
   `--status` reads them without importing), and declare `LIBRARY` in the port module.

   Pipetting goes through `venus_interop.plr.steps`: a port builds a `Pipetting` (cLLD, submerge,
   fluid height, liquid following, mix) per step and calls `steps.aspirate` / `steps.dispense`.
   The test compares, per step, the record's settings as the interpreter binds them
   (`Pipetting.from_record`) with what the port meant (`steps.OBSERVERS`) and with the PLR
   arguments it passed (`steps.plr_arguments`). Settings are then checked, not only transcribed.

7. **Make sure the test can fail.** Change one table entry or one argument's wiring in the port
   and see the test catch it.

8. **Run the method's demo end to end** on the simulator (`examples/`), checking the volumes it
   should produce.

## Liquid classes

A step names its liquid class; the class lives in Venus's database (`Config\ML_STARLiquids.mdb`), the
method's own (a kit or repository ships one) or the install's. Read it once with
`tools/liquid_classes.py DB --out classes.json` (`pip install .[liquids]`) and give the port
`VenusLiquidClasses.from_json(...)`: it gives PLR classes by Venus name (a name the database lacks
falls back to PLR's STAR table) and the Venus codes libraries decide by (tip type, dispense mode).
`--check-plr` compares every class the database shares with PLR's table; Hamilton's stock classes
agree exactly. Methods' own classes differ from any default (NIST's FastMixing classes mix at
500 uL/s), so a port should not run without its method's database.

## Extending the interpreter

The interpreter stops where Venus calls a compiled service: the deck-layout object, the
liquid-class database, the instrument. `run.stopped` says where. Model the one call the library
needs, and no more:

- When a call changes the deck, record it as a `StepEvent` with `settings`. For example,
  `HSLLabwrAccess::RelativePositionValuesSetForLabwareID` becomes a `LabwareShift`; the tap of a
  plate move shows up that way.
- When a call only reads something for a trace, answer it with `Unknown` (as device
  `GetLabwarePosition` does).
- A whole library function Venus runs through a compiled service (the liquid-class database, the
  deck object, SQL over temporary files) can be replaced by a Python model:
  `answers["functions"]["namespace::name"]` (lower case; the namespace's tail will do) is called
  with the run and the parameters as cells by lower-case name, by-reference ones bound to the
  caller's. Use the port of that function as its model when there is one: the NGSStar test runs the
  STAR Tip Tools planner port inside the HSL that way.
- A step type it does not know yet gets a handler in `Run._device_step`. Transport steps
  (`_transport_step`) and moves (`_move_step`) record their sequence's current item without
  consuming it, plus their bound settings.

## Traps met so far

- **Disabled steps.** Code inside `/* {{ 1 "" "0" */ if(0){` is switched off in the Method Editor
  and never runs; the trace marks it `[disabled step, never runs]`. Read past it: a function named
  `Move96HeadToFront` may no longer move anything to the front.
- **Error policies are behaviour.** A dispense to liquid (cLLD) into a dry container raises Venus's
  Liquid Level error (#102). Depending on the step's policy, that means repeat, then stop for the
  operator. A port that follows the library faithfully also fails there. Set up the starting state
  so the error does not arise, and say so.
- **Connected cavities.** A reservoir whose positions share one cavity (`ConnectedCtr=1`) has one
  volume and one level: `VenusDeck` gives its wells one shared tracker. Fill helpers must fill the
  cavity, not each position.
- **The simulator's LLD reads.** A cLLD search hands the container's tracker the volume it
  measured, read to 0.1 mm, so wells dispensed into "to liquid" end a few µL off. Before calling a
  volume difference a logic error, switch that writeback off and check again.
- **State the library keeps between calls.** Grip tools stay mounted until a move ejects them; a
  front channel set once is reused. Venus draws the CO-RE grip tools' front channel from the clock
  (`GetNewFrontChannel`); a port takes it as an argument, and tests call `SetFrontChannel` first.
- **The same name in two libraries.** `Move96HeadToFront` is in both Common96HeadSubMethods (it
  moves to a sequence) and the culture-processing Move96HeadAndArm (raw firmware, head up and
  forward). Calls resolve by namespace, so give each library its own module with its own `LIBRARY`.
  A test of two libraries lists the second in `COVERS_ALSO = {"<NAMESPACE>": [...]}`.
- **State that outlives the run.** Methods read Venus tip counters into their tip sequences at
  the start (`TipCount::Read2`) and write them back at the end (`Write2`), so the racks carry over
  between runs. These calls are tagged `[data]` and are easy to skip, but they decide where the
  first tip comes from. `plr/libraries/tip_count.TipCounters` keeps them in SQLite, in Venus's own
  element-counter tables (a status per position; simulated runs in their own table), shared by
  TipCount and STAR Tip Tools.
- **Libraries missing from the Venus install.** Kit methods include libraries that a given Venus
  install lacks (`STAR Tools\`, `HSL_MethodHelper.hsl`). Copies often sit in other method packages
  (pyhamilton bundles STAR Tools; NIST's repository has HSL_MethodHelper). Pass those folders as
  extra roots; a port test takes them from `VENUS_INTEROP_HAMILTON_LIBS` (separated by
  `os.pathsep`). An unresolved include shows in `trace_method.py`'s output.
- **A recorder accepts anything.** The port tests stand a recorder in for PLR, so an argument PLR
  would refuse passes them. Run the method's demo on the simulator after changing how a port
  calls PLR. (PLR's dispense turns cLLD on under surface following unless `lld_mode` is OFF; the
  test passed, the demo did not.)
- **Value types are behaviour.** HSL values are variants. Libraries branch on `GetType`
  (NGSStarLoading's volume texts show an integer-typed volume as 0) and `StrStr` raises on a
  value with no type. A first run of the loading test showed "[0uL]" because the interpreter had
  turned 94.0 into 94. When text from the HSL and the port disagree, check the value's type first.
- **A library's own source can be missing.** NGSStarLoading includes `ArrayTools\`, which is on
  no machine here. Declare stubs for the missing functions in the test's source and replace them
  with Python models (`answers["functions"]`). Say that these are models made from the names, not
  checked against the HSL.
- **Sequence counting.** Steps that count manually (0) don't advance their sequence; the library
  does that with `SetCurrentPosition` / `AlignSequences` (`methods/sequences.py`). Transport and
  move steps never count.

## The toolkit

What ports and translations are built from. Each models one documented Venus behaviour; the source is
in the docstring.

| Where | What | Venus counterpart |
|---|---|---|
| `methods/sequences.py` `Sequence` | A sequence's items and `cur`, `end`, `max`, `used`; every element function (`set_current_position`, `increment`, `set_count`, `set_max`, `reset`, `lookup_position`, `position_count_for_current_labware`, add/insert/remove, `copy`/`assign`); position properties (`set_property`, `set_property_range`, `get_property`, which raises "property not found") | Sequence element functions (HSL reference), HSLSeqLib |
| `methods/sequences.py` `take`, `take_head96` | The positions a pipetting step uses, by channel pattern, channel use and counting | Step help "Sequence counting", "Channel Use" |
| `methods/sequences.py` `align`, `loop` | AlignSequences / Adjust Sequences; the Method Editor's loop over a sequence (`for _ in sq.loop(seq): ...`; `rewind=False` for a loop written without the final SetCurrentPosition(1)) | Method Editor Loop / Adjust Sequences |
| `plr/venus_deck.py` `VenusDeck` | A layout imported to PLR and addressed as Venus does: `seq(name)` (live state, one object per name), `items(seq)`, `resolve(item)`, `at(labware, position)`, `labware(seq)`; connected cavities share one tracker; `clear_absent(trace)` takes off what the method brings in later | The deck layout and its sequences |
| `plr/venus_deck.py` `Gripper` | Plate and lid moves to Venus placeholders: the object goes to the holder the placeholder stood on | CO-RE gripper / iSWAP steps |
| `plr/steps.py` | `Pipetting` (cLLD, submerge, fluid height, liquid following, mix; `from_record`), `plr_arguments`, `aspirate` / `dispense`, `OBSERVERS` (what a port meant, for tests); `CoreGrip`, `core_grip_arguments` | Aspirate / Dispense / ZSwap step settings |
| `plr/liquid_classes.py` `VenusLiquidClasses` | PLR liquid classes by Venus name, tip type, dispense mode, from `tools/liquid_classes.py`'s JSON | `ML_STARLiquids.mdb` |
| `plr/libraries/tip_count.py` `TipCounters` | Tip counters that outlive the run (SQLite) | HxElementCounter |
| `methods/hsl_eval.py` | The HSL interpreter for checking ports. `answers`: `functions` (a library function replaced by a Python model, e.g. its port), `tip_counters`, `labware_data`, `liquid_classes`, `simulation` | Venus's runtime |
| `tests/port_harness.py` | `hsl_run`, `steps_of`, `RecordingDeck`, `RecordingChannels`, `assert_same_steps` | – |
| `examples/nist_deck.py` | For demos: `install` (PLR's wastes and grip tools where the layout has its own), `give_room` / `make_room` (sources and destinations sized for a run; cavities filled as one), `write_worklist`, `print_plate_map` | – |
| `tools/trace_method.py` | `--out` traces, `--calls` call counts, `--status` coverage and the work queue (verdicts in `tools/function_notes.json`) | – |
| `tools/stp_dump.py` | A `.stp`'s step records, settings named | Step dialogs |

Ported libraries, each `plr/libraries/<module>.py` with `LIBRARY` = its Venus namespace:

| Module | Venus library | Check |
|---|---|---|
| `gsf_ims` | NIST GSF-IMS shared submethods | `test_gsf_ims_port.py` |
| `plate_and_lid` | NIST PlateAndLidMovement | `test_plate_and_lid_port.py` |
| `common_96head` | NIST Common96HeadSubMethods | `test_96head_port.py` |
| `move_96head_and_arm` | NIST culture-processing Move96HeadAndArm | `test_96head_port.py` |
| `lmsf_utilities` | NIST LMSF_Utilities (sequence properties) | `test_lmsf_utilities_port.py` |
| `tip_handling_96`, `tip_count` | NIST Tip Handling with 96-Head; Hamilton HSLTipCountingLib Read2/Write2 | `test_tip_counters_port.py` |
| `ngsstar_processes` | Hamilton NGSStarProcesses: reagent transfer, CO-RE plate transports, incubation timer, tip counters | `test_ngsstar_processes_port.py`, `test_ngsstar_transports_port.py`, `test_ngsstar_state.py` |
| `star_tip_tools` | Hamilton STAR Tip Tools (tip planner, counters) + HelperLibrary | unit tests; the planner runs inside the NGSStar port test |
| `ngsstar_loading` | Hamilton NGSStarLoading: volumes per sample, containers and their volumes, the RunData / Mastermix_Prep sheets, labware per process | `test_ngsstar_loading_port.py` (Avenio's own calls, 1/8/24/96 samples) |
| `ngsstar_prep` | Hamilton NGSStarPrep: heater shakers, CPAC, ODTC on PLR's drivers (an ODTC method run in the background while the method pipettes) | `test_ngsstar_prep_port.py` (Avenio's own calls, both HHS configurations) |

## Translating a method

A method's `main` and its sections (`GetParams`, `StartUp`, `CalculateOutputs`, ...) become a class
whose methods keep the sections' names and call the ports in the same order, one Python line per
call. `examples/groq_seq_demo.py` shows the whole pattern:

- **Parameters** the method reads from a file that isn't there become a `Parameters` dataclass with
  illustrative defaults, labelled as such, chosen so every volume is one the channels can move.
- **The start deck:** `VenusDeck.clear_absent(trace)` removes what the method only brings in later;
  `install` puts PLR's grip tools and wastes in; `fill` gives sources what the run takes (connected
  cavities as one volume) and wastes a heel where a dispense goes to liquid.
- **Arithmetic** the method does (volume models, concentrations) is written out as in the method,
  including its quirks; the demo's report checks each well against that model, so a quirk shows as
  a number (GROQ-Seq's column 12).
- **Aborts:** a Venus runtime error ends `main` and runs the abort handler (`RegisterAbortHandler`,
  usually CleanUp). The demos raise `sequences.SequenceError`, a port's own error
  (`gsf_ims.SubmethodError` for the library's ErrRaise checks) or a `MethodError`, catch them in
  `run`, and run CleanUp, as Venus would.
- **Defects in the method's source** (a property read where none was set, an index from an unset
  variable, a loop that never dilutes what it reports): translate the method as written, following
  what Venus documents it does (often: abort), and put the evident fix behind a flag (`--repair`)
  that is clearly not the method. Record each in the module docstring, and what only Venus can
  settle in CONVENTIONS §11. Look at what a library check would do before calling something a
  defect: GROQ-Seq's library-stock path stops in GSF-IMS's own channel check, in Venus too.
- **Operator dialogs** become calls to an operator interface at the same place, with the dialog's
  own text (choices, confirmations, tables, files, pictures); a scripted operator answers them in
  tests and unattended runs, and an unanswered question is an error. (The earlier demos' `Parameters`
  are pre-answered dialogs.)
- **What is left out stays visible** (user, 2026-10-18). Every Venus call the translation doesn't
  carry over (email alerts, the scheduler's file handshakes, error-recovery dialogs, debugging
  message boxes, TipCount::Edit2) gets a comment at that place in the translation, naming the call
  and why it is left out, besides the docstring. `out` in `tools/function_notes.json` is a decision
  to record there, not to drop silently. The run report and the sample-tracking mapping files
  (STCC) are in scope: a translation produces them. Venus's deck view is out: PLR's visualizer
  shows the same.

## Ports so far

What each needed that the earlier ones had not built (keep a line per port):

| Port | New |
|---|---|
| GSF-IMS | The interpreter's device steps through `.stp` records; sequences as index rules; the differential test |
| PlateAndLidMovement | Gripper steps in the interpreter, labware shift (the tap), labware position; gripper eject |
| Common96HeadSubMethods, Move96HeadAndArm | Move and firmware-command steps |
| LMSF_Utilities | Sequence position properties |
| Tip counters | The element counter in the interpreter |
| NGSStar reagent transfer | Function models (`answers["functions"]`), extra library roots, bare-name binding, the tip planner |
| `plr/steps.py` | Settings capture in the interpreter; settings compared, not only transcribed |
| Liquid classes | The `.mdb` reader |
| Marionette, GROQ-Seq methods | `sequences.loop`; worklists; listed-position racks in the importer; the abort and source-defect policy |
| NGSStarLoading | Excel workbooks read and written with SQL (`Run.workbooks`, SQLite); `Scripting.FileSystemObject`; HSL value types kept (a float operand gives a float; `Floor(x, hslTrue)`), since libraries branch on `GetType`; unassigned variables as integer 0 (CONVENTIONS §11) |
| NGSStarPrep | Device drivers answered by recording models, compared with recording PLR devices in one vocabulary; PLR's ODTC backend: `upload_method_set`, `execute_method` (venus-plr) |

## Inputs

None of the method sources are in this repository. Tests find them through environment variables:

- `VENUS_INTEROP_NIST`: a copy of NIST's lmsf_hamilton repository.
- `VENUS_INTEROP_CORPUS`: the layouts and labware.

Keep downloaded method files in their own folder, and never commit them.
