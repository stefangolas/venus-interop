# NIST LMSF protocol: DNA Extraction

Reconstructed 2026-10-16 from `Methods/GSF-IMS Project/E. coli Methods/Fitness Selection 2.With DNA Extraction/DNA Extraction.{med,hsl,sub,stp,lay}` via the decompiler traces (`.local/session_state/analysis/traces/DNA Extraction.{trace,condensed}.md`). 566 steps, 18 sub-methods. Everything below is read from the trace; the few inferences are marked. Re-checked 2026-10-16 against the longer traces. These now include the libraries' `private` functions (plate moves, MPE² error handling) and mark steps switched off in the editor as disabled. Those disabled steps had been shown as live, and two statements in the first version came from them.

## What it does

Plasmid-free genomic DNA extraction from *E. coli* cultures grown in a deep-well **Spin Plate**: pellet resuspension (P1), alkaline lysis (P2) and neutralisation (N3) on a heater shaker, clarification through an **Agient Filter Plate** pushed by the **MPE²** into a Receiving Plate, DNA binding on a **Nunc Binding Plate**, two washes (PB, PE), drying, and elution in water — either pushed by the MPE² into an Eppendorf 350 µL elution plate, or spun through in a centrifuge (operator choice).

**Scheduling context:** it runs after "Combine old GP wells into Spin Plate.med" and the Overlord job "Get DWP from STAR then Centrifuge DWP.ovp"; at start the Spin Plate (with lid) sits at the Handoff position. It reads `C:\Program Files (x86)\HAMILTON\LMSF_FrontEnd\parameters.csv` and is one stage of a PAA Overlord chain.

**Four-fold multiplexing:** every consumable exists in 4 deck copies (`Lysate_Plate_Buffer_1..4`, `N3_Buffer_1..4`, …); `DNA_plate_number` from `parameters.csv` (else an operator dialog) selects one via `sequence_number = DNA_plate_number % 4` (0 → 4). One extraction runs per invocation; four share the deck.

## Parameters (`parameters.csv` keys → defaults)

| Key | Default | Notes |
|---|---|---|
| `DNAPlateNumber` | dialog | which of the 4 deck sets |
| `cultureVolume` | 500 | clamped to 200–500 µL; sets the supernatant split (below) |
| `isPipetting` | "true" | when "false", pipetting is skipped and operator dialogs stand in |
| `isDebugging` | from the csv; "true" if the key is missing | dialogs per sub-method. The method also has a step `is_debugging = "false"`, but it is **disabled** in the editor and never runs, so the csv value decides. The csv is written by the LMSF front end at run time and isn't in the repo, so the value a real run uses is unknown. |
| `spin_final_elution` | "maybe" | "yes" → centrifuge elution, "no" → MPE² elution, "maybe" → dialog |
| (hardcoded) | | `use_iSWAP = "true"`, `shake_speed = 200` RPM |

Fixed MPE² geometry: `FPonRPNozzleHeight = FPonRPFilterHeight = 86.5`, `BPNozzleHeight = 38.4`, `BPFilterHeight = 31.35`, `BPLenghtofNozzles = 6.6`, `BPNozzleOffset = 0`, `EPlateH = 14.35`. The method sets `MPE2COMPort = 7` but never uses it: the lab's `Methods/Common/MPE_Library` (`InitializeMPELibrary`) hard-codes **COM 14 at 921600 baud**, and that is what `Connect` opens. A dialog asks for the port only if either value is 0.

## Deck (sequence roles)

Spin Plate (deep-well; pellets in columns 4/6/8, and the supernatant goes into columns 3/5/7 beside them) · Lysate Plate (Abgene, on HHS_1; one 3-column set per `sequence_number`) · N3 per set (`N3_Buffer_1..4`). P1/P2 (DNA_Buffers_2 columns 2–4 / 9–11), PB/PE (DNA_Buffers_1 columns 3–5 / 8–10) and elution buffer (column 5) are **one fixed set**, not one per run. The positions come from the layout's sequences; see `LMSF_OPERATIONAL_LOGIC.md` · Agilent Filter Plate (FP) + Eppendorf DWP Receiving Plate (RP) at storage → MPE² · Nunc Binding Plate (BP) storage → MPE² · Eppendorf 350 µL elution plate (EP) storage → pipetting position → MPE² · 2× Heater Shaker (HHS_1, HHS_2, clamps closed at start) · tips: 1000 µL filtered channels, 300 µL filtered channels, wide-bore (support-seated, cut length 79.8 mm), and an **offset** 1000 µL rack with its own support + handoff · CO-RE gripper tool `COREGripTool_OnWaste_1000ul_0001` · MPE² waste.

