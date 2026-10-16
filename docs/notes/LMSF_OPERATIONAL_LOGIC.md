# NIST LMSF methods: operational logic only

Written 2026-10-16. This note covers three methods: DNA Extraction, Marionette protease gradient plate prep v5 and 02 Colony Picking. It keeps only what the robot physically does and the control flow that decides it. Scheduler handshakes, `parameters.csv` parsing, worklist and metadata output, tip-counter files, debug dialogs and trace comments are all left out. The full write-ups are `LMSF_DNA_EXTRACTION.md`, `LMSF_MARIONETTE_PROTEASE_GRADIENT.md` and `LMSF_COLONY_PICKING.md`.

Sources: each method's own `.hsl`/`.sub` source, re-indented and read with its disabled steps marked; the device-step settings in the decompiler traces; and the sequences in each method's `.lay` file, which give the well positions here. Before this pass the sequences had not been resolved to positions. Inferences are marked.

Notation: `ch` = independent pipetting channels; `96H` = 96-head. `GRIP a → b` = a CO-RE gripper move, with the plate and lid conventions of `PlateAndLidMovement` (see the DNA Extraction write-up). `[if X]` = a branch in the code. *Into liquid* = a dispense with cLLD and liquid following; *dry* = no LLD, at a fixed height.

## Common mechanics

- **Sequence walk.** Every multi-well transfer is the same loop: set the sequence to position 1, then while positions remain, `AlignSequences` takes the next N positions (N = active channels), pipettes, and advances. The number of passes is therefore the length of the sequence divided by N, so **the layout's sequence lists fix both the order and the count**. Two of the methods use repeated entries on purpose (below).
- **Tip policy belongs to the call site, not the liquid.** The same transfer helper is called with tips that are picked up once and kept, kept for one reagent, or replaced on every pass. Each step below says which.
- **No pipette mixing after additions,** except where stated. Mixing is a setting on a single aspirate or dispense step, never a separate step.

---

## 1. DNA Extraction

**Material:** 24 E. coli pellets in Spin Plate columns 4, 6 and 8 (24 wells), with the supernatant still on them. Columns 3, 5 and 7, next to them, take the waste.
**Layout sets:** `sequence_number` (1–4) picks one 3-column set on the Lysate Plate, Filter Plate (FP), Receiving Plate (RP) and Binding Plate (BP). Set 1 is columns 1–3. The buffer sources are **one fixed set**, not one per run: P1 is in DNA_Buffers_2 columns 2–4 and P2 in columns 9–11; PB is in DNA_Buffers_1 columns 3–5 and PE in columns 8–10; elution buffer is in column 5 of its plate.
**96-head mode:** every 96H step uses the first 24 nozzles (3 columns × 8), picked from the offset tip rack.

