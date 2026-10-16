# venus_lay — converting between Venus `.lay` files and PyLabRobot decks

Status, 2026-10-15: steps 1–3 are implemented and tested (`hxcfg`, `layout`, `definitions`, `rules`, `plr_import`, plus `plr_export` for imported decks). Step 4, writing layouts for decks built in PLR, is not started. See section 5. PLR version: main at 0f03af3 (`1.0.0b1`), installed in `.venv`.

## 1. Goal

Convert a Hamilton Venus deck layout (`.lay`) to a PyLabRobot (PLR) deck and back, without Venus installed.

- **LAY → PLR**: every carrier, rack, stack and lid on the deck becomes a PLR resource at the correct location.
- **PLR → LAY**: a PLR deck becomes a `.lay` that Venus opens, with a default sequence generated for every rack.
- **Not preserved**: user-made sequences, layers, barcodes and view settings. As established, these are often stale and PLR has nowhere to put them. LAY→PLR keeps them as metadata so a LAY→PLR→LAY round trip can carry them through, but the converter never interprets them.

The package must not depend on any Hamilton executable. `HxCfgFilConverter.exe` presses Enter in whatever window has focus each time it runs, so it is unsuitable for scripts or CI.

## 2. Layers

```
                 ┌─────────────────────────────────────────────┐
  plr_import.py  │ Layout + Definitions  ──►  PLR Deck (JSON)   │   (planned)
  plr_export.py  │ PLR Deck  ──►  Layout + generated sequences  │   (planned)
                 ├─────────────────────────────────────────────┤
  rules.py       │ geometry and sequence rules (pure functions)│
                 ├─────────────────────────────────────────────┤
  layout.py      │ Layout model: carriers, racks, lids, seqs   │
  definitions.py │ .rck / .tml / .lid / .ctr loading + search  │
                 ├─────────────────────────────────────────────┤
  hxcfg.py       │ HxCfgFile: binary + text read/write, footer │
                 └─────────────────────────────────────────────┘
```

Each layer only imports the ones below it. Nothing below `plr_*` imports PyLabRobot.

### 2.1 `hxcfg.py`: file format

All Venus configuration files share one container format, HxCfgFile. Layouts, rack and carrier definitions, and methods (`.med`) all use it, in either a binary or a text form.

**Model**

```python
@dataclass
class Section:            # DataDef,TYPE,VERSION,NAME,
  type: str
  version: int
  name: str
  entries: list[tuple[str, str]] | None   # dictionary section  { key, "value", ... }
  items: list[str] | None                 # list section        [ "item", ... ]

@dataclass
class CfgFile:
  version: int            # HxCfgFile,N  (2 or 3)
  valid: bool             # ConfigIsValid,Y
  sections: list[Section] # dictionary sections first, then list sections (binary order)
  footer: Footer          # author, valid, time, length offset; checksum recomputed on write
  binary: bool            # form it was read from
```

**Binary form** (all little-endian):

```
u16 version (2|3)   u16 valid (1)   u32 dict_count
  dict_count × { str "TYPE,NAME"  u16 section_version  u32 n  n × (str key, str value) }
version 3 only:
  u32 list_count
  list_count × { str "TYPE,NAME"  u16 section_version  u32 n  n × str }
"\r\n" footer
str = u8 len | 0xFF u16 len, then latin-1 bytes
```

**Text form**: `HxCfgFile,3;` and `ConfigIsValid,Y;`, then `DataDef,TYPE,VER,NAME,` blocks with `{ key, "value", }` or `[ "item", ]`, CRLF line endings, then the footer line. Inside a value: `\\`, `\"`, `\n`, `\r`, `\t`, and `\0xhh` for any other byte outside printable ASCII.

**Footer**: `* $$author=…$$valid=…$$time=…$$checksum=XXXXXXXX$$length=NNN$$`

- `checksum` is CRC32 of everything from byte 0 up to and including `$$checksum=`.
- `length` is the footer line length plus an offset that depends on the form: 0 for text, 2 for binary, kept as found when rewriting an existing file.