## The protocol

### StartUp
Tip counters for the four tip types (auto values); `Initialize`; MPE² init/connect (skipped in simulator); both HHS created and plate locks closed.

### PipetteMove01 — remove supernatant
1. CO-RE gripper: Spin Plate lid → lid waste (ZSwap get/place, grip width 84.5, force 5, speed 277).
2. Loop over `Spin_Plate_supernatant` (8 channels, 1000 µL filtered tips, liquid class `HighVolumeFilter_Water_SlowAsp_DispSurfEmpty`):
   - aspirate **1000 µL** (cLLD 5, liquid following, submerge 3) → dispense into **adjacent wells of the same Spin Plate** (`Spin_Plate_liquid_waste`, dispense mode 8 = surface, submerge 2);
   - aspirate the remainder **`culture_volume × 3.6` − 1000 µL** (aspirate mode 2, submerge 2) → dispense to the waste wells.
   The 3.6× factor says the pellets retain ≈3.6× the culture volume in liquid (inference from the maths, not stated in the method).

### PipetteMove01A — resuspend and transfer to Lysate Plate
1. Lids: Lysate Plate (on HHS) and DNA Buffers 2 lid off (ZSwap, plate press 0.5 on park).
2. Per column: **200 µL Buffer P1** into the Spin Plate wells (300 µL filtered tips, `StandardVolumeFilter_Water_DispenseSurface_Empty`); then aspirate **300 µL** of the resuspended culture with **mix 10 × 220 µL** (`StandardVolumeFilter_Water_FastMixing…`) and dispense into Lysate Plate `sequence_number` (dispense mode 8).
3. `RenewOffsetTips` (below) if the offset rack is empty.

### PipetteMove02 — Buffer P2, shake
96-head **stamping with 24 tips** (channel pattern = first 24 of 96) from the offset tip support: **250 µL Buffer P2** into the Lysate Plate (`HighVolumeFilter_96COREHead1000ul_…`), tips ejected to the waste chute with a 5 s shake (2 s in the later stages). Then **HHS_1 shake 120 s at 200 RPM** (start shaker, park the P2 lid back, wait, stop). The emptied Spin Plate goes to waste (gripper, no tap, grip width 78.95 for the DWP).

### PipetteMove03 — Buffer N3, shake
Clear 96-head/arm; N3 buffer lid off; 96-head 24 tips: **350 µL Buffer N3** into the Lysate Plate; eject+shake 2 s; **HHS_1 shake 120 s**; lid back on N3 during the wait.

### PipetteMove04 — filter the lysate
1. With iSWAP/CO-RE: RP from storage → MPE² (lid parked); Agilent FP from storage → MPE² (lid parked).
2. 96-head 24 tips with **wide-bore tips** (support-seated), aspirate **900 µL** lysate with **mix 3 × 675 µL** (0.75 × volume), liquid class `HighVolume_WideBore3_2_Water_DispenseSurfaceEmpty`; dispense onto the FP (dispense height 13 above filter, detect mode 18 — open question §11).
   **The wide-bore tips are a firmware redefinition, done at run time.** `DPXPRECUTTEDTIPSLIB::SetCuttedTipLenght(ML_STAR, 5, 79.8, wide_bore_volume)` rewrites tip type 5 (1000 µL filtered) with a `C0TT` firmware command:
   - Stock definition `tt05tf1tl0871tv10650tg3tu0`: 87.1 mm, 1065.0 µL.
   - New length: 79.8 mm − 8.0 mm (a fixed offset in the library) = `tl0718`, so 15.3 mm is cut off.
   - New volume: the cut-off cone is modelled with diameter `0.171 × 15.3 + 0.632` = 3.25 mm, so `π/4·d²·L/3` = 42 µL. The library takes that off plus a 20 µL safety margin: `tv10030`.
   - It hands back 938 µL as the usable volume (by reference, into `wide_bore_volume`). The method caps `pipette_volume_1` at that volume; 900 µL is under it, so nothing changes.

   The library also has a cut-length check, `CheckForOrginalLengthMinusNewLengthGreater15mm`, which would show a "Verify TipParameter" dialog with no timeout. The call to it is a **disabled step**, so it never runs; no check or dialog stands between the cut and the `C0TT`. (The disabled check would have said "Maximum cutting length = 15mm" but rejected only cuts over 40 mm. Its message for a negative cut reads "Please consult your Hairdresser for Tip extension.;)".) After the wide-bore transfer, `ResetCuttedTipLenght(ML_STAR, 5)` sends `C0TT` with the stock `tt05…tl0871tv10650…` again, so tip type 5 is back to normal for later steps.
