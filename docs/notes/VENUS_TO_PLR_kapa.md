# The KAPA HyperPlus deck: Venus's representation and PLR's

`kapa_deck.py` builds the deck of Hamilton's NGS STAR MOA KAPA HyperPlus kit
(`NGS-Protocols/protocols/KAPA_HyperPrep/KAPA_HyperPlus_Deck.lay`, driven by
`HyperPrep_HyperPlus.py` through pyhamilton) by hand in PyLabRobot. This note records how Venus
represents the deck, where that is how people run robots but would mislead in PLR, and what PLR
does instead. `compare_to_lay.py` prints where the PLR deck differs from the layout.

The rule throughout: **the layout says what stands where; positions come from PLR factories**,
which are tested against Hamilton's templates and the manufacturers' drawings.

## 1. The machine

| Venus | PLR |
|---|---|
| `Deck: ML_STAR2.dck`, a 54-track STAR | `STAR(simulation=True)`, `STARDeck` (54 tracks) |

A STAR is a STARlet with 24 more tracks. Checked on Hamilton's `ML_Starlet.dck` / `ML_STAR2.dck`
and PLR's recordings and deck factories: width 1360 -> 1900, 30 -> 54 trays, and everything tied to
the right-hand end (waste block, trash, CO-RE gripper tools, teaching rack; tip waste and arm limits
in the recordings) moves +540.0 = 24 x 22.5. The left end is identical. The one site that differs:
the STARlet deck defines `96COREWash`, the STAR deck does not.

The NGS decks use the space left of track 1, with the left side panel off: the ODTC carrier, the
96-head external waste, the lid stack. `STAR(...)` defaults to `left_side_panel_installed=False`.

## 2. One physical object, one resource

Venus places *labware at positions*; a plate that moves is a different labware at each place.
PLR has *objects that move*, carrying their state (liquid, tips, lids).

| Venus | PLR |
|---|---|
| `MIDI_Pipette` (ABGENE_MIDI.rck on 3_DWP) and `MIDI_OnMagnet` (MagneticStandPlate_AlpaguaMagnumEx.rck on 5_MagPlate) | one MIDI plate, moved between the MIDI nest and the magnet |
| `HSP_Pipette` and `HSP_ODTC` | one Hard-Shell plate, moved into the ODTC and back |
| `Ham_ComfortLid_ODTC` on site 2_ODTC_LID | the lid assigned to the plate in the ODTC |
| `Ham_ComfortLid_Stack_0001..0005`: five labware at one X/Y, 6.7 apart, not on the carrier | one `ResourceStack` of five ComfortLids on the ODTC carrier's lid park (PacBio's copy of the template even names that site `2_ComforLidStack`, stack size 5) |

Venus's labware files also bundle things that are separate objects:

| Venus file | what it is | PLR |
|---|---|---|
| `MagneticStandPlate_AlpaguaMagnumEx.rck` | `ABGENE_MIDI.rck` field for field, plus the magnet's 3D model | `alpaqua_96_plateadapter_magnum_ex` (a `PlateAdapter`) in the DWP nest; the MIDI plate is assigned to it |
| `SMP_CAR_24_15x75_A00.rck` | the 24-position sample carrier with 15 x 75 tubes in it | `Tube_CAR_24_A00` with tubes in its holders |

## 3. Frames and numbering

- **A labware's position is its A1.** Venus's `TForm` is the first container's centre, placed
  through `BndryX/BndryY`; PLR places a resource by its front-left-bottom corner.
- **Sites count from the back.** Venus site k of a 5-position carrier is PLR's index 5 - k.
- **A template is a coordinate frame, not always a physical thing.** `MFX_CAR_ODTC_MTP_V2` is
  one track wide at track 1 with every site 201.8 to the left and 12.5 in front of the carrier's
  own frame (V1). It is the same carrier (the same 3D model in all seven kits); the offset is where
  the kits mount it. PLR: `hamilton_mfx_carrier_7T_odtc_v2` stands at deck (-101.8, 50.5, 100).
  V2's one real change, the ODTC's plate seat 2.6 higher (97.1), is in the factory.
- **Lids are referenced about 4 mm above their bottom** in Venus (their nesting depth, 4.06): the
  layout's lid Z is 4.0 above PLR's for the same lid.

## 4. Taught coordinates are not geometry

Some layouts carry positions corrected on one instrument (the NGS teaching method writes these),
or never corrected at all where the method does not go. Z of each plate on the HP Tabbed carrier
against Hamilton's template sites (template - layout):

| layouts | 1_HSP | 2_HSP | 3_DWP (MIDI) | 4 (300 mL reservoir) | magnet (MIDI) |
|---|---|---|---|---|---|
| ONT LSK109, the guide deck | 0 | 0 | 0 | 0 | 28.6 above the nest |
| KAPA, 10x, PacBio (one lineage: same ODTC V2, same OLD_CPAC carrier) | +2.0 | +3.2 | +4.5 | +6.6 | 30.1 |
| QIAseq | +1.6 | +1.6 | +3.9 | 0 | 28.7 |
| Hamilton's templates (PLR) | 0 | 0 | 0 | 0 | 29.21 (`Alpaqua_MagEx.tml`) |

