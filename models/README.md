# 3D models for the viewer

GLBs the 3D viewer draws imported Venus decks with (`venus_interop/plr/viewer_models.py`). Each is in
its resource's frame: front-left-bottom corner, metres, Z up. Nothing is converted at run time: a
labware with no GLB is drawn as a box.

GROQ-seq additionally uses the existing `plr-models` MPE² mesh. Its GLB node transforms are
registered to the imported filter site at runtime; geometry is not regenerated. It remains at
rest because this method does not operate MPE². The DNA extraction demo's animated integration
continues to use `MPE2Model` and the simulation state observer.

## What the viewer uses

GROQ also attaches `star_base_deck_frame.glb` to the existing STAR device. Build it with
`tools/build_groq_star_base.py`: it retains the lower chassis components of PLR's `star_base.glb`,
omits the hood and duplicate waste hardware, and translates by minus PLR's `STAR_DECK_LOCATION`.
The imported device/deck/resources do not move. The sidecar records the frame transform and
component-selection Delta entries; compressed geometry buffers are unchanged.

| Labware (Venus definition) | GLB | From |
|---|---|---|
| `HTF_L.rck`, `STF_L.rck`, `TIP_50ulF_L.rck` (tip racks) | `hamilton_96_tiprack_standard` | PyLabRobot |
| their tips | `hamilton_tip_1000uL`, `_300uL`, `_50uL` | PyLabRobot |
| `COREGripTool_OnWaste_1000ul.rck` and the tools | `hamilton_core_gripper_1000ul_5ml_on_waste`, `hamilton_core_gripper_tool` | PyLabRobot |
| MultiFlex carriers, 5 positions (135 x 497 mm) | `MFX_CAR_L5_base` | PyLabRobot |
| MultiFlex carriers, 4-position shaker plate (157.5 x 497 mm) | `MFX_CAR_7T_shaker` | PyLabRobot |
| MultiFlex `TipBC` sites | `hamilton_mfx_tiprackholder_standard` | PyLabRobot |
| MultiFlex `DWP`, `DWPNestRB` sites | `hamilton_mfx_plateholder_DWP_HP_tabbed` / `_DWP_flat` (the nearer by height) | PyLabRobot |
| `SMP_CAR_24_17x100_A00.rck` | `Tube_CAR_24_A00.glb` | here (from `plr-viz3d-scratch/tools/out`) |
| `RGT_CAR_5R60_A00.tml` | `Trough_CAR_5R60_A00.glb` | here (from `plr-viz3d-scratch/tools/out`) |
| `MFX_CAR_2Empty_2HHSF30DWP`, `MFX_CAR_2Low_2HHC`, `MFX_CAR_HHC_Empty_2Base HPTab` | same-named assembled GLBs | NIST's exact named `.x` assemblies |
| `MFX_CAR_5DWP NestRB`, `MFX_CAR_5DWP`, `MFX_CAR_5TipBC` | same-named assembled GLBs | NIST's `.x` assemblies (5TipBC is available but not used on GROQ-seq) |
| `Culture_Processing_STAR_MPE2_Base_Back.tml` | `Culture_Processing_STAR_MPE2_Base_Back.glb` | NIST's `[MPE]2 Base.x` |
| `[MPE]2.rck` in GROQ-seq | `hamilton_mpe2_animated.glb` | unmodified copy from `plr-models/models`; registered by `examples/mpe2_model.attach_visual` |

The MultiFlex modules are matched by height: Venus's site against PLR's module on its base. Tip
sites match within 0.8 mm. Plate sites stand 2.6 mm above PLR's tabbed holder (0.5 mm above the
flat one on `MFX_CAR_5DWP NestRB`), so a plate there may float that much above the drawn holder.

The assembled GLBs take precedence over those approximations and include all their modules;
no extra base or module resources are drawn for them. The generic MultiFlex configurator remains
the builder for catalogue configurations. Imported sites retain their custom Venus coordinates.
The remaining four GROQ-seq carriers use the existing PLR base and module assets (14 modules).

Rebuild the thirteen assets with `.venv/Scripts/python tools/build_groq_viewer_models.py`.
Use `--references`, `--mpe2`, and `--output` to override the downloaded LabWare folder, existing
MPE² GLB, and destination. Inputs are read only. Each converted asset has a `.geometry.json`
with source hashes and a Delta ledger. Mesh minima are placed at the definitions' `3D*Offset`,
with mm converted to metres; overhangs are preserved. This cosmetic registration remains
unverified against Venus's 3D rendering (CONVENTIONS §11). No protocol dimensions are changed.

## Consumables and accessories

**Consumable update:** Ten more GLBs now cover the growth plate, both reservoirs, three lids,
the HT/ST/50 CO-RE II supports, and the 60 mL Hamilton trough. Build with
`.venv/Scripts/python tools/build_groq_consumables.py`. Nine are approximate visual reconstructions;
the trough uses its original `.hxx`. Their `.geometry.json` files record inputs, reconstructed
parameters, source hashes, and Delta entries. Reservoir geometry has one or six cavities; the
96/48 pipetting positions remain unchanged. The viewer may still draw its generic well/liquid
overlays inside these meshes. Tip support occupancy and removable lids remain separate resources.