3. **FP incubation 120 s** (timer runs across the next moves).
4. **MPE²: `FilterPlateToWaste` with program `pressure,20,240;pressure,65,60;`** — 20 (mbar?) for 240 (s?), then 65 for 60 — pushing lysate through the filter into the RP below. Units are the MPE library's; not verifiable from the method alone.
5. FP lid back on, then the FP (with lid) is **lifted and placed back on the MPE² 4 mm higher** (a same-position move with `z_shift = 4`). This is presumably to break it off the nozzles before transport; that's an inference. Then FP and RP go back to storage with their lids.

### PipetteMove05 — bind DNA
BP from storage → MPE² (no lid); RP lid off. 96-head 24 tips: **900 µL** cleared lysate RP → BP (submerge 7, dispense height 13). RP lid back. **MPE²: `FilterPlateToWaste` `pressure,40,60;`** — DNA binds to the silica membrane; flow-through to waste. `RenewOffsetTips`.

### PipetteMove06 — wash PB
Lid off DNA Buffers 1 (PB/PE); 96-head 24 tips: **900 µL Buffer PB** → BP; **MPE²: `FilterPlateToWaste` `pressure,40,60;`** to waste. `RenewOffsetTips`.

### PipetteMove07 — wash PE, dry
**900 µL Buffer PE** → BP; **MPE²: `FilterPlateToWaste` `pressure,40,60;pressure,65,420;`** — wash then a 420 s high-pressure dry. Then the BP is lifted off the nozzles and re-seated (same-position move, `z_shift = 7`).

### PipetteMove08 — elution
`UserChoiceElution`: `spin_final_elution` "yes" → centrifuge, "no" → MPE², "maybe" → dialog (`mpe_final_elution = 2 − return`).
1. **130 µL water/elution buffer** into each BP well (300 µL filtered tips, `StandardVolumeFilter_Water_DispenseJet_Empty`, dispense jet onto the membrane); **incubate 300 s**.
2. **MPE² path:** BP back onto the MPE²; EP to the MPE² (grip force 4 — lighter for the lo-bind plate); MPE clamps the BP (`SetFilterHeight/SetNozzleHeight/FilterPlatePlaced/ClampFilterPlate`), collection plate registered (`SetCollectionPlateHeight(14.35)`, `SetControlPoints("pressure,65,420;")`), **`ProcessFilterToCollectionPlate`** pushes the eluate into the EP; EP back to storage with lid; BP retrieved to storage; `FilterPlateRemoved`.
3. **Centrifuge path:** BP onto the EP-spin adapter (operator does the spin); dialogs in/out; **210 s** timer stands in for the centrifuge run.

### CleanUp
Tip counters written to the status file (`C:\Shared Files\LMSF Scheduler\Hamilton\tip_status.csv`, from the private `TipHandlingParameters`); MPE² disconnect; HHS terminate; head/arm parked; completion dialogs; BP lid restored on the spin path.

## Recurring mechanics worth knowing

- **RenewOffsetTips:** the 96-head stamping picks from an *offset* rack. The sub-method ejects anything on the offset support to the waste chute (with a 10 s chute shake), then picks 96 tips from `Tips_1000_Handoff` and ejects them onto `TipSupport_1000_offset_1`. The 24-channel steps then pick from `Tips_1000_Offset_pickup`.
- **96-head channel pattern** `111111111111111111111111` + 72 zeros = the first 24 positions — i.e. 3 rows × 8. All stamping uses these 24.
- **Plate and lid moves** (`Methods/Common/PlateAndLidMovement`). When `use_iSWAP` is true, every move is a CO-RE gripper (ZSwap) get/place pair; nothing is moved by hand. Each public `Move<Labware>…` sets that labware's grip height, width and force: 84.5 mm plates, 80 mm FP/EP, 78–78.95 mm DWPs, force 4 for the lo-bind EP and 5 otherwise. It then calls one of two private movers:
  - Shared settings: grip opening 88 mm, Z speed 75, grip speed 277, `ZSwapStrengthFactor = 0.5`.
  - `MovePlateWithLidAndTap` uses `TransportMode = 2`, so plate and lid travel together. It checks the plate after placing it and doesn't check it on pick-up; X acceleration level 1, plate press 0.
  - `MovePlateNoLidNoTap` turns both plate checks off.
  - `MoveLid` checks the lid after placing it, with plate press 0.5; `MoveLidNoTap` uses no check and press 0. So "Tap" in these names appears to mean the presence check plus press after a place; that's an inference from the parameter differences.
  - **`z_shift`:** before placing, the destination labware's Z is raised by `z_shift` mm (`HSLLabwrAccess::RelativePositionValuesSetForLabwareID`, via `LMSF_UTILITIES::SeqZShift`), and it's lowered again afterwards. The plate is therefore set down `z_shift` mm above its nominal seat: 1 mm for MPE²/storage places, 4 mm for the FP re-seat, 7 mm for the BP re-seat.
  - **Gripper channel choice:** on every new gripper pick-up (`new_front_gripper = 1`), the upper channel (`ToolUpperChannel`) is chosen from the clock's seconds: `floor(sec / 59.01 × 7 + 2)`, giving channel 2–8. `CheckFrontChannel` re-draws if the stored value isn't an integer from 2 to 8. Presumably this spreads wear across channels; that's an inference.
  - `TraceGripper` logs the tool's absolute X/Y/Z/R whenever the grippers are ejected after a move.
