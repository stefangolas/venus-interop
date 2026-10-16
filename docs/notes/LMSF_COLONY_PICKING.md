# NIST LMSF protocol: 02 Colony Picking

Reconstructed 2026-10-16 from `Methods/culture processing/02 Colony Picking.{hsl,sub,stp,lay}` via the decompiler traces (`.local/session_state/analysis/traces/02 Colony Picking.{trace,condensed}.md`), with the libraries it includes read from source. Everything below is read from the code; inferences are marked.

**Whose code this is.** The method's footers say `author=Hamilton`, 2018-10-09. Its helper libraries (`Library/Culture processing/LabwareHandling`, `TipHandling`, `Move96HeadAndArm`, and `Library/PAA/RunTimeErrorHandling`) date from 2016–2018 and are signed by Hamilton or Hamilton staff IDs. The camera side is Hamilton's **easyPick II** library (`easyPickIILibrary/easyPickII_Steps`, 2016). So this is a Hamilton-written integration template for a culture-processing cell with the Overlord scheduler (PAA), kept in NIST's repo. It isn't LMSF-written code like the GSF-IMS methods, and its style shows it: `A_/B_/C_/D_` stages, global `_str…` names and file handshakes in place of `parameters.csv`.

## What it does

The method picks up to **12 colonies from each of 4 agar plates** into one 96-well Growth Plate:

- agar plate 1 → wells 1–12;
- agar plate 2 → wells 13–24;
- agar plate 3 → wells 25–36;
- agar plate 4 → wells 37–48.

Each agar plate is photographed on the light table, and easyPick II's image analysis finds the colonies. Each colony gets a dynamic labware spot at its deck coordinates, and the 8 channels then "aspirate" there: a 0 µL touch with capacitive LLD on the agar. The tip is then rinsed into a growth well with one 100 µL mix. All labware arrives and leaves through a file handshake with the scheduler.

## Settings (`A_Definitions`, hard-coded)

| Variable | Value | Notes |
|---|---|---|
| `_strTransferPositionGrowthPlate`, `…AgarPlate` | `PlateHandOff` | the handoff position named in handshake files |
| `_strTransferPositionTips300` | `TipsHandOff` | |
| `_strGrowthPlateName` / `_strAgarPlateName` / `_strTips300Name` | `GrowthPlate` / `AgarPlate` / `Tips300` | the `LabwareName` in handshake files |
| `_strLightSource` | `EASYPICKII_HELPER::LIGHTSOURCE::_MLSTAR_DIV3_PWM3` | light table |
| `_strLightSourceTop` | **never set** | its assignment (`_MLSTAR_DIV2_PWM1`) is a disabled step; see open items |
| `_intLightIntensity` | 12 | percent, for both lights |
| `_strCameraSettings` / `_strColoniesSettings` | `"Culture Processing"` | named easyPick II settings sets; the simulator uses `"Culture Processing Simulation"` for the colony settings |
| `_intMaxColoniesPerWell` | 12 | despite the name, this is the picks per agar plate; it's also passed as `[12]`, the per-rack maximum for `RetrieveColonyPositions` |
| `_strFilepathStatus` | `C:\HamiltonOutputFiles\HamiltonStatus.csv` | deleted at start, written at end |
| (unused) | `_strWastePositionTips1000/300/50`, `_blnConfigurationWithDialogs = 0`, `_blnShowCameraLiveView = false` | set, never read in this method |

Picking channels: `GetNumberOfPipettingChannels(ML_STAR)`, so all of them (8 on a standard STAR).

## The handshake with the scheduler (`LABWAREHANDLING`, `RUNTIMEERRORHANDLING`)

