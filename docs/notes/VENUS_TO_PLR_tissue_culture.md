# The tissue-culture STARlet deck: Venus's representation and PLR's

`tc_deck.py` builds the Chory lab's tissue-culture deck
(`Robot_Code/tissue_culture/test_environment/scripts/deck.lay`, driven through pyhamilton by
`sample.py`, `dilute.py` and friends, positions named in `labware.py`) by hand in PyLabRobot.
Everything here is scratch: the three 3D-printed pieces are lab hardware and are not committed.

| File | What |
|---|---|
| `tc_deck.py` | the deck (`build_tc_deck()` -> `TCDeck`, names as `labware.py`) |
| `build_models.py` | STLs (`C:\Users\stefa\tc_platform_models`) -> `models/*.glb` in each resource's frame, slimmed (60k / 16k / 12k triangles) |
| `compare_to_lay.py` | PLR vs layout, per position the methods use |
| `reach_survey.py` | from which sides the iSWAP reaches each plate position |
| `probe_moves.py` | headless: channels, 96-head and iSWAP through the methods' moves, collision gate on |
| `render_tc.py` | headless screenshots into `shots/` |
| `tc_view.py` | the viewer (`--demo`: a pass through dilute.py's moves) |

## 1. What stands where

STARlet (`ML_Starlet.dck`, 30 tracks), left side panel off.

| Venus | PLR |
|---|---|
| TIP_CAR_480BC_A00 at track 4: dirty (HTF), high_volume (HTF), ethanol (HTF), std_1 (STF), std_0 (STF), back to front | `TIP_CAR_480BC_A00`; `hamilton_96_tiprack_1000uL_filter` / `_300uL_filter` |
| PLT_CAR_L5AC_A00 at track 11: reagent_plate, ethanol_plate, sample_park, plate_384_park, culture_plate | same carrier; `HAM_DW_12_ml` is a 1.2 mL **deep-well plate** (P/N 235655), not a trough: `hamilton_96_wellplate_1200uL_Ub` built from the .rck/.ctr |
| PLT_CAR_L5AC_A00 at track 18: sample_plate_4..0 | sample_plate_0..3 (Greiner 384 + lid); site 1 left empty (`labware.py` has no sample_plate_4) |
| PLT_CAR_L5AC_A00 at track 25: culture_plate_park (site 1), reagent_trough (site 5) | the lid park (below) and the printed trough |
| waste, bleach, water_0..3 (Nunc stand-ins left of track 1) | one `WashStation` (the printed 2 x 4 reservoir block), 8 `Trough`s |
| single_channel_bleach (track 10 gap), ethanol_waste (track 17 gap) | `SingleChannelBath` x 2 (the printed bath) |
| reagent_trough (HAM_DW_12_ml stand-in) | `ReagentTrough` (the printed 4-channel trough) |
| transfer_station / _384 / _flipped | one tray, `transfer_station` (the three are one footprint within 0.6 mm; flipped = the plate turned 180) |
| reader_tray_384 (angle 180) | tray `reader_tray_384`, turned 180 |
| microscope_96 (angle 90) | tray `microscope_96`, turned 90 |
| ethanol (Nunc stand-in at -232.6, 119.8, Z 135) | nothing: the lab's ethanol washer is out of the process; `ETHANOL_BLOWOUT_A1` keeps the spot the stdvol rinse still blows out over |
| core96slidewaste_0001 moved to A1 (-232.1, 110.3) | `trash_core96` there (its deck site is under the wash station) |

Left out as Venus-only: `culture_plate_midpoint`, `culture_plate_flipped_1pos/_2pos` (the one
culture plate on carrier 18 / 11 site 5, turned 180 for flip_plate.py: PLR turns the plate),
`single_channel_waste` (a stand-in on the culture plate's own site, unused), `dirty_tips_std_vol`
(same site as `dirty_tips_high_vol`: a site holds one rack; HTF loaded).

## 2. Lids: positions, not covers

Venus gives the trough and the ethanol plate a Nunc "plate" with a lid on top
(`reagent_trough_lid`, `ethanol_washer_lid`). No script moves those lids and both are pipetted
throughout, so they are lid positions: PLR leaves both uncovered. The lids that move:

- culture plate lid <-> `culture_plate_park` (track 25 site 1). Venus puts a Nunc plate at Z 227
  there: 40.85 above the site, the height of a 41 mm deep-well plate. Built as an empty Nunc
  plate on a 1.2 mL DWP riser. **Unconfirmed.**
- sample plate lids <-> `sample_park` (track 11 site 3): an empty Greiner 384 plate (the lid's Z
  there is a lid-on-a-plate Z).

## 3. The printed pieces: placement

Frames and measurements are ray casts on the STLs (`build_models.py`, docstrings in `tc_deck.py`).

- **Trough**: on the L5AC site, turned 180 (barbs to the front). The only way its channels meet
  the columns the scripts aim at: cols 3/5/7/10 + `xDisplacement=3.75` land within 0.8 mm of the
  four channel centres. Sunk into the site's 4.74 recess: the traces put the tips at Z 198.6 in it,
  under the 201.2 its floor would have standing on the rim; sunk, the floor is 196.5. A `Resource`,
  not a `Plate` (PLR sinks a plate by its wells' offset; this is set explicitly).
- **Wash station**: stands on its three runners on the deck. The layout's six reservoir positions
  fit the model's reservoir centres at pitch 125 x 90 to +-1.5 mm in Y; the best X would put it
  3.6 into track 4, so it stands flush against the tip carrier instead (waters 4.6, waste and
  bleach 1.7 left of the taught head position). Its right column's back two reservoirs are not in
  the layout (`right_2`, `right_3`). The floor is 125.0; the layout teaches the head at 167.2
  (42 higher), and the head's lowest tool bottom with 300 uL tips is 128.6. So the methods'
  96-head calls need `minimum_height=167.2` (the head's floor defaults to the container's bottom).
- **Single-channel bath**: one track wide, centred in the track 10 / 17 gaps (the layout's A1 is
  3.75 left of centre, as on the trough). A keel runs underneath; it is put on the deck (in a deck
  slot it would stand 8 lower). Its handle hangs over the deck's front edge like a carrier's.
  **ethanol_waste** is a single-channel bath too (the user; the traces dispense there with 8
  channels). Layout Zs for the printed pieces are "where the tips should go", not geometry.

## 4. Off-deck trays

Not modelled: drawn as a 4 mm plate-sized pad whose top is the layout's plate bottom. A plate
put on each lands within 0.4 mm of the layout's A1 (`compare_to_lay.py`), which checks the
turned trays. The microscope's 90 is taken as counter-clockwise from above: unchecked.
The reader tray (X 870..997) runs into the STARlet model's right side wall (seen in `shots/trays_top.png`).

## 5. What the simulated machine does with it (`probe_moves.py`, `reach_survey.py`)

- 8 channels reach the trough's channels, both baths and the wash station's waste.
- The 96-head runs bleach and water_0..3 with `minimum_height=167.2`.
- iSWAP: the transfer station is reached only gripped from the right, the reader and microscope
  only from the left, front-row sites not from the front. Park -> reader gripped right, put down
  left turns the plate 180: the reader tray's 180 and the scripts' `labwareOrientation` 4 -> 2.
  Plate moves pass the collision gate: culture plate <-> transfer station, sample plate -> 384
  park (back, put down front: turned 180 at the park; the gate refused putting it down from the back, cause not traced),
  park <-> reader, park -> transfer station.
- **Refused**: a Nunc lid put down on a Nunc plate (the culture lid to its park, and back). A
  lid is a box; nesting 1.84 puts its bottom 1.06 below the Nunc wells' tops, and the gate lets a
  drop touch its destination and what that stands on, not the destination's wells. Not loosened
  here: see the open questions.

## 6. What the May traces say (`LogFiles/HxUsbComm202605*.trc`, top level only)

The STARlet running pyhamilton's OEM method, 14-19 May. Firmware X is signed by `xd`.

| What | Trace | Deck |
|---|---|---|
| trough, 8 ch (C0 AS) | x 679.7 / 742.7, tips to Z 198.6 | channels 0 / 3; floor 196.5 (sunk) |
| wash-station waste, 8 ch (C0 DS) | x 153.4, y 263.5..200.5, Z 165 | inside `waste` |
| ethanol_waste (C0 DS) | x 470, y 217.5..154.5, Z 144 | the track 17 bath |
| 96-head (C0 EA/ED) | water_0..3 at x -67.7, bleach at 54.4 / 356.3; floor (zm) 165 | as the layout; tips 50-60 above the printed floor |
| 96-head blow-out (C0 ED) | x -232.6, y 119.8 | `ETHANOL_BLOWOUT_A1` |
| culture lid (C0 PP/PR, gr1 = front) | grip Z 194.9 on the plate, 232.8 at the park: 37.9 higher | 39.4 higher (DWP riser + Nunc): the park's stack fits to 1.5 mm |
| sample lid park (gr1) | grip Z 194.2, the sample plates' 193.2 | an empty 384 plate: consistent |
| culture plate <-> transfer station (gr2 = right) | **x -170.8, y 313.9**, grip Z 208 | the layout's (-164.5, 455.5): **142 mm apart in Y** |

- Grips: lids and front-row plates are gripped **from the front** (gr1) on the real machine. The
  fork's reach model refuses "front" at those sites (Y 114.5): it is stricter than the STARlet.
- The transfer station: either the layout has changed since May or the Cytomat's station has two
  places (`cytomat.move_transfer_station('right')`). The deck keeps today's layout.
- No reader or microscope moves in these traces.

## 7. Open (what would settle each)

1. The transfer station's place: today's layout (-164.5, 455.5) or the May traces' (-170.8, 313.9)? (user)
2. What stands on track 25 site 1 under the culture lid? The traces fit a 41 mm riser plus a plate to 1.5 mm. (user)
3. Reader and microscope: a trace with dilute.py's reader move and microsope_transfers.py (C0 PP/PR x, y, Z, gr).
4. The lid-on-plate refusal: let a lid being put down on a plate touch that plate's wells in the gate (a fork change), or keep refusing.
5. The fork's iSWAP reach refuses front grips at front-row sites that the real STARlet makes (a fork change).