Identical plates on identical nests 1.2 mm apart in one deck is a teaching record, not a design.
PLR keeps nominal geometry; per-instrument corrections are calibration, a separate concern (and
Phase 4's teaching method is where they would be measured). A caution for real runs: where the
nominal floor is *below* a taught one, a fixed-height aspiration (KAPA removes supernatant at
0.3-0.8 above the bottom) aims into the floor on that instrument. Teach, or use cLLD.

Where the method does not go, the layout is simply wrong: on the Heater Shaker carrier at track 48
KAPA has `HHS3_MIDI` at Z 214.6; the template's site is 183.0.

## 5. State that Venus keeps outside the deck

| Venus / pyhamilton | PLR |
|---|---|
| `TrackedTips`, `StackedResources`: occupancy in SQLite (`~/.pyhamilton`) keyed by layout names | tip tracking on each `TipSpot`, the `ResourceStack` itself; the deck serialises with its state |
| `set_labware_property(TipSupport, MlStarCore96TipRack, tip type)` when a new rack is ejected onto the support | the support's spots hold the tip objects that were ejected there; nothing to relabel |
| `assign_reagent_map(name, positions)` on tracked containers | liquid tracking in the containers |
| default 96-head waste: the rack with property `MlStarIsCore96WasteRack` | the deck component `trash_core96`, which the driver uses as the head's discard location |

### What the one-object model catches

`HyperPrep_HyperPlus.py` removes supernatant and ethanol with
`transfer_96(..., MIDI_OnMagnet, MIDI_OffMagnet, ...)`: into `MIDI_OffMagnet`, the nest the same
plate has just left for the magnet. In Venus's model they are two labware, so nothing says the
nest is empty; in PLR the plate is on the magnet and the nest holds nothing to dispense into. The
demo sends it to the 96-head liquid waste, as pyhamilton's own `ethanol_wash` does.

## 6. The 96-head waste

PLR's default `trash_core96` (-58.2, 106.0, 216.4; "got this location from a .lay file") is
Hamilton's **slide waste with tip chute**: `Core96SlideWaste.tml` on deck site `96CORESlideWaste`
puts its rack's A1 at (-42.0, 120.1), which PLR's comment reproduces. The NGS decks use the
**external waste without chute** (`Core96ExternalWaste.tml`, deck site `96COREExtWaste`): rack at
(-242.7, 44.45), Z 185. The KAPA deck replaces the default with it, under the same component name.
Its eject height (173.9) copies how PLR's slide-waste value sits over that waste's floor: by
analogy, unverified.

Placing it at its real rack exposed a bug: centring the 96-head over a resource put channel A1 at
the array's front-left, half a pitch in (4.5 off in X, 58.5 in Y), and PLR's default trash stood
60 mm behind the waste it stands for to make up for it. Fixed in both drivers (commit d2d42f09b);
the default trash now stands at Hamilton's slide-waste rack and commands exactly what it did.

## 7. Choices and findings

- Only what the method uses is loaded, with the carriers that physically stand there. Left out as
  unused: the plate and lid waste chutes on the right, a parked MIDI, the plates on the Heater
  Shakers. KAPA mixes by pipetting and never shakes.
- The stacking carrier at 7T-M1 (X 55, left of track 1) is `PLT_CAR_L4ST_LOW_A00` with three
  z stacks: three MIDI plates, three and five Hard-Shells, at Hamilton's stacking pitches (28.75,
  12.25: PLR's plates now carry them). Venus lists each plate of a stack as its own labware, as it
  does the lids. The NGS kits raise the carrier's front site to 53 (the library's is 18) with
  nothing to say what stands under it; PLR keeps 18, so that stack sits 35 lower than the layout.
  All of PLR's L4ST factories failed to build (missing `pedestal_size_z`); fixed.
- The ODTC carrier's nominal footprint overlaps the stacking carrier's by 0.7 (V2's 201.8 offset
  is not nine tracks); their bodies clear. The deck's footprint check is waived for it.
- The ethanol reservoir `Ham_DW_Rgt_96L` has the same container as Hamilton's `Axygen_DW_96_res`
  (same equation, depth, base, cLLD); only the A1 inset differs, by 1 mm, which a single connected
  reservoir does not see. PLR: `cor_axy_1_troughplate_300mL_Vb`.
- The cold plate on the CPAC: KAPA's is hand-placed 4.65 in front and 3.5 above the verified
  Hard-Shell-on-PCR-adapter seat; PacBio leaves it at the catalogue's 102.6 (the top of Hamilton's
  CPAC model). PLR keeps the verified seat.
- The master-mix tubes: Venus's `cup_15x75.ctr` is not on this machine; `kapa_deck.tube_15x75` is
  a generic stand-in. Hamilton's six identical 24-position carrier definitions put tube centres
  1.5 (X) and 2.0 (Y) from PLR's `Tube_CAR_24_A00`; Hamilton's mesh does not settle which edge
  the offset is from. Low impact in a 13 mm tube.

Transport: the method moves plates with the CO-RE gripper; the v1 driver can pick the tools up but
has no CO-RE plate move yet, so the demo uses the iSWAP. Gripped from the front it cannot reach the
HP Tabbed carrier's front site (the magnet); gripped from the back it reaches every move, picking
up and putting down from the same side so nothing is turned (`probe_iswap.py`).

Fixed in PLR on the way (fork, `viz3d-motion`): `Trough_CAR_5R60_A00` had four sites, the fourth
7.5 mm off its pitch (Hamilton: five at 96 mm; KAPA's bead trough stands on that site); lids did
not nest in a stack (Hamilton's ComfortLid stacks at 6.7, not its 8.5 height). Added: the Magnum EX,
the OLD DWP HP Tabbed nest, the ODTC carrier V2.
