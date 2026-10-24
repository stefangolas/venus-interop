# GROQ-seq model references

Investigated 2026-10-23 against the missing-model inventory in `README.md` and `handoff.md`.
This is a source inventory, not a change to the viewer or to labware geometry.

**Subsequent integration:** `tools/build_groq_viewer_models.py` now prepares the six assembled
MultiFlex GLBs and MPE² base, and copies the existing animated MPE² GLB unchanged. GROQ-seq uses
five of those assemblies and the MPE² at rest, preserving imported resources and sites. See
`README.md` for current viewer coverage; the search results below describe the original inventory.

## Downloaded reference bundle

`.local/session_state/nist/groq_model_references/` contains **82 files, 24,424,635 bytes**
from [djross22/lmsf_hamilton, S-Cell_STAR-2](https://github.com/djross22/lmsf_hamilton/tree/S-Cell_STAR-2/LabWare).
Original paths are preserved under `LabWare/`. `manifest.json` records URLs, byte counts and SHA-256
hashes. `inspection.json` records parsed definition fields and model bounds/triangle counts.
The fetch used the branch name, not a pinned commit; hashes identify the downloaded content.

All **15 downloaded `.x`/`.hxx` files load successfully** with `venus_interop.plr.xfile.load`.
This verifies parsing, not visual alignment or mesh fidelity. No GLBs were generated.
The local scripts `fetch_groq_references.py` and `inspect_groq_references.py` are in
`.local/session_state/`. Two additional Agilent PDF downloads returned HTTP 403; their contents
were accessible through web search, and the links are below. The manifest records those failures.

## Existing geometry: use before authoring

Paths below are relative to the bundle's `LabWare/` directory.

| Missing item | Downloaded source | Assessment |
|---|---|---|
| MPE² base | `ML_STAR/MPE2/[MPE]2 Base.x` | 24 triangles; simple base geometry, not a detailed mechanical model |
| MPE² unit | `ML_STAR/MPE2/[MPE]2.x` | 412 triangles, 4 material groups; static reference, distinct from the existing animated whole-device GLB |
| HHS carrier and low sites | `ML_STAR/MultiFlexCarrier/MFX_CAR_2Empty_2HHSF30DWP.x` | Exact named assembled carrier, 1,316 triangles |
| Two HHCs and low sites | `ML_STAR/MultiFlexCarrier/MFX_CAR_2Low_2HHC.x` | Exact named assembly, 24,772 triangles |
| HHC, base and EZ-pick sites | `ML_STAR/MultiFlexCarrier/MFX_CAR_HHC_Empty_2Base HPTab.x` | Exact named assembly, 30,292 triangles |
| DWP holders | `ML_STAR/MultiFlexCarrier/MFX_CAR_5DWP.x` and `MFX_CAR_5DWP NestRB.x` | Exact named assemblies; candidates to replace nearest-height holder approximations |
| TipBC holders | `ML_STAR/MultiFlexCarrier/MFX_CAR_5TipBC.x` | Exact named assembly |
| WasteBlock | `ML_STAR/CORE/WasteBlock.hxx` | 2,540 triangles |
| Verification | `ML_STAR/CORE/Verification.hxx` | 180 triangles |
| Teaching needle, 5 mL | `ML_STAR/CORE/TeachingNeedle5ml.hxx` | 1,168 triangles |
| Teaching needle block | `ML_STAR/CORE/TeachingNeedleBlock.hxx` | 10,784 triangles |
| 96-head slide waste | `ML_STAR/96COREHEAD/core96SlideWasteRack.hxx` | 1,172 triangles; also downloaded `Core96SlideWaste.hxx`, a different larger waste component (48 triangles) |
| 60 mL trough | `ML_STAR/Reagent/rgt_cont_60ml_BC_A00.hxx` | 164 triangles; avoids substituting the differently sized PLR trough |

[MPE² sources](https://github.com/djross22/lmsf_hamilton/tree/S-Cell_STAR-2/LabWare/ML_STAR/MPE2),
[assembled MultiFlex sources](https://github.com/djross22/lmsf_hamilton/tree/S-Cell_STAR-2/LabWare/ML_STAR/MultiFlexCarrier),
[CORE sources](https://github.com/djross22/lmsf_hamilton/tree/S-Cell_STAR-2/LabWare/ML_STAR/CORE),
[96-head sources](https://github.com/djross22/lmsf_hamilton/tree/S-Cell_STAR-2/LabWare/ML_STAR/96COREHEAD),
[trough source](https://github.com/djross22/lmsf_hamilton/blob/S-Cell_STAR-2/LabWare/ML_STAR/Reagent/rgt_cont_60ml_BC_A00.hxx).

**Alignment needs inspection before conversion.** The three shaker/HHC assemblies have mesh
bounds starting at `(0, 0, 0)` and extending to X=154.5, Y=526.5 mm, whereas the carrier definitions
use a 157.5 × 497 mm footprint. Do not automatically stretch the entire assembly into the definition
box: protrusions and handles may explain the difference. MPE² source origins are also offset;
its unit spans approximately 424 × 158.23 × 185.67 mm and its base 443.95 × 497.08 × 8.3 mm.
Use the `.tml`/`.rck` model transforms and inspect placement against deck sites.
Drawing a complete carrier assembly requires avoiding duplicate base/module drawings.

Individual HHC and HHS parts plus manufacturer photos already exist at
`C:/Users/stefa/plr-viz3d-scratch/hamilton_library/tools/mfx_extracted/`:
`6601900-01.x` / `.jpg` (HHC) and `HHS_FlatDWP.x` / `.jpg` (HHS flat DWP).
See `../plr-viz3d-scratch/hamilton_library/MULTIFLEX_ASSEMBLY.md` and the checked-in
`venus_interop/multiflex/data/mfx_catalogue.json`. That catalogue has HHC and HHSF30DWP entries,
but no exact `Low`, `Low_base`, or `EZ_pic` id matches were found in this inspection.
Use the exact assembled carrier meshes to investigate those labels; do not assume an individual
module match from height alone.

## Consumables requiring authored geometry

### Fourtitude growth plate

The strongest visual reference is NIST's own
[`Growth plate.4ti-0255.png`](https://github.com/djross22/lmsf_hamilton/blob/S-Cell_STAR-2/LabWare/Culture%20Processing/Growth%20plate.4ti-0255.png),
downloaded beside `Fourtitude Growth Plate with Lid.rck`, `.lid`, the unlidded `.rck`, and
`96 well growth plate.ctr`. Viewed locally: the photo shows the clear plate, 8 × 12 square wells,
tapered lower well walls, flat central bottoms, perimeter frame, and corner details.
The [NIST-associated culture-method paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC9462466/)
identifies the 4titude 4ti-0255 as clear polystyrene, square wells, 1.1 mL maximum per well.
Together these give strong identification evidence; no exact CAD or dimensioned drawing was found.

Venus specifies **127 × 86 × 19.2 mm**, 9 mm pitch, 8 rows × 12 columns, container base 1.3 mm.
Use the saved container fields for the liquid geometry and the photo for the external shell.
Do not substitute a conventional round-well assay plate.

### Agilent single-cavity 290 mL reservoir

Strong product match: [Agilent 201250-100](https://www.agilent.com/store/en_US/Prod-201250-100/201250-100),
single cavity with **12-column pyramid floor geometry**, not the 96-pyramid 300 mL reservoir.
The product page includes an image. The
[manufacturer datasheet, 5994-4423EN](https://www.agilent.com/cs/library/datasheets/public/ds-cell-analysis-5994-4423en-agilent.pdf)
gives 127.76 × 85.47 mm footprint, 44.04 mm height and 39.22 mm well depth.
The matching downloaded Venus `.rck` has 127 × 86 × 44.04 mm and its `.ctr` depth is 39.22 mm.
Record the footprint difference if choosing physical manufacturer dimensions; don't silently
change the imported resource dimensions. Its 96 Venus positions are pipetting locations inside
one cavity, not 96 physical wells.

### Agilent six-well reservoir

**Identity resolved from the rack Description field:** Agilent **204284-100**, the irradiated
variant of [201284-100](https://www.agilent.com/store/en_US/Prod-201284-100/201284-100):
six columns, 47 mL per column, 24 pyramid floor features, 44 mm high.
See the [manufacturer datasheet, 5994-4428EN](https://www.agilent.com/cs/library/datasheets/public/ds-cell-analysis-5994-4428en-agilent.pdf).
NIST includes a large
[`Agilent 6 well reservoir.png`](https://github.com/djross22/lmsf_hamilton/blob/S-Cell_STAR-2/LabWare/Agilent/Agilent%206%20well%20reservoir.png),
downloaded along with the definitions and bitmap. The local image viewer rejected this PNG;
its PNG header and 3725 × 2685 dimensions were checked, but the image was not visually assessed.
The manufacturer page provides another image reference.

Venus specifies 127 × 86 × 44 mm, 6 columns at 18 mm pitch and 8 rows at 9 mm pitch.
Those 48 positions do not mean 48 separate wells.

### The three lids

All three downloaded `.lid` definitions (Fourtitude and both Agilent reservoirs) specify
**127 × 86 × 9.15 mm**, `CoverThickness=2.5`. These are useful constraints, but identical
definition dimensions do not establish identical physical lids or their manufacturer.
**Identity resolved for the single-cavity lid:** its Description explicitly names Agilent
**202497-100**, a clear polystyrene universal lid, also confirmed by
[Agilent's lid listing](https://www.agilent.com/en/product/microplates/standard-custom-microplates/microplate-lids-seals-740874).
The six-column lid says "Universal lid for Agilent 6 column plate" and the growth lid says
"Universal lids used on growth plates"; their exact SKUs remain unconfirmed. No underside drawing
or original lid mesh was established. Separate approximate lid assets are used, not a factory alias.
[Azenta's microplate lid range](https://www.azenta.com/products/microplate-lid) is a visual lead
(universal and condensation-ring variants), not an established match. Its full page returned 403.
The definitions should govern current Venus placement; physical lid seating remains unverified
as already recorded in CONVENTIONS §11.

### CO-RE II tip supports (HT, ST, 50 µL)

Downloaded the full small
[`TipSupport CO-RE II` folder](https://github.com/djross22/lmsf_hamilton/tree/S-Cell_STAR-2/LabWare/TipSupport%20CO-RE%20II):
`.rck`, `.ctr`, and volume-specific `.bmp` references, but no 3D model is listed there.
Their Description fields all name **6608647-01**. The referenced `Core96_TipSupport.png` is
present in the Venus install at `Labware/ML_STAR/96COREHEAD/` and was visually inspected: a dark
perforated rectangular support with a lower peripheral skirt. The small volume-specific bitmaps
are UI labels, not useful mechanical views. The target filtered racks have these Venus dimensions:

| Variant | Definition box, mm | Container base, mm |
|---|---|---|
| HT | 122.4 × 82.6 × 16.8 | -68.7 |
| ST | 122.4 × 82.6 × 23.8 | -35.2 |
| 50 µL | 122.4 × 82.6 × 23.8 | -25.7 |

Each has 12 × 8 positions on 9 mm pitch. Negative container bases are definition coordinates,
not evidence for negative physical shell thickness. The definition box is not a mechanical drawing.
[Hamilton's CO-RE II technical announcement](https://assets-robotics.hamiltoncompany.com/File-Uploads/CO-RE-II-Announcement.pdf)
provides tip/interface illustrations, but does not establish the support body dimensions.
The [PacBio Hamilton NGS STAR guide](https://www.pacb.com/wp-content/uploads/Guide-overview-Automated-PureTarget-kit-96-for-the-Hamilton-NGS-STAR-MOA-system.pdf)
is a further application/layout reference; exact support CAD and detailed side views remain missing.

## Suggested generation order

**Waste and teaching conversion completed:** `tools/build_groq_viewer_models.py` now also
converts `WasteBlock.hxx`, `Verification.hxx`, `TeachingNeedle5ml.hxx`,
`TeachingNeedleBlock.hxx`, and `core96SlideWasteRack.hxx` from the downloaded references.
All five are attached by their exact definition filename. Original mesh extents and definition
offsets are retained, including negative teaching Z offsets and the waste block's overhang.
Each conversion records hashes and a Delta ledger; registration against Venus remains unverified.
The full deck preview was inspected and the viewer/consumable tests pass (21 tests).

**Consumable generation completed:** `tools/build_groq_consumables.py` now emits nine approximate
meshes (growth plate, both reservoirs, three separately named lids, three support definitions)
and converts the original 60 mL trough. All are attached by definition filename in `viewer_models`.
Each has a `.geometry.json` provenance file and Delta ledger. The generated models retain Venus
footprints and heights. Rims, wall thicknesses, lower taper dimensions, colors, lid roof thickness
and support shell details are explicit visual approximations; tip-support variants sharing a part
number are not claimed to be physically different hardware. Their protocol definitions are untouched.
The `.ctr` files remain authoritative for liquid calculations, not the cosmetic tapered mesh.

1. Convert the exact carrier assemblies, trough and CORE accessory meshes, checking their authored
   transforms and avoiding duplicate module rendering.
2. Inspect the downloaded MPE² geometry against the existing animated GLB before choosing one.
3. Author the growth plate and two reservoirs from their definitions and identified visual references.
4. Resolve lid identity and support body details before claiming faithful geometry for those parts.
