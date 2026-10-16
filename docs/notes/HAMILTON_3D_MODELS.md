# Hamilton 3D model reference

As of 2026-09-27. Where Hamilton's own 3D models for STAR labware, carriers and Multiflex (MFX) modules live, what format they are in, how to turn them into GLB for the PLR viewer, and what has been converted so far. Companion files in this folder: `REVIEW.md` (the whole Hamilton library), `MULTIFLEX_ASSEMBLY.md` (how MFX carriers are assembled, with the catalogue rules).

**Licence.** No licence is stated on any of these files. They are Hamilton's. Converting them for our own use and viewing is fine; ask Hamilton before committing or shipping any of them (or GLBs made from them) in PLR.

## Where the models are

| Source | Path or link | 3D files | What they cover |
| --- | --- | --- | --- |
| Multiflex Carrier Assistant v4.10 | Hamilton library, *Hamilton GUIs and Tools* / `MultiflexCarrierAssistantv4.10.zip`; extracted to `tools/mfx_extracted/` | 101 `.x` (text), 1 `.hxx` | All 5 MFX baseplates and ~90 modules: nests, tip modules, HHS nests, CPAC, heating/cooling, shakers (Teleshake, Variomag), tilt, turntable, stacker, lid park, brackets. Also `MultiMFX.INI` (the assembly catalogue) and 84 module photos (`.jpg`) |
| Local Venus install | `C:\Program Files (x86)\HAMILTON\LabWare` | 29 `.hxx`, 3 `.x` | Plate carriers (L4ST x4, L5AC, L5MD, P3AC, P3MD, P3LI), tip carriers (288, 384, 480, 384BC, 480BC), waste blocks, 96/384 slide waste, teaching needle, verification block |
| Hamilton shared library, *Hamilton Labware* | https://download.hamiltonsupport.com/wl/?id=VQY0XAzTfcT7KY29A1YJtZVFwZ7GMOO2 ; all 42 archives downloaded to `labware/` (`labware_inventory.json` lists contents) | 55 (`.x` text, `.x` binary, `.x` compressed `xof 0303tzip`, `.hxx`) | Tip boxes and lids (10–12 MB each, compressed), tip-box carriers, wide-bore tip racks, ODTC and MFX_CAR_ODTC_MTP, PLT_CAR_L5_DWP, reagent carriers and troughs, magnet stands, centrifuges, MPE2, Plate Loc sealer, CO-RE suction tool (incl. `smp_car_32_a00.hxx`) |
| NGS protocol labware (local) | `C:\Users\stefa\NGS-Protocols\assets\NGSStarMOA\...` | 35 `.hxx`, 55 `.x` | Assembled MFX carriers composed in Venus (e.g. `MFX_CAR_2HHS30NuncDWP_2CPACflat`), SMP_CAR_24/32, RGT carriers, tip carriers, some plates and lids |

Download any file from the shared library with `curl -L "https://download.hamiltonsupport.com/wl/?id=<share>&path=<url-encoded folder/file>&download=1"` (`fetch_labware.py` does the labware folder).

## Formats

| Format | Header | How to read |
| --- | --- | --- |
| DirectX text `.x` | `xof 0302txt` / `xof 0303txt` | `x_to_glb.py` (this folder) |
| DirectX binary `.x` | `xof 0303bin` | Not handled yet (wide-bore tip racks, Nimbus pedestals) |
| DirectX compressed `.x` | `xof 0303tzip` / `bzip` | Not handled yet (Ham_MLTipBox_*, RCK_TipBox*): MSZIP-compressed text, needs a decompress step first |
| Hamilton `.hxx` | `Hamilton3dData`, then a gzip stream holding a text `.x` (and sometimes textures) | Decompress from the gzip magic (`\x1f\x8b\x08`), then treat as text `.x`; `C:\Users\stefa\96channelhead\convert_tube_carrier.py` shows it |