**Waste and teaching update:** The viewer now uses the original authored meshes for
**WasteBlock, Verification, TeachingNeedle5ml, TeachingNeedleBlock, and core96 slide waste**.
These five assets are included in `build_groq_viewer_models.py`, with source hashes and Delta
ledgers. Teaching mesh Z minima retain the definition offsets of -94.9 and -52 mm; the waste
block retains its 186 mm mesh width despite its 30 mm logical box. The slide rack uses the
definition's `core96SlideWasteRack.hxx`, not the separate larger `Core96SlideWaste.hxx`.
All entries in the original inventory below now have visual models. Fine moulding details,
exact physical support/lid geometry, and accessory registration against Venus remain unverified.

**Reference search update, 2026-10-23:** [GROQ_SEQ_REFERENCES.md](GROQ_SEQ_REFERENCES.md)
records 82 downloaded NIST reference files, including 15 successfully parsed `.x`/`.hxx` models,
the MPE² base/unit and exact assembled MultiFlex carriers. It also identifies consumable photos
and manufacturer datasheets. The source-location notes below predate that fetch; the viewer
now uses the assembled carriers, MPE², consumable and accessory assets described above.

From the NIST decks GROQ-Seq.2_TFs (`5ae1a84b57e5.lay`) and Marionette (`3ed5809e547e.lay`), as of
2026-10-23. "Source" is a Hamilton `.x`/`.hxx` on this machine, which could be converted; "-" means
none was found (Venus install, `plr-viz3d-scratch`, NGS-Protocols).

### Original labware inventory (superseded by coverage updates above)

| Venus definition | Decks | On a deck | Source |
|---|---|---|---|
| `Culture Processing\Fourtitude Growth Plate with Lid.rck` | both | 3 | - (no 3D model named) |
| `Culture Processing\Fourtitude Growth Plate with Lid.lid` | both | 7 | - (no 3D model named) |
| `Agilent\Agilent single cavity 12 col pyr bottom 290 mL reservoir with lid.rck` | both | 2 | - (no 3D model named) |
| `Agilent\Agilent single cavity 12 col pyr bottom 290 mL reservoir with lid.lid` | both | 3 | - (no 3D model named) |
| `Agilent\Agilent 6 well reservoir.rck` | both | 1 | - (no 3D model named) |
| `Agilent\Agilent 6 well reservoir.lid` | both | 2 | - (no 3D model named) |
| `TipSupport CO-RE II\Core2_96_TipSupport_HT_Filter_L.rck` | both | 5 | - (no 3D model named) |
| `TipSupport CO-RE II\Core2_96_TipSupport_ST_Filter_L.rck` | both | 3 | - (no 3D model named) |
| `TipSupport CO-RE II\Core2_96_TipSupport_50ulTipFilter_L.rck` | both | 1 | - (no 3D model named) |
| `ML_STAR\Reagent\rgt_cont_60ml_BC_A00.rck` | both | 5 | `NGS-Protocols\...\rgt_cont_60ml_BC_A00.hxx` (PLR's `hamilton_1_trough_60mL_Vb` is a different footprint) |
| `ML_STAR\CORE\WasteBlock.tml` | both | 1 | Venus install `ML_STAR\CORE\WasteBlock.hxx` |
| `ML_STAR\CORE\Verification.rck` | both | 2 | Venus install `ML_STAR\CORE\Verification.hxx` |
| `ML_STAR\CORE\TeachingNeedle5ml.rck` | both | 1 | Venus install `ML_STAR\CORE\TeachingNeedle5ml.hxx` |
| `ML_STAR\CORE\teachingneedleblock.rck` | both | 1 | Venus install `ML_STAR\CORE\TeachingNeedleBlock.hxx` |
| `ML_STAR\96COREHEAD\core96slidewaste.rck` | both | 1 | Venus install `ML_STAR\96CoReHead\core96SlideWasteRack.hxx` |

### MultiFlex modules

These modules are drawn where the exact named carrier assemblies include them. Individual module
mapping is still incomplete; the table records the constituent parts.

**Not drawn: the `Low` modules of `MFX_CAR_2Low_2HHC`.** NIST's assembled `.x` (the only model its
`.tml` names) has the heater-coolers but nothing under the two `Low` sites: only the base plate,
about 8 mm over the carrier's bottom, and rails to 21.5 mm. The sites are at 27.9 mm, so a plate on
them (`Media_source`) is drawn about 17 mm over the visible surface. Venus's own 3D data has the same
gap. No exact `Low` part has been identified in the extracted MultiFlex parts.

| Site label | Height over the base (mm) | Carriers | Source |
|---|---|---|---|
| `Low` | 9.9 | `MFX_CAR_2Empty_2HHSF30DWP`, `MFX_CAR_2Low_2HHC` | `plr-viz3d-scratch/hamilton_library/tools/mfx_extracted` (Hamilton's MultiFlex parts, `.x`) |
| `Low_base` | 25.2 | `MFX_CAR_HHC_Empty_2Base HPTab` | the same |
| `EZ_pic` | 15.2 | `MFX_CAR_HHC_Empty_2Base HPTab` | the same |
| `HHC` (heater-cooler) | 62.8, 69.0 | `MFX_CAR_2Low_2HHC`, `MFX_CAR_HHC_Empty_2Base HPTab` | the same |
| `HHSF30DWP` (heater-shaker, flat DWP nest) | 65.8 | `MFX_CAR_2Empty_2HHSF30DWP` | PLR has `hamilton_heater_shaker` and `hamilton_hhs_nest_flat_dwp`; not assembled here |

The assembled sources are downloaded under `.local/session_state/nist/groq_model_references/`.