Four CSV files under `C:\PAATestFolder\LabwareHandling\`, each holding one record with the fields `TransferPosition, LabwareName, TransferPositionOccupancy`:

| Call | What it does |
|---|---|
| `RequestLabware(name, pos)` | Waits, polling every 2 s with no timeout, until `RequestLabwareInput\RequestLabwareInput.csv` is gone (the trace message reads "waiting for Overload [sic] to finish using file"). Then writes it with occupancy `0`: the position is empty, please fill it. |
| `WaitForLabwareRequestCompletion(…)` | Polls every 2 s for `RequestLabwareInputComplete\RequestLabwareInputComplete.csv`, for up to 259,200 s (72 h). Reads its record into the outputs, then deletes it. |
| `ReturnLabware(name, pos)` | Deletes any old `ReturnLabwareOutput\ReturnLabwareOutput.csv`, then writes it with occupancy `1`: labware is at the position, take it. |
| `WaitForLabwareReturnCompletion(…)` | The same polling (2 s, 72 h) on `ReturnLabwareOutputComplete\ReturnLabwareOutputComplete.csv`; reads it, then deletes it. |

After every **request**, the method checks the completion record with `IF_AND_IF_OR::If_And_3_Variables`: position, name, and occupancy `"1"` must all match. On a mismatch, `TransportError()` writes `C:\PAATestFolder\RunTimeError\RunTimeError.csv` with `TransportError=1`, and the method aborts. The file's other columns (`SeeSawModuleError, TiltModuleError, PipettingError, FileCreationTimeoutError, UnknownHardwareError, PumpModuleError`, all `0`) suggest the error file is shared with other modules of the culture-processing cell; that's an inference. **Returns are not checked**, and neither wait's own return value is used. A 72 h timeout on a request shows up as a mismatch; on a return, the method carries on.

**Simulation:** after each request or return, the method waits 6 s and writes the completion file itself (`UtilityCreate…CompletionFile`), so a simulated run doesn't need the scheduler.

## The protocol

### B_Initialise
`Initialize` (errors: initialise/cancel by default). Simulator detection. **`easyStep_Init`** starts the easyPick II application (`INIT::Init`, trace level full) and polls `APPLICATION::IsRunning` up to 100 times; any start error goes to `ShowErrorDialog` and then `abort`. The number of channels is read.

### C_Pipetting

1. **300 µL tips.** `TIPHANDLING::CheckAvailableTipsFromDeck(Tips300ulStandardVolumeTipWithFilter_Partial, 48, 300)` reads the `300ulStandardVolumeTipWithFilter` tip counter and returns:
   - **0**: at least 48 tips are left (4 plates × 12 picks); nothing to do.
   - **1**: some tips are left but fewer than 48. The partial rack is moved to `…_HandOff` with the CO-RE gripper and returned to the scheduler as `Tips300` at `TipsHandOff` (`ReturnLabware` + wait).
   - **2**: the rack is empty, and it goes to `…_Waste`.
   - In cases 1 and 2, a fresh rack is then requested at `TipsHandOff`, checked, and moved from `…_HandOff` into `…_Partial` (grippers ejected after).
   - Tip-rack grip: width 77, open 86, height 13.5 (a disabled step holds an older 10.0), grip speed 277.8, Z speed 75, X acceleration level 4, plate press 1, no plate checks, `ToolUpperChannel = 8`.
2. **Growth Plate in.** `Move96HeadAndArm`, which here really is firmware: `H0ZA za68500` (96-head Z to 685.0) and `H0YA ya07500` (Y to 750.0), then a `MoveToPosition` to move the arm right. Then `RequestLabware(GrowthPlate, PlateHandOff)` and the check. ZSwap `GrowthPlate_HandOff` → `GrowthPlate`: grip height 6, width 80, open 86, force 5, plate check on place.
3. **Agar plates in, ×4.** For each plate: park the head and arm, `RequestLabware(AgarPlate, PlateHandOff)`, check, then ZSwap `trpAgarPlateHandOff` → `trpAgarPlates1To4` (grip height 8, width 81, open 88, check on place; the destination sequence advances). The four plates go into a stack on the deck; `PlateStackSeqCalculation` is included for it, but the trace shows no calls to it.
4. **Per agar plate `n` = 1…4.** The Growth Plate start is set to position 1/13/25/37 and the rack ID to `AgarPlate<n>`. Then:
   1. ZSwap `trpAgarPlates1To4` → `trpAgarPlatePicking`, the light table (height 8, width 81).
   2. Lid off: `Agar_Plate_lid` → `Agar_Plate_Lid_Park` (grip height 5, width 84.5, open 90). The grippers are ejected here, so the channels are free for picking.
   3. `MoveToPosition` moves the arm out of the camera's view.
   4. **Imaging loop** (repeats until the analysis succeeds):
      1. Show the easyPick II window. Light table on (`easyStep_Light_On`, 12%), then the top light (`MLSTAR::Light_On`, 12%).
      2. **Take a picture** (`easyStep_Colony_TakePicture`, settings "Culture Processing", camera kept open). The simulator instead loads `settings\ColonyDemo\Demo_Plate_gray.tif`.
      3. Lights off.
      4. **Analyse** (`easyStep_Colony_Analyse` with the colony settings, asynchronous picture save, rack barcode `AgarPlate<n>`, description `AgarPlate`), which returns `intEasyPickIIRackID`.
      5. On failure: the error dialog, then a custom retry dialog. Its return value 2 aborts; anything else retakes the picture.
   5. `DATABASE::GetEasyPickIIRack(...)` gets the picture file and rack dimensions.
   6. **Pick cycles** (repeat until 12 have been picked):
      1. **Positions.** The channel pattern is all channels, left-aligned (`ChannelPattern_LeftAdjust`). `easyStep_Colony_RetrieveColonyPositions` asks the easyPick II database for up to that many colonies (cap `[12]`). It returns the used pattern, the used and total counts, colony IDs and target well numbers. Each colony's light-table X/Y is converted to deck X/Y/Z, relative to the reference labware `easypickii_adjust_small_0001` and the plate `Agar_Plate`. Each spot is placed as a `ml_star\EasyPickII\ColonySpot\colony_spot.rck` container and gathered into `seqColonySequence`. The cycle ends if no colonies were found, or none are pickable.
      2. 2 s pause; hide the window.
      3. **TipPickUp**: 300 µL filtered tips from `…_Partial`, used pattern, sequence counting on. The tip counter is written straight away.
      4. **Aspirate (the pick)** at `seqColonySequence`:
         - 0 µL, liquid class `StandardVolumeFilter_Water_DispenseSurface_Empty`;
         - **cLLD sensitivity 1**, liquid following on, fluid height 5, submerge 0, aspirate mode 0, mix 0.
         The tip finds the agar surface by capacitance and touches the colony; nothing is aspirated. That's an inference from the 0 µL with cLLD; the code doesn't say it.
      5. **Dispense (the inoculation)** into `GrowthPlate_Picking`:
         - 0 µL, dispense mode 3, submerge 2, cLLD 1, liquid following;
         - **mix 1 × 100 µL**.
         The colony is rinsed off the tip into the medium already in the well. That's an inference; the plate's fill isn't in this method.
      6. **TipEject** to the default waste.
      7. **`easyStep_Colony_UpdatePickingState`** takes the Aspirate step's per-channel return. A colony is marked `OK` if that channel had no error, or if the operator's recovery button was 4 or 9; otherwise `ERROR`. Picked += used.
   7. Lid back: `Agar_Plate_Lid_Park` → `Agar_Plate_lid` (check on place). Plate back: `trpAgarPlatePicking` → `trpAgarPlates1To4`. Hide the window.
5. **Agar plates out, ×4.** ZSwap `trpAgarPlates4To1` → `trpAgarPlateHandOff`, so the stack is emptied in reverse. Then park the head and arm, `ReturnLabware(AgarPlate, PlateHandOff)`, and wait.
6. **Growth Plate out.** ZSwap `GrowthPlate` → `GrowthPlate_HandOff` (grippers ejected), park, `ReturnLabware(GrowthPlate, PlateHandOff)`, wait.

### D_Cleanup and OnAbort
On success, the head and arm are parked and `HamiltonStatus.csv` is written with `Status = 1`. `easyStep_DeInit` is called **twice** on hardware (once inside `if (!simulation)`, once unconditionally) and once in the simulator. `OnAbort` shows a custom dialog, sets the abort flag and runs `D_Cleanup`, which then writes `Status = 0` and skips the park.

## Error handling

- easyPick II calls: any error code goes to `ShowErrorDialog`, which hides the application window and shows the library's error text (`APPLICATION::GetErrorText`) with no timeout. Then the method **aborts**, except after a failed analysis, which can be retried.
- Device steps: the ZSwap gets repeat on execution/not-executed errors and cancel on hardware/labware errors. Places cancel on everything. Tip pick-up, aspirate and dispense carry their `.stp` policies; the anti-droplet-control error defaults to cancel.
- Scheduler side: `RunTimeError.csv` (transport error) plus `HamiltonStatus.csv`.

## Open items (specific to this method)

- **The top light's source variable is never set.** Its assignment is a disabled step, so `MLSTAR::Light_On(ML_STAR, _strLightSourceTop, 12)` gets an unassigned variable. Whether that errors out (and so aborts every real run), is a no-op, or lights a default source depends on easyPick II and HSL behaviour we haven't checked.
- **The per-cycle limit is computed but not used.** `intNumberOfColoniesForNextCycle = 12 − picked`, capped at the channel count, goes nowhere. Every cycle offers the full channel pattern with the cap `[12]`. Whether easyPick II's database stops at 12 for the rack (`i_arrintMaxNumberOfColoniesToPick`) or a second 8-channel cycle can pick 16 has to be checked in the library DLL's behaviour. If it can pick 16, plate `n` overruns into the next plate's wells.
- *(Resolved 2026-10-16 from the `.lay`.)* `GrowthPlate_Picking` is rows A, C, E, G, each from column 1 to 12. So agar plate 1 → A1–A12, 2 → C1–C12, 3 → E1–E12, 4 → G1–G12, and rows B, D, F and H stay empty. If the 12-pick cap doesn't hold, plate 1's picks 13–16 land in C1–C4. Plate 2 then starts at C1 and inoculates those same wells again. Plate 4 has no positions left after G12.
- The meaning of recovery buttons 4 and 9 in a step return (counted as picked), and of cLLD sensitivity 1 and dispense mode 3: Venus enums, CONVENTIONS §11.
- The retry dialog (`96f42b90…`) and the abort dialog (`19f01a63…`) are custom dialogs whose text isn't in the method files.