**API**

```python
read(path_or_bytes) -> CfgFile            # detects the form
write_binary(cfg) -> bytes
write_text(cfg) -> bytes
footer_ok(data) -> bool
```

**Acceptance (T0/T1)**
- Every corpus file reads, and its footer verifies.
- `write_<same form>(read(f)) == f` byte for byte.
- `write_text(read(binary))` matches Hamilton's converter output byte for byte up to the footer.

### 2.2 `layout.py`: the layout model

Wraps the `DECKLAY,<instrument>` section (and `DECKLAY,<instrument>_COVER` for lids) in typed objects. Keys the model doesn't know are carried through untouched.

```python
@dataclass
class Placement:          # one Labware.N.* group
  fields: dict[str, str]  # every subkey verbatim: Id, File, Template, SiteId, TForm.3.X, ZTrans, ...
  lid: Placement | None   # the _COVER section's Labware.N (N is the plate's index)
  # typed properties over `fields`: id, file, template, site_id, tform, z, z_mode, angle,
  # def_seq_valid, kind ('carrier' | 'rack' | 'lid' | 'other')

@dataclass
class Sequence:
  name: str
  items: list[tuple[str, str]]   # (labware id, position id)
  read_only: str | None

@dataclass
class Layout:
  instrument: str
  header: dict[str, str]          # Deck, ActiveLayer, PhoenixVersion, ...
  labware: list[Placement]
  covers: list[Placement]
  sequences: list[Sequence]
  layers: list[Layer] | None      # None when the file has no Layer.Cnt
  cfg: CfgFile                    # the other sections (DEVICE, RESOURCES, ...) pass through
```

Values stay strings, so `Layout.from_cfg(cfg).to_cfg() == cfg` holds exactly. Numbers are parsed by properties and formatted (`fmt`, shortest form) only when assigned. Keys are written in plain ASCII order, as Venus does in every corpus file. Indexes are regenerated from list positions; a lid moves with its plate.

**Acceptance (T1)**: `to_cfg(from_cfg(cfg))` gives an identical file on every corpus layout.

### 2.3 `definitions.py`: labware definitions

- `DefinitionStore(search_paths)` resolves a `Labware.N.File` against a list of roots:
  1. the Venus `Labware` folder,
  2. the folder of the layout itself,
  3. the corpus.

  Lookup is case-insensitive, because Windows file names are.
- It loads `.rck` (racks), `.tml` (carriers), `.lid` and `.ctr` (containers), which are all HxCfgFile.
- `Rack` exposes `rows`, `columns`, `dx`, `dy`, `boundary_x`, `boundary_y`, `dim`, `stack_height`, `hole_count`, `index_mode` (`IX.Index`) and `container`.
- `Carrier` exposes its sites as `{site_id: (x, y, z, dx, dy)}`.
- A missing definition is reported, not fatal. In the corpus, 87 of 284 referenced files are missing. A placement with no definition is kept as an opaque resource with its stored coordinates.

### 2.4 `rules.py`: geometry and sequences

Pure functions, each matching a rule measured on the 152-layout corpus. The counts are in the layout page.

| Function | Rule |
|---|---|
| `rail_location(site_id)` | `<w>T-<rail>` → X = 100 + (rail−1)·22.5, Y = 63, Z = 100. `M` means a negative rail. |
| `a1_offset(rack)` | (BndryX, BndryY + (Rows−1)·Dy), with Rows taken as 1 when it is missing |
| `rack_corner(tform, rack)` / `rack_tform(corner, rack)` | Convert between TForm.3 and the rack's front-left corner |
| `site_z(carrier_z, site)` | Rack Z = site Z when ZTransValue is 0 or 1 |
| `stack_z(site_z, racks)` | Each rack sits at the Z of the one below plus that one's StackHt |
| `lid_corner(plate_corner, rack, lid)` | Lid centred on the plate footprint. Lid Z is kept as stored (no rule yet). |
| `default_sequence(id, rack)` | Named by the rack's `IX.Index` and `IX.Inc`; see the table below. Racks with no grid get `1..HoleCnt`. |

