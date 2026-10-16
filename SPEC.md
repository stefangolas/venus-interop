# venus-interop: specification

Utilities for working between Hamilton Venus and PyLabRobot (PLR), and for scripting Venus's own files, without Venus installed.

Status, 2026-10-15: first assembly of work from `pressure_speed` (the converter) and `plr-viz3d-scratch` (multiflex, 3D models, NGS deck notes). The rules every module follows are in [docs/CONVENTIONS.md](docs/CONVENTIONS.md).

## 1. Scope

| In scope | Out of scope |
|---|---|
| Reading and writing Venus files: layouts, labware definitions, methods' text files | Driving instruments (that is PLR's job) |
| Converting layouts and labware between Venus and PLR, with every difference accounted for | Rendering and motion (`plr-viz3d`) |
| Hamilton's multiflex carriers as data and rules | Hamilton's large binary assets (referenced, not copied) |
| Method tooling: step markers, footers, the pLLD speed library | Editing `.med` files through Venus |
| Corpora and the tests that run over them | |

**Principles:**
1. **No Hamilton executables.** In particular `HxCfgFilConverter.exe`, which sends keystrokes to the focused window.
2. **Lossless first.** File → model → file is byte-identical. LAY → PLR → LAY is byte-identical.
3. **Every changed number is recorded** (the delta ledger), and tests fail on unexplained differences.
4. **Rules are measured.** Each placement or naming rule states its evidence (corpus counts) and its known exceptions.
5. **The core works without PLR.** Only `venus_interop.plr` and `venus_interop.multiflex.plr` import pylabrobot.

## 2. Layout

```
venus-interop/
  venus_interop/
    files/        hxcfg.py      HxCfgFile container: binary + text, footers (.lay .rck .tml .lid .ctr .dck .med)
                  layout.py     DECKLAY model: placements, lids, sequences, layers; lossless
                  definitions.py labware definitions and where to find them (Labware roots, kit folders, by name)
                  footer.py     "$$checksum" footers of text files (.hsl .hs_ .hsi .sub)
    rules/        placement.py  measured placement and naming rules (CONVENTIONS 3, 3b, 4)
                  capture.py    what a layout says beyond plain carrier-site assignments
                  deltas.py     the delta ledger
    plr/          plr_import.py layout -> PLR deck (metadata keeps the Venus fields)
                  plr_export.py imported deck -> layout (byte-identical)
                  deck_export.py PLR-built deck -> layout + definition files (prefer exact | stock)
                  name_match.py Venus definition <-> PLR resource, by fingerprint
                  generate.py   Venus definition -> PLR factory source + model
                  to_venus.py   PLR resource -> Venus definition files
                  xfile.py      Hamilton .x / .hxx 3D models
                  templates/    ML_STAR2.lay (STAR template; STARlet derived)
                  data/         stock_map.json (PLR factory -> stock Hamilton file)
    multiflex/    catalogue.py  Multiflex Carrier Assistant catalogue (MultiMFX.INI) as data
                  assembly.py   baseplate + modules -> sites; check against a Venus-built .tml
                  data/         mfx_catalogue.json
    methods/      hsl.py        step markers in .hsl / .sub: steps, step types, rows
                  plld/         PLLD_Speed.hsl: pLLD search speed (the earlier guide)
    corpora.py    corpus registry: sources, local paths, how to build the definition index
  tools/          command-line entry points (below)
  tests/          unit tests always; corpus tests with VENUS_INTEROP_CORPUS / NGS path set
  docs/           CONVENTIONS.md, and the notes this work rests on (multiflex, NGS decks, discrepancies)
  examples/       hand-built PLR decks for NGS layouts (need the plr-viz3d fork)
```

**Dependencies:**
- **Core** (`files`, `rules`, `multiflex.catalogue`, `multiflex.assembly`, `methods`): standard library only.
- **`plr`:** pylabrobot (tested at main 0f03af3, `1.0.0b1`).
- **Models:** trimesh and manifold3d.

## 3. Modules

### 3.1 `files`

