# Venus ↔ PyLabRobot: conversion rules and conventions

Each rule here is either measured on the corpus (with counts) or read from Hamilton's or PLR's files; anything else is marked *unverified*. The corpus is 152 layouts (149 on STAR-family decks) and the 249 labware definitions they use, of which 196 are on hand. Code references are to `venus_interop/` (files/, rules/, plr/, multiflex/, methods/).

Contents: [1 Files](#1-the-hxcfgfile-container) · [2 Layouts](#2-layouts-lay) · [3 Coordinates](#3-coordinates-and-placement) · [4 Sequences](#4-sequences-and-position-names) · [5 Definitions](#5-labware-definitions) · [6 3D models](#6-3d-models) · [7 Venus → PLR](#7-venus--plr-mapping) · [8 PLR quirks](#8-pylabrobot-behaviour-the-converter-works-around) · [9 Venus quirks](#9-venus-data-quirks) · [10 Round trips](#10-round-trips-what-is-and-isnt-isomorphic) · [11 Open](#11-open-questions)

---

## 1. The HxCfgFile container

Used by `.lay .rck .tml .lid .ctr .dck .med`. Implemented in `files/hxcfg.py`, which rewrites every corpus file byte for byte.

**Binary** (little-endian):

```
u16 version (2|3)   u16 valid (1)   u32 dict_count
  dict_count × { str "TYPE,NAME"  u16 section_version  u32 n  n × (str key, str value) }
version 3 only:
  u32 list_count
  list_count × { str "TYPE,NAME"  u16 section_version  u32 n  n × str }
"\r\n" footer
str = u8 length | 0xFF u16 length, then latin-1 bytes
```

**Text**:
- The file starts `HxCfgFile,3;` then `ConfigIsValid,Y;`, followed by `DataDef,TYPE,VER,NAME,` blocks: `{ key, "value", … };` for dictionaries, `[ "item", … ];` for lists.
- Lines end in CRLF.
- Value escapes: `\\` `\"` `\n` `\r` `\t`, and `\0xhh` for any other byte outside printable ASCII.
- Our text writer's output equals `HxCfgFilConverter.exe`'s, up to the footer, on 150/150 layouts.

**Footer**: `* $$author=…$$valid=…$$time=…$$checksum=XXXXXXXX$$length=NNN$$`
- `checksum` is the CRC32 of everything from byte 0 up to and including `$$checksum=`.
- `length` is the footer line's length plus an offset: 0 in text form, 2 in binary. Keep whatever offset a file already has.

**Keys** within a dictionary section are in plain ASCII order in every corpus file. Writers sort.

**Don't use `HxCfgFilConverter.exe` in scripts.** It is a GUI program that sends `{ENTER}` with `SendKeys` to whatever window has focus each time it runs.

## 2. Layouts (`.lay`)

The main section is `DECKLAY,<instrument>` (usually `ML_STAR`), plus `DECKLAY,<instrument>_COVER` for lids. Other sections (DEVICE, RESOURCES, SYSTEM, HxPars lists) pass through unchanged.

| Keys | Meaning |
|---|---|
| `Labware.Cnt`, `Labware.N.*` | One placement per N, contiguous from 1 |
| `Labware.N.File` | Definition path, relative to the Venus `Labware` folder (sometimes absolute; normalise from `\Labware\`) |
| `Labware.N.Id` | Unique labware id |
| `Labware.N.Template` | Parent id, or `default` for the deck |
| `Labware.N.SiteId` | A site of the parent's `.tml`, or `<w>T-<rail>` on the deck (`M` = negative rail: `6T-M3` is rail −3) |
| `Labware.N.TForm.1/2` | Rotation matrix rows; `TForm.3` is the position (see §3) |
| `Labware.N.ZTrans` | Z of the labware's bottom |
| `Labware.N.ZTransValue` | 0 or 1: Z follows the site. 2: Z set by hand. |
| `Labware.N.Angle` | Rotation in degrees (three corpus racks) |
| `Labware.N.DefSeqValid` | 1: Venus keeps a default sequence for it (§4) |
| `_COVER: Labware.N.*` | The lid of main-section labware N. Same index: 436/436 lids. Lid id = `<plate id>_lid` (430/430). |
| `Seq.Cnt`, `Seq.N.{Name,Cnt,ReadOnly}`, `Seq.N.Item.M.{ObjId,PosId}` | Sequences. `ReadOnly` is absent in older layouts. |
| `Layer.Cnt`, `Layer.N.{Name,Viz,LabwareCnt,SeqCnt}`, `Layer.N.M.{LabwareName,SeqName}` | Layers. Absent in older layouts. |
| `Deck` | `ML_STAR2.dck` (STAR, 54 tracks), `ML_Starlet.dck` (30), `ML_FlexStar.dck`; Nimbus decks are out of scope |

**File paths.**
- **In layouts**, `Labware.N.File` is relative to the Venus `Labware` folder in 6588 of 6605 references. The other 17 are absolute:
  - 15 point into a kit's own `Labware` folder (e.g. `…\NGSStar\PacBio\Library Prep\Labware\SMP_CAR_LARGE\…`);
  - 2 point elsewhere (`…\HAMILTON\Library\STAR Tools\TipSupport.rck`).
- **In definitions**, every reference is written twice: once relative to the `Labware` folder (`Cntr.1.file`, `Site.N.LabwareFile`, `3DModel`, `Bitmap`, `Image3D`) and once relative to the definition file itself (`Cntr.1.fileRel = .\x.ctr`, `…Rel`). The `Labware`-relative copy is sometimes a stale absolute path from the author's machine (`C:\Users\Hutchens_W\…`, `F:\FVKII\…`); the `.\` twin still works.
- **Resolving a reference** (`definitions.normalize`):
  1. `Labware`-relative;
  2. absolute paths cut back to the part after `\Labware\`;
  3. for references inside a definition (`DefinitionStore.ref`), the `…Rel` twin relative to the referring file;
  4. then a search by file name.
- **Writing a reference:** always `Labware`-relative, never absolute, plus the `.\` twin in generated definitions, as Venus does. The target PC then only needs the files under its own `Labware` folder; its absolute location doesn't matter.

The layout model (`files/layout.py`) keeps every value as the string Venus wrote and regenerates indexes from list order; a lid moves with its plate. All 152 layouts rewrite byte for byte.

## 3. Coordinates and placement

Venus deck coordinates are PLR deck coordinates, with the same origin, axes and millimetres.

| Rule | Formula | Evidence |
|---|---|---|
| Carrier on a rail | corner = (100 + (rail − 1) × 22.5, 63, 100) | 1071/1071; equals PLR `track_to_location` |
| A carrier's `TForm.3` | its front-left-bottom corner | – |
| A rack's `TForm.3` | the **A1 position** (back-left centre) = corner + (BndryX, BndryY + (Rows − 1) × Dy), with Rows taken as 1 when missing | 3747/3830 on carrier sites (the rest are hand nudges); 61/62 on rails; PLR-computed A1 = Venus A1 on 3940/3940 imported racks |
| Rack on a site | corner = carrier corner + (Site.X, Site.Y) | as above |
| Rack Z | site Z (= carrier ZTrans + Site.Z) when ZTransValue is 0 or 1 | 3417 + 30 hand-set |
| Stacks | each rack sits at the lower rack's Z + the **lower** rack's `StackHt` | 111/112 steps. Racks at the *same* Z on one site are alternatives, not a stack. |
| Lid XY | lid corner = plate corner + ((plate.Dx − lid.Dx)/2, (plate.Dy − lid.Dy)/2): centred | 350/382 |
| Lid Z | **no rule in the data**: keep the stored value. For decks built in PLR, use lid base = plate base + `RackBaseToCoverBase` (*unverified*) | None of four candidate formulas fits any of the 383 lids with definitions. Identical plate-and-lid pairs on Z-from-site placements sit at different offsets (Agilent reservoir + the same lid: +43.05, +40.25, +39.95), so these values were set by hand. On rack-based nests (`ZTransValue = 1`) the plate sits 1.3 mm lower but its lid doesn't move. |
| Site order | Venus site 1 is at the back. PLR carriers count sites from the front (`PLT_CAR_L5AC_A00`: index 0 at y = 8.5). The converter orders PLR sites front to back; each holder is named `<carrier>_site_<Venus site id>`. | MULTIFLEX_ASSEMBLY.md, KAPA notes, PLR |
| Rotation | `Angle ≠ 0` is not analysed; such labware is imported unrotated, with a warning | 3 racks |
| Venus `.x` frames | Y up | `plr/xfile.py` swaps to Z up and reverses the winding |

The old rule `Dim.Dy − BndryY` for the A1 offset is wrong in general; it only holds for symmetric 96-well plates. `plr-viz3d-scratch/hamilton_library/mfx_reference.py` still uses it.

## 3b. Placement conventions: what the systematic offsets are

Measured on 4,467 racks on carrier sites in the corpus and the NGS layouts, with copies of a layout counted once (`tools/redundancy.py`, `rules/capture.py`). Each rule below explains a class of offsets that §3's site rule alone does not.

**Height, by `ZTransValue`:**

| Height explained by | Racks | `ZTransValue` | Rule |
|---|---|---|---|
| the site's Z | 3,840 | 0 or 1 (3,730); 2 (110) | **Z follows the site.** Within 0.3 mm in another 69, all hand nudges |
| the rack below + that rack's `StackHt` | 140, plus whole chains | 1 | **Stacks are chains:** each rack sits on the one below at that one's `StackHt`. Only the bottom of a chain can be offset from the site, e.g. MIDI plates on `PLT_CAR_L4ST` at +4, +32.85, +61.6 (steps of 28.75); ComfortLids at +2.0 … +22.1 (steps of 6.7); Hard-Shell plates at −31, −18.75, −6.5 (steps of 12.25). |
| site Z + the rack's container base (`Cntr.1.base`) | 93 | **always 2** | Tip racks, wastes and teaching blocks: −83.5 (`HTF_L`), −72.5, −39, −29.5 (CO-RE 96 tip supports), −52 (teaching needles), −22 (slide wastes), +23 (verification). As if the site height was typed into a field meaning the container base. Which height the robot uses is a Venus check. |
| anything else | 325 | 2 in 93% | Hand-set or taught heights |

So `ZTransValue` 0 or 1 is reliable: the rack is on its site or on a stack (18 exceptions in 3,900). Only `ZTransValue 2` carries a height that has to be kept.

**Several racks on one site:**
- **At the same height:** alternatives (one object or a choice), not two objects.
- **At different heights:** either a stack (the step equals `StackHt`) or alternatives each at the site's height (e.g. a 50 µL and a 1000 µL tip rack on one tip module). Each rack is measured against whichever explains it better.

**x / y:**
- **The site's corner:** 97.8% of racks.
- **Systematic offsets** (the same in several distinct layouts) are small: −0.05 / −0.05 for reagent containers on `RCT_CAR_3R60_2R20`; +0.2 for the Nalgene trough on a rack-based carrier.
- **Centring:** +0.38 / −0.26…−0.28 for 4titude plates on rack-based nests. That is an SBS plate (127.76 × 85.48) centred on Venus's 127 × 86 site, i.e. a physical plate centred where Venus's nominal one sits at the corner.

**Layout-level conventions** (same offset in several layouts, not in any definition):

| Where | Offset | What it is |
|---|---|---|
| MIDI on the magnet site (`5_MagPlate`) | +28.6 | the magnet plate's height (Hamilton's `Alpaqua_MagEx.tml`: 29.21) |
| HP Tabbed sites in KAPA, 10x, PacBio | +2.0, +3.2, +4.5, +6.6 | a teaching record copied between decks (KAPA notes); QIAseq and the ONT guide deck have 0 |
| 60 ml reagent containers on `RCT_CAR_3R60_2R20` | +2.3 (+3.3 at one site) | the container's seat in that carrier |
| Roche 20 ml reservoir on `RCT_CAR_3R60_2R20` | +12.6 | the reservoir's seat |
| Hard-Shell plates on a heater-shaker DWP nest | +30 … +31 | the plate on an adapter that is not in the layout |

**Multiflex** (`tools/mfx_reconcile.py`, `docs/notes/MULTIFLEX_ASSEMBLY.md`):
- **The catalogue rebuilds 22 of 26 sites** in Venus-built multiflex carriers exactly.
- **pylabrobot's factories** on `fork/viz3d-motion` reproduce Venus's site heights exactly for the HP Tabbed L5 carrier, the 7T heater-shaker carriers (flat MTP nests stand on the 29 mm riser) and the ODTC carriers v1 and v2.
- **ODTC V2 anchor:** V2 sits −201.8 / −12.5 from V1. That is where the kits mount it, so the factory doesn't model it.
- **Three open points:**

| Point | Detail |
|---|---|
| Plate x / y | The heater-shaker and HP Tabbed factories put an SBS plate's corner on the site corner (+0.38 / −0.26 from Venus). The ODTC and CPAC factories centre it, as Venus does. The non-centring factories should probably centre. |
| CPAC height | Hamilton's own templates disagree: 102.6 (Roche), 91.6 (PacBio), 90.5 (10x). pylabrobot's seat (77 + adapter) comes from layout placements, so it is −9.8 against the Roche template and +4.5 against the 10x one. Measure. |
| Template quirks | ODTC templates carry a lid site 12 mm above the plate site; pylabrobot puts the lid on the plate. The HP Tabbed template has 5 unused placeholder sites at (4.5, −61.5). |

## 4. Sequences and position names

- A rack with `DefSeqValid = 1` has a default sequence named after its id, listing every position column by column (back to front, then left to right).
- **Labels** come from the rack's `IX.*` settings:

| IX.Index | IX.Inc | Labels | Example | Evidence |
|---|---|---|---|---|
| 1 | 0 | A1, B1 … H1, A2 (letters on rows) | most plates | 585+ exact sequences |
| 0 | 1 | 1, 2 … numbered down the columns | tip racks, wastes | 1201+ |
| 0 | 0 | 1, 13, 25 … numbered across the rows (still listed column by column) | Nunc 1.3 ml plates | 2, plus single-column racks |
| 1 | 1 | letters on columns, numbers on rows, letters fastest | portrait plates | 1 |
| – | – | no Rows/Columns → `1 … HoleCnt` | troughs, tools | – |

- `IX.First` is 1 everywhere; any other value raises `UnsupportedNaming`.
- `IX.Start = 1` appears only on portrait racks. It probably selects the A1 corner; *unverified*.
- Every stored position name in the corpus is a valid generated name (2511/2511).
- Stored sequences that differ from the generated default (625) are user edits:
  - 291: the rack's own sequence was deleted and the rack is in a shared one (tips);
  - 260: reordered;
  - 63: cut to a subset;
  - 11: other.

## 5. Labware definitions

**Rack (`.rck`, section `RECTRACK`)**:
- **Grid:** `Rows`, `Columns`, `Dx`, `Dy`, `BndryX/Y` (centre of the front-left position, from the corner).
- **Body:** `Dim.Dx/Dy/Dz` and `StackHt`.
- **Container:** `Cntr.1.file` (the `.ctr`), and `Cntr.1.base`, the container floor above the rack bottom (negative for tips hanging below the rack).
- **Properties:** `Property.N` / `PropertyValue.N`.
- **Shared liquid:** `ConnectedCtr = 1` means all positions are one liquid (troughs).
- **Other:** `SingleCntr`; `Stagger` (ignored by the generator, noted).

**Tip racks** carry `MlStarTipRack` (or `MlStarXLTipRack`) = Hamilton tip type, plus `managedSequenceName`. `DataType = 2` is *not* a tip marker; most plates have it.

| Type | Tip | PLR creator |
|---|---|---|
| 0 / 1 | 300 µL / with filter | `hamilton_tip_300uL` / `_filter` |
| 2 / 3 | 10 µL / with filter | `hamilton_tip_10uL` / `_filter` |
| 4 / 5 | 1000 µL / with filter | `hamilton_tip_1000uL` / `_filter` |
| 22 / 23 | 50 µL / with filter | `hamilton_tip_50uL` / `_filter` |
| 25 / 29 | 5 mL / 4 mL with filter | PLR's creators raise (§8); the tip is built from the `.ctr` |
| 36 / 45 | slim 300 µL / with filter | `hamilton_tip_300uL_filter_slim` |
| 35 / 44 | 250 µL piercing / 150 µL piercing with filter | none |

**Container (`.ctr`, section `CONTAINER`)**:
- **Whole container:** `Depth`, `Dim.Dx/Dy` (top footprint), `BaseMM`, and the liquid-level and teaching fields (`LSHt`, `Clearance`, `Tch*`, `cLLD`), which aren't used yet.
- **Segments** `N.{Shape,DX,DY,DZ,Min,Max,EqnOfVol}`: segment 1 is the *top*, and `Min..Max` is its height range above the floor. `EqnOfVol` gives the volume in µL of a fill `h` mm deep *within that segment*.

| Shape | Solid | Size fields | Volume check |
|---|---|---|---|
| 0 | cylinder | diameter `DZ` | `ht.ctr`: π·3.4² = 36.32 = `h*36.3168` |
| 1 | box | `DX × DY` | `gre_384_sq`: 3.75² = `h*14.0625` |
| 3 | frustum | top diameter `DX`, bottom diameter `DY` | linear in `h` (area at mid-height) |
| 4 | round bottom (spherical cap) | diameter `DZ` | `h*h*(π·r − π/3·h)` with r = DZ/2 |
| 5 | V bottom (cone to a point) | diameter `DZ` at the top | `h*(π·r²/3)` |

Total volume at height h = Σ over segments of `EqnOfVol(clamp(h − Min, 0, Max − Min))` (`generate.Container.volume`).

**Carrier (`.tml`, section `TEMPLATE`)**:
- **Sites:** `Site.N.{Id,X,Y,Z,Dx,Dy}`, relative to the carrier corner. Also `Stack`, `StackSize` and `LabwareFile`.
- **3D model:** `3DModel` + `3DxOffset/3DyOffset/3DzOffset`.
- **Multiflex carriers:** each site is `<posn>_<module IdName>`, and the Multiflex Carrier Assistant catalogue gives its geometry (`docs/notes/MULTIFLEX_ASSEMBLY.md`).

**Rack body profile.** Many racks (85 of 117 in the corpus) also give the body's outer shape: `SegmentCount_x/y` and `Seg_x.N` / `Seg_y.N` `{LowerWidth, UpperWidth, SegmentHeight}`, from the bottom up. `Cos_96_Fl` is 124 × 82 for the bottom 8 mm and 127.5 × 85.3 for the next 6.2 mm, i.e. the skirt. The generated models don't use this yet. `Hole.{Shape,X,Y,Z}` describes the hole in the rack top.

**Lid (`.lid`, section `COVER`)**:
- **Fields:** `Dim.Dx/Dy/Dz`, `CoverThickness`, `RackBaseToCoverBase`, `StackHt`, `CoveredStackHt`, `XExtent/YExtent` (the plate footprint it fits).
- **Seating:** the lid base sits `RackBaseToCoverBase` above the plate base, so PLR's `nesting_z_height` = plate height − `RackBaseToCoverBase`. Consistent with `CoveredStackHt = RackBaseToCoverBase + Dim.Dz` on the Nunc lids, otherwise *unverified*.

## 6. 3D models

| Format | How to read it |
|---|---|
| `.x` text (`xof 0302txt`/`0303txt`) | `plr/xfile.py` (from `x_to_glb.py`): frames, materials, Y-up to Z-up |
| `.hxx` | the `Hamilton3dData` header, then gzip streams; the first holds a text `.x` (`xfile.x_text`) |
| `.x` binary or `tzip` | not read yet |

- **Who has models:** carriers and devices name theirs in `3DModel`. Racks usually reference only a PNG (`Image3D`), so plates and tip racks generally have no Venus mesh. Hamilton says its 3D data is cosmetic.
- **PLR's convention:** `resources/<vendor>/resource_model/<factory>.glb`, in metres, origin at the front-left-bottom corner.
- **Authored models** are aligned by bounding box: footprint centred on the definition's, bottom at z = 0. The model's size and Venus's `3D*Offset` are recorded in `<name>.geometry.json`. *Unverified* against Venus's own placement.
- **Generated models** (`generate.model_for`) are built in PLR's frame:

| Kind | Generated as |
|---|---|
| Rack | the definition's box, with each container's solid cut out at its position and floor |
| Carrier | a slab with a pocket at each site |
| Lid | a 1 mm shell |
| Trough | the box with one cavity |

  Generated models have no skirt, ribs or rims, so they're never smaller than the real labware, which keeps them safe for collision checks. A generated model comes from the same numbers as the resource, so it can't catch a wrong number.

## 7. Venus → PLR mapping

**Layouts** (`plr/plr_import.py`):

| Venus | PLR |
|---|---|
| Deck file | `HamiltonSTARDeck` sized as `STARDeck` / `STARLetDeck`, with PLR's built-ins (trash, waste block, teaching rack, grippers) off |
| `.tml` | `Carrier`, with a `ResourceHolder` per site (`metadata["venus"]["site_id"]`) |
| `.rck` with a grid | `Plate` (wells sized from the `.ctr`) or `TipRack` |
| anything else, or a missing definition | `Resource` at the stored position |
| lid | `Lid` on the plate (or a plain `venus_lid` resource, §8) |
| every resource | `metadata["venus"]["fields"]` = the raw `Labware.N.*` strings |
| the deck | `metadata["venus"]` = header, order, sequences, layers, other sections |

**Definitions** (`plr/generate.py`, `tools/generate_labware.py`):

| Venus | PLR |
|---|---|
| tip rack | `TipRack` with the creator for its tip type |
| plate | `Plate`, wells with bottom type and cross-section from the `.ctr`, and volume ↔ height from the segment equations |
| `ConnectedCtr = 1` | `Trough` |
| `SMP_CAR_*` or a cup/tube/vial container | `TubeRack` with a `Tube` in each holder |
| `.tml` | `Carrier` |
| `.lid` | `Lid` (nesting height from §5) |
| no grid | `Resource` |

- **Footprint:** within 1 mm of SBS, the footprint snaps to 127.76 × 85.48 and positions are re-centred, keeping each position's offset from the centre (76 definitions).
- **Names:** the factory name is the definition's file stem, sanitised; lids get `_lid`.
- **Alias, don't generate,** only when there's evidence it's the same product, not just the same geometry:
  - the same rack and tip type (tip racks);
  - the PLR function has the Venus file's name;
  - a PLR docstring names the Hamilton file.

  A unique geometric match alone isn't enough: the Nalgene 300 mL trough fits an Axygen trough plate. Current result on the corpus: 17 aliases (13 tip racks, 4 carriers) and 179 generated.
- **Matching** (`plr/name_match.py`) compares fingerprints:
  - the pipetting positions relative to the footprint *centre*, needed because Venus uses a nominal 127 × 86;
  - the footprint and height;
  - tip filter, length and volume (nominal ≤ PLR capacity ≤ 1.35 × nominal);
  - well size (±1 mm) and depth (±2 mm).
- **Composite labware**, one Venus file standing for two PLR objects:
  - an Alpaqua magnet `.rck` is the MIDI plate plus the magnet; in PLR it's a `PlateAdapter` with the plate on it (KAPA notes);
  - `SMP_CAR_*.rck` is the carrier plus its tubes.

## 8. PyLabRobot behaviour the converter works around

PLR main at 0f03af3 (`1.0.0b1`).

| PLR behaviour | Effect | Workaround |
|---|---|---|
| Coordinates rounded to 4 decimals | Venus stores float32 noise (`99.9999847412`) | Positions compared within 2e-4 mm |
| `Deck.deserialize` refuses overlapping resources | Venus allows alternatives at one spot | Nest under the overlapped resource (`nested_under`) |
| `Carrier` takes only site holders | Some racks use sites the definition lacks | Add a holder flagged `extra` |
| Lids may be at most 1.0 mm smaller than their plate | Venus's Greiner 384 lid is 1.3 mm short against Venus's own rounded plate | Plain `venus_lid` resource on import. In generated definitions the SBS snap fixes it. |
| `hamilton_tip_4000uL_filter`, `hamilton_tip_5000uL` raise "Tip diameter is not defined" | 4 and 5 mL tips | Tip built from the `.ctr` |
| No rotation on assignment | Rotated Venus labware | Placed unrotated, with a warning |
| Embedded tip racks sit `sinking_depth` (6 mm) below their site, centred over a smaller holder | Venus puts the rack's `ZTrans` on the site and its corner at the site's X/Y | Export: `ZTrans` = rack z + sinking depth, and the site is found from where the rack actually is |
| A tip spot is the tip's seat | Venus's `Cntr.1.base` is the tip's bottom | spot z = base + (tip length − fitting depth), and the inverse on export |
| Factories set `model` to their base factory (`hamilton_96_tiprack_standard` for every Hamilton tip rack, `hamilton_tip_carrier_L5` for every 5-position tip carrier) | The model doesn't identify the labware | Stock lookup compares a fresh instance of each candidate factory: positions, size and tip |
| `TIP_CAR_480BC_A00` and `TIP_CAR_480_A00` are identical in PLR (no barcode window) | Export can't tell which was meant | The first stock match is used (`TIP_CAR_480.tml`) |
| `create_ordered_items_2d` with a circular cross-section requires equal x/y | Some Venus wells are rectangular | Rectangle cross-section when x ≠ y |

## 9. Venus data quirks

- **Rounded footprints:** most SBS labware is drawn 127 × 86; the true size is 127.76 × 85.48.
- **Linear volumes:** many volume equations are linear (an area times h). Example: `Cos_96_Fl` gives 171 µL at 5 mm where PLR's measured model gives 160, and its floor is 3.57 vs PLR's 3.03.
- **Wells drawn square** for convenience (the 4titude growth plate's description says so).
- **Stand-ins:** a definition may stand in for something else on the deck (Nunc plates for printed wash stations, `Ham_DW_12_ml` as a trough). A file describes itself, not necessarily what's on the deck.
- **Taught coordinates:** layouts carry teaching corrections. Identical plates on identical nests can sit 1–4 mm apart in Z (KAPA notes). Keep these as calibration, not geometry.
- **Lid "parks":** some "lids" are parking spots on empty plates, not covers (tissue-culture notes).
- **Tip heights:** Venus and PLR disagree on where a 1000 µL tip ends. In the same rack, `HTF_L.rck` (`ht.ctr`: 95 mm, base −83.5) puts the tip bottom 2.1 mm above PLR's `hamilton_96_tiprack_1000uL_filter`. For 300 µL tips they agree within 0.1 mm (60 vs 59.9 mm long). Worth checking on the instrument.

## 10. Round trips: what is and isn't isomorphic

| Round trip | State | Notes |
|---|---|---|
| file → model → file (`hxcfg`, `layout`) | **Byte-identical** on all corpus files | |
| LAY → PLR → JSON → LAY | **Byte-identical** on 149/149 STAR layouts | Lossless because PLR resources carry the raw Venus fields as metadata. PLR edits rewrite only the moved positions. |
| PLR deck → LAY → PLR | **Equal positions** (A1 / corners within 0.001 mm; tip heights as in §9) on STAR and STARlet test decks; the second trip, PLR → LAY → PLR → LAY, is **byte-identical** | `plr/deck_export.py`, `tests/test_deck_export.py` |
| Venus definition → PLR → Venus files → PLR | **Equivalent** on 197/197 corpus definitions | `tools/roundtrip_definitions.py venus`, `tests/test_to_venus.py` |
| PLR resource → Venus files → PLR | **Equivalent** on every PLR labware resource, with three exceptions | `tools/roundtrip_definitions.py plr` |

*Equivalent* means equal in everything both sides model, within these tolerances:

| Quantity | Tolerance |
|---|---|
| Footprint | 1 mm (the SBS snap) |
| Positions, measured from the centre | 0.001 mm |
| Well size, depth, floor | 0.01 mm |
| Volume at ¼, ½, ¾ and full height | 1% |
| Tip filter and length | identical |

The PLR exceptions:
- **Not labware:** the 3 trash/wash-station resources.
- **Mixed tube sizes:** 2 Opentrons racks with 50 and 15 ml tubes, which would need Venus's multi-container racks.
- **Understood differences:** `Eppendorf_96_wellplate_250ul_Vb`, whose PLR volume is 0.89 µL at height 0 while Venus volumes start at 0; and racks of empty holders, whose Venus container is sized to the holder.

This is a round trip of meaning, not bytes. A Venus definition that goes through PLR comes back as a new file. Venus-only fields are dropped: liquid-level and teaching fields, barcodes, images, categories, and the original `IX.*` labelling (written back as A1-style). If byte-identical definitions are ever needed, carry the source fields in the PLR resource's metadata, as layouts do.

**PLR → Venus definitions** (`plr/to_venus.py`):

| PLR | Venus |
|---|---|
| `Plate`, `TipRack`, `TubeRack` | `.rck` + `.ctr` |
| `Trough` | `.rck` with positions on a 9 mm grid and `ConnectedCtr = 1` (*unverified in Venus*) |
| a lone tube or container | 1 × 1 `.rck` |
| plain `Resource` | `.rck` with no positions |
| `Lid` | `.lid` |
| `Carrier` | `.tml` |

- **Location:** files are written binary under `<Labware>\PLR\<model>.*`, with both path forms.
- **Grid:** recovered from item centres; non-rectangular grids are refused.
- **Labels:** `IX.Index = 1, IX.Inc = 0`, so Venus position names equal PLR identifiers.
- **Volume:** stacked segments, each with a cubic `EqnOfVol` fitted through the PLR volume at four heights. That's exact for frustums, cones and spherical caps. Segments start as a tenth of the depth and are halved wherever the cubic misses three check heights by more than 0.1%, which puts boundaries at steps in the well shape (at most 40 segments, at least 0.05 mm each).
  - Volume functions that stop short of the well's depth are extended at their top cross-section.
- **Tips:**
  - `MlStarTipRack` is set only when pylabrobot's creator for that Hamilton tip type makes a tip of the same length; wide and ultrawide variants get none.
  - `PlrTipFilter`, `PlrTipFittingDepth` and `PlrTipMaxVolume` properties carry what Venus's tip codes don't; the generator reads them back.
  - Tip container base = spot z − rack sinking depth − (tip length − fitting depth): *unverified* in Venus.
- **Lids:** `RackBaseToCoverBase` = plate height − `nesting_z_height`. `CoverThickness` is unknown in PLR and written as 1 mm.
- **Carriers:**
  - sites are numbered from the back;
  - `Site.N.X/Y/Z` is where a child lands (holder location + child offset);
  - `MlStarCarWidthAsT` = width / 22.5.

## 10b. Exporting decks built in PLR (`deck_export.export`)

**Starting layout.**
- A deck with Venus metadata starts from its own layout.
- Any other deck starts from a template: `plr/templates/ML_STAR2.lay`, a 4.5 STAR layout holding only Venus's six standard items (waste block, waste, teaching needles, verification blocks), its `base` layer and its waste sequences.
- STARlet: the same template with the waste-block group moved 540 mm (24 tracks) left and `Deck = ML_Starlet.dck`. Venus's own maintenance layouts show the same shift.
- PLR's built-in deck parts (trash, waste block, teaching rack, grippers) are left out; the template's Venus equivalents stand in for them.

**Definition file.**
- A stock Hamilton file when one is provably the same labware: `plr/data/stock_map.json`, built by `tools/build_stock_map.py` with the alias rule. At export, a fresh instance of the mapped factory must match the resource's positions, size and tip.
- Otherwise, files written by `to_venus` under `<Labware>\PLR\<model>.*`, returned in `Export.files` for installing.

**Placement fields:**

| Kind | Fields |
|---|---|
| All | `Angle 0`, `BarcodeCnt 0`, `Inst ""`, identity rotation, `TForm.3.Z 1` |
| Carrier on a rail | `SiteId <w>T-<rail>` (`w` from `MlStarCarWidthAsT` or width / 22.5), `ZTransValue 2`, `DefSeqValid 0`, the carrier `Clsid` |
| Rack on a carrier | `Template` = carrier, `SiteId` = the Venus site at the rack's corner; `ZTransValue 1` when its Z is the site's, else 2; `TForm.3` = PLR's A1 centre; `DefSeqValid 1` with a default sequence named by the definition's `IX.*`; `IsCovered 1` with a lid |
| Lid | in the `_COVER` section at its plate's index; `TForm.3` = its corner, `ZTransValue 0` |

These are the most common values in the corpus for each kind of placement (§2).

New labware joins the active layer.

## 10c. The delta ledger (`rules/deltas.py`)

Every number a conversion changes, and every interpretation it makes, is recorded as a `Delta`: resource, kind, quantity, PLR value, Venus value, size in mm, the decision taken, and why. Export: `Export.deltas`. Import: `deck.metadata["venus"]["deltas"]`.

| Kind | Meaning | Example |
|---|---|---|
| `convention` | The same thing measured from different reference points. Exact; reversed on the way back. | Tip racks: `ZTrans` = PLR z + 6 mm sinking depth; tip spot = Venus base + (tip length − fitting depth) |
| `stock_disagrees` | A stock Hamilton file describes the same labware with different numbers | `HTF_L.rck`: tip bottom 2.1 mm above PLR's |
| `approximation` | A number Venus can't hold exactly, with its bound | Lid `CoverThickness` unknown in PLR |
| `interpretation` | A choice where the source is ambiguous | Rotated labware placed unrotated; a tip type guessed from a file name |
| `missing` | Information not available | A definition file not found: a plain box at the stored position |

**Rule:** a round trip is accounted for only if each difference it produces matches a ledger entry of the same quantity and size. `tests/test_deck_export.py::test_every_round_trip_difference_is_in_the_ledger` enforces it, in absolute positions too: where the robot goes, not just shapes.

**Stock files, `prefer`.**
- **`exact` (default):** use a stock Hamilton file only if the importer, reading it back, reproduces the PLR resource to 0.001 mm (positions, item sizes, depths, tip bottoms, carrier sites). Otherwise write our own file. Round trips are exact.
- **`stock`:** use stock files wherever they are the same labware. A round trip then returns Venus's numbers, and each difference is in the ledger.

**A carrier site** (`to_venus.site_corner`) is where a rack's corner and bottom would be, independent of what stands on it:
- **Plate holders:** the holder itself. PLR then lowers each plate onto the site's pedestal by an amount that depends on the plate (3.03 mm for `cor_96_wellplate_360uL_Fb` on `PLT_CAR_L5AC_A00`). Venus puts plates at the site height. The export keeps PLR's height (`ZTransValue 2`) and records it.
- **Tip-rack holders:** a Hamilton tip rack (122.4 × 82.6) centred on the holder, oriented like the holder (`TIP_CAR_288` holds portrait racks), at the holder's height.

**Tip type on import** (`plr_import._tip_creator`), in this order:
1. the rack's Hamilton tip type (`MlStarTipRack`);
2. our `PlrTip*` properties;
3. a guess from the file name, recorded as an interpretation.

**Our own files:**
- Named after the PLR model, unless different content already has that name; then a content hash is appended. pylabrobot gives every Hamilton tip rack the model `hamilton_96_tiprack_standard`, whatever its tips.
- Tip racks carry the same properties as Venus's own: `MlStarTipRack`, `MlStarCore96TipRack`, `MlStarIsWasteRack`, `MlStarIsCore96WasteRack`.

**Stock audit** (`tools/audit_stock.py`), pylabrobot vs Hamilton's files for the same labware:
- **All 22 carriers agree exactly**, including the portrait `TIP_CAR_288` once its sites are measured correctly.
- **Every tip rack differs** in hole size: PLR's spot is 7.2 mm, Venus's container 6.8 mm. These are different quantities (the hole vs the tip); no effect on pipetting.
- **Tip bottoms:**

| Tips | pylabrobot collar height | Venus tip bottom vs PLR |
|---|---|---|
| 10 µL (`LTF_L`) | 6 mm | −2.1 mm (lower) |
| 50 µL, 300 µL (`TIP_50ul*`, `ST*`) | 8 mm | 0 / −0.1 mm |
| 1000 µL (`HT*`) | 10 mm | +2.1 mm (higher) |
| slim 300 µL | – | +2.0 mm |

The difference is pylabrobot's own `collar_height` minus the flat `fitting_depth = 8` it uses for every Hamilton tip (plus 0.1 mm of tip length). Venus's tip containers sit each tip in its rack by its collar. pylabrobot uses the collar only to set where a pickup *starts* (`STAR pick_up_tips`: begin = spot + collar height), while its tip spot and tip-bottom arithmetic assume 8 mm for all. So for 10 and 1000 µL tips the two systems likely agree on how to *pick up* a tip, but disagree by about 2 mm on where the tip's end is afterwards, which matters for liquid heights. Settle this on the instrument, then fix it in pylabrobot or here.

## 10d. The capture log (`rules/capture.py`, `tools/capture_log.py`)

**Pure assignment.** A placement whose fields all follow from the rules (§3–4) says only "this labware on this carrier site", the same information as pylabrobot's `carrier[i] = plate`. Everything else is information the layout carries, and the importer records it in `deck.metadata["venus"]["capture"]`:

| Field | Meaning |
|---|---|
| `x/y` | off the site's position (or the rail position), with (dx, dy) |
| `z` | off the site height, or the stack height when on another rack, with dz and the layout's `ZTransValue` |
| `alternative` | at the same place and height as another rack: one object, or a choice, not two objects |
| `position` | off any carrier: free on the deck, or on a site its carrier doesn't define |
| `rotation` | rotated |
| `lid z` | hand-set lid heights (§3) |
| `sequence` | an edited or deleted default sequence |
| `definition` | missing: the placement can't be checked |

**Reading it.**
- A rack higher on a site than another is measured against the stack height or the site's own height, whichever is closer. Two tip racks on one site at different heights are alternatives, not a stack.
- Offsets are grouped by (labware file name, carrier file name and site), counting distinct layouts; copies count once.
- **Systematic:** the same offset, within 0.05 mm, in at least 2 distinct layouts. That points to a missing rule (a nest, a pedestal, a module height), or to a teaching record copied between decks. The KAPA, 10x and PacBio HPTab offsets are the latter. Everything else is a one-off nudge or a taught position.

**Substituted definitions.** When a definition was found only by file name and the layout puts its labware more than 1 mm off the substitute's site, the import ledger flags it, unless the offset is one §3b explains:
- **Over 10 mm:** likely a different file with the same name.
- **1–10 mm:** can't be told apart from teaching.

(KAPA's `3D Models\Tips@0 uL\HTF_L.rck` at −83.45 mm was first flagged as a different file. It is the container-base pattern instead: the stock `HTF_L.rck`'s own base is −83.5, and 93 other racks show the same pattern with their right files.)

**Reports:** `reports/capture_corpus/README.md (regenerate with tools/capture_log.py)` (149 layouts) and `reports/capture_ngs/README.md` (10). Each has one log per layout, labware sorted by how often it sits off its site, and the systematic offsets.

**Results:**
- **Racks on carrier sites, position only:** 81% of corpus racks sit exactly on their site (x, y and z); 53% on the NGS decks.
- **Labware types most often off:** reagent containers (`rgt_cont_60ml` off in height 100% of the time on the NGS decks), ODTC ComfortLids, HSP and MIDI plates on multiflex, heater-shaker and CPAC sites (about 50%), 384-well and filter plates in the corpus.
- **Systematic offsets:**
  - tip racks on multiflex tip modules (`TipBC` sites) sit 29–84 mm below the site in up to 25 layouts: the racks sit in the module, which the multiflex catalogue should explain;
  - MIDI on the magnet +28.6 mm (the magnet's height);
  - 60 ml reagent containers +2.3/+3.3 mm on `RCT_CAR_3R60_2R20`;
  - the Roche 20 ml reservoir +12.6 mm;
  - ODTC lid sites.

## 11. Open questions

| Question | How to settle it |
|---|---|
| Lid Z rule | Test `RackBaseToCoverBase` and the 4 mm offset on the 436 corpus lids |
| `IX.Start = 1` (A1 corner on portrait racks) | Venus, or a portrait layout with a known plate |
| 384-tip racks, piercing and slim tips | PLR has no equivalent; generated |
| Column reservoirs (Agilent 12/6/4/2) | Venus doesn't mark shared liquid; group positions by container width |
| Authored model registration | Compare with Venus's 3D view, or with `3D*Offset` |
| Tip-end height for 10 and 1000 µL tips: Venus and pylabrobot differ by ±2.1 mm, the collar difference (§10c) | Measure a mounted tip's end on the instrument (e.g. a cLLD or capacitive touch-off on a known surface) |
| Whether Venus accepts the files written under `Labware\PLR` (troughs especially) | Open an exported layout in the Deck Editor |
| Multiflex carriers | Route through the catalogue instead of matching |
| Whether the Method Editor accepts a scripted `.med`/`.hsl` step insertion (§12): row numbering, library registration, outlining and flowchart data | Open the edited copy in the Method Editor and check the new steps and their parameters |
| The per-channel key `-534183622` in pipetting and gripper blocks (values 0/5/7/10/18 in the corpus; the rest of the block reads as LLD and touch-off settings) | Compare records against Venus's Aspirate/Dispense step dialogs |
| The `TipType`, `DispenseMode`, `SequenceCounting`, `TouchOffMode` enum values in HxPars records (e.g. `TipType = 5`) | Enumerate one step of each type in the Method Editor and read the saved `.stp` |
| The mapping from the `-534118376` command id in HxPars records to command names | Compare records of known commands across corpus `.stp` files |
| What an error entry's `UseDefault`, `Timeout`/`Infinite` and `AddRecovery` do at run time (§12): whether `UseDefault = 1` applies the default recovery without a dialog, whether `Timeout` is the operator's response time, what `AddRecovery = -1` or a recovery id means | Set each in a step's Error Settings dialog and read the saved `.stp`; then provoke the error in the simulator |
| `.pkg` (§12): the header words (0, 2, 1, 0), the two per-entry FILETIMEs, and the manifest item keys `-347734004/05/06/07/10/11/12` and `-347734008` (a layout's device binding) | More packages, preferably one exported here from a known method with the Package Wizard |
| What HSL does when a function is passed a variable that was never assigned: Colony Picking passes `_strLightSourceTop`, whose assignment is a disabled step, to `EASYPICKII::MLSTAR::Light_On` | Run the method in the simulator, or a two-line test method, and read the trace |
| Step-return recovery codes: `StepReturn::GetRecoveryButton` values 4 and 9, which easyPick II's `UpdatePickingState` counts as picked | Trigger errors with known recoveries in the simulator and read the step return |
| PTL enum values: `ErrorHandling` (5 in the corpus), `drivingMode` (1 = aspirate driven, 2 = dispense driven per `HSLPTLLib.hsl`), `DispenseMode`, `AspirateMode` | The smart step dialog against the generated `SetPipettingState` lines |
| What Venus's element counter (tip counter) stores and how `ReadElementCounterIntoSequence` applies it: a status per position, here read as "tips before the current position used", the same while tips are taken in order | Read a tip counter file after a partial run, and read it into a sequence in the simulator |
| How Venus's CO-RE grip force (0-9 in step records) and grip speed (e.g. 277.8, no unit stated) relate to PLR's `grip_strength` (0-99) and `grip_speed_y` (mm/s); ports pass the force through unchanged and leave the speed at PLR's default | Read the firmware command a ZSwapGetPlate step sends in Venus's trace (C0ZP grip strength and speed fields) for known settings |
| Whether a sequence copy (`a = b`, `CopySequence`) carries its position properties (`methods.sequences` copies them; the HSL reference doesn't say) | A two-line test method in the simulator: set a property, copy, read it on the copy |
| The CO-RE 96 Head Tip Eject step's `UsePickUpPosition` values: 2 is read as "default waste" from the order the dialog help lists Off / pick-up position / default waste | Set each option in the step dialog and read the saved `.stp` |
| The Venus Y and Z of the culture-processing `Move96HeadAndArm` firmware moves (`H0YA ya07500`, `H0ZA za68500`): 117.19 mm and 342.5 mm with PLR's head drive resolutions; 68500 is the top of the head's Z window either way | Run the move and read the head's position back |

## 12. Method files (`.med`, `.hsl`, `.sub`)

This section records how Venus stores a method, which is enough to script an edit later. Nothing here writes method files yet: `methods.hsl` only reads, and the Method Editor stays authoritative. The worked example is the pLLD change in [plld-search-speed.html](plld-search-speed.html) (route 3B). Figures are measured on PyHamilton's `star-oem/VENUS_Method/STAR_OEM_noFan.*`.

**A step lives in two files.**
- Its position and nesting are in the `.hsl` (or the `.sub`, for the method's own sub-methods), as marker comments around its generated code.
- Its settings are a record in the `.med`, keyed by the same GUID. The `.med` holds no step order.
- Change one file without the other and the editor no longer sees a valid step.
- `.stp` (device-step instances such as Aspirate and Firmware Command) and `.res` (resources) are also written on save. Library and sub-method calls don't need them.

| File | Holds | Form |
|---|---|---|
| `.med` | One `HxPars` list section per step, named by its GUID, plus editor bookkeeping (below) | HxCfgFile (§1), binary by default. `files.hxcfg` reads and rewrites it byte for byte (1,906 sections, 1.6 MB) |
| `.hsl` | Step order, as markers; variable declarations; `#include` lines | Text with a footer (`files.footer`) |
| `.sub` | The method's sub-methods, with the same markers | Text with a footer (length offset 2) |

### The `.med`

- **Step records:**
  - Each is `DataDef,HxPars,3,<guid>,` followed by a list of key/value items.
  - GUIDs are lowercase hex written `8_4_4_16`, e.g. `5f5e5c89_0c1a_497b_80c550dbc4676208`.
- **Key prefixes:**
  - `1` a string, `3` a number, `(` opens a nested block, `)` closes it.
  - Many keys are negative integers (`1-534642685`). Their meaning is known only from context.
- **A library-call record**, from `HSLJsonLib::GetArrayLength`:

  | Item | Meaning |
  |---|---|
  | `1ReturnValue` | Variable the result goes into |
  | `1FunctionName` | e.g. `HSLJsonLib::GetArrayLength` |
  | `3FieldCount` | Number of parameters |
  | `(FunctionPars … )` | Parameter names |
  | `1-534642685` | Library path, e.g. `HSLJson\HSLJson.hsl` |
  | `(BlockData … )` | `1-533921782`: the step icon (`SingleLibFunction.bmp`). `1-533921779`: the generated code line, which is stored here as well as in the `.hsl` |
  | `1Timestamp` | When the step was last edited |
  | `(ParamValue 1Value.0 … )` | Bound values, in parameter order |
  | `(Variables … )` | Variables the step uses |

- **Editor bookkeeping** (observed; meanings inferred):

  | Section | Contents |
  |---|---|
  | `HxPars HxMetEdData` | Editor version (`6.3.1.1147`) and method options (`SchedCompCmd`, `SampleTracker`, `CustomDialogCompCmd`, …) |
  | `HxPars HxMetEd_MainDefinition` | The `main` sub-method's definition |
  | `HxPars HxMetEd_Submethods` | Each sub-method's parameters: name, description, direction and type flags |
  | `HxPars HxMetEd_Outlining` | `3<guid><n>` → a state, for 157 parts of compound steps. This is the editor's folded or unfolded view |
  | `ActivityData ActivityData` | `ActivityDocument`: one base64 blob (10 kB) holding the flowchart view |
  | 8 GUID records of 3 items (`3`, `0`, `)`) | No `.hsl` or `.sub` marker refers to them. Perhaps leftovers of deleted steps |

- **Join check:** all 1,753 step GUIDs in the `.hsl` and all 139 in the `.sub` have a `.med` record.

### Markers in the `.hsl` and `.sub`

```
// {{{ 5 "main" "Begin"                         a section begins (a sub-method, the include block)
// {{{ 90 1 0 "<guid>" "{<step type CLSID>}"    a step: editor row, two fixed fields (copy them as-is), GUID, type
<the step's generated code>
// }} ""                                        end of the step's code
// {{ 94 1 0 "<guid>" "{...}"                   one part of a compound step (If / Else / End,
                                                 loop begin / end); the parts share one GUID
// {{{ 5 "main" "End"                           the section ends
```

The `.hsl` also has `LibraryInsertLine` and `VariableInsertLine` markers:
- New `#include`s go above `LibraryInsertLine`, inside `namespace _Method { … }`.
- New variables go above `VariableInsertLine`.

| Step type CLSID | Step |
|---|---|
| `{C1F3C015-47B3-4514-9407-AC2E65043419}` | Library function call |
| `{7C4EF7A7-39BE-406A-897F-71F3A35B4093}` | Sub-method call, including toolkit calls such as `STAR_OEM_TOOLKIT::Channels_1ml_Aspirate` |
| `{B31F3531-5D80-11D4-A5EB-0050DA737D89}` | If / Else |
| `{B31F3532-5D80-11D4-A5EB-0050DA737D89}` | Loop |
| `{B31F3533-5D80-11D4-A5EB-0050DA737D89}` | Break (inferred) |
| `{B31F3543-5D80-11D4-A5EB-0050DA737D89}` | Assignment (inferred) |
| `{B31F3544-5D80-11D4-A5EB-0050DA737D89}` | Assignment with calculation |
| `{586C3429-F931-405F-9938-928E22C90BFA}` | Comment or blank line |
| `{3293659E-F71E-472F-AFB4-6A674E32B114}` | Error handling (inferred: `onerror goto`) |
| `{9EC997CD-FD3B-4280-811B-49E99DCF062C}` | Return (inferred) |

Venus writes the CLSIDs in mixed case (`{7C4EF7A7-39BE-406a-…}`). Keep the case the file has, and compare case-insensitively. `tools/hsl_steps.py` lists a method's steps.

More step types, classified from the code Venus generates for them (inferred from the 10 NIST methods and their 5 libraries, 2026-10-15):

| Step type CLSID | Step |
|---|---|
| `{B31F3534…3F-5D80-11D4-A5EB-0050DA737D89}` | File open / read record / write record / close; input dialog; set / get sequence position; timer start / wait (inferred per suffix: 34 open, 36 read, 37 write, 38 close, 39 input dialog, 3A set position, 3B get position, 3E timer start, 3F timer wait) |
| `{B31F3540-…}` | Get elapsed time (inferred) |
| `{21E07B31-8D2E-11d4-A3B8-002035848439}` | User dialog (message) |
| `{998A7CCC-…}`, `{E09A7A75-…}`, `{2C884145-…}` | Custom dialog, tip-handling-state config, pipetting-state config (inferred) |
| `{4900C1F7-…}`, `{67A8F1C9-…}`, `{72EACF88-…}`, `{F17B7626-…}` | Array: set size / get element / get size / add last (inferred) |
| `{930D6C31-8EFB-11d4-A3BA-002035848439}` | Abort (inferred) |
| `{F07B0071-8EFC-11d4-A3BA-002035848439}` | Trace comments and blank compound parts, not a device step |
| `{DB5A2B39-…}`, `{B558D25C-…}` | Copy list; inline sequence-array pipetting block (inferred) |

### Device steps and the `.stp`

A device step (Aspirate, Dispense, TipPickUp, iSWAP moves, …) is written in three places that join on the step GUID:

1. **Marker**, with the type carrying the device variable: `"STAR:{541143FA-7FA2-11D3-AD85-0004ACB1DCB2}"`. `STAR` / `ML_STAR` is the device object the call goes through; the CLSID names the command (named from `Config\ML_STAR.cfg`, regex `1-534118383 <Name> … 1-534118394 &{CLSID}`).
2. **Generated code**, naming the command twice: `arrRetValues = STAR._541143FA_7FA2_11D3_AD85_0004ACB1DCB2("<guid>"); // TipPickUp` — CLSID with dashes as underscores, and the call's argument is the step's own GUID, not a sequence.
3. **`HxPars` record** in the `.stp` beside the file that holds the step (method or library), section name = the GUID.

The `.stp` record is an HxCfg item list like the `.med`'s, with two more facts (measured over all 407 HxPars records of the session corpus):

- **Key prefixes:** `1` string, `3` int, `5` double, `10` object reference; block names (`(Errors`, `(-534183936`) carry no prefix.
- **The `(Variables …)` block names the numeric keys.** It maps each method variable to where it is stored: opcode `10` → a top-level key, `30` → a block key, `31` → the sub-index inside it, `32` → the key inside that block. So `-534183924` is the aspirate volume because `p_vol` is bound there. Every key any record binds to a variable is named this way; keys no record binds are constants (same value corpus-wide) or gripper settings named by their neighbours.

`methods.stp_pars.KEY_NAMES` is the resulting table with the per-channel pipetting block (`-534183936`) and the gripper/wash block (`-534183935`) resolved. Open remain (§11): the varying `-534183622`, the `TipType`/`DispenseMode` enums, the `-534118376` command id.

### Error policies in the `.stp`

Each device step's record carries an `(Errors` block: one entry per error the step can raise, holding what Venus does when it occurs (`stp_pars.Record.errors()`, rendered by `protocol.render_error`). Measured over the 407 records of the NIST corpus (2,262 entries, 2026-10-16):

- **Shape:** `(Errors (<n> RepeatCount UseDefault Timeout ErrorSound AddRecovery Infinite ErrorDescription ErrorNumber (Recoveries (<code> RecoveryVisible RecoveryDescription RecoveryFlag RecoveryTitle RecoveryDefault) …) NbrOfRecovery ErrorTitle) …)`.
- **Titles are string-table ids**, resolved from the `RT_STRING` resources of `Bin\HxGruCommandEnu.dll` (all 80 ids in the corpus resolve; `tools/gru_strings.py` regenerates `stp_pars.ERROR_TITLES`/`RECOVERY_TITLES`). Errors: 372 Hardware, 374 Not Executed, 382 Insufficient Liquid, 386 No Tip, 816 Liquid Level, 1854 Unexpected cLLD found, 2059/2061 TADM upper/lower limit, … Recoveries: 370 Cancel, 436 Abort, 420 Repeat, 416 Exclude, 432 Bottom, 434 Air, 426 Waste, 428 Continue, 424 Next, 418 Initialize, 430 Barcode, 818 Available. `HxStandardLanguageEnu.dll` reuses the same ids for unrelated strings; the GRU table is the one whose titles fit.
- **Recovery slot codes:** 1 is always Cancel and 2 always Abort; 3–7 hold different recoveries per error.
- **Values:** `UseDefault` 1 in 1,130 of 2,262 entries; `RepeatCount` 1–3 in 89; `Timeout` `0` (1,684), the variable `userResponseTime` (577) or `600` (1); `Infinite` 1 in 1,345; `AddRecovery` `0`, `-1` or a recovery title id (424, 428, 432). `RecoveryFlag` is always 1. What `UseDefault`, `Timeout`/`Infinite` and `AddRecovery` do at run time is open (§11); the traces print them raw.

### PTL smart steps

Pipette, TipPickup and TipEject *smart steps* (marker `{B558D25C-EB8A-4a43-8878-125E1847965C}` for Pipette) have no `.stp` record: the Method Editor writes their whole dialog into the generated code, so all settings are in the `.hsl`. One step is a block of `sequence arrseqAspirate_<id>[]` / `arrseqDispense_<id>[]` arrays filled by `SetAt`, `PTL::ResetPipettingStateAndSequences("")`, about 60 `PTL::SetPipettingState("<Key>", <value>)` lines (every dialog field, defaults included; `SetTipHandlingState` for tip steps), and one guarded call, e.g. `PTL::Pipette3(ML_STAR, <tips>, <asp arrays>, <disp arrays>, aspirateMultiplicity, dispenseMultiplicity, pipettingVolume, restVolume, drivingMode, tipRenewalCycleSeq, tipRenewalCycleMul, tipRenewalCycleVol, tipType, seqMergedAspirate, seqMergedDispense)`; argument names from `Library\HSLPTLLib.hsl`. `protocol` folds each block into one step with named settings (`protocol.PTL_ARGS`); this is the "config-heavy" style (Triplicate, Simple media, Three inducer, Zyppy, part of DNA Extraction). The library also sets washing and loading defaults (`SetWashingStateDefault`, `SetLoadingStateDefault`) in the method's `AutoInitBlock`, outside `main`.

### Sections, functions and includes

Measured on the 10 NIST LMSF methods and their 5 libraries (`methods.hsl_code`, 2026-10-15):

- **Methods and libraries declare code differently.** A method's sub-methods are *sections* (`main`, `GetParams`, `StartUp`, `CleanUp`, `OnAbort`, …) marked with `// {{{ 5 "<name>" "Begin"`; only the method's `OnAbort` (in the `.sub`) is also a `function`. Libraries define everything as HSL `function`s.
- **A library file lists every function twice**: a prototype block up top (lines ending `;`, sometimes with `= default` arguments), then each definition later, again opening its own `// {{{` section, with the step markers as comments inside the braces. Match definitions and replace prototypes; don't count both.
- **`private function` and `static function` are definitions too.** The lab's own libraries use them: `GSF-IMS.shared_submethods` 5, `PlateAndLidMovement` 5, `LMSF_Utilities` 6. So do `Culture processing`, `easyPickII_*`, `STAR Tools`, `HSLLabwrAccess` and Hamilton's Deck Animation library. Before `hsl_code` read the modifier (2026-10-16), these bodies were missing from the traces. Six of the ten methods' traces grew by 16–29% once it did, e.g. `PlateAndLidMovement`'s `GetNewFrontChannel`, which picks the CO-RE gripper's front channel from the clock's seconds. The function inventory in `notes/PROTOCOL_EXTRACTOR_SCOPE.md` predates this and undercounts.
- **A step switched off in the Method Editor stays in the code**, wrapped as `/* {{ 1 "" "0" */ if(0){  /* }} "" */` … `/* {{ 1 "" "1" */ } /* }} "" */`. These wrappers sit between the `// {{` step markers, so a reader that walks only the markers sees the disabled steps as live. `hsl.steps()` marks them `Step.disabled` (2026-10-16), and the traces render them as `# [disabled step, never runs] …`, with device steps keeping their settings. 17 of the NIST files have them. Some change what the method does: DNA Extraction's `is_debugging = "false"`, the DPX cut-tip check, and the 96-head park's `H0YA` firmware command are all disabled.
- **`if( 0 == f.Open(…) ) { MECC::RaiseRuntimeErrorEx(…) }` is a checked call, not a condition.** Venus writes file and timer steps this way. A condensed view that drops the guard must keep the call (`f.Open(…);`). Until 2026-10-16 the condensed traces lost every file open/write/close and every `SetTimer`/`WaitTimer` this way; the full traces were always complete.
- **Function bodies are brace-matched, not marker-bounded**: the body runs from `function name(…) [ret] {` to the matching `}`, skipping strings and `//` comments. The step markers survive inside the body text, so `hsl.steps()` works on a body unchanged.
- **Includes resolve under the Library and Methods folders.** A method includes `"GSF-IMS Project\\GSF-IMS.shared_submethods.hs_"` (under `Methods\`), `"Common\\Common96HeadSubMethods.hs_"`, `"HSLTipCountingLib.hsl"` (under `Library\`); extensions `.hs_`/`.hsl`/`.hsi` mix in one include list. `protocol.include_closure` tries the including file's folder, then each root, and follows includes transitively (the 10 NIST methods pull in 44–85 files each, all resolved).
- **A `.hs_` is a generated header, the `.hsi` its body.** A sub-method library's `.hs_` (`// this ALWAYS GENERATED file contains the sub-method library header`) holds every function as an empty stub under `#ifndef HSL_RUNTIME` and `#include __filename__ ".hsi"` under `#ifdef HSL_RUNTIME`: the editor sees the stubs, the runtime the `.hsi` with the step-marked bodies. A method pulls in its `.sub` the same way (`#include __filename__ ".sub"`). Hamilton's own libraries are plain `.hsl`, with include guards (`#ifndef __HSLUtilLib2_hsl__`).
- **Comments hold stale includes.** Hamilton changelog comments quote old include lines (`HSLML_STARLib.hs_`: `// Renamed include file: #include "HSLUtilLib2.hs_" --> #include "HSLUtilLib2.hsl"`); strip comments before scanning.
- **Namespace rule:** a library is called through `NS::function(...)`, where `NS` is the namespace the file declares (`namespace LABWAREHANDLING {`). For the lab's libraries it equals the file stem with every non-alphanumeric character replaced by `_`, uppercased: `GSF-IMS.shared_submethods` → `GSF_IMS_SHARED_SUBMETHODS`, `Tip Handling with 96-Head` → `TIP_HANDLING_WITH_96_HEAD`; `protocol.load_library` reads the declaration and falls back to the stem rule.
- **The NIST repo's methods and libraries are not all from the same version.** Against the libraries as committed, `Three inducer gradient plate prep_v2` calls `pipette_media` with 8 arguments (the library takes 7), `pipette_dil_series` with 7 (takes 8), and `pipette_selector` / `pipette_inducer`, which the committed `GSF-IMS.shared_submethods.hsi` doesn't define; `Simple media…` and `Triplicate…` call `Clear96HeadAndArm` with 1 argument (takes 2). These methods wouldn't compile against the committed libraries; the traces mark each such call with a `# note:`.
- **The methods are thin; the libraries hold the device steps.** A method's `main` reads `parameters.csv`, calls the lab's libraries, and writes status files; the pipetting calls (`STAR._…`) are in `GSF-IMS.shared_submethods`, `PlateAndLidMovement` (~26 move/lid functions via the CO-RE gripper), `Common96HeadSubMethods`, `Tip Handling with 96-Head` and `LMSF_Utilities`. Counting device steps on the `.hsl`/`.sub` alone reports none.

The decompiler/pretty-printer built on these facts is scoped in [notes/PROTOCOL_EXTRACTOR_SCOPE.md](notes/PROTOCOL_EXTRACTOR_SCOPE.md): `methods.hsl_code` (function bodies), `methods.stp_pars` (HxPars records, error policies) and `methods.protocol` exist. `protocol.load_method` gathers a method's include closure and the `.stp` beside each file; the tracer expands `main` and the registered abort handler (`::RegisterAbortHandler("OnAbort")`), inlines library functions whose bodies have step markers (a method section and a library function of the same name are told apart by namespace), keeps hand-written library code as call lines, folds PTL smart steps, and renders TraceComment texts as section headings. The volume maths is kept symbolic (`aspirate volume = <p_vol>`) because that is what the method computes.

### Method packages (`.pkg`)

What the Method Editor's Package Wizard exports: a method with its libraries, labware and configuration, for import on another instrument. `files.pkg` lists and extracts one without Venus (`python -m venus_interop.files.pkg list|extract`). Measured on one package, Hamilton's `Deck Animations Library Demo 231101.pkg` (Venus 6.0.2.50007, 301 entries, 13.6 MB):
- **Container:** `HamPkg`, four u16 words (0, 2, 1, 0), a u32 entry count, a FILETIME (2023-11-01 11:42 UTC, which matches the file name), the Venus version (20 bytes). Then 36-byte entries: an 8-byte hex id, a u32 flag, two FILETIMEs, an offset and a size. Each entry's data is a u32 unpacked size, a u32 packed size and a zlib stream; all 301 decompress to their stated size.
- **Manifest:** the one entry with flag 0, a binary HxCfgFile with an HxPars list section `McListData`. `files.hxcfg` round-trips it byte for byte. Its `ListItems` hold 542 files.
  - 300 are carried: each names its entry id (`-347734013`), its name relative to its folder (`-347734014`) and the path it installs to (`-347734015`).
  - 242 are listed with an empty id and not carried. All are stock Venus files (`HSLMECCLib.hs_`, the standard bitmaps and labware), expected to exist on the target.
  - Items list the files they refer to under `-347734009` (`-347734000` each), e.g. a layout's 15 labware files.
- **Paths are absolute** (`C:\Program Files (x86)\Hamilton\Library\…`), plus two from the packer's Temp folder (`ML_STAR_<n>`, `SystemConf`: the instrument configuration). `files.pkg.extract` writes each below the Hamilton folder, and anything else under `_external/`. It resolves `..` first and never writes outside the target folder.
- Reading only: `files.pkg` doesn't write packages.

### Footers

Every text file Venus writes ends with `// $$author=…$$valid=…$$time=…$$checksum=XXXXXXXX$$length=NNN$$`. A text-form HxCfg file uses `*` instead of `//`.
- **`checksum`:** CRC32 of the file from its first byte up to and including `$$checksum=`. This matched on all 14 Venus files checked.
- **`length`:** the footer line's length plus an offset. The offset is 0 for `.hsl`, `.hs_` and text HxCfg files, and 2 for `.hsi`, `.sub` and binary HxCfg files. Keep the offset the file already has.
- **Tools:**
  - `files.footer.ok` checks a footer, and `files.footer.rewrite` recomputes it.
  - `files.hxcfg.write` writes the `.med`'s footer.

### Inserting a step: the edit a script would make

Take adding `PLLD_SPEED::SetZSpeed(ML_STAR, channelVariable, plldSearchSpeed)` before `Channels_1ml_Aspirate`:

1. **`.med`:**
   - Add a record with a new GUID, cloned from a record of the same step type.
   - For a library call, change `FunctionName`, the library path, `FunctionPars`, `ParamValue`, `Variables` and the code line in `BlockData`.
   - Write the file back with `files.hxcfg`, never with Hamilton's converter.
2. **`.hsl`:**
   - Add the marker block in the right place.
   - Renumber the rows after it. Do the whole sub-method in one pass, so the rows stay sequential.
   - Add the `#include` and the variable if they are new.
3. **Footers:** recompute the `.hsl`'s footer, and the `.sub`'s if it changed.

The pLLD change is four steps:

| Step | Call | Where |
|---|---|---|
| a | `JSON_GetFloatValue` of `plldSearchSpeed` | After row 80 |
| b | `SetZSpeed` | Before the aspirate (row 91) |
| c | `RestoreZSpeed` | After the aspirate (row 93) |
| d | `RestoreZSpeed(ML_STAR, "11111111")` | In `initialize`, after `LiquidClassLib::Initialize` |

Route 3A, adding the steps in the Method Editor, is the recommended one. It's guaranteed valid because the editor writes every file itself. With either route, save once from the editor afterwards.

**Still unknown, because route 3B is untested in Venus (also listed in §11):**
- whether the editor needs contiguous row numbers (renumbering avoids the question);
- whether a library import is registered anywhere besides the `#include`;
- whether `HxMetEd_Outlining` or the flowchart blob must list a new step (probably they are only stale until the first save);
- the exact parameter-binding fields of a cloned record.

**A future `methods.med` module (not built):**
- It would parse the step records into objects.
- It would provide `insert`, `delete` and `set_parameter`, keeping the `.med`, `.hsl`, `.sub` and footers in step.
- It would check consistency: every marker has a record, rows are sequential, and footers hold.
- It isn't built by choice: the Method Editor covers the need today.
