# 3D models for the NIST decks: what exists and what must be made

As of 2026-10-16. Every labware definition placed on the three NIST decks written up so far (DNA Extraction `ce242e85d05d.lay`, Marionette `3ed5809e547e.lay`, Colony Picking `02 Colony Picking.lay`), and where its 3D model would come from. The **Generate** section is the work list for making models offline; the rest can be converted or assembled from files we have.

**Counts:** 69 distinct definitions. 39 need a model made, 24 convert from a Hamilton file, 2 assemble from Multiflex modules, 4 already draw with a PLR model. Not counted: the deck's own parts, and moving parts that have no definition (the last section).

**How the viewer picks a model:** a resource is drawn from `<model>.glb` when one exists anywhere in the pylabrobot package, or from its `reference_glb`. Otherwise it is a box of the resource's size. So everything under **Generate** currently draws as a box. `tools/generate_labware.py` already writes plain box-and-well GLBs from definitions; the point of this list is better models than those.

**Conventions in the tables:**
- Sizes in mm, from the Venus definition (`Dim.Dx/Dy/Dz`). "A1 centre" is `BndryX/BndryY`, measured from the rack's front-left corner. "Well bottom Z" is the container base above the rack's bottom (negative for tip supports and filter plates, whose wells hang below).
- Well shape from the container's `Shape`: 0 round, 1 square.
- "Used in" counts placements: `DNA` DNA Extraction, `Mar` Marionette, `Col` Colony Picking. A plate placed at several deck positions counts once per position.
- **Reservoirs:** the 8 × 12 "wells" are Venus's pipetting positions, not cavities. The cavity count is in the name (12-column, 2-column, 4-column, 6-well, single-cavity); take the shape from the vendor's drawing.
- **Lids:** all 9–9.15 mm tall. Each is drawn for the plate or reservoir of the same name.

**Sources:**
- Definitions: the corpus copies of NIST's labware (`.local/session_state/corpus/defs_raw/`).
- Hamilton models: the Venus install, the NIST repo's `LabWare/` (195 files, fetched 2026-10-16 into `.local/session_state/nist/models/`: 131 text `.x`, 62 `.hxx`, 2 binary `.x`; one `.hxx`, `RGT_CAR_4R200_B00`, wraps a binary `.x`), the Multiflex Carrier Assistant set, and the Hamilton share. All the files in **Convert** are text `.x` or `.hxx`, which `venus_interop.plr.xfile` reads (`HAMILTON_3D_MODELS.md`). It applies no textures; the MPE²'s photo planes are the only textured model here.

## Generate

### Plates

| Definition | Footprint × height (mm) | Grid, pitch | A1 centre from front-left (mm) | Well (mm) | Well bottom Z | Used in |
|---|---|---|---|---|---|---|
| `Agilent\Agilent filter plate GF 5.0 um.rck` | 127 × 86 × 44 | 8x12, 9 / 9 | 14, 11.5 | square 8.1 × 8.1, depth 41.5 | -3 | DNA 1 |
| `Agilent\Agilent filter plate.rck` | 127 × 86 × 43.75 | 8x12, 9 / 9 | 14, 11.5 | square 8.1 × 8.1, depth 41.5 | -3 | DNA 2 |
| `Culture Processing\96 well growth plate.rck` | 127 × 86 × 19.2 | 8x12, 9 / 9 | 14.2, 11.2 | square 7.7 × 7.7, depth 17.5 | 1.3 | Col 2 |
| `Culture Processing\ABGene 96 well 1200 ul plate.rck` | 127 × 86 × 23.5 | 8x12, 9 / 9 | 14, 11.5 | round 8 × 8, depth 20.9 | 2.2 | DNA 2 |
| `Culture Processing\Fourtitude Growth Plate with Lid.rck` | 127 × 86 × 19.2 | 8x12, 9 / 9 | 14, 11.5 | square 7.7 × 7.7, depth 17.5 | 1.3 | DNA 5, Mar 3 |
| `Culture Processing\Nunc 1 well agar plate.rck` | 127 × 86 × 14.2 | 1x1, 9 / 9 | 63.5, 42.6 | square 121.3 × 78.7, depth 11.5 | 1.7 | Col 6 |
| `Eppendorf\Eppendorf_96-well 2 mL DWP with cell pellet.rck` | 127 × 86 × 44.2 | 8x12, 9 / 9 | 14, 11.5 | round 7.8 × 7.8, depth 41.2 | 1.7 | DNA 2 |
| `Eppendorf\Eppendorf_96-well 2 mL DWP.rck` | 127 × 86 × 44.2 | 8x12, 9 / 9 | 14, 11.5 | round 7.8 × 7.8, depth 41.2 | 1.7 | DNA 3 |
| `Eppendorf\Eppendorf_96-well DNA lo-bind elution plate.rck` | 127 × 86 × 14.35 | 8x12, 9 / 9 | 14, 11.5 | round 7 × 7, depth 11.25 | 2.4 | DNA 3 |
| `Nunc\Nunc Binding Plate with Lid.rck` | 127 × 86 × 31.3 | 8x12, 9 / 9 | 14, 11.5 | round 8.3 × 8.3, depth 29.5 | -6.8 | DNA 5 |