- **96-head park:** `Move96HeadToFront` runs a `Head96Move` step (MoveType 2, direction 2) to `move_seq`. Its other two steps are disabled and never run: the `Move96HeadUp` call, and a `FirmwareCommand` `H0YA ya07500` (Y to 750.0 mm). (The first version of this note named `H0ZA`/`H0YA` firmware commands as the park; that came from disabled code.)
- **MPE² errors go to an operator console.** Every MPE² wrapper call in `MPE_Library` (`Connect`, `FilterPlatePlaced`, `ProcessFilterToWasteContainer`, `FilterPlateRemoved`, …) loops until the call succeeds. Auto-recovery is off (`useAutoErrorRecovery = 0`), so each failure calls the private `HandleError`. It reads the MPE²'s last error into a custom dialog and returns the operator's choice; 5 breaks out of the retry loop. Choice 7 opens `ManualMPEErrorRecovery`, a menu that loops until the operator finishes, with these actions:
  - re-initialise the library, connect over COM, disconnect, or initialise the device;
  - toggle the vacuum check;
  - re-register the filter plate's heights;
  - process to waste or to the collection plate, with control points the operator types in (`UserSelectControlPoints`) and a "return plate?" flag;
  - clamp the plate, retrieve it, or mark the filter or collection plate as removed.
  Any of these that fails shows the device error and returns to the menu.
- **Error handling:** every file/step gets `MECC::RaiseRuntimeErrorEx` guards (11–6 recoveries per device step, string-table ids). Endless-sequence loop warnings guard `while (GetCurrentPosition() > 0)` idioms.
- **The manual fallback:** with `use_iSWAP = "false"` or `is_pipetting = "false"`, each robot action is replaced by an operator dialog naming the next manual action — the method doubles as a printed SOP. The fallback is incomplete, though. `PipetteMove08` sets `is_pipetting = "true"` before eluting, so elution always pipettes. The MPE² steps, the heater shaker and the lid moves outside `[if use_iSWAP]` run in either mode.

## Open items (§11-adjacent, specific to this method)

- `dispense mode 8`, `DispenseMode 3/5`, `detect mode (open)` 5/7/10/18, `aspirate mode 0/2`, `TipType 0/1/5` — enum semantics still open (§11).
- MPE² pressure program units ("pressure,65,420"): the lab's `Methods/Common/MPE_Library` passes the string straight to Hamilton's `HSLMPELib`, so the units are Hamilton's and are not stated in either.
- `pipette_volume_2 = culture_volume × 3.6` — pellet hold-up factor, measured by the lab, not derived.
- **An abort leaves tip type 5 redefined.** `OnAbort` only writes a trace comment and never calls `ResetCuttedTipLenght`. An abort between the two `C0TT`s in `PipetteMove04` therefore leaves tip type 5 at 71.8 mm / 1003 µL. Whether a re-initialise restores the firmware's tip table is unverified.
- **The `C0TT` comes after the wide-bore pick-up:** `Head96TipPickUp` runs first, then `SetCuttedTipLenght`. Whether the 96-head reads the `C0TT` tip table at all is unverified.
- **Spin path, last lid move:** on the spin path, `PipetteMove08` moves the BP lid from `Lid_parking_Numc_BP` onto the BP/EP stack. `main` then moves a lid from that same parking position to BP storage. Unless the operator puts the lid back during the centrifuge dialogs, whose text isn't in the method files, the gripper reaches into an empty position.
- **The supernatant comes off in 3 passes, two aspirates each:** `Spin_Plate_supernatant` and `Spin_Plate_liquid_waste` list each column twice because every aspirate and dispense step counts 8 positions on, so a pass's second aspirate (the remainder, aspirate mode 2) reaches the same column as its first (1000 µL). Corrected 2026-10-17 from "6 passes"; running the method in PLR (`examples/dna_extraction_demo.py`) showed the six-pass reading takes 3.6 mL from 2 mL wells.
