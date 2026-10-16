# Discrepancies, contradictions and vague points in the reference data (2026-09-28)

**Impact** is judged by what PLR uses to build pipetting commands and raise errors:
- the well X/Y centre;
- the well floor height (cavity bottom);
- the plate and container top, which sets traverse heights and where liquid-level detection starts;
- the volume ↔ height function, for liquid following without detection;
- max_volume, for overflow errors.

Mesh bounds and colours affect only what is drawn. Differences under 0.5 mm are caliper error.

## Operationally material
| # | Point | Sources | Impact | Settle by |
|---|---|---|---|---|
| 1 | CPAC plate seat height (above carrier base) | Catalogue and Roche carrier 102.6; PacBio 91.6; 10x 90.5; Roche layout plates at 91.5–92.8; PLR `inheco_cpac_ultraflat` seat 77 + 18 bracket ≈ 95 | 4–11 mm in Z: no reach or a crash | Caliper: carrier plate to the skirt rest |
| 2 | CPAC plate Y | Site centred; Roche/KitName layouts place plates 4.05 mm forward (Avenio 3.7) | 4 mm in Y: the tip hits the rim of a 96-well plate | Same measurement |
| 3 | What sits on the CPAC | Layouts and `t_trpHSP_OnCPAC` put HSP/MIDI plates on it; `CPAC_Adapter.png` shows a 24-hole tube block; catalogue has "CPAC Flat" and "CPAC 2 mL" separately | Everything on it | Protocol documentation or an operator |
| 15 | MIDI well Ø | Mesh 7.32; Hamilton `abgene_midi.ctr` 6.8 | Centres unaffected; about 2 mm liquid height at 500 µL from volume | Caliper on an AB-0859 well |

## Real but within tolerance, or already matching Hamilton's behaviour
| # | Point | Sources | Why it's fine |
|---|---|---|---|
| 6 | Flat nest 2 vs 3 mm | Flat DWP 83.7/83.0; flat MTP 112.7/112.7 | Each variant uses its own catalogue value |
| 9 | Pedestal in shaped nests (Nunc, Sarstedt, PCR96) | No source gives one | pedestal 0 means catalogue site Z, the same as Venus |
| 18 | HSP cavity floor | Bio-Rad gives the depth to the outer tip only; the mesh gives 0.91 above the tip | ≈0.3 mm; 186 vs 200 µL to the rim |
| 16 | MIDI dimensions | Thermo gives no drawing; mesh and Venus heights agree | Corroborated by two sources |
| 11 | Shaker carrier pitch | Old PLR 121 (two positions interpolated); Hamilton 120 | Fixed: `MFX_CAR_L4_SHAKER` now uses Hamilton's positions (ea48db37f) |

## No operational effect (display, naming, bookkeeping)
| # | Point | Sources | Note |
|---|---|---|---|
| 4 | CPAC footprint | Hamilton model 128 × 88 × 84.6 (164 triangles); PLR 113 × 89 × 129; Inheco says the Ultraflat is 80 tall | The seat (#1) is what matters |
| 5 | "1.5 / 2 / 3 mm" in HHS nest names | Only the catalogue names them | Their numbers are already per variant |
| 7 | Flat-MTP riser | Hamilton's model: 29 mm block; site = DWP + 29 exactly; no part number | Plate height unchanged with or without the riser |
| 8 | HHS models reach Z −10 | Catalogue Offset3DZ −10 appears only on VWR DWP96, flip tube and HHC | Placement checked against assembled carriers |
| 10 | `NotValidForCarrier` | HHS (1) and CPAC (2) both on carrier 3 | Unused |
| 12 | 7T rear tab 29.5 mm behind the carrier | Hamilton's model; the tube carrier's overhang is at the front | Kept as authored |
| 13 | Avenio hand-placed labware up to 1.25 mm off its template | Avenio `.lay` | Factories use the templates |
| 14 | PLT_CAR_2TIP_2PCR_MTP PCR96 site 0.5 in Z | Catalogue vs Venus | Not implemented |
| 17 | HSP mesh vs Bio-Rad | Mesh A1 X 14.03 and height 16.37; Bio-Rad 14.38 and 16.06 | Factory uses Bio-Rad; mesh aligned on the wells |
| 19 | HSP volume equation | Venus `h × 13.40` (linear) vs cone geometry | PLR uses the cone geometry |
| — | MIDI max volume | Brim ≈ 1030 µL; Thermo nominal 800 | PLR raises overflow only above ≈1030 (behaviour, not targeting) |

## Update (CPAC research, see CPAC_RESEARCH.md)
- **#1:** Inheco's drawing gives 80 from the feet to the thermal adapter top, so the adapter top is at 98 on the bracket. Every protocol value sits 5–7.5 below it: plates sink into plate-specific adapters (MIDI 3200376, PCR 3200203). Catalogue 102.6 = Hamilton's model top, not a seat.
- **#2:** The 4 mm Y shift appears only in Roche/KitName hand-placed labware. The edited templates and Hamilton's models are centred.
- **#4:** PLR's `inheco_cpac_ultraflat` sizes are the drawing's plan dimensions: 129 is the length, 77 the contact width, neither a height.

## Update (STAR vs STARlet, 2026-09-28; sources `Config\ML_Starlet.dck`, `Config\ML_STAR2.dck`, the fork's recordings and `star_decks.py`)
- **STAR = STARlet + 24 tracks.** Hamilton's decks differ only in `Dim.Dx` (1360 → 1900), tray count (30 → 54), the added track sites, and the right-hand waste block (+540). PLR's deck factories and derived recordings match: right-end items +540.0; track 1 (X 100), arm left limits (x_range 95.0, workspace −323.2) and `trash_core96` unchanged.
- **Waste block 1318 vs 1315: not a discrepancy.** Both are in Hamilton's deck: `WasteBlock` site 1318.0 (PLR `core_grippers`) and rail sites r8/r12/r16 at 1315 (PLR `waste_block`).
- **96 CO-RE waste: open, and it matters (172.8 mm).** The STAR's `96COREExtWaste` site = the STARlet's `96COREWaste` (−390.70, 11.95; STARlet also has `96COREWash`). The NGS layouts put `core96externalwaste.rck` (122.4 x 82.6, same as PLR's) at (−231.0, 117.25, Z 185). PLR's `trash_core96` is at (−58.2, 106.0, 216.4). Same rack dims, so probably a different mounting; find PLR's source before changing anything.