```
INIT    Initialize; MPE² connect (skipped in the simulator); both heater shakers (HHS_1, HHS_2) locked
        (HHS_2 is never used after that)

01  Remove supernatant                          8 ch, 1000 µL filtered tips
    GRIP Spin Plate lid → waste
    [if is_pipetting] for each column pair (4→3, 6→5, 8→7), visited TWICE
                      (each column appears twice in the sequence lists, so there are 6 passes):
        new tips
        aspirate 1000 µL from the pellet wells (cLLD, liquid following, submerge 3)
          → dispense into the waste wells beside them
        aspirate (3.6 × culture_volume − 1000) µL, aspirate mode 2
          → dispense into the waste wells
        eject
      (Aspirate mode 2 is probably "aspirate all", which would make the second
       volume an upper limit. Unverified: the enum is in CONVENTIONS §11.)

01A Add P1, resuspend, move to the Lysate Plate   8 ch, 300 µL filtered tips
    GRIP Lysate Plate lid → park (it is on HHS_1); GRIP DNA_Buffers_2 lid → park
    [if is_pipetting] for each pellet column (3 passes):
        new tips
        aspirate 200 µL P1 → dispense dry onto the pellet (no LLD, fluid height 2)
        aspirate 300 µL from the pellet well with MIX 10 × 220 µL (resuspension)
          → dispense into Lysate Plate (set) column
        eject
    [if offset rack empty] RenewOffsetTips

02  Lysis (P2)                                   96H × 24, 1000 µL tips
    [if is_pipetting] pick 24 tips; aspirate 250 µL P2; dispense into the Lysate Plate
                      (no mixing); eject with a 5 s waste-chute shake
    start HHS_1 at 200 rpm; 120 s timer, during which:
        GRIP the DNA_Buffers_2 lid back on; GRIP the empty Spin Plate → waste
    wait for the timer; stop HHS_1; keep it locked
    [if offset rack empty] RenewOffsetTips

03  Neutralisation (N3)                          96H × 24
    park the 96H; GRIP the N3 lid → park
    [if is_pipetting] pick tips; aspirate 350 µL N3 (set); dispense into the Lysate Plate; eject (2 s shake)
    HHS_1 at 200 rpm for 120 s; the N3 lid goes back on during the wait

04  Clear the lysate through the filter plate    96H × 24, wide-bore tips
    [if use_iSWAP] GRIP RP (with lid) storage → MPE²; GRIP RP lid → park
                   GRIP FP (with lid) storage → MPE² on top of the RP, placed 1 mm high; GRIP FP lid → park
    [else]         park the 96H; a dialog asks the operator to do it
    [if is_pipetting]
        pick 24 wide-bore tips from their tip support
        C0TT: redefine tip type 5 as 71.8 mm long, 1003 µL      ← AFTER the pick-up
        cap the volume at the usable 938 µL (900 stays 900)
        aspirate 900 µL lysate with MIX 3 × 675 µL (aspirate mode 2)
          → dispense dry 13 mm above the FP filter
        start the 120 s incubation timer
        eject; C0TT: restore tip type 5 to stock
    [else] start the 120 s timer
    GRIP the Lysate Plate lid back on; wait for the timer
    MPE² push through to the RP: "pressure,20,240;pressure,65,60;"      (skipped in the simulator)
    [if use_iSWAP] FP lid back on; GRIP FP lifted and re-seated 4 mm high (same position)
                   GRIP FP → storage; RP lid back on; GRIP RP → storage
    [else]         MPE² FilterPlateRemoved
    [if offset rack empty] RenewOffsetTips

05  Bind                                          96H × 24
    [if use_iSWAP] GRIP BP lid → park; GRIP BP storage → MPE², 1 mm high; GRIP RP lid → park
    [if is_pipetting] pick tips; aspirate 900 µL cleared lysate from the RP (submerge 7)
                      → dispense dry 13 mm above the BP membrane; eject
    GRIP the RP lid back on; park the 96H
    MPE² to waste: "pressure,40,60;"
    [if offset rack empty] RenewOffsetTips

06  Wash 1 (PB)                                   96H × 24
    GRIP DNA_Buffers_1 lid → park
    [if is_pipetting] 900 µL PB → BP (dry, 13 mm); eject
    MPE² to waste: "pressure,40,60;"
    [if offset rack empty] RenewOffsetTips

07  Wash 2 (PE) + dry                             96H × 24
    [if is_pipetting] 900 µL PE → BP (dry, 13 mm); eject
    GRIP DNA_Buffers_1 lid back on
    MPE² to waste: "pressure,40,60;pressure,65,420;"       (wash, then a 420 s dry)
    GRIP BP lifted and re-seated 7 mm high (same position)

08  Elute                                         8 ch, 300 µL filtered tips
    is_pipetting := "true"                        ← forced, even in manual mode
    choose the path: spin_final_elution "yes" → centrifuge, "no" → MPE², otherwise a dialog
    [MPE² path]  [if use_iSWAP] GRIP EP (with lid) storage → pipetting position; GRIP EP lid → park
                                GRIP BP MPE² → on top of the EP
                 [else]         park the 96H; dialogs
    [spin path]  GRIP EP lid (at storage) → park; GRIP BP MPE² → on top of the EP at storage
    GRIP elution buffer lid → park
    for each BP column (3 passes): new tips; aspirate 130 µL (always from the same
        8 source wells) → JET dispense (no LLD, fluid height 6); eject
    start a 300 s timer
    [MPE² path]  elution buffer lid back on; GRIP BP → MPE², 1 mm high; EP lid back on
                 MPE²: set heights, plate placed, clamp
                 GRIP EP (with lid) → MPE²; EP lid → park
    [spin path]  GRIP BP lid onto the BP/EP stack; elution buffer lid back on; dialog
    wait for the timer
    [MPE² path]  MPE² to the collection plate: "pressure,65,420;"
                 EP lid back on; GRIP EP → storage; MPE² collection plate removed, retrieve the filter plate
                 GRIP BP → storage, 1 mm high; BP lid back on; MPE² filter plate removed
    [spin path]  dialog; 210 s timer (the operator centrifuges); dialog

END     MPE² disconnect; HHS terminate; park the head and arm
        [spin path] dialog; GRIP the BP lid from Lid_parking_Numc_BP → BP storage
```

