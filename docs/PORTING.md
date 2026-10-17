# Porting Venus libraries to PyLabRobot

How to turn a Venus method into Python on PLR that keeps its logic: port the **libraries** it calls,
one module each under `venus_interop/plr/libraries/`, then translate the method's own `main` call for
call. This file is the workflow; `plr/libraries/gsf_ims.py` and `plr/libraries/plate_and_lid.py`
are the worked examples, with their checks in `tests/test_gsf_ims_port.py` and
`tests/test_plate_and_lid_port.py`.

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
- **Protocol logic only.** Error-recovery branches, operator dialogs, trace and worklist output and
  the scheduler's file handshake become notes or stubs, not code.

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
   every step: command, (labware, position) per channel, and the settings that matter. Copy one of
   the two tests. The HSL side is a small `main` that `#include`s the library and calls it; the port
   side gets a recording stand-in for the PLR device.

   Declare in the test what it checks, `LIBRARY = "<NAMESPACE>"` and `COVERS = [...]` (literals:
   `--status` reads them without importing), and declare `LIBRARY` in the port module.

7. **Make sure the test can fail.** Change one table entry or one argument's wiring in the port
   and see the test catch it.

8. **Run the method's demo end to end** on the simulator (`examples/`), checking the volumes it
   should produce.

## Extending the interpreter

The interpreter stops where Venus calls a compiled service: the deck-layout object, the
liquid-class database, the instrument. `run.stopped` says where. Model the one call the library
needs, and no more:

- When a call changes the deck, record it as a `StepEvent` with `settings`. For example,
  `HSLLabwrAccess::RelativePositionValuesSetForLabwareID` becomes a `LabwareShift`; the tap of a
  plate move shows up that way.
- When a call only reads something for a trace, answer it with `Unknown` (as device
  `GetLabwarePosition` does).
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
- **Sequence counting.** Steps that count manually (0) don't advance their sequence; the library
  does that with `SetCurrentPosition` / `AlignSequences` (`methods/sequences.py`). Transport and
  move steps never count.

## Inputs

None of the method sources are in this repository. Tests find them through environment variables:

- `VENUS_INTEROP_NIST`: a copy of NIST's lmsf_hamilton repository.
- `VENUS_INTEROP_CORPUS`: the layouts and labware.

Keep downloaded method files in their own folder, and never commit them.
