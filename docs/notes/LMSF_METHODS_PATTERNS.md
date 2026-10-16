# NIST LMSF methods: cross-cutting patterns

Measured 2026-10-16 over the 10 fetched methods and their 5 libraries (device-step and namespace-call census; traces in `.local/session_state/analysis/traces/`). Companion to the per-method protocol write-ups.

## Unit operations

Static device-step inventory across all methods + libraries (~200 steps total):

| Device step | Count | Role |
|---|---|---|
| Head96TipPickUp / Eject | 23 / 17 | bulk tip handling |
| Head96Aspirate / Dispense | 22 / 20 | stamping (usually 24-channel patterns) + reagent dosing |
| ZSwapGetPlate / ZSwapPlacePlate | 20 / 20 | every lid/plate move is the CO-RE gripper |
| Aspirate / Dispense (1–8 ch) | 12 / 11 | inside `GSF-IMS.shared_submethods`, reached via `pipette_media` (14×), `add_reagent_*` (19×) |
| Initialize | 11 | one per method |
| iSWAP GetPlate / PutPlate / Park | 4 / 4 / 4 | only the MPE² example |
| FirmwareCommand / Head96Move / MoveToPosition | 2 / 2 / 2 | the 96-head park, inside `Common96HeadSubMethods`, reached via `Move96HeadAndArm` (15×). In the LMSF library the park is the `Head96Move`; its `FirmwareCommand` (`H0YA ya07500`) is a disabled step. Colony Picking's own `Culture processing\Move96HeadAndArm` does send `H0ZA za68500` + `H0YA ya07500`. |

The lab is 96-head-first; 8-channel pipetting always goes through the shared library; iSWAP barely used (ZSwap instead). All variety lives in settings + call-site binding, not in new steps.

## Data handling

1. **`parameters.csv` → Dictionary → default → clamp** (`GetParams`, identical contract everywhere; `cultureVolume` 200–500).
2. **Sequence properties as the data model** — `SeqSetPropertyRange/ByWell`, `SeqCopyPropsFromShortSeq` stamp concentrations, plasmid and strain IDs onto wells; the Growth Plate sequence is the experiment record.
3. **Filesystem as the message bus** — worklist + metadata CSVs out, `HamiltonStatus.csv` status out, and the `LABWAREHANDLING` handshake (RequestLabware → completion file → WaitFor…Completion) synchronises method-to-method through the Overlord.
4. **Persistent tip counters** — `TipCount::Read2/Write2/Edit2` (~63 calls) survive across runs.
5. **Dictionary KV-store** (90 `GetItem`s) and `Translate()` around every literal.

## Recurring logic patterns

- **Sequence-walk idiom:** `SetCurrentPosition(1); while (GetCurrentPosition() > 0) { AlignSequences(…); pipette; }` + `EndlessSequenceLoopWarning` + `SetMax(GetTotal())` reset — Venus's iterate-a-sequence, everywhere.
- **Per-channel volume arrays:** `number_channels` → `p_vol_arr` (first N = volume, rest 0), bound through the `ArrayAddIndex/ArrayStartIndex` HxPars keys.
- **Runtime liquid-class selection** by tip type: `STAR_TIP_TOOLS::GetTipType` → if/else between `StandardVolume…` and `HighVolume…`.
- **Over-fill multiplier** `f/(f−1)` on gradient starts (compensates the dilution series' withdrawals).
- **Lazy restock:** `RenewOffsetTips` only when `GetCurrentPosition() == 0`.
- **Feature flags as mode switches:** `is_pipetting` / `is_debugging` / `use_iSWAP` / `_blnSimulationMode` — robot run, manual SOP (dialogs) and simulator-safe script in one file.
- **Multiplexing by modulo:** `sequence_number = plate % 4` + `GetAt(sequence_number-1)` — four runs share one deck.
- **Two pipetting styles coexist:** config-heavy (`PTL::SetPipettingState` per step: Triplicate 511, Simple media 328, Zyppy 112 calls, direct `PTL::Pipette3`) vs library-wrapped (GROQ/Marionette: one device step in the method, everything through the shared library). DNA Extraction mixes both.
- **Disabled steps left in place:** a step switched off in the Method Editor stays in the code inside `if(0){ … }`. It appears in 17 of the fetched files: 8 of the 10 methods, plus `LMSF_Utilities`, `Common96HeadSubMethods`, the culture-processing libraries and the DPX/STAR tip tools. Some examples change what a reader would conclude:
  - DNA Extraction's `is_debugging = "false"`;
  - DPX's cut-tip check;
  - Colony Picking's top-light source;
  - Simple media's `CalculateOutputs` + `SaveWorklistAndMetadata`.
  The traces mark these steps `# [disabled step, never runs]`; before 2026-10-16 they were shown as live code.
- **Guard boilerplate:** every file op wrapped in `if (0 == …) RaiseRuntimeErrorEx(<negative code>, MECC::IDS::…)` (123 total).
- **Stage naming:** `PipetteMoveNN` sections (DNA Extraction, Zyppy) or `A_Definitions/B_Initialise/C_Pipetting/D_Cleanup` (Colony Picking); scheduler sections `GetParams/StartUp/CalculateOutputs/SaveWorklistAndMetadata/CleanUp/OnAbort`.