### Reservoirs

| Definition | Footprint × height (mm) | Grid, pitch | A1 centre from front-left (mm) | Well (mm) | Well bottom Z | Used in |
|---|---|---|---|---|---|---|
| `Agilent\Agilent 12 column reservoir.rck` | 127 × 86 × 44 | 8x12, 9 / 9 | 12.95, 11.5 | square 8.1 × 8.5, depth 41 | 3.8 | DNA 1 |
| `Agilent\Agilent 2 column reservoir for 24-tip.rck` | 127 × 86 × 44 | 8x12, 9 / 9 | 14, 11.5 | square 20 × 8.5, depth 41 | 3.8 | DNA 1 |
| `Agilent\Agilent 4 column reservoir for 24-tip.rck` | 127 × 86 × 44 | 8x12, 9 / 9 | 14, 11.5 | square 9 × 8.5, depth 41 | 3.8 | DNA 3 |
| `Agilent\Agilent 6 well reservoir.rck` | 127 × 86 × 44 | 8x6, 18 / 9 | 19, 11.5 | square 17 × 8.5, depth 41 | 1 | DNA 1, Mar 1 |
| `Agilent\Agilent single cavity 12 col pyr bottom 290 mL reservoir with lid.rck` | 127 × 86 × 44.04 | 8x12, 9 / 9 | 13.5, 11.5 | square 9.4 × 9.4, depth 39.22 | 4 | DNA 1, Mar 2 |
| `Culture Processing\Active liquid waste trough.rck` | 127 × 86 × 55 | 8x12, 9 / 9 | 13.45, 10.95 | square 9 × 9, depth 25 | 1.4 | Col 1 |
| `Culture Processing\Nalgene 300 ml open trough.rck` | 127 × 86 × 42 | 8x12, 9 / 9 | 13, 11.5 | square 9 × 9, depth 37 | 2 | Col 5 |

### Tip supports

| Definition | Footprint × height (mm) | Grid, pitch | A1 centre from front-left (mm) | Well (mm) | Well bottom Z | Used in |
|---|---|---|---|---|---|---|
| `ML_STAR\96COREHEAD\Core96_TipSupport_50ulFilterTip_L.rck` | 122.4 × 82.6 × 20 | 8x12, 9 / 9 | 11.7, 9.8 | round 6.8 × 6.8, depth 50.4 | -29.5 | Col 1 |
| `ML_STAR\96COREHEAD\Core96_TipSupport_HTFilter_L.rck` | 122.4 × 82.6 × 13 | 8x12, 9 / 9 | 11.7, 9.8 | round 6.8 × 6.8, depth 95 | -72.5 | Col 1 |
| `ML_STAR\96COREHEAD\Core96_TipSupport_STFilter_L.rck` | 122.4 × 82.6 × 20 | 8x12, 9 / 9 | 11.7, 9.8 | round 6.8 × 6.8, depth 60 | -39 | Col 1 |
| `TipSupport CO-RE II\Core2_96_TipSupport_50ulTipFilter_L.rck` | 122.4 × 82.6 × 23.8 | 8x12, 9 / 9 | 11.7, 9.8 | round 6.8 × 6.8, depth 50.4 | -25.7 | DNA 1, Mar 1 |
| `TipSupport CO-RE II\Core2_96_TipSupport_HT_Filter_L.rck` | 122.4 × 82.6 × 16.8 | 8x12, 9 / 9 | 11.7, 9.8 | round 6.8 × 6.8, depth 95 | -68.7 | DNA 5, Mar 5 |
| `TipSupport CO-RE II\Core2_96_TipSupport_ST_Filter_L.rck` | 122.4 × 82.6 × 23.8 | 8x12, 9 / 9 | 11.7, 9.8 | round 6.8 × 6.8, depth 60 | -35.2 | DNA 2, Mar 2 |