Unchanged from the converter (CONVENTIONS §1–2, §5), plus:
- **`footer.py`:** checks and rewrites the `$$author…$$checksum…$$length` footer that text method files carry. The rules are in CONVENTIONS §1. It never touches a file in place unless asked.
- **`definitions.DefinitionStore`:** resolves references in this order:
  1. the index;
  2. roots in order (put the layout's own kit folder first);
  3. the `…Rel` twin;
  4. by name, opt-in and recorded.

### 3.2 `rules`

`placement` holds the rules of CONVENTIONS §3, §3b and §4 as functions. `capture` and `deltas` are as described in CONVENTIONS §10c–10d.

### 3.3 `plr`

The converter, unchanged in behaviour. Public entry points:
- **Layouts:** `lay_to_plr(layout, store) -> Deck`, `plr_to_lay(deck, store) -> Layout`, `deck_export.export(deck, store, prefer="exact") -> Export`.
- **Definitions:** `to_venus.venus_files(resource) -> VenusFiles`, `generate.spec_for(definition, store)` + `generate.emit(spec)`, `name_match.best_matches(...)`.

### 3.4 `multiflex`

**`catalogue.Catalogue`** loads Hamilton's `MultiMFX.INI` (parsed to `data/mfx_catalogue.json`):
- baseplates: name, template, origin, pitch, 3D origin;
- modules: id name, abbreviation, offsets, `Base`, size, part number, companion modules, carriers it is not valid for.

**`assembly.sites(baseplate, modules) -> [Site]`**, with modules given per position (1 = back). The rule is from MULTIFLEX_ASSEMBLY.md:

```
X = B.OriginX + M.OriginLOffsetX
Y = B.OriginY + (n - 1) * B.OffsetY + M.OriginPOffsetY
Z = M.Base
(Dx, Dy) = (M.Width, M.Length)
```

A companion module (`AddModul`) adds a second site on the same position at its own `Base`.

**`assembly.check(tml)`** finds the baseplate (from width and first site), reads each site's module from its id (`<n>_<IdName>`), and compares every site with the rule. The result is a list of differences.

**`multiflex.plr`** (needs PLR) builds an `MFXCarrier` from the same sites. It is a generic configurator that complements the hand-written factories, which stay in pylabrobot. Each site becomes a `PlateHolder`: an SBS plate centred on the 127 × 86 site (CONVENTIONS §3b) and resting at `Base`.

### 3.5 `methods`

- **`hsl.steps(text)`** reads the step markers Venus writes into `.hsl` / `.sub` (`// {{{ row block 0 "guid" "{clsid}"`). It returns rows, blocks, GUIDs and step types (library call, sub-method call, If, loop, assignment, comment, …), with the code between markers. That is enough to list, find and diff a method's steps outside Venus. Writing steps back is a non-goal: the `.med` stays authoritative, see the pLLD guide.
- **`plld/PLLD_Speed.hsl`** is the library from the pLLD search speed guide: `SetZSpeed` / `RestoreZSpeed` through `PxAA`.

### 3.6 `corpora`

A registry of the layouts and definitions the corpus tests use:
- **lmsf_hamilton** (GitHub);
- **pyhamilton** samples;
- **NGS-Protocols** (local);
- **the local Venus install;**
- **the Hamilton shared library** (downloaded by `plr-viz3d-scratch`).

For each it records where it comes from, where it is locally, and how to index it. `tools/build_corpus.py` builds `raw/*.lay`, `defs_raw/` and `defs_index.tsv` from local folders. Fetching from the network is explicit and opt-in.

## 4. Tools

| Tool | Does |
|---|---|
| `generate_labware.py` | Venus definitions → PLR factories + models |
| `roundtrip_definitions.py` | definition round trips, both directions |
| `build_stock_map.py`, `audit_stock.py` | PLR ↔ stock Hamilton files, and where they disagree |
| `capture_log.py` | capture logs for layouts; systematic offsets |
| `redundancy.py` | how much of each layout follows from the rules |
| `known_exceptions.py` | the rule exceptions the tests allow |
| `mfx_check.py` | multiflex carriers (`.tml`) against the catalogue rule |
| `mfx_reconcile.py` | pylabrobot's multiflex factories against Venus templates (needs the fork) |
| `hsl_steps.py` | list a method's steps |
| `build_corpus.py` | corpus folders from local sources |

## 5. Tests

| Suite | Needs |
|---|---|
| unit (files, rules, multiflex, methods) | nothing |
| PLR (import/export, definitions, deck export, ledger) | pylabrobot |
| corpus (T0–T4, rules, capture) | `VENUS_INTEROP_CORPUS` |
| NGS | `VENUS_INTEROP_NGS` (an NGS-Protocols checkout) |
| stock audit | a Venus install (`C:\Program Files (x86)\HAMILTON\Labware`) |

## 6. Provenance

- **Moved here:** the code from `pressure_speed` (the converter, its tests, CONVENTIONS) and from `plr-viz3d-scratch/hamilton_library` (the multiflex catalogue and rules, `x_to_glb`), plus notes from `plr-viz3d-scratch` (MULTIFLEX_ASSEMBLY, DISCREPANCIES, CPAC_RESEARCH, HSP_MIDI_PLATES, HAMILTON_3D_MODELS, REVIEW, the KAPA and TC `VENUS_TO_PLR` notes).
- **Left where they are:** rendering, iSWAP/motion and 3D-model build scripts, and the Hamilton binaries and downloads. The originals were not changed.