**RenewOffsetTips:** 96H picks up whatever is on the offset support and ejects it to the chute with a 10 s shake. It then picks a full 96 from the handoff rack and ejects them onto the offset support. The 24-nozzle steps then pick from that support, three columns at a time, starting from the back (positions 89–96, then 81–88, and so on).

**Control logic that matters**
- **There's no loop over samples on the 96-head side.** One 24-nozzle stamp handles all 24 samples. Only the 8-channel steps (01, 01A, 08) loop, over 3 or 6 passes.
- **Tip changes:** 8-channel steps take new tips on every pass. The 96H takes a new 24 for every reagent. The offset rack is refilled only when its position counter reaches 0, and that check runs between stages in `main`, not inside them.
- **Timers overlap with motion:** both shakes, the FP incubation and the elution incubation start a timer, do the plate and lid moves, then wait. The 120 s FP incubation therefore includes the tip eject, the second C0TT and a lid move.
- **The `is_pipetting=false` mode isn't consistent.** Stage 08 sets `is_pipetting = "true"`, so elution always pipettes. The MPE² steps and every gripper move inside `[if use_iSWAP]` run whatever `is_pipetting` is.
- **The tip-type redefinition is global, and an abort leaves it in place.** `OnAbort` only writes a trace comment, so an abort between the two `C0TT`s leaves tip type 5 at 71.8 mm. Whether a re-initialise restores the firmware's tip table is unverified.
- **The redefinition comes after the pick-up.** The 96H picks the wide-bore tips while tip type 5 is still stock, and the `C0TT` follows. Whether the 96-head uses the `C0TT` tip table at all, at pick-up or afterwards, is unverified (CONVENTIONS §11).

