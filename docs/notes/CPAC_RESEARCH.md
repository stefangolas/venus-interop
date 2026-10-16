# CPAC on the MFX shaker carrier: research (2026-09-28)

Heights are mm above the carrier's base. The carrier plate top is at 8; Hamilton's CPAC bracket spans 8 to 18.

## Sources searched
| Source | Result |
|---|---|
| labautomation.io Hamilton share: main (304 entries, 13 folders) and user uploads (`crawl_share.py`, `share_*.json`) | Nothing on the CPAC or Inheco. Only the HHC and the ODTC. |
| labautomation.io forum (search API: cpac, cpac ultraflat, cpac adapter) | Thread 2979: photo of a MIDI on a CPAC (`references/forum2979_midi_on_cpac.jpg`). Thread 6563: Hamilton support recommends teaching Z per position. Nothing dimensional. |
| Inheco CPAC brochure (live link redirects to the homepage; Wayback copy 2022-01-16: `references/inheco_cpac_brochure.pdf`, page 4 rendered `cpac_ultraflat_drawing.png`) | **Dimensioned drawing of the CPAC Ultraflat 7000166/7000190/7000165.** See below. |
| Inheco "Disposable Details & Corresponding Thermal Adapter Plates", May 2019 (Wayback 2020-09-26: `references/inheco_adapter_plates.pdf`, text in `.txt`) | Adapter part numbers per plate; no heights |
| Inheco CPAC Microplate manual (Wayback: `references/inheco_cpac_microplate_manual.pdf`) | Covers the Microplate variant, not the Ultraflat |
| Local Venus install and NGS protocol assets | Venus templates and layouts (below), and the loading picture `CPAC_Adapter.png` (a 24-hole tube block). `NGSStarProcesses.smt` handles labware `HSP_CPAC` and "2 tubes on the CPAC" |
| Hamilton assembled carriers (`match_assembly.py`) | CPAC and bracket models are centred in the slot (X 77.25 in the model frame, Y 58.05, Z 18). The PacBio carrier uses the same `.x` as Roche with a different `.tml` |
| PLR git history (`inheco/cpac.py`, PR #684; issues #493, #494; PR #482) | No record of how its numbers were measured |

## Inheco drawing, CPAC Ultraflat
- **Height 80** from the feet to the top of the thermal adapter (the plate contact).
- Thermal adapter contact surface 113 × 77, R5 corners.
- Adapter width 89; body 128 long, 129 overall; base 86 wide; feet 62 and 100 apart; M4 fixation threads.
- PLR's `inheco_cpac_ultraflat` (113 × 89 × 129, child z 77) matches these plan dimensions. Its size_z of 129 is the unit's **length**, and 77 is the contact surface's **width**. Neither is a height.

## Inheco adapters for the plates in these protocols
- Abgene AB-0765/AB-0859 (MIDI): **3200376** (static unit), 227 g.
- Low-profile 96 PCR, 150–200 µL (HSP class): universal **3200203**; 3200526 gives more contact.
- Flat-bottom plates: universal **7900016**.
- No heights are published in retrievable documents.

## Plate seat on the CPAC (plate bottom above the carrier's base)
| Source | Value | Relative to the adapter top (18 + 80 = 98) |
|---|---|---|
| Catalogue and Roche template | 102.6 (= Hamilton's crude model top: 84.6 on the bracket; Inheco's unit is 80) | +4.6: not a plate seat |
| Roche/KitName layout, HSP (Bio-Rad hard-shell) | 92.7–92.8 | −5.2 |
| KitName layout, MIDI | 91.5 | −6.5 |
| PacBio template (edited) | 91.6 | −6.4 |
| 10x template (edited) | 90.5 | −7.5 |
| PLR `inheco_cpac_ultraflat` (z 77, "measured"; other numbers misread) | ≈ 95 | −3 |

Reading: plates sit 5–7.5 mm below the adapter top. That fits their wells sinking into a shaped adapter, with the skirt going down around it, and the adapter depends on the plate. The protocol values are per-instrument taught positions (Hamilton support's advice in 6563), which explains the ±1 mm spread.

## Front-to-back position
- The Roche and KitName layouts place plates 4.05 mm forward of the site (Avenio 3.7).
- The PacBio and 10x edited templates keep Y centred, and Hamilton's models centre the CPAC and bracket.
- Most likely a teach/hand-placement offset in one protocol family, not geometry.

## Proposed PLR model
bracket (10, Hamilton `BracketShakerBaseCPAC`) → CPAC Ultraflat (Inheco: 80 to the adapter top) → per-adapter plate seat:
- MIDI adapter 3200376: plate bottom 73.5 above the CPAC foot (Venus 91.5 − 18).
- PCR adapter 3200203: 74.8 (Venus 92.8 − 18).
- Tube adapter (CPAC 2 mL, `CPAC_2mLTubes.rck`): from its rack definition.

Still open: the adapter heights themselves (Inheco), and whether the 4 mm Y is physical. One caliper measurement per adapter would settle both.

## Implemented (commits aacf54867, 57288bc97)
- `inheco_cpac_ultraflat(..., adapter=)`: 129 × 89 × 80; plate centred; seat flat 77 / abgene_midi 73.5 / pcr_low_profile 74.8.
- `hamilton_mfx_cpac_bracket` (134 × 100 × 10, with model).
- Tests reproduce the Roche/KitName plate heights (192.8, 191.5 on the deck) and the template A1 (1186.75, 152.55).

## Still ambiguous: how the height splits between bracket and CPAC
- **A (implemented):** 10 mm bracket (Hamilton's model), and plates sit 5–6.5 below the CPAC's 80 top.
- **B:** plates rest on the CPAC's top. Inheco's 129 × 89 top rim is larger than a plate, so a plate can't sink below it. Under B, the CPAC's feet stand ~11.5–12.8 above the carrier base, i.e. a ~4–5 mm bracket, with Hamilton's 10 mm bracket model being schematic like its 84.6 mm CPAC.
- Both give identical absolute plate positions, because the seats are fitted to Venus. Only the drawn proportions differ, and in A the plate visually overlaps the CPAC box.
- Settle by measuring the bracket thickness, or the CPAC's feet height above the carrier plate.
