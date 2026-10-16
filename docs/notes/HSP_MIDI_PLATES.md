# Bio-Rad Hard-Shell (HSP) and Abgene MIDI plates: preliminary notes (2026-09-28)

These are raw findings from Hamilton NGS STAR labware. Nothing is in PLR yet. Neither plate exists in
`plr-viz3d` or `pylabrobot`. Checked: `resources/biorad/plates.py` has only the 384-well plate, and
`thermo_fisher/plates.py` has no MIDI plate.

## Sources
All paths are under `C:\Users\stefa\NGS-Protocols\assets\` and mirrored in `C:\Program Files (x86)\HAMILTON\NGSStar\`:
- `NGSStar/KitProvider/KitName/Labware/`: `BioRadHardshell.rck`, `bioradhardshell.ctr` (Version 1.0),
  `ABGENE_MIDI.rck`, `abgene_midi.ctr`, `BioRad PCR Full Skirt White.x`, `0.8 mL Abgene MIDI Plate.x`.
- `.../NGS STAR (MOA) ODTC Carrier/2021-04-23_Updated Biorad Plate Definition/`: HSP **Version 1.1**
  (`Image3D` = HSP9601.bmp, so part **HSP9601**, white shell). Use v1.1; it corrects v1.0.
- Every copy of the `.x` meshes is byte-identical: Bio-Rad md5 `d2f14873…`, MIDI md5 `b2c89089…`.
  The v1.1 update did not change the mesh.
- MIDI carrier: `MFX_CAR_2MTP HPTab_MIDI HPTab_2DWP HPTab.tml` (+ `.x`, 10x/KAPA/PacBio/QIAseq).
  This is a binary tml with header `03 00 01 00…`. `venus_files.py` can't parse it yet; the values below come from a string dump.

## Bio-Rad Hard-Shell 96, HSP9601 (Venus v1.1)
- Rack: 127 × 86 × 15.5 (Venus nominal footprint), 8 × 12 at 9 mm, BndryX 14, BndryY 11.5
  → A1 centre (14, 74.5) in the 127 × 86 frame. On a true 127.76 × 85.48 plate, re-centred, that is
  (14.38, 74.24), which is 14.38 × 11.24 from the top-left corner (the usual ANSI numbers). This is inferred; check it against the Bio-Rad drawing.
- Container: `Cntr.1.base` 1 (well bottom 1 mm above the plate bottom). Depth 14.81, one segment,
  Shape 3 (conical), top Ø 5.46, bottom Ø 2.64 (1.DY). Venus volume `h*13.4030` µL/mm is linear:
  a crude area-average. So well top = 15.81.
  v1.0 values were Ø 5.4 / 2.0, depth 14.5, `h*11.5087`, LSHt 17, Clearance 20; v1.1 has LSHt 16, Clearance 17.
- Mesh: 3 meshes, 24,130 vertices. Bounds X ±63.88, Y (up) −0.055…16.367, Z ±42.74, i.e.
  **127.76 × 85.48 × 16.42**, centred on the footprint, base at 0. Shape quality not yet inspected visually.
- Still needed: the Bio-Rad drawing for height (catalogue ~16.1?), the skirt height, the flange, the true
  bottom geometry (V/round), and nominal/working volume (200 µL nominal?). None of these is confirmed here.

## Abgene 0.8 mL MIDI plate (Thermo AB-0859?)
- The part number is not in the files; "AB-0859" is a guess to verify. The rack Description reads "AbGene MIDI storage plate".
- Rack: 127 × 86 × 31, 8 × 12 at 9 mm, BndryX 14, BndryY 11.5, `Cntr.1.base` **3**.
- Container: 2 segments, depth 27, so the well top is at 30.
  - Lower segment 0–3.8 mm: Shape 3 (conical), Ø 6.8 → 2.4, `h*17.8861`.
  - Upper segment 3.8–27 mm: Shape 0 (cylinder), Ø 6.8 (`h*36.3168` = π·3.4², exact), 1.DX 6.9 / 1.DY 4.7
    unexplained.
  - Total by the Venus equations: ≈ 36.317·23.2 + 17.886·3.8 ≈ **910 µL** brim (nominal 0.8 mL).
- Mesh: 5 meshes, 78,600 vertices (10.5 MB). Bounds **127.76 × 85.48**, Y 0.13…29.985. Top at 30.0
  matches base 3 + depth 27 exactly. It is a detailed mesh, not a box.

## MIDI on the MOA MFX carrier (MFX_CAR_2MTP HPTab_MIDI HPTab_2DWP HPTab)
The carrier is 135 × 497 × 130, i.e. the L5 baseplate. Sites are listed front to back, all at X 4, 127 × 86:

| Site Id | Y | Z | Role (from the name) |
|---|---|---|---|
| 5 | 8.5 | 82.4 | DWP HPTab |
| 4 | 104.5 | 82.4 | DWP HPTab |
| 3 | 200.5 | 94.8 | MIDI HPTab |
| 2 | 296.5 | 109.7 | MTP HPTab |
| 1 | 392.5 | 109.7 | MTP HPTab |

Sites 6–10 are 1 × 1 markers at Y −62, Z 112, probably for the gripper or the lid. The site IDs are bare numbers, not
`<posn>_<IdName>`, so this carrier does not come from the MFX Assistant catalogue. The pitch of 96 matches the L5 rule.
"HPTab" is probably a plate holder with a tab, raised to a common working height. Not verified.

## For the PLR import
- Probable factory names: `BioRad_96_wellplate_200uL_Vb` (check the volume and bottom type), and `thermo_AB_96_wellplate_800uL_Vb_MIDI`
  or similar (follow the PLR naming conventions, `<brand>_<n>_wellplate_<vol>uL_<bottom>`).
- Use the Venus data for well geometry and heights. Use the manufacturer drawings for the outer dimensions,
  the A1 offset and the skirt. Save the PDFs to `references/`, per the 96channelhead practice.
- Compute the volume functions from the frustum/cylinder geometry, not the linear Venus equations.
- Meshes: both are usable as a first pass through `x_to_glb.py` (licence caveat as for the other Hamilton assets). A
  better model can come later, as the user said.

## Shipped (2026-09-28, commit f99a003b2 on viz3d-motion, not pushed)
- `biorad_96_wellplate_200uL_Vb`: Bio-Rad bulletin 5496 (saved in `references/`, page 5 rendered):
  127.76 x 85.48 x 16.06, A1 14.38 / 11.24, well 14.81 from the rim to the outer tip, Ø 5.46 → 2.64, 200 µL.
  The rim is 0.58 above the deck. The cavity floor 0.91 above the tip comes from the mesh, so the cavity is 13.90 deep and holds 186 µL.
  The mesh differs from the drawing: A1 at 14.03 / 11.14, and 0.31 taller (16.37). It is registered on the wells (+0.35 X, −0.1 Y).
- `thermo_TS_abgene_96_wellplate_800uL_Vb`: Thermo has no drawing, so this uses the mesh, which Venus corroborates.
  Height 29.99; tip 2.99, floor 3.19; a cone Ø 1.26 → 7.32 over 3.79, then a Ø 7.32 cylinder. Brim ≈ 1032 µL.
  The mesh sits within 0.02 of the ANSI grid, so it is not moved. Venus's Ø 6.8 disagrees with the mesh's 7.32.
- Builder: `build_plate_glbs.py`. It keeps the source MeshNormals and sets materials:
  - HSP: white shell (opaque) and clear PP wells (α 0.35).
  - MIDI: opaque natural PP. A translucent version rendered as glass rods.
- Renders: `plr-viz3d-scratch/plate_render/`. Top views in SwiftShader wash out white plastics (a lighting issue, not these models).
- Licence: the meshes are Hamilton-derived. Ask before pushing them to the fork or upstream.
