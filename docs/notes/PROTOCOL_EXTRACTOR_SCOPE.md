# Scope: HSL → protocol decompiler and pretty-printer

Status: scoped 2026-10-15, **built 2026-10-16**: `methods/hsl_code.py`, `methods/stp_pars.py` and `methods/protocol.py` are in, tested, and produce full + condensed traces for all 10 NIST methods (`.local\session_state\analysis\traces\*.trace.md` / `*.condensed.md`, 0 unresolved settings). The trace captures everything (capture-everything, then condense): library and method-section calls inline recursively with bound args, every call tagged by role (`robot`/`equipment`/`data`/`config`/`ui`), device steps render with their `.stp` settings and volumes symbolic (`aspirate volume = <p_vol>`); identical function bodies elide after 3 expansions (settings are per-GUID, so repeats are structurally identical). The condensed view drops trace-file plumbing and error-guard boilerplate, renders parameter reads as `params[key]`, and keeps robot operations, control logic and device settings. Remaining: write the protocol documents for the 10 methods from these traces.

## What it is

A **decompiler + pretty-printer**, not a transpiler: read a Venus method (`.hsl` + `.sub` + included `.hsi` libraries), resolve names and arguments, and emit a written protocol (markdown) — numbered steps with volumes as symbolic formulas, tip policy, liquid classes, mixing, LLD, gripper moves.

It is the **front half of a compiler plus a documentation back-end**. A transpiler to runnable PLR/PyHamilton would need complete semantics (error recoveries, scheduler behavior, dialogs) and is explicitly out of scope.

## What is already proven (probes from 2026-10-15)

| Claim | Evidence |
|---|---|
| The code is pre-chunked into an AST by Venus: `// {{{` step markers, sections, compound parts | `venus_interop.methods.hsl` parses all 10 methods + 5 libraries losslessly (189–1,733 steps per method) |
| Command names are free: the generated code has the call **and** a trailing `// Aspirate` comment; the `.stp` record also carries `1StepName = "Aspirate"` | `GSF-IMS.shared_submethods.hsi:168`; `GSF-IMS.shared_submethods.stp` record `05a6e94c…` |
| Device-step calls are `<var>._<CLSID-with-underscores>("step-guid")`, variable usually `STAR` in libraries, `ML_STAR` in methods | grep of `GSF-IMS.shared_submethods.hsi` |
| The **`.stp` record self-documents its numeric keys**: the `(Variables …)` block maps method variable names → (channel-block, key-id), so `-534183924` = aspirate volume (`p_vol`), `-534183914` = `mix_cycles`, `-534183915` = `mix_volume` | same record |
| Liquid class is a plain string key in the record: `1LiquidName = "HighVolumeFilter_Water_FastMixing_DispenseSurface_Empty"` | same record |
| Per-channel settings come as 8 blocks under key `-534183936`, usually identical across channels; divergences are the interesting bits | same record |
| The library surface is small: ~70 unique functions across the 5 `.hsi` libraries (GSF-IMS 15, PlateAndLidMovement 26, LMSF_Utilities 21, Common96Head 5, TipHandling96 3). Each library lists functions twice (declaration + definition) | function inventory regex over `lmsf_libs/*.hsi` |
| Control flow is a bounded CLSID set: If/Else `{B31F3531}`, Loop `{B31F3532}`, plus ~15 unknown B31F35xx and a handful of others; each nameable by reading the code Venus generates for it | `hsl.summary` per file |
| `{F07B0071-…}` is the trace/blank wrapper, not a device step | HANDOFF §4 |

## Architecture (proposed, stdlib only, no PLR dependency)

```
venus_interop.methods.hsl        exists: step/section markers
venus_interop.methods.hsl_code   NEW: function bodies (regex + brace matching skipping strings/comments)
venus_interop.methods.steps      NEW: classify step CLSIDs; parse expressions inside assignments/calls
venus_interop.methods.stp_pars   NEW: HxPars record → typed dict; decode keys via (Variables) map
                                      + a named-key table for the anonymous remainder
venus_interop.methods.protocol   NEW: binder (args, globals, params.csv) + expansion of main
                                      + markdown back-end
```

1. **Function inventory** per library (names, arity) — done manually here, trivially automated.
2. **Expression level**: assignments, `Dictionary::GetItem`, `String::Split`, array indexing. Only as deep as the volume maths needs; everything else passes through as `<call>` placeholders.
3. **Binder**: parameters.csv keys (GetParams section), `ML_STAR.<name>` globals → the layout's sequence (count, labware, positions via `files.layout`), call arguments bound positionally.
4. **Device steps**: guid → `.stp` record → `Aspirate 200 µL [p_vol] from `from_seq`, 1000 µL filtered tips (TipType 5), liquid class …, mix 3× at …`. Volume keys that hold variables render the variable name; constants render the number.
5. **Back-end**: markdown per method — purpose, deck table, parameters, then the numbered protocol with TraceComment texts as headings.

## Remaining unknowns (measured, not assumed)

- **~10 anonymous numeric keys per channel block** (`-534183918`, `-534183919`, `-534183622`, `-534183700`, `-534183876`, `-534183913`, `-534183920`, `-534183925/6/28`, `3DispenseMode`, `3TipType` enum). Decodable by (a) records where the value is a literal rather than a variable (meaning inferred from context), (b) comparison across the 105 `.stp` files, (c) Venus step dialogs. Bounded: one table, built once, reused by every method.
- Enum values for `TipType` (numeric 5 = ?), `DispenseMode`, `SequenceCounting`, `TouchOffMode` — same approach.
- Error/recovery text is string-table IDs (`3ErrorDescription = 1689`). *Resolved 2026-10-16:* the titles are in `Bin\HxGruCommandEnu.dll` (CONVENTIONS §12, "Error policies"); traces render every error policy, and the condensed view keeps the ones set to repeat or use their default.
- The ~15 unknown control-flow CLSIDs — nameable by inspection, one afternoon.
- Includes resolve under the Library and Methods folders, not next to the method. Extension variants `.hs_/.hsl/.hsi` seen in the same method's include list. *Resolved 2026-10-16:* `protocol.load_method` follows the include closure (a `.hs_` header to its `.hsi` body) and loads only the `.stp` files beside those files (CONVENTIONS §12).

## Effort estimate

| Stage | Effort |
|---|---|
| hsl_code (function bodies) + CLSID classification | ~½ session |
| stp_pars + the named-key table (the honest risk: stops at the first key the (Variables) trick doesn't cover) | 1–2 sessions |
| binder + expansion + markdown back-end | 1 session |
| Write-up pass over the 10 methods using the traces | ½ session |

Roughly 3–5 focused sessions to a working extractor over the 10 LMSF methods. Generalizing beyond this lab's library style (Avenio's NGSStarProcesses, dialog-driven code) is a larger project and should be a separate decision.

## Deliverables

1. `venus_interop.methods.protocol` + tests (round-trip: every device step in the trace must come from a real call site; settings joined from the `.stp`).
2. `docs/notes/` protocol write-ups for the 10 methods, generated traces kept in `.local\session_state\`.
3. CONVENTIONS entry for the named-key table with its evidence, per the "rules are measured" rule.