Position labels depend on two settings in the `.rck` file. The local Venus library uses six combinations of the four `IX.*` keys.

| IX.Index | IX.Inc | Labels and order | Example | Evidence |
|---|---|---|---|---|
| 1 | 0 | A1, B1 … H1, A2 (letters on rows), column-major | most plates | 585+ exact sequences |
| 0 | 1 | 1, 2 … 8, 9 (numbered down the columns), column-major | HTF_L tips, CORE waste | 1,201+ exact |
| 0 | 0 | 1, 13, 25 … (numbered across the rows), column-major order | Nunc 1.3 ml plates | 2 exact, plus single-column racks |
| 1 | 1 | A1 … H1, A2 (letters on columns, numbers on rows), letters fastest | ans_96_c18_spe (portrait, placed at 90°) | 1 sequence |

- `IX.First` is 1 everywhere. Any other value raises `UnsupportedNaming`.
- `IX.Start = 1` appears only on portrait racks (`Cos_1536_10ul_P`, `ans_96_c18_spe`, a 1×1 trough). It probably picks the corner where A1 sits, which sequence names alone can't show. `naming_confidence()` returns `unverified` for these, so an exporter can refuse or warn.

384-well "quadrant" orders and other non-column-major sequences in the corpus are user edits, not a different convention.

Deviations in the corpus (manual nudges, ZTransValue 2) are reported by `rule_report()`, never "fixed".

### 2.5 `plr_import.py` / `plr_export.py` (planned)

**LAY → PLR**
1. Build the deck from `Deck` (`ML_STAR2.dck` → `STARDeck`, `ML_Starlet.dck` → `STARLetDeck`).
2. For each carrier on a rail: find the PLR carrier class through the name map, or build a `Carrier` from its `.tml`. Assign it with `rails=`.
3. For each rack on a carrier site: find the PLR plate or tip rack class, or build `Plate`/`TipRack` from the `.rck`. Assign it to the site and check that the rule-predicted location equals the stored TForm.
4. Stacks become `ResourceStack` objects, and lids become `Lid` objects on their plate.
5. Anything that can't be placed by rule keeps its stored absolute location, with a warning.
6. Venus-only fields go into `resource.metadata["venus"]`: File, Id, Clsid, ZTransValue, extra, and the original sequences.

**PLR → LAY**
1. Walk the deck tree. Each resource needs a Venus `File`. It comes from `metadata["venus"]`, then the name map, then an error listing the resources without a mapping.
2. Compute TForm, ZTrans and SiteId with the inverse rules.
3. Generate one default sequence per rack with `DefSeqValid = 1`, and copy the `DECKLAY` header from a template layout for the target deck.
4. Write a binary `.lay` with a fresh footer.

**Name map**: a table `venus_names.csv` (`venus_file, plr_factory`). It is seeded with the 29 `Hamilton name:` docstrings in PLR and extended by hand.

## 3. Test plan