**Open (operational)**
- On the spin path, the BP lid is moved from `Lid_parking_Numc_BP` onto the BP/EP stack in stage 08. At the end, `main` moves a lid from that same parking position back to BP storage. Unless the operator puts the lid back during the centrifuge dialogs (their text isn't in the method files), the gripper reaches into an empty position.

---

## 2. Marionette protease gradient plate prep v5

**Plate map** (Growth Plate, from the layout's sequences):

| Columns | Rows A, C, E, G | Rows B, D, F, H |
|---|---|---|
| 1 | media only | media + vancomycin (no TMP) |
| 2 | media + TMP (zero point of the salicylate gradient) | same |
| 3–7 | TMP + **salicylate gradient from stock 1** (column 7 is the top) | TMP + **salicylate gradient from stock 2** |
| 8–12 | TMP + salicylate-1 background + **vancomycin gradient** (column 12 is the top) | TMP + salicylate-2 background + vancomycin gradient |

TMP is only added on plates 3–5 (`with_tmp = plate_number ≥ 3`); on plate 2 the TMP volumes are 0. V = `media_volume`; t = `dil_series_transf_vol` = V/(f−1); m = f/(f−1). The gradient-start columns (7 and 12) get every component × m.

```
GRIP Growth Plate (with lid) handoff → position; GRIP GP lid → park; GRIP media lid → park

[if is_pipetting]  MEDIA                    4 ch, 1000 µL filtered tips, ONE pick-up for all of it
    pre-wet once: aspirate p_vol from the media trough → dispense back into it
    for each group, 4 wells per pass, always aspirating from trough positions C6–F6:
        cols 2–6        V − tmp
        cols 8–11       V − sal_bg − tmp
        col 7 A/C/E/G   V·m − sal1_start − tmp·m
        col 7 B/D/F/H   V·m − sal2_start − tmp·m
        col 12          V·m − van_start − sal_bg·m − tmp·m
        col 1 A/C/E/G   V
        col 1 B/D/F/H   V − van
      each: aspirate (cLLD) → DRY dispense (no LLD, fluid height 0.3)
    eject

GRIP media lid back on; GRIP reagent stock plate lid → park

[if is_pipetting]  SALICYLATE               4 ch, 300 µL filtered tips
    new tips; pre-wet in stock 1 (wells 19–22)
        col 7 A/C/E/G ← sal1_start; col 12 A/C/E/G ← sal_bg·m; cols 8–11 A/C/E/G ← sal_bg
      the same 4 tips throughout, dispensing INTO LIQUID and going back to the stock each time
    eject; new tips; the same for stock 2 (wells 27–30) → the B/D/F/H rows; eject

[if with_tmp]      TMP                      8 ch, 300 µL, NEW TIPS EVERY COLUMN   ← not gated by is_pipetting
    cols 2–6, 8–11 ← tmp; col 7, col 12 ← tmp·m        (into liquid, no mix)

[if is_pipetting]  VANCOMYCIN               1000 µL tips, new tips every pass
    col 12 ← van_start (8 ch, stock wells 1–8); col 1 B/D/F/H ← van (4 ch, stock wells 3–6)

SERIAL DILUTIONS                            8 ch, 1000 µL, ONE tip set per series   ← not gated by is_pipetting
    vancomycin: from [12, 12, 11, 10,  9, 8    ]
                to   [12, 11, 10,  9,  8, waste]
    salicylate: from [ 7,  7,  6,  5,  4, 3    ]
                to   [ 7,  6,  5,  4,  3, waste]
    each step: aspirate t with MIX 2 × t at the source (cLLD, liquid following)
               → dispense t INTO LIQUID at the target
    eject after each series

GRIP reagent stock plate lid back on; GRIP GP lid back on; park the head and arm
```

**Control logic that matters**
- **Every well ends at V.** The start columns are over-filled by m; each step takes t out, and the last step sends t from the bottom column to `Liquid_waste`. So the series is volume-balanced at both ends: the starts lose t, and every middle and end column gains t and loses t. That balance comes only from the layout's sequence lists. The code passes `from`/`to` and never mentions waste.
- **The first step of each series is a self-transfer** (12 → 12, 7 → 7). The start column has just received 3–4 separate additions with no mixing. Mixing is part of the aspirate, so the self-step mixes the start column, takes t and puts it back, and the next step mixes it again before moving t on. This is presumably a deliberate extra mix; that's an inference, since the code doesn't say. It costs one pass and needs no extra code.
- **Mixing happens only at aspiration in the series.** Each target is mixed when it becomes the next source, so the bottom column is mixed before its t goes to waste. Nothing is mixed after TMP or vancomycin; the next series step mixes them in. Columns 1 and 2 are not in either series, so their additions (vancomycin, TMP) are never pipette-mixed.
- **Tip reuse is ordered so it's mostly harmless:** media uses one set of tips for all 96 wells (the seven groups cover the plate), but they dispense dry into empty wells. Salicylate reuses tips while dispensing into liquid, but at that point the wells hold only media, so the only carry-over is media back into the salicylate stock. Each dilution series keeps one tip set from high to low concentration, so residue moves the same way as the dilution.
- **The `is_pipetting=false` mode isn't consistent:** TMP and both serial dilutions sit outside the `is_pipetting` checks, so a "manual" run still aspirates from the series wells and still adds TMP. Media, salicylate and vancomycin do respect the flag.
- **Channel count is a call-site choice:** 4 channels wherever a group comes in alternating rows or from a 4-well trough position, and 8 channels for whole columns. The library's shape check enforces it (the source holds N positions; the destination is a multiple of N).

---

## 3. 02 Colony Picking

**Map:** agar plate n (1–4) → one Growth Plate row: plate 1 → A1–A12, plate 2 → C1–C12, plate 3 → E1–E12, plate 4 → G1–G12 (`GrowthPlate_Picking` = rows A, C, E, G, column by column). Rows B, D, F and H stay empty.

```
INIT  Initialize; start easyPick II (polls IsRunning up to 100×; abort on error)

TIPS  check the 300 µL partial rack against 48 tips
      ≥48 left → nothing to do
      some left → GRIP rack → handoff (the scheduler takes it); new rack handoff → partial
      empty → GRIP rack → waste; new rack handoff → partial

GRIP  Growth Plate handoff → deck
for n = 1..4: park the 96H and arm; GRIP agar plate handoff → stack slot n

for n = 1..4:
    Growth Plate position := 1 / 13 / 25 / 37   (row A / C / E / G)
    GRIP agar plate (stack slot n) → light table; GRIP its lid → lid park; eject the grippers
    move the arm out of the camera's view
    loop (until the analysis succeeds):
        light table on (12%); top light on (12%, source variable never set; see the write-up)
        take a picture; lights off
        analyse → OK: leave the loop | fail: error dialog → retry dialog (2 = abort, otherwise retry)
    picked := 0
    loop (pick cycle):
        get up to 8 colony positions from easyPick II (channels left-aligned, cap [12])
        none found or none pickable → leave the loop
        each colony → a 1-well labware spot at its deck X/Y/Z
        new 300 µL tips (one per colony channel)
        "aspirate" 0 µL at the colony: cLLD sensitivity 1, liquid following, submerge 0
             → the tip touches the agar surface (inference)
        "dispense" 0 µL into the next Growth Plate wells: into liquid, submerge 2, MIX 1 × 100 µL
             → the cells are rinsed off into the medium (inference)
        eject tips
        mark each colony OK or ERROR from the aspirate step's per-channel return
        picked += colonies used     (a failed pick counts too)
        picked ≥ 12 → leave the loop
    GRIP lid back on; GRIP agar plate → stack slot n

for n = 4..1: GRIP agar plate → handoff; park; the scheduler takes it
GRIP Growth Plate → handoff; park; the scheduler takes it
END   park; easyPick II de-initialised (called twice on hardware)
```

**Control logic that matters**
- **Two loops with exits on conditions inside them** (`while (1 == 1)` with `break`): the imaging loop exits on a successful analysis, and the pick loop exits on "nothing to pick" or "12 reached". The run ends early only by `abort`, never by a cleaner path.
- **The pick target is checked after the cycle, not before it.** `12 − picked` is computed and then never used. Every cycle asks for up to 8, so with 8 channels the run goes 8 → 16 unless easyPick II itself stops at the `[12]` cap. If it doesn't, the second cycle's last 4 colonies go into the first 4 wells of the next row (C1–C4 for plate 1). The next plate then starts at C1 and inoculates those same wells again, so two strains share each of those wells. Plate 4 has no wells left after G12: the 48-position sequence ends there, and what Venus does when a dispense runs past the end is unverified. The tip check (48 = 4 × 12) also assumes the cap holds.
- **A failed pick still takes a well.** `picked` counts the colonies offered, not the successful ones, and the Growth Plate sequence moves on either way. An ERROR colony leaves an uninoculated well, which the database records.
- **Tips:** new tips for every cycle, one per colony, all filtered 300 µL tips.
- **Physical isolation:** each agar plate is on the light table, uncovered, only during its own imaging and picking, and the stack is emptied in reverse order. Rows B, D, F and H are left empty; that's presumably a spacer between strains (an inference).

---

## What this pass changed in the other write-ups

- DNA Extraction: the buffer plates are one fixed set, not four copies. `C0TT` comes after the wide-bore pick-up. Stage 08 forces `is_pipetting`. An abort leaves tip type 5 redefined. The final lid move on the spin path may reach into an empty position. The supernatant columns are each visited twice.
- Marionette: the method's path. The plate map. The series' self-transfer first step and its last step to waste. TMP and the series ignore `is_pipetting`.
- Colony Picking: the well order (rows A, C, E, G), which closes that open item, and the exact well collision if the cap doesn't hold.
