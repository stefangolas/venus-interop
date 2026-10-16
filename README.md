# venus-interop

Read, write and convert Hamilton Venus files in Python, without Venus installed, and move decks and labware between Venus and [PyLabRobot](https://github.com/PyLabRobot/pylabrobot) (PLR) with every difference accounted for.

```python
from venus_interop.files import layout
from venus_interop.files.definitions import DefinitionStore
from venus_interop.plr import plr_import, plr_export

store = DefinitionStore.default()                     # the local Venus Labware folder
lay = layout.read_layout("KAPA_HyperPlus_Deck.lay")   # binary or text form
deck = plr_import.lay_to_plr(lay, store)              # a pylabrobot HamiltonSTARDeck
deck.metadata["venus"]["capture"]["summary"]          # what the layout says beyond plain site assignments
again = plr_export.plr_to_lay(deck, store)            # byte-identical to the original file
```

## What it does

| Area | Module | Status |
|---|---|---|
| Venus's config-file container (`.lay .rck .tml .lid .ctr .dck .med`), binary and text | `files.hxcfg` | Every corpus file rewrites byte for byte; text output matches Hamilton's converter |
| Deck layouts as objects: placements, lids, sequences, layers | `files.layout` | Lossless on 152 + 10 layouts |
| Labware definitions and where to find them (Labware roots, kit folders, `…Rel` paths, by name) | `files.definitions` | |
| Text-file footers (`.hsl .hs_ .hsi .sub`): check and rewrite the checksum | `files.footer` | |
| Measured placement and naming rules | `rules.placement` | Each with corpus counts; see [docs/CONVENTIONS.md](docs/CONVENTIONS.md) |
| Capture log (nudges, taught heights, stacks, alternatives) and delta ledger | `rules.capture`, `rules.deltas` | |
| Layout → PLR deck → layout | `plr.plr_import`, `plr.plr_export` | Byte-identical on 149/149 STAR corpus layouts and 10/10 NGS layouts |
| PLR-built deck → layout + definition files | `plr.deck_export` | Exact round trips; stock Hamilton files used only when provably identical |
| Venus definition → PLR factory code + 3D model | `plr.generate` | 196 corpus definitions; models authored (`.x`/`.hxx`) or generated |
| PLR resource → Venus definition files | `plr.to_venus` | Equivalent round trips for 197/197 corpus definitions and all PLR labware types but trash and two mixed racks |
| Venus definition ↔ PLR resource matching | `plr.name_match` | By geometry + tip type, never by geometry alone |
| Multiflex carriers: Hamilton's catalogue, assembly rule, check, PLR builder | `multiflex` | 31/43 NGS sites exact; differences explained |
| Method code: step markers, step types | `methods.hsl` | Read-only; the `.med`/`.hsl` format is documented in CONVENTIONS §12 |
| pLLD search speed library (`PxAA` zv) | `methods/plld/PLLD_Speed.hsl` | See [docs/plld-search-speed.html](docs/plld-search-speed.html) |

Not here:
- **Driving instruments:** use pylabrobot.
- **Rendering and motion:** `plr-viz3d`.
- **Editing `.med` files:** the Method Editor stays authoritative. How a step is stored across `.med`, `.hsl` and `.sub`, and the edit a script would make, are in [CONVENTIONS §12](docs/CONVENTIONS.md#12-method-files-med-hsl-sub).
- **`HxCfgFilConverter.exe`:** never used. It sends an Enter keystroke to the focused window.

## Install

```
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[plr,models,test]"
```

The core (`files`, `rules`, `multiflex` without `.plr`, `methods`) needs only the standard library. `plr` needs pylabrobot (pinned to main at 0f03af3, `1.0.0b1`), and models need trimesh and manifold3d.

## Command-line tools

All tools are in `tools/` and print usage with `-h`.

| Tool | Does |
|---|---|
| `capture_log.py OUT LAYOUTS… [--kits DIR] [--labware DIR]` | Per-layout logs of what each layout says beyond the rules, plus labware that sits off its site and systematic offsets |
| `redundancy.py --corpus DIR [--ngs DIR]` | How much of each layout is regenerable from (labware, carrier, site) |
| `generate_labware.py OUT [DEFS…] [--corpus DIR --layouts]` | PLR factories and `.glb` models from Venus definitions |
| `roundtrip_definitions.py plr` / `venus --corpus DIR` | Definition round trips, with the differences listed |
| `build_stock_map.py`, `audit_stock.py` | Map PLR factories to stock Hamilton files, and list where they disagree |
| `model_coverage.py --corpus DIR [--ngs DIR]` | How much of the used labware has a 3D model |
| `mfx_check.py PATH…` | Multiflex carriers against the catalogue rule |
| `mfx_reconcile.py` | pylabrobot's multiflex factories against Venus templates (needs the `plr-viz3d` fork) |
| `hsl_steps.py METHOD.hsl [--summary]` | A method's steps and step types |
| `build_corpus.py OUT --source ngs_protocols …` | A corpus folder from local sources |
| `known_exceptions.py` | Regenerate the rule exceptions the tests allow |

## Tests

```
.venv\Scripts\python -m pytest                     # unit tests; corpus tests skip
set VENUS_INTEROP_CORPUS=C:\path\to\corpus         # + 1,500 corpus tests (about 3 minutes)
set VENUS_INTEROP_NGS=C:\Users\stefa\NGS-Protocols # + the NGS STAR layouts and multiflex carriers
```

A corpus folder holds `raw/*.lay`, `defs_raw/` and `defs_index.tsv`; `tools/build_corpus.py` builds one, and `venus_interop/corpora.py` lists the sources. A few tests also need a local Venus install for its stock labware.

## Findings worth knowing

These are documented with evidence in [docs/CONVENTIONS.md](docs/CONVENTIONS.md).

- **A rack's `TForm.3` is its A1 position.** It equals the corner + (BndryX, BndryY + (Rows − 1) · Dy). The often-quoted `Dim.Dy − BndryY` is only right for symmetric 96-well plates.
- **`ZTransValue` 0 or 1 means "on the site or on a stack"**, with 18 exceptions in about 3,900. Only `ZTransValue 2` heights carry information, including 93 racks set to site Z + their container base.
- **Default sequences:**
  - Named by `IX.Index` / `IX.Inc` (A1… or numbered down columns or across rows).
  - Stored sequences that differ are user edits.
- **Venus and PLR model the same objects differently:**
  - Venus uses a nominal 127 × 86 plate footprint.
  - PLR tip racks sit 6 mm into their carrier (`sinking_depth`).
  - Venus's container base is the tip's bottom, while a PLR tip spot is its seat.
- **Tips:** for 10 and 1000 µL tips, Venus's files and PLR's model disagree by ±2.1 mm on where the tip ends. That's exactly PLR's collar heights (6 / 10 mm) against its flat 8 mm fitting depth. Unverified on an instrument.
- **pylabrobot gaps the converter works around** (CONVENTIONS §8):
  - 4/5 mL tips can't be built.
  - Overlapping labware is refused when loading a deck.
  - Coordinates are rounded to 1e-4.
  - Models name base factories.

## 3D models

Coverage of the labware the corpus and NGS layouts use (`tools/model_coverage.py`), as distinct definitions / placements:

| | Hamilton model on this PC | Named, file not downloaded | None (generated) |
|---|---|---|---|
| Carriers | 36% / 22% | 32% / 61% | 18% / 15% |
| Racks | 14% / 25% | 6% / 8% | 59% / 61% |
| Lids | 0 | 0 | 77% / 87% |

The rest are definitions that aren't on hand. Generated models are bounding-box bodies with each container cut out: conservative for collision checks, and never a check on the numbers they're made from.

## Layout of the repository

See [SPEC.md](SPEC.md) for the architecture, [AGENTS.md](AGENTS.md) for working on it, and [docs/](docs/) for:
- the conventions;
- the converter's original spec;
- the notes this work builds on (multiflex assembly, Venus-to-PLR notes for the KAPA and tissue-culture decks, Hamilton data discrepancies, CPAC research).

`examples/` holds the hand-built PLR decks for the KAPA and tissue-culture layouts. They need the `plr-viz3d` fork (`fork/viz3d-motion`) for the multiflex, ODTC and CPAC factories.