| Stage | Test | Needs |
|---|---|---|
| T0 | Every corpus file reads and its footer verifies | corpus |
| T1 | Byte-identical rewrite (binary→binary, text→text), and layout model round trip | corpus |
| T2 | Rules hold, with named exception lists | corpus + definitions |
| T3 | LAY→PLR→LAY gives a **byte-identical** file (metadata carries what PLR can't express) | PLR |
| T3b | The same, with metadata stripped to non-derivable fields only: placement comes from the rules and sequences from the generator, for layouts with no edits. This is the real test of the rules. | PLR |
| T4 | PLR→LAY→PLR equal on generated decks, and PLR→LAY→PLR→LAY byte-identical from the second LAY on | PLR |
| deferred | Deck Editor opens the output; Venus-reported well positions; lid Z; 384-well order; rotated labware | Venus |

The corpus (152 layouts, 197 definitions) isn't checked in because it comes from third-party repositories. Tests find it through `VENUS_LAY_CORPUS` and skip when it is unset. Synthetic files built in the tests cover T0/T1 and the rule functions, so those always run.

## 4. Open questions

- Lid Z has no rule; it is kept as stored on import and needs a value on export (deferred, Venus).
- `IX.Start = 1` (portrait racks): which corner is A1. 384-well non-column-major orders turned out to be user edits.
- Rotated labware (`Angle ≠ 0`) isn't analysed yet.
- Does Venus accept a text-form `.lay`? It doesn't matter for now, because we can write binary.

## 5. Progress

| Step | Module | State | Evidence |
|---|---|---|---|
| 1 | `hxcfg.py` | done | All 152 layouts and 197 definition files, plus a 2.3 MB `.med` in both forms, rewrite byte for byte. Text output equals the Hamilton converter's on 150/150. |
| 1 | `layout.py` | done | 152/152 layouts rewrite byte for byte through the model. |
| 2 | `definitions.py` | done | Resolves against an index plus the Venus `Labware` folder, case-insensitively. 53 referenced files are still not found. |
| 2 | `rules.py` + `known_exceptions.json` | done | Totals in the table below. Every failure is listed by labware id, so a new failure fails the test. |
| 3 | `plr_import.py`, `plr_export.py` (imported decks) | done | LAY→PLR→JSON→LAY is byte-identical on 149/149 STAR-family layouts. PLR's A1 centre equals Venus's stored A1 on 3,940/3,940 unrotated racks. Moving carriers in PLR moves exactly their trees in the exported file. |
| 4 | `deck_export.py` for decks built in PLR | done | STAR and STARlet test decks: PLR → LAY → PLR gives equal positions; PLR → LAY → PLR → LAY is byte-identical. Stock Hamilton files are used where provably the same, otherwise files are written to `Labware\PLR`. |
| 5 | Venus checks | deferred | |

Corpus results (STAR-family decks, rotated labware skipped):

| Rule | Pass | Known exceptions |
|---|---|---|
| carrier_on_rail | 1071 | 0 |
| rack_on_rail | 61 | 1 (a 0.4 mm nudge) |
| rack_on_site | 3745 | 83 (manual nudges); 17 skipped because the carrier definition is missing |
| rack_z (bottom of site) | 3417 | 30 |
| stack_step | 111 | 1 |
| lid_name | 430 | 0 |
| lid_xy | 350 | 32 |
| sequence_names (every stored position is a valid generated name) | 2511 | 0 |
| default_sequence (stored == generated) | 2187 | 625 |

The 625 default-sequence differences all look like user edits, not a different Venus default:

| Count | What the user did |
|---|---|
| 291 | Deleted the rack's own sequence; the rack is in a shared sequence, typically tips |
| 260 | Reordered it, usually row-major A1, A2… or 8-channel interleaving on 384-well plates |
| 63 | Cut it down to a subset |
| 10 | Deleted it, with no other sequence covering the rack |
| 1 | Used different position names |

So T3 carries sequences through metadata unchanged, and T3b compares against generated ones only where the stored sequence wasn't edited. The real oracle for the default is still a fresh Venus layout (deferred).

Running the tests:

```
pytest                                   # 21 synthetic tests; corpus tests skip
VENUS_LAY_CORPUS=<corpus> pytest         # + 1042 corpus tests (~1 min)
VENUS_LAY_CORPUS=<corpus> python tools/known_exceptions.py   # regenerate the exception list
```

### PLR import details and limitations found (step 3)

- **Deck**: `HamiltonSTARDeck` sized as `STARDeck` (ML_STAR2, ML_FlexStar) or `STARLetDeck` (ML_Starlet), with PLR's built-in trash, waste block, teaching rack and grippers turned off. Venus's own waste and teaching labware come in as ordinary resources. Nimbus and diagnostic decks raise `UnsupportedLayout`.
- **Resources**:
  - `.tml` → `Carrier`, with one `ResourceHolder` per site.
  - `.rck` with a grid → `Plate` (wells sized from the `.ctr`), or `TipRack` when the rack has an `MlStar*TipRack` property. (`DataType = 2` is not a tip marker: most plates have it.)
  - Anything else, or a missing definition → a plain `Resource`.
- **Tip type** is guessed from the file name. The Venus file stays authoritative in metadata.
- **Metadata**: every resource carries `metadata["venus"]["fields"]`, the raw `Labware.N.*` strings. The deck carries the header, the labware order, sequences, layers and the other file sections. Export writes the fields back and recomputes `TForm.3`/`ZTrans` only when the PLR location moved by more than 2e-4 mm.

Things PLR (main) does that the importer works around:

| PLR behaviour | Effect on Venus layouts | Workaround |
|---|---|---|
| Rounds coordinates to 4 decimals | Venus stores float32 noise (`99.9999847412`) | Positions compared within 2e-4 |
| `Deck.deserialize` refuses overlapping resources | Venus allows alternatives at one spot (96/384 slide wastes, parked plates) | Nest the second under the first, recorded as `nested_under` |
| `Carrier` accepts only site holders | Some racks use a site the carrier definition lacks | Add an extra `ResourceHolder`, flagged `extra` |
| Plates and lids refuse a lid smaller than the plate | Some Venus lids are 1–2 mm narrower than their plate | Keep it on the plate as a plain `venus_lid` resource, linked by `lid_of` |
| `hamilton_tip_4000uL_filter` / `5000uL` raise "Tip diameter is not defined" | 4 ml and 5 ml tip racks | Use a 1000 µL tip as a stand-in; **a PLR bug worth reporting** |
| No rotation | 3 rotated racks in the corpus | Placed unrotated with a warning; the round trip is still exact |

### Labware definitions → PLR (`generate.py`, `name_match.py`, `xfile.py`, `tools/generate_labware.py`)

Every rule and convention is in [CONVENTIONS.md](CONVENTIONS.md). State on 2026-10-15, over the 249 definitions the corpus decks use:
- 53 aren't on hand.
- 17 become aliases to PLR factories: 13 tip racks matched on tip type, 4 carriers matched on name.
- 179 are generated as factories: 67 plates, 52 carriers, 23 lids, 15 tip racks, 8 troughs, 6 tube racks, 8 plain resources.
- Each generated factory gets a `.glb`: 20 authored Hamilton models, 159 generated.
- All 196 build in PLR, and every generated grid's positions equal Venus's.

```
.venv/Scripts/python tools/generate_labware.py OUT_DIR --corpus <corpus> --layouts
.venv/Scripts/python tools/generate_labware.py OUT_DIR "Corning-Costar\Cos_96_Fl.rck" ...
```

### PLR → Venus definitions (`to_venus.py`, `tools/roundtrip_definitions.py`)

`to_venus.venus_files(resource)` writes the `.rck`/`.ctr`/`.lid`/`.tml` for any PLR labware. Definitions now round-trip in meaning in both directions:
- Venus → PLR → Venus files → PLR: 197/197 corpus definitions equivalent.
- PLR → Venus files → PLR: every PLR labware resource, apart from trash and 2 mixed tube racks.

What "equivalent" covers is in CONVENTIONS.md §10. This is the piece step 4 needs: a deck built in PLR can now reference files under `<Labware>\PLR\`.

### Placement conventions (CONVENTIONS.md §3b, §10c, §10d)

- **Heights:** with `ZTransValue` 0 or 1 a rack's height follows its site, or the stack below it (18 exceptions in about 3,900). Only `ZTransValue 2` heights carry information.
- **Systematic offsets** each have a recorded cause: stacks as chains, the container base typed as the height (93 racks), SBS centring on 127 × 86 sites, and layout-level seats (magnet, reagent carriers, teaching records copied between decks).
- **Multiflex:** pylabrobot's multiflex factories agree with Venus's templates in height everywhere except the CPAC, and differ in plate centring on two carrier types. Both are listed as open points.
- **Capture log:** every converted deck records what its layout says beyond plain site assignments.