Hamilton says the 3D data is cosmetic: it does not affect the labware definition ([labautomation.io](https://labautomation.io/t/labware-3d-data/2520)). The labware editor takes `.x` and `.hxx`; Blender 2.8 and earlier can export `.x`.

## Converting: `x_to_glb.py`

```
python x_to_glb.py <out_dir> <file.x> [<file.x> ...]     # system Python: it needs trimesh (the plr-viz3d venv does not have it)
```

What it does, and the conventions it assumes:

- Parses the data objects (templates skipped, `//` and `#` comments stripped), walks the `Frame` hierarchy and applies each `FrameTransformMatrix` (row vectors, D3D order: `world = local @ parent`).
- Reads each `Mesh`'s vertices and faces (polygons fanned into triangles) and its `MeshMaterialList`, including materials defined inline or referenced by name.
- Groups triangles by material colour: one glTF material per distinct `faceColor` + `power`; roughness = sqrt(2 / (power + 2)), metallic 0, double-sided. **Colour is kept exactly as authored.** None of the files converted so far uses a texture (`TextureFilename` appears only as a template declaration).
- Swaps Y-up to Z-up (`(x, y, z) -> (x, z, y)`) and reverses the winding, since the swap mirrors.
- Writes coordinates as-is: the MFX files are in **millimetres**, so the GLBs are in mm (the PLR viewer's `reference_glb` convention is metres, Z-up: scale by 0.001 or declare units when loading). trimesh does not apply glTF's Y-up rotation.
- Writes `report.json` beside the GLBs: triangles, material count, bounds.

**Model origins (MFX modules):** centred in X and Y; Z = 0 at the module's mounting face. HHS models reach down to Z = -10. The catalogue gives `Offset3DZ = -10` only for the VWR DWP96, flip-tube and HHC entries; the HHS entries (41–49) give none, so the -10 is not explained by the catalogue. Placement checked against the Venus-assembled 7T `.x`: HHS centres at X 77.25 (+1.5 carrier 3DxOffset), Y 418.05/298.05/178.05/58.05, feet at Z 8 (see `MULTIFLEX_ASSEMBLY.md`).

## Converted so far

Output in `glb_mfx/`, served by the viewer below.

| Model | Source file | Triangles | Colours | Size X x Y x Z (mm) | Lowest Z (mm) | Assessment |
| --- | --- | --- | --- | --- | --- | --- |
| HHS flat MTP (199033/199034) | `HHS_FlatMTP.x` | 728 | 4 | 148 x 105 x 114.9 | -10 | Whole HHS body + nest; good |
| HHS flat DWP (199033/199034) | `HHS_FlatDWP.x` | 624 | 3 | 147.1 x 104.7 x 85.9 | -10 | Good |
| HHS Nunc DWP (199037/38/39) | `HHS_DWP_Nunc.x` | 5,920 | 4 | 147.1 x 104.7 x 102.4 | -10 | Detailed; matches Hamilton's photo (silver body, dark 96-pin nest, clamps) |
| HHS 1.5 mm Sarstedt (199027) | `HHS_Sarstedt.x` | 9,736 | 3 | 147.1 x 104.7 x 94.3 | -10 | Detailed |
| HHS PCR96 ABI (188298) | `HHSPCR96ABI.x` | 12,616 | 3 | 147.1 x 104.7 x 85.9 | -10 | Detailed |
| CPAC Flat (58246/47/48-01) | `cpac.x` | 164 | 1 | 128 x 88 x 84.6 | 0 | Crude stand-in, one white material; the real part (photo) has a silver bracket frame, black insulation and a white block |
| CPAC 2 mL | `cpac2mL.x` | 164 | 1 | 128 x 88 x 84.6 | 0 | Same geometry as CPAC Flat |
| CPAC tube module | `CPACTubeModule.x` | 2,008 | 2 | 134.5 x 103.7 x 41.1 | 0 | The 2 mL tube rack used with CPAC 2 mL |
| CPAC bracket (kit 188362) | `BracketShakerBaseCPAC.x` | 44 | 1 | 134 x 100 x 10 | -10 | A plate |

Earlier, separately (the other agent, `C:\Users\stefa\96channelhead`): `SMP_CAR_32_A00.glb` (tube carrier 173410, from `.hxx`, installed in PLR's `resources/hamilton/resource_model/`, uncommitted) and `head96.glb` (a generated 96-head stand-in, not a Hamilton file; it needs normals).

## Viewer

`viewer/` is a static three.js page (the three.js build vendored in `plr-viz3d`): model list, orbit view on a 10 mm grid, and Hamilton's photo and catalogue facts beside each model.

```
cd C:\Users\stefa\plr-viz3d-scratch\hamilton_library\viewer
python -m http.server 8097 --bind 127.0.0.1      # then open http://127.0.0.1:8097/
```

To add models: convert into `glb_mfx/`, copy the GLBs and `report.json` into `viewer/glb/`, the photos (`<stem>.jpg` from `tools/mfx_extracted/`) into `viewer/photos/`, and add a `CATALOGUE` entry in `viewer/index.html` for the name and part number.

## Next steps

1. Convert the remaining MFX files the same way (baseplates, nests, heating/cooling, shakers, HHC 6601900-01), and add binary and compressed `.x` support for the tip boxes if they are wanted.
2. Test the 3D placement rule: convert a Venus-assembled carrier (`MFX_CAR_2HHS30NuncDWP_2CPACflat.x` in the NGS library) and compare with the modules placed by `Origin3D` + `Offset3D`.
3. For viewer use in PLR: a `reference_glb` per resource model name, in metres, Z-up; kept out of the repo until redistribution is settled.