### Lids

| Definition | Footprint × height (mm) | For | Used in |
|---|---|---|---|
| `Agilent\Agilent 12 column reservoir.lid` | 127 × 86 × 9.15 | the `.rck` of the same name | DNA 2 |
| `Agilent\Agilent 2 column reservoir for 24-tip.lid` | 127 × 86 × 9.15 | the `.rck` of the same name | DNA 2 |
| `Agilent\Agilent 4 column reservoir for 24-tip.lid` | 127 × 86 × 9.15 | the `.rck` of the same name | DNA 4 |
| `Agilent\Agilent 6 well reservoir.lid` | 127 × 86 × 9.15 | the `.rck` of the same name | DNA 2, Mar 2 |
| `Agilent\Agilent filter plate.lid` | 127 × 86 × 9.15 | the `.rck` of the same name | DNA 3 |
| `Agilent\Agilent single cavity 12 col pyr bottom 290 mL reservoir with lid.lid` | 127 × 86 × 9.15 | the `.rck` of the same name | DNA 2, Mar 2 |
| `Culture Processing\ABGene 96 well 1200 ul plate.lid` | 127 × 86 × 9.15 | the `.rck` of the same name | DNA 4 |
| `Culture Processing\Fourtitude Growth Plate with Lid.lid` | 127 × 86 × 9.15 | the `.rck` of the same name | DNA 9, Mar 6 |
| `Culture Processing\Nunc 1 well agar plate.lid` | 127 × 86 × 9 | the `.rck` of the same name | Col 7 |
| `Eppendorf\Eppendorf_96-well 2 mL DWP with cell pellet.lid` | 127 × 86 × 9.15 | the `.rck` of the same name | DNA 3 |
| `Eppendorf\Eppendorf_96-well 2 mL DWP.lid` | 127 × 86 × 9.15 | the `.rck` of the same name | DNA 3 |
| `Eppendorf\Eppendorf_96-well DNA lo-bind elution plate.lid` | 127 × 86 × 9.15 | the `.rck` of the same name | DNA 5 |
| `Nunc\Nunc Binding Plate with Lid.lid` | 127 × 86 × 9.15 | the `.rck` of the same name | DNA 6 |

### Other

| Definition | Footprint × height (mm) | Grid, pitch | A1 centre from front-left (mm) | Well (mm) | Well bottom Z | Used in |
|---|---|---|---|---|---|---|
| `ML_STAR\easyPickII\Culture Processing PLT_CAR_2DWPRackBased_LIGHT_A01.tml` | 157.5 × 497 × 130 |  | ,  |  |  | Col 1 |
| `ML_STAR\easyPickII\easypickii_adjust_big.rck` | 12 × 12 × 8 | 1x1, 0 / 0 | 6, 6 | square 6 × 6, depth 7 | 0 | Col 1 |
| `ML_STAR\easyPickII\easypickii_adjust_small.rck` | 6 × 6 × 1 | 1x1, 0 / 0 | 3, 3 | square 6 × 6, depth 1 | 0 | Col 4 |

## Convert

