# Multiflex carrier assembly: the spatial model

Sep 27, 2026 · Stefan Golas · local copy of https://claude.ai/code/artifact/d87a0024-a9d7-4c69-aedd-c2be7e6a467d

## Purpose and scope

A Hamilton Multiflex (MFX) carrier is a fixed baseplate with numbered positions, each holding one exchangeable module, and every labware site on it follows from two sets of numbers: the baseplate's and the module's. This document describes that spatial model as Hamilton's Multiflex Carrier Assistant ("MFX Labware Assistant 3D", v4.10) encodes it, so that PLR can build the same assemblies from data.

- **In scope:** the physical parts (baseplates, modules, brackets, labware), the coordinate conventions, and the rules that place a site and a 3D model.
- **Out of scope:** code, class names or an implementation plan for PLR, and device control (the heater-shaker or CPAC drivers).
- **How it was read:** from the tool's own data files and binary, without installing or running it. Every rule below is either stated in those files or checked against carriers Venus assembled; the rest is marked as unclear.

## Sources

Everything here comes from Hamilton's own files and from carriers Venus assembled; nothing is measured by hand.

| Source | Where | What it gives | How it was read |
| --- | --- | --- | --- |
| [Multiflex Carrier Assistant v4.10](https://download.hamiltonsupport.com/wl/?id=VQY0XAzTfcT7KY29A1YJtZVFwZ7GMOO2) (`MultiflexCarrierAssistantv4.10.zip`, folder *Hamilton GUIs and Tools*) | Hamilton's shared download library | The installer: one embedded Microsoft cabinet, 240 files | Cabinet carved out of the EXE and opened with Windows `expand`; nothing installed or run |
| `MultiMFX.INI` | inside the installer | The catalogue: 4 baseplates, 99 module entries (the header says 97), every placement parameter, with a field-by-field template | Parsed as text |
| `LabwareAssistant3D.exe` (139 KB) | inside the installer | The tool itself, a Visual Basic 6 program; its strings name the INI keys it reads | Strings only; not decompiled |
| `Install.bat` and 7 `.reg` files | inside the installer | Where the tool installs: models and definitions into `LabWare\ML_STAR\MultiflexCarrier`, the EXE into `Bin`, a "Labware Assistant..." entry in Venus's method editor tools menu | Read |
| 101 `.x` models, 84 `.jpg`, 15 `.rck`, 12 `.ctr`, 5 `.tml` | inside the installer | 3D models of the baseplates and modules (DirectX text format), a photo per module, labware definitions, blank carrier templates | Listed; headers read |
| Assembled MFX carriers, e.g. `MFX_CAR_2HHS30NuncDWP_2CPACflat.tml` / `.x` | `C:/Users/stefa/NGS-Protocols/assets/NGSStarMOA/...` (10x Genomics protocol labware) | Real carriers composed in Venus, with their site positions | Parsed; used to check the rules |
| [Library Downloads (Links)](https://labautomation.io/t/library-downloads-links/1052) | labautomation.io | Where the Hamilton library is and who curates it | Read |
| [Library Downloads? (Requests), page 5](https://labautomation.io/t/library-downloads-requests/40?page=5) | labautomation.io | A carrier request resolved "using Multiflex Carrier Assistant tool" | Read |
| [Labware 3D data](https://labautomation.io/t/labware-3d-data/2520) and [3D models view and Hamilton labware editor](https://labautomation.io/t/3d-models-view-and-hamilton-labware-editor/1064) | labautomation.io | `.x`/`.hxx` formats; Hamilton states the 3D data is cosmetic and does not affect the labware definition | Read |

No licence is stated for the Hamilton files. Everything they contain is Hamilton's.

Local copies: the extracted installer is in `tools/mfx_extracted/` beside this file, and the parsed catalogue in `tools/mfx_catalogue.json`.

## Physical anatomy

An MFX carrier is built in layers: a baseplate on the deck tracks, one module per baseplate position, and labware on the modules.

```
Every labware site sits on a module, which sits on a baseplate

  Labware: plate, tip rack, tubes              Its bottom sits at the module's Base height
     |
  Module: nest, HHS, CPAC, heater, shaker      One per position; 127 x 86 mm (tip modules 122.4 x 82.6)
     |
  Bracket set, e.g. part 188133                Holds module to baseplate; HHS and HHC entries list none
     |
  Baseplate: 5-pos, 4-pos, 7T shaker, portrait Fixed positions at a set pitch; 5 to 7 tracks wide
     |
  STAR deck tracks                             The assembled carrier loads like any other carrier
```

The module decides what a position does, and the site's height. The catalogue groups them into these families, all as separate entries with Hamilton part numbers:

| Family | Examples in the catalogue | What sits on it |
| --- | --- | --- |
| Plate nests | MTP / DWP / MIDI modules; rack-based (RB) and container-based (CB) nests; high-precision (HP) flat, raised, sloped and tabbed nests | A plate |
| Tip holders | Tip, Tip BC, NTR1, NTR4, NTR1 384, tip park, tip stack (ST/low), tip isolator | A tip rack (footprint 122.4 x 82.6 mm) |
| Temperature | Heating module (188045), cooling module (188046), CPAC flat and CPAC 2 mL (58246/47/48-01), Hamilton Heater Cooler, HHC (6601900-01) | A plate or tubes |
| Shaking | Hamilton Heater Shaker (HHS) nests for flat MTP/DWP, Nunc DWP, Sarstedt, PCR96 ABI, VWR DWP96, flip tubes; Teleshake and Teleshake 95; active nests and active plate nests | A plate, or tubes |
| Other | Tilt, turntable, stacker (landscape and portrait), gripper module, lid park, reagent (RGT) modules and refills, tube modules, gravity waste, Matrix 1.4 mL rack | Varies |

Three companion parts come with some modules:

- **Brackets.** Most modules name a bracket set (`Info3`, e.g. "with brackets 188133") and a bracket model (`BracketShakerBase.x`; `BracketShakerBaseCPAC.x` for CPAC; `BracketCTHT.x` for heating and cooling). The heater-shaker nests, the HHC and the active plate nests list none.
- **Added modules.** A module can pull in another on top of it (`AddModul`): heating and cooling modules add a lid, the Matrix rack adds a downholder.
- **Labware files.** Some modules install their own rack and container definitions (e.g. CPAC 2 mL tubes, reagent refills, gravity waste trough).

## The four baseplates

Each baseplate fixes where position 1 is and how far apart the positions are; everything else comes from the modules. Values are from `MultiMFX.INI` (`[Carrier1]` to `[Carrier4]`); sizes and clearance from the blank templates (`MFX_CAR_*_XXX_A00.tml`, `Dim.Dx/Dy/Dz`, `Clearance`).

| Baseplate | Template | Size X x Y (mm) | Tracks | Positions | Position 1 site origin X, Y (mm) | Pitch Y (mm) | 3D origin X, Y, Z (mm) | 3D offset X (mm) | Clearance (mm) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MFX 5 Position Carrier | `MFX_CAR_L5_XXX_A00` (alt. `MFX_CAR_5_XXX_A00`) | 135 x 497 | 6 | 5 | 4, 392.5 | -96 | 4, 392.5, 18 | 0.5 | 130 |
| MFX 4 Position Carrier | `MFX_CAR_L4_XXX_A00` | 135 x 497 | 6 | 4 | 4, 344.5 | -96 | 4, 344.5, 18 | 0.5 | 130 |
| MFX 4 Position Carrier (Shaker Carrier) | `MFX_CAR_7T_XXX_A00` | 157.5 x 497 | 7 | 4 | 15.25, 375.05 | -120 | 13.75, 375.05, 18 | 1.5 | 90 |
| MFX Portrait Carrier | `MFX_CAR_P3_XXX_A00` | 112.5 x 497 | 5 | 3 | 22, 329.5 | -146 | 22, 329.5, 18 | 0 | 130 |

- **Position numbering.** Position 1 is at the back (largest Y); each next position is one pitch nearer the front. On the 5-position plate that puts the five sites at Y 392.5, 296.5, 200.5, 104.5 and 8.5, the same Y as PLR's `PLT_CAR_L5AC_A00` plate carrier. PLR's `hamilton_mfx_carrier_L5_base` places module bodies instead, 94 mm deep at Y 4.5 to 388.5 on an 18.2 mm baseplate; a plate centred in them lands at the same Y, and 18.2 mm is close to the catalogue's 3D origin Z of 18.
- **The shaker carrier** is a track wider and uses a 120 mm pitch, room for devices larger than a nest. It is the only baseplate marked `HasBracket=Y`.
- **Positions are counted, not listed.** The catalogue gives only the first position and the pitch; a baseplate has no per-position table.
- **Templates hold placeholders.** The templates carry 10 sites (5 on the 5-position alternate), all at X 4, Y -62, Z 112, size 1 x 1 mm. The tool overwrites one per module placed, and the rest stay: a 5-position carrier from the Roche library still holds 5 such leftover sites.

## Module parameters

A module is described by its site height, its footprint and a small X/Y shift; the other fields handle brackets, companions and labware files. The field list is the catalogue's own template (`[Modul0]`); the meanings are read from the values and checked against assembled carriers where the last column says so.

| Field | Physical meaning | How sure |
| --- | --- | --- |
| `Base` | Height of the labware site above the carrier's origin (bottom of the carrier), in mm: where the labware's bottom rests | Checked: equals site Z in every assembled carrier except CPAC |
| `Width`, `Length` | Footprint of the labware site, X by Y: 127 x 86 mm for plates, 122.4 x 82.6 for tip racks, 123 x 88 for the Sarstedt HHS nest | Checked: equals site `Dx`, `Dy` |
| `OriginLOffsetX` | Shift of the site in X from the baseplate's site origin, e.g. 2.3 mm for tip modules, which centres a 122.4 mm rack in a 127 mm slot | Checked (tip modules on the 5-position plate) |
| `OriginPOffsetY` | Shift of the site in Y, e.g. +1.7 for tip modules (centring 82.6 in 86), -1.55 for 3 mm HHS nests, -1.05 for 2 mm ones | Checked (tip modules, HHS nests) |
| `OriginLOffsetY`, `OriginLOffsetZ` | Further shifts, used only by the HHC entry (-1.95, -0.6) | Unchecked |
| `OriginX`, `OffsetY` (module) | Present on most entries (OriginX 4 on nests, 3.65 on HHS nests; OffsetY 0.05 on HHS, 16.5 and 46 on heating/cooling and lids). Not used by any rule that reproduces the assembled carriers | Unclear |
| `Offset3DX/Y/Z` | Where the module's 3D model is placed relative to its position, e.g. -0.5 in X for most nests, (-74.75, -53.9, -10) for the HHC | Unchecked (3D) |
| `BracketFile`, `Info3` | The bracket model drawn under the module, and the bracket kit's part number | Stated |
| `NotValidForCarrier` | The one baseplate (1 to 4, as numbered in the previous section) this entry cannot go on; most modules have two entries, one per baseplate family | Partly checked; see open questions |
| `AddModul` | Another catalogue entry placed on top of this one: heating and cooling modules add a lid (entries 31, 32), the Matrix rack adds a downholder (1001, 1002) | Stated |
| `LabwareFile`, `FileCopy1..n` | Rack and container definitions (and sometimes a model) the module brings | Stated |
| `TipRack`, `StackLabware` + `StackSize`, `Cover`, `Snap`, `OverSize`, `BorderOnly` | Flags on the site: holds tips, holds a stack, is covered, labware snaps to it, the module overhangs its position | Stated; effect on geometry unclear |
| `InPortrait` | Only on portrait variants of the sloped HP nests, together with `Offset3DZ` 65 | Unclear |
| `Picture` | The module photo; its base name also matches the module's `.x` model (e.g. `HeatingModule.jpg`, `HeatingModule.x`) | Observed for many; not confirmed for all |

Representative modules, as the catalogue gives them:

| Module | Part no. | Site height `Base` (mm) | Site footprint (mm) | Site shift X, Y (mm) | Bracket |
| --- | --- | --- | --- | --- | --- |
| MTP Module | 188041 | 112 | 127 x 86 | 0, 0 | 188133 |
| DWP Module | 188042 | 85 | 127 x 86 | 0, 0 | 188133 |
| Tip Module BC | 188160 | 114.7 | 122.4 x 82.6 | 2.3, 1.7 | 188133 |
| NTR1 Module | 191420 | 77 | 122.4 x 82.6 | 2.3, 1.7 | 188133 |
| PCR Module 96 | 188049 | 109.5 | 127 x 86 | 0, 0 | 188133 |
| Heating Module | 188045 | 88 | 127 x 86 | 0, 0 | 188216 (4-position) |
| HHS 3mm Flat MTP | 199034 | 112.7 | 127 x 86 | 0, -1.55 | none |
| HHS 3mm Nunc DWP | 199039 | 83 | 127 x 86 | 0, -1.55 | none |
| HHS PCR96 ABI | 188298 | 91.2 | 127 x 86 | 0, -1.55 | none |
| Teleshake 95 DWP | 188197 | 75.5 | 127 x 86 | 0, 0 | 187471 |
| CPAC Flat | 58246/47/48-01 (Reno) | 102.6 | 127 x 86 | 0, 0 | 188362, "modified base" |
| Hamilton Heater Cooler | 6601900-01 | 80.61 | 127 x 86 | 1.64, -1.95 (Z -0.6) | none |

The catalogue's help text defines the abbreviations: BDZ = a Bonaduz (Switzerland) part, RNO/RENO = a Reno (USA) part, HP = high precision, RB = rack-based (the rack's base touches a flat module), CB = container-based (the wells touch a raised module).

## Coordinate frames and assembly rules

A labware site on position n is the baseplate's position-1 origin, moved n - 1 pitches toward the front, shifted by the module's small X/Y offsets, at the module's `Base` height. This reproduces 22 of 26 sites in Venus-assembled carriers exactly; the next section lists the four that differ.

**Frames.** All values are in mm, in the carrier's own frame as Venus writes it in a `.tml`: X across the carrier (left to right), Y along it (front to back), Z up, origin at the carrier's front-left-bottom corner, as for any Hamilton carrier. A site's X, Y is its front-left corner; its Z is where the labware's bottom rests.

**Labware site of a module on position n** (n = 1 at the back), from the baseplate B and the module M:

```latex
\begin{aligned}
X_{site} &= B.\mathrm{OriginX} + M.\mathrm{OriginLOffsetX} \\
Y_{site} &= B.\mathrm{OriginY} + (n - 1)\,B.\mathrm{OffsetY} + M.\mathrm{OriginPOffsetY} \\
Z_{site} &= M.\mathrm{Base} \\
(D_x, D_y) &= (M.\mathrm{Width},\ M.\mathrm{Length})
\end{aligned}
```

**Worked example.** An HHS 3mm Nunc DWP nest (part 199039) on position 2 of the shaker carrier: X = 15.25 + 0 = 15.25; Y = 375.05 + 1 x (-120) - 1.55 = 253.5; Z = 83; size 127 x 86. The 10x Genomics carrier `MFX_CAR_2HHS30NuncDWP_2CPACflat.tml` has site 2 at X 15.25, Y 253.5, Z 83, 127 x 86.

**Tip modules** show why the shifts exist: a tip rack's 122.4 x 82.6 mm footprint is centred in the 127 x 86 slot, (127 - 122.4) / 2 = 2.3 in X and (86 - 82.6) / 2 = 1.7 in Y. The heater-shaker nests shift -1.05 or -1.55 in Y instead, their own 2 mm or 3 mm variants.

**Companion modules.** An `AddModul` entry is placed on the same position and adds a second site at its own `Base`: a heating module (site at 88 mm) with its lid entry (135.5 mm), or a Matrix rack (81.5 mm) with its downholder (128.5 mm). Venus's own ODTC carrier stacks sites the same way (a plate site and a second one 12 mm higher at the same X, Y).

**3D models (not checked).** The drawing places each model from the baseplate's 3D origin rather than its site origin. The fields suggest this rule, which has not been tested against a Venus-assembled `.x`:

```latex
P_{model} = (B.\mathrm{Origin3DX},\ B.\mathrm{Origin3DY},\ B.\mathrm{Origin3DZ}) + (B.\mathrm{Offset3DX},\ (n-1)\,B.\mathrm{OffsetY},\ 0) + (M.\mathrm{Offset3DX},\ M.\mathrm{Offset3DY},\ M.\mathrm{Offset3DZ})
```

With an `Origin3DZ` of 18 on every baseplate, 18 mm reads as the height of the baseplate's top, where modules and brackets stand. For most nests the X terms cancel (e.g. 4 + 0.5 - 0.5 = 4, the site X). The bracket models are presumably placed the same way; the portrait variants and the HHC carry larger offsets.

## Validation against Venus-assembled carriers

The rules reproduce 22 of 26 sites in six Venus-built MFX carriers exactly in X, Y, Z and size. Three CPAC sites differ only in height, and one position holds a module that could not be identified. The carriers come from protocol labware folders under `NGS-Protocols/assets/NGSStarMOA`; the module on each position was read from the carrier's name.

| Carrier (`.tml`) | Protocol folder | Baseplate | Modules, back to front | Sites checked | Exact match | Differences |
| --- | --- | --- | --- | --- | --- | --- |
| `MFX_CAR_2MTP HPTab_MIDI HPTab_2DWP HPTab` | Roche | 5-position | MTP HP tabbed x2, MIDI HP tabbed, DWP HP tabbed x2 | 5 | 5 | none |
| `MFX_CAR_2TipBC_DWP_PCR96_DWP NestRB` | Oxford Nanopore | 5-position | Tip BC x2, DWP, PCR 96, DWP rack-based | 5 | 5 | none (tip sites at X 6.3, Y 394.2 and 298.2, as predicted) |
| `MFX_CAR_2HHSF30MTP_HHSF30DWP_CPAC` | Roche | Shaker (7T) | HHS 3mm flat MTP x2, HHS 3mm flat DWP, CPAC | 4 | 4 | none |
| `MFX_CAR_2HHSF30MTP_HHSF30DWP_CPAC` | PacBio | Shaker (7T) | as above | 4 | 3 | CPAC site at Z 91.6, catalogue 102.6 |
| `MFX_CAR_2HHS30NuncDWP_2CPACflat` | 10x Genomics | Shaker (7T) | HHS 3mm Nunc DWP x2, CPAC x2 | 4 | 2 | both CPAC sites at Z 90.5, catalogue 102.6; X, Y match |
| `MFX_CAR_2HHS30NuncDWP_Empty_PCR96` | Oxford Nanopore | Shaker (7T) | HHS 3mm Nunc DWP x2, "Empty", PCR 96 | 4 | 3 | position 3 at Y 133.5, Z 75.5: no catalogue entry has that pair |

What this settles and what it does not:

- **Settled:** the baseplate origins and pitches, the meaning of `Base`, `Width`/`Length`, `OriginLOffsetX` and `OriginPOffsetY`, and position 1 being at the back.
- **The CPAC height varies by protocol:** 102.6 mm (Roche, as the catalogue says), 91.6 (PacBio), 90.5 (10x Genomics). The labware on the CPAC, or a hand edit after the tool wrote the carrier, would explain it; nothing in these files says which.
- **Position 3 of the Oxford Nanopore shaker carrier** has Z 75.5, which matches Teleshake 95 DWP, but Y 133.5 implies a -1.55 shift, as on the HHS nests. It may be an HHS without a nest, a different module, or an edit.
- **Not covered:** the 4-position and portrait baseplates, most module families, and every 3D placement. No assembled `.x` was compared with the 3D rule.
- **ODTC carriers** (`MFX_CAR_ODTC_MTP`, `_V2`) are not built from this catalogue; they come from a separate Hamilton labware archive and put two sites 12 mm apart at the same X, Y.

## Unclear points and open questions

The site rules are solid for the 5-position and shaker baseplates; the 3D placement, the portrait baseplate and several fields are not yet pinned down.

| Question | What is known | What would settle it |
| --- | --- | --- |
| Does the 3D rule place models correctly? | Fields exist (`Origin3D*`, `Offset3D*` on both baseplate and module); the formula above is a reading of their names | Convert a Venus-assembled `.x` (e.g. `MFX_CAR_2HHS30NuncDWP_2CPACflat.x`) and the standalone module models, then compare positions |
| Where is each model's own origin? | Unknown until the `.x` files are converted; they carry DirectX transform frames | Convert the models and read their frames and bounds |
| What does `NotValidForCarrier` mean exactly? | Each entry lists one number from 1 to 4. HHS entries (1) and CPAC (2) both appear on the shaker carrier (3), so the number is at least not the carrier they go on | Place modules in the running tool, or find an assembled carrier on each baseplate |
| What do the L and P in `OriginLOffsetX`, `OriginPOffsetY` stand for? | They act as X and Y shifts on landscape baseplates; landscape/portrait is the obvious reading but does not fit how they are used | Assembled portrait-carrier sites; the tool's source |
| What do the module-level `OriginX` and `OffsetY` do? | No rule that reproduces the assembled sites uses them (e.g. OriginX 3.65 on HHS nests) | They may drive the tool's 2D drawing; check against the tool's screen or a portrait carrier |
| Why do CPAC heights differ (102.6, 91.6, 90.5 mm)? | The catalogue gives 102.6 and notes "modified base" and brackets 188362 | CPAC documentation, the labware each protocol puts on it, or a measurement |
| What is at position 3 of the Oxford Nanopore shaker carrier? | Y 133.5, Z 75.5; named "Empty" | The protocol's deck layout, or the lab that wrote it |
| Do portrait variants rotate the model? | Portrait variants of sloped HP nests carry `InPortrait=1` and `Offset3DZ` 65; `_P` models exist for many modules | Converted `_P` models and a portrait assembly |
| Is the site origin the labware's front-left corner? | That is the Venus `.tml` convention and the values fit it | Already standard for Hamilton carriers; low risk |
| Does the HHS (heater-shaker) device body appear in the models, or only its nest? | HHS entries have site heights of 76 to 112.7 mm and no brackets, which fits a device standing on the baseplate with a nest on top | Convert `HHS_*.x` and inspect |
| Are the 97 or 99 entries all distinct parts? | The header says `ModuleCount=97`; 99 sections are present, including the downholders 1001 and 1002 added by `AddModul` | Count entries reachable in the tool |
| Can these files be redistributed? | No licence is stated; Hamilton's forum says the 3D data is cosmetic | Ask Hamilton before shipping their models or catalogue in PLR |

- [ ] Convert one assembled carrier and its modules to test the 3D rule
- [ ] Find an assembled 4-position and a portrait carrier to test those baseplates
- [ ] Settle the CPAC height with its documentation or a measurement

## Implications for a PLR utility

A PLR equivalent needs two small tables of parts, baseplates and modules, and one rule that turns a choice of module per position into sites. Everything else (drawing, brackets, devices) hangs off that.

- **A baseplate description:** size, tracks, number of positions, position-1 site origin, pitch, and its 3D origin. Four rows cover Hamilton's range.
- **A module description:** part number, site height, site footprint, X/Y shift, bracket, which baseplates it fits, companion modules it brings (lid, downholder), and any racks it provides (CPAC tube rack, reagent refills). The catalogue's 99 entries carry 76 distinct names once the per-baseplate duplicates are merged.
- **An assembly:** a baseplate plus one module per position, with the sites derived, never typed. PLR already works this way in outline: `hamilton_mfx_carrier_L5_base` takes a module per position, and PLR has a handful of MFX modules. The difference is that PLR places module bodies and lets each module place its site, while the catalogue gives the site directly. Both agree when a module's body depth and its centring are known.
- **Devices on modules.** HHS nests, CPAC, the HHC and the shakers are instruments sitting in a position. A PLR assembly could tie a position's site to the device resource that controls it (PLR has heating_shaking, shaking and temperature_controlling device modules), so that moving a plate onto that site is moving it onto the device.
- **Checks built in.** A module entry that doesn't fit the chosen baseplate, a module that needs companions, a site clearance above the baseplate's (130 mm, or 90 on the shaker carrier).
- **Testable against Venus.** Every Venus-assembled `.tml` gives exact expected sites, so the six carriers in the Validation section could serve as reference cases, and any lab's own MFX `.tml` files as more.
- **Models kept apart from numbers.** The site rule needs only the catalogue's numbers. The 3D models are a separate, optional layer, and whether Hamilton's `.x` files may be redistributed is still open.
- **A reader for Venus files helps beyond MFX.** The same `.tml`/`.rck`/`.ctr` formats describe every Hamilton carrier and rack, and the installed Venus help (`Hxlabwr3enu.chm`, not yet opened) is the likely reference for their fields.