| Definition | Model file | From | Used in |
|---|---|---|---|
| `ML_STAR\MPE2\[MPE]2.rck` | `ML_STAR\MPE2\[MPE]2.x` | NIST LabWare | DNA 1, Mar 1, Col 1 |
| `ML_STAR\MPE2\Culture_Processing_STAR_MPE2_Base_Back.tml` | `ML_STAR\MPE2\[MPE]2 Base.x` | NIST LabWare | DNA 1, Mar 1 |
| `ML_STAR\MPE2\STAR_MPE2_Base_Back.tml` | `ML_STAR\MPE2\[MPE]2 Base.x` | NIST LabWare | Col 1 |
| `ML_STAR\MultiFlexCarrier\CultureProcessing_MFX_CAR_2Empty_2MediaLine.tml` | `ML_STAR\MultiFlexCarrier\MFX_CAR_2Empty_2MediaLineX.x` | NIST LabWare | Col 1 |
| `ML_STAR\MultiFlexCarrier\CultureProcessing_MFX_CAR_2Empty_TipBC_LiquidWaste.tml` | `ML_STAR\MultiFlexCarrier\MFX_CAR_2Empty_TipBC_LiquidWaste.x` | NIST LabWare | Col 1 |
| `ML_STAR\MultiFlexCarrier\CultureProcessing_MFX_CAR_Empty_2MediaLine_Thermoshake.tml` | `ML_STAR\MultiFlexCarrier\CultureProcessing_MFX_CAR_Empty_Thermoshake_2MediaLine.x` | NIST LabWare | Col 1 |
| `ML_STAR\MultiFlexCarrier\MFX_CAR_2DWP NestRB_3TipBC.tml` | `ML_STAR\MultiFlexCarrier\MFX_CAR_2DWP NestRB_3TipBC.x` | NIST LabWare | Col 1 |
| `ML_STAR\MultiFlexCarrier\MFX_CAR_2Empty_2DWP_Empty.tml` | `ML_STAR\MultiFlexCarrier\MFX_CAR_2Empty_2DWP_Empty.x` | NIST LabWare | DNA 1, Mar 1 |
| `ML_STAR\MultiFlexCarrier\MFX_CAR_2Empty_2HHSF30DWP.tml` | `ML_STAR\MultiFlexCarrier\MFX_CAR_2Empty_2HHSF30DWP.x` | NIST LabWare | DNA 1, Mar 1 |
| `ML_STAR\MultiFlexCarrier\MFX_CAR_2Empty_TipBC_DWP.tml` | `ML_STAR\MultiFlexCarrier\MFX_CAR_2Empty_TipBC_DWP.x` | NIST LabWare | DNA 1, Mar 1 |
| `ML_STAR\MultiFlexCarrier\MFX_CAR_2Low_2HHC.tml` | `ML_STAR\MultiFlexCarrier\MFX_CAR_2Low_2HHC.x` | NIST LabWare | DNA 1, Mar 1 |
| `ML_STAR\MultiFlexCarrier\MFX_CAR_5DWP NestRB.tml` | `ML_STAR\MultiFlexCarrier\MFX_CAR_5DWP NestRB.x` | NIST LabWare | DNA 1, Mar 1, Col 1 |
| `ML_STAR\MultiFlexCarrier\MFX_CAR_5DWP.tml` | `ML_STAR\MultiFlexCarrier\MFX_CAR_5DWP.x` | NIST LabWare | DNA 1, Mar 1 |
| `ML_STAR\MultiFlexCarrier\MFX_CAR_5TipBC.tml` | `ML_STAR\MultiFlexCarrier\MFX_CAR_5TipBC.x` | NIST LabWare | Col 2 |
| `ML_STAR\MultiFlexCarrier\MFX_CAR_HHC_Empty_2Base HPTab.tml` | `ML_STAR\MultiFlexCarrier\MFX_CAR_HHC_Empty_2Base HPTab.x` | NIST LabWare | DNA 1, Mar 1 |
| `ML_STAR\Reagent\RGT_CAR_5R60_A00.tml` | `ML_STAR\Reagent\RGT_CAR_5R60_A00.hxx` | NIST LabWare | DNA 1, Mar 1 |
| `ML_STAR\Reagent\rgt_cont_60ml_BC_A00.rck` | `ML_STAR\Reagent\rgt_cont_60ml_BC_A00.hxx` | NIST LabWare | DNA 5, Mar 5 |
| `ML_STAR\SMP_CAR_24_17x100_A00.rck` | `ML_STAR\smp_car_24_a00.hxx` | NIST LabWare | DNA 1, Mar 1 |
| `ML_STAR\96COREHEAD\core96slidewaste.rck` | `ML_STAR\96COREHEAD\core96SlideWasteRack.hxx` | Venus install | DNA 1, Mar 1, Col 1 |
| `ML_STAR\CORE\TeachingNeedle5ml.rck` | `ML_STAR\CORE\TeachingNeedle5ml.hxx` | Venus install | DNA 1, Mar 1, Col 1 |
| `ML_STAR\CORE\teachingneedleblock.rck` | `ML_STAR\CORE\TeachingNeedleBlock.hxx` | Venus install | DNA 1, Mar 1, Col 1 |
| `ML_STAR\CORE\verification.rck` | `ML_STAR\CORE\Verification.hxx` | Venus install | DNA 2, Mar 2, Col 2 |
| `ML_STAR\CORE\waste2.rck` | `ML_STAR\CORE\Waste2.hxx` | Venus install | DNA 1, Mar 1, Col 1 |
| `ML_STAR\CORE\WasteBlock.tml` | `ML_STAR\CORE\WasteBlock.hxx` | Venus install | DNA 1, Mar 1, Col 1 |

## Assemble

| Carrier | Baseplate | Positions (back to front) | Used in |
|---|---|---|---|
| `ML_STAR\MultiFlexCarrier\MFX_CAR_1Tip_1DWP_3TipBC.tml` | MFX 5 Position Carrier | 1_TipBC: Tip Module BC; 2_DWP: DWP Module; 3_TipBC: Tip Module BC; 4_TipBC: Tip Module BC; 5_TipBC: Tip Module BC | DNA 1, Mar 1 |
| `ML_STAR\MultiFlexCarrier\MFX_CAR_2DWP_3TipBC.tml` | MFX 5 Position Carrier | 1_DWP: DWP Module; 2_DWP: DWP Module; 3_TipBC: Tip Module BC; 4_TipBC: Tip Module BC; 5_TipBC: Tip Module BC | DNA 1, Mar 1 |

## Covered by PLR

| Definition | PLR model | Used in |
|---|---|---|
| `ML_STAR\HTF_L.rck` | `hamilton_96_tiprack_standard.glb` | DNA 1, Mar 1, Col 5 |
| `ML_STAR\STF_L.rck` | `hamilton_96_tiprack_standard.glb` | DNA 1, Mar 1, Col 6 |
| `ML_STAR\TIP_50ulF_L.rck` | `hamilton_96_tiprack_standard.glb` | DNA 1, Mar 1, Col 6 |
| `ML_STAR\CO-RE-GRIP\COREGripTool_OnWaste_1000ul.rck` | `hamilton_core_gripper_1000ul_5ml_on_waste.glb` | DNA 1, Mar 1, Col 1 |

`PLT_CAR_2DWPRackBased_LIGHT_A01.tml` is the easyPick II light carrier (two DWP positions); its definition names no model and gives only the footprint.

The two **Assemble** carriers name no model of their own. They are built from Carrier Assistant modules with `venus_interop.multiflex.assembly`, which matched every site to a module above.

## Parts with no definition

Moving or attached hardware the protocols use that no labware file describes:

| Part | Used by | What's known |
|---|---|---|
| MPE² shuttle, upper lifter, lower lifter, manifold, waste tray | DNA Extraction | `MPE2.md` §6: the mechanism, the firmware's names for each axis, the states that move them, the deck sites. Travel and sizes are not in the sources |
| easyPick II picking tool | Colony Picking | Not on the share or in PLR. The colony-picking write-up (`LMSF_COLONY_PICKING.md`) describes what it does; no geometry |
| Pre-cut wide-bore 1000 µL tips | DNA Extraction | A tip 71.8 mm long holding 1003 µL (the method's `C0TT`); PLR's `hamilton_tip_1000uL.glb` shortened would do |
