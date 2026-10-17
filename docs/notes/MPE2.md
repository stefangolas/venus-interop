# Hamilton MPE²: protocol, mechanism, and a brief for modelling it

As of 2026-10-16. The MPE² is Hamilton's positive-pressure solid-phase extraction unit for the STAR: a filter plate is clamped under a pressure manifold, and the liquid pushed through it goes to waste or into a collection plate. The NIST DNA Extraction method (`LMSF_OPERATIONAL_LOGIC.md` §1) uses it for the lysate clearing, the bind, both washes and the elution.

PyLabRobot has no MPE² support. This note is what's needed to add it: the protocol (§2–4), how the NIST method drives it (§5), and the mechanism, written so someone without the sources can model and animate it (§6).

## 1. Sources

| Source | What it gave |
|---|---|
| Hamilton's labautomation.io share, `Hamilton Device Libraries/Hamilton MPE2 HSL Driver v2.1.0.0.zip` | One MSI holding the HSL library, the COM driver and the transport layer. Unpacked without installing; all 16 Hamilton DLLs are .NET, decompiled with ILSpy 9.1 |
| `Hamilton.Module.SPEMainController.dll`, `DecodeSupport.cs` | An embedded `InstrumentDefinition` XML (Hamilton's own interface definition, dated 2021-01-05): every object, address, interface, method, argument type, enum, struct and error, with help strings. Everything in §3–4 is from it unless marked |
| `Hamilton.Drivers.MPE.dll`, `MPEFirmware.cs` | What Venus actually sends: which overloads, the control-point string parser, defaults |
| `Hamilton.Components.TransportLayer.*` | The HOI transport over TCP and over serial |
| Hamilton share, `Hamilton Labware/[MPE]2_STAR.zip` | The 3D model, the labware definitions and three photos (§6.4) |
| NIST `lmsf_hamilton`, the DNA Extraction trace | The settings the lab uses (§5) |

The decompiled source and the XML stay out of this repo; this note restates the facts.

## 2. Software stack

```
Venus HSL          HSLMPELib.hsl           (string control points, device ids)
COM                HamiltonMPE.HSLMPE      (Hamilton.Drivers.MPE.dll)
driver             HamiltonMPE.MPEFirmware (parses, validates, picks overloads)
generated proxy    SPEMainController       (one class per firmware object; HoiType(interface, method))
transport          ComLink: HOI2 over HARP2, over TCP or over serial (RS-232 PPP framing)
```

The firmware speaks **HOI**, the same object-interface protocol as the Hamilton Prep and the Nimbus. PyLabRobot's `pylabrobot/hamilton/transport/tcp/` implements it for the Prep and was built from the same transport assembly (it cites `HoiPacket2Constants`). Over TCP an MPE² driver is that transport plus the table below.

**Serial is different.** The NIST lab connects on a COM port (§5), through an FTDI USB-serial chip at 921,600 baud. ComLink frames HOI packets there in two layers, neither in PLR:

- `Rs232PppInterface`: start byte `0xAA`, end byte `0xCC`, escape byte `0xBB`; a header CRC and a data CRC; discovery frames.
- `SerialProtocol0Frame` inside it: a 12-byte header (protocol, flags DAT/SYN/FIN/ACK/NAK, version, response code, uint32 length, uint32 sequence number), with ACK frames and retransmission.

The escape rule and the CRC polynomial are in `Rs232PppInterface.cs` / `Rs232PppPacket` and haven't been written up yet.

## 3. Objects and the commands that matter

The device's root object is `SPEMainControllerRoot`. Addresses are module.node.object, as the definition gives them; the driver finds the module with ComLink's `GetModuleByName` and then uses the objects under it. PLR's equivalent is `resolve_path("SPEMainControllerRoot.SPEControl")`.

| Object | Address | Role |
|---|---|---|
| `SPEMainControllerRoot` | 0x0001.0x0001.0xBF00 | Root |
| `SPEControl` | 0x0001.0x0001.0x1000 | The SPE state machine: everything Venus uses |
| `WasteSystem` / `Vacuum` | 0x0001.0x0001.0x0300 / 0x0310 | Waste containers and their vacuum |
| `ValvesAndSensors` | 0x0001.0x0001.0x0200 | Pressure monitoring |
| `MotorControllerRoot` | 0x0001.0x0200.0xBF00 | Motor controller (a second node) |
| `PlateShuttleAxis` | 0x0001.0x0200.0x1200 | Shuttle between integration and process areas |
| `UpperLifterAxis` | 0x0001.0x0200.0x1400 | Clamps the filter plate to the manifold |
| `LowerLifterAxis` | 0x0001.0x0200.0x1600 | Raises the collection plate |
| `DispenseAxis` | 0x0001.0x0200.0x1800 | The optional dispenser accessory |

Commands go to `SPEControl`, **interface 1** (the generated interface file says 0; the definition and the proxy's `SendAndReceive` say 1). Command = HOI2 action `CommandRequest`; status = `StatusRequest`.

| Method | Kind | Parameters (wire type) | Notes |
|---|---|---|---|
| 1 `ControlState` | status | → `SPEControlStatesId` (enum) | §4 |
| 2 `LabwareParameters` | status | → struct `SLabwareParameters` | FilterPlateHeight, FilterPlateNozzleHeight, CollectionPlateHeight, Offset, MaximumPenetration (all REAL32, mm) |
| 3 `MaximumCombinedHeight` | status | → REAL32 | |
| 4 `SPEControlPointRange` | status | → struct `SPEControlPointRanges` | Min/MaxFlowPerWell (SLPM), Min/MaxPressurePerWell (PSIG) |
| 5 `ManifoldInformation` | status | → struct `ManifoldInfo` | SerialNumber, CalibrationDate (STRING), NumberOfPorts (UINT32) |
| 6 / 18 / 21 / 22 `Initialize` | command | 6: none (obsolete); 18: BOOL smart; 21: BOOL smart, UINT32 vacuumTimeout, UINT32 vacuumRunTime, `WasteContainerSelect`, BOOL disableUpperLimitCheck; 22: as 21 without vacuumTimeout | Venus's plain `Initialize` sends 21 (smart, 10,000, 10,000, the first waste container present, false), or 18-with-timeout when no container is present |
| 7 `FilterPlatePlaced` | command | REAL32 filterHeight, REAL32 nozzleHeight | |
| 8 `FilterPlateRemoved` | command | none | |
| 9 `ClampFilterPlate` | command | none | |
| 10 `RetrieveFilterPlate` | command | none | |
| 11 `CollectionPlatePlaced` | command | REAL32 collectionPlateHeight, REAL32 offsetFromNozzles | |
| 12 `CollectionPlateRemoved` | command | none | |
| 13 / 20 / 23 / 24 `ProcessFilterPlateToWaste` | command | `SPEControlPoint[]`, BOOL returnFilterPlateToIntegrationArea, then: 13 UINT32 vacuumTimeout, waste; 20 as 13 + BOOL disableUpperLimitCheck; 23 waste, BOOL disableUpperLimitCheck; 24 as 23 + UINT32 vacuumRunTime, BOOL leaveVacuumRunning | Venus sends **23** |
| 14 `ProcessFilterPlateToCollection` | command | `SPEControlPoint[]`, BOOL returnFilterPlateToIntegrationArea | |
| 15 `Abort` | command | none | |
| 16 `GetLastCommandResults` | status | → BOOL commandBeingProcessed, `SPEControlStatesId[]` traversedStates, HoiResult errors | The states a command passed through: useful for the simulator's tests |
| 17 `IsInitialized`, 19 `CompletionStatus` | status | → BOOL | |

Types:

- `SPEControlPoint` = {REAL32 Duration (s), `SPEControlPointType` Type, REAL32 Value}. Type: 0 Flow (SLPM per well), 1 Pressure (PSIG per well), 2 None (idle).
- `WasteContainerSelect`: 0 WasteContainer1, 1 WasteContainer2, 2 NoWasteContainer.
- Errors (interface 1): 0x01 InvalidCommandForState, 0x02 InvalidHeight, 0x05 SPEProcessAborted, 0x06 WasteSystemErrorCausedAbort, 0x07/0x09 requested flow/pressure outside calibration, 0x0B IntrusionDetectedCausedAbort, 0x0C PressureDidNotDissipate, 0x0E input pressure over 120 psi, 0x10 under 80 psi, and others; 18 in all.

**Control-point strings.** Venus methods write steps as `"type,value,seconds;"`, e.g. `"pressure,20,240;pressure,65,60;"`. `MPEFirmware.RetrieveControlPoints`:

1. strips whitespace, appends a missing final `;`, and checks `^([A-Za-z]+,\d*\.?\d*,\d*\.?\d*;)+$`;
2. maps `pressure`, `flow` and `idle` to the three types (anything else is error 1427);
3. **divides each value by the manifold's `NumberOfPorts`** before range-checking it per well and sending it.

`NumberOfPorts` is the manifold's well count, 24, 48 or 96 (the driver lays dispenses out as 6 × 4, 6 × 8 or 12 × 8 from it). So the number in a method string is a total for the manifold, not a per-well value: on a 96-port manifold `pressure,20` sends 0.21 psig per well.

**Completion.** The device acknowledges a command at once and reports its end later, with a `CommandProcessingComplete` event (`ISPEControlCom`); Venus's driver waits on that event, polling a flag every 100 ms. `CompletionStatus` (method 19) reports the same thing on request, with the command's errors, so a driver can poll it instead of subscribing to events. A PLR driver should take per-well values, with a helper that reproduces Venus's division for strings copied from methods.

## 4. The state machine

`SPEControl` is a state machine; commands are refused outside their states (error 0x01). The SPE states, from the definition's help strings:

| Id | State | Where things are |
|---|---|---|
| 0 | Uninitialized | Unknown |
| 1 | Initializing | Transitory |
| 2 | Ready | The working stack, with no collection plate, is in the integration area, waiting for a filter plate |
| 3 | FilterPlatePlaced | A filter plate is on top of the working stack |
| 4 | ClampingFilterPlate1 | Transitory: the upper lifter carries the filter plate up and clamps it against the pressure manifold; the rest of the stack returns to the integration area |
| 5 | FilterPlateClamped | The filter plate is clamped; the rest of the stack is in the integration area |
| 6 | ProcessFilterPlateToWaste | Transitory: pressure on the clamped plate; effluent into the waste tray and the waste system. Starts clamped or from the integration area; ends at either, per `returnFilterPlateToIntegrationArea` |
| 7 | RetrievingFilterPlate1 | Transitory: the clamped filter plate returns to the top of the working stack in the integration area |
| 8 | CollectionPlatePlaced | A collection plate is on top of the waste tray |
| 9 | RetrievingFilterPlate2 | The filter plate is retrieved while a collection plate is present |
| 10 | IntegrationAreaPlateStack | Filter and collection plates are in the integration area |
| 11 | ProcessFilterPlateToCollection | Transitory: pressure on the clamped plate; effluent into the collection plate, which ends at the bottom of the stack in the integration area |
| 12 | ClampingFilterPlate2 | Clamping with a collection plate present |
| 13–26 | Evaporator, priming, dispensing | Accessories (evaporator, dispenser); not used by the NIST method |

The two paths the NIST method uses:

```
to waste:       Ready -FilterPlatePlaced-> 3 -ProcessToWaste-> [4] 6 [7] -> 3 (returned) or 5 (left clamped)
to collection:  Ready -CollectionPlatePlaced-> 8 -FilterPlatePlaced-> ... -Clamp-> 12 -> clamped
                -ProcessToCollection-> 11 -> 10 -CollectionPlateRemoved / FilterPlateRemoved-> Ready
```

The bracketed states are inferred from the help strings, not observed. `GetLastCommandResults` returns the states actually traversed, so the first session on hardware can confirm these.

## 5. How the NIST DNA Extraction drives it

From the trace (`DNA Extraction.condensed.md`) and `LMSF_OPERATIONAL_LOGIC.md` §1:

- **Connection:** `ConnectUsingCOM`, COM 7, 921,600 baud, device id from the method; `MPE2Waste = 0` (waste container 1).
- **Heights:** filter plate on the receiving plate: filter 86.5, nozzle 86.5; binding plate: filter 31.35, nozzle 38.4 (method constants `FPonRP*`, `BP*`, mm).
- **Steps:**

| Stage | Call | Control points |
|---|---|---|
| 04 clear the lysate | to waste, with the filter plate stacked on the receiving plate declared as one 86.5 mm "filter plate": the lysate collects in the receiving plate under it (inferred from the heights) | `pressure,20,240;pressure,65,60;` |
| 05 bind | to waste | `pressure,40,60;` |
| 06 wash 1 | to waste | `pressure,40,60;` |
| 07 wash 2 + dry | to waste | `pressure,40,60;pressure,65,420;` |
| 08 elute | to collection (EP under BP) | `pressure,65,420;` |

- **Calls:** stages 04–07 each go through the method's `FilterPlateToWaste` wrapper: `FilterPlatePlaced`, `ProcessFilterToWasteContainer` with the plate returned, `FilterPlateRemoved`, though the plate stays on the unit between washes. Stage 08: `FilterPlatePlaced`, `ClampFilterPlate`, the STAR puts the elution plate in the free integration area, `CollectionPlatePlaced`, `ProcessFilterToCollectionPlate` with the plate left clamped, the STAR takes the elution plate, `CollectionPlateRemoved`, `RetrieveFilterPlate`, the STAR takes the binding plate, `FilterPlateRemoved`.
- **Deck:** the base `Culture_Processing_STAR_MPE2_Base_Back.tml` (one unit) carries `[MPE]2.rck`; the plates the gripper puts on it are `RP_on_MPE`, `FP_on_MPE`, `Nunc_BP_MPE2` and `Eppendorf_EP_MPE`, all on that template.
- **Manual recovery path:** dialogs that let the operator re-enter heights and control points, then call `FilterPlatePlaced`, `ProcessFilterToWasteContainer`, `ClampFilterPlate` and `CollectionPlatePlaced` directly.

## 6. Brief: modelling and animating the MPE²

Self-contained for whoever builds the model and its animation in the PLR 3D viewer.

### 6.1 What exists

`[MPE]2_STAR.zip` (Hamilton share, `Hamilton Labware/`) holds:

| File | Content |
|---|---|
| `[MPE]2.x` (36 kB) | DirectX text (`xof 0303txt`). Frames: `Root`, `Cube`, `Cube_001`, `Cube_002`, `Cube_003`, and three textured planes `Top_Image`, `_MPE_2_Left_Image_Windows_Black2`, `_MPE_2_Right_Image_Windows_Black2`. Four boxes with photos on them; **no moving parts** |
| `[MPE]2 Base.x` (3.5 kB) | The base: `Cube`, `Cube_001` |
| `[MPE]2 Image.png`, `Top Image.png`, `[MPE]2 Left/Right Image Windows Black2.png` | The textures; also the best photographic reference available |
| `[MPE]2.rck` | 45 × 45 × 1 mm labware, one position; model offset X −325.5, Y −56, Z 0 |
| `STAR_MPE2_Base.tml` | The two-unit base, 67.5 × 497 × 15 mm; model offset X −422.5 |

Measured with `venus_interop.plr.xfile` (mm, Z up, in the model's own frame):

| Mesh | X | Y | Z | Reads as |
|---|---|---|---|---|
| whole `[MPE]2.x` | −354.0 … 70.0 | −78.7 … 79.5 | 1.5 … 187.2 | The unit: about 424 × 158 × 187 |
| `m3` | −354.0 … −81.9 | −78.7 … 79.5 | 3.2 … 187.2 | The main body, off the deck |
| `m0` | −352.7 … 70.0 | −78.0 … 78.0 | 1.5 … 183.6 | The housing, reaching onto the deck |
| `m1` | −75.4 … 64.6 | −49.9 … 50.1 | 46.6 … 59.2 | A plate-sized box (140 × 100): the filter plate seat |
| `m2` | −75.0 … 65.0 | −49.8 … 50.2 | 24.4 … 39.3 | The same below it: the collection plate seat |
| `[MPE]2 Base.x` | −203.3 … 240.6 | −248.5 … 248.6 | 0 … 8.3 | The base plate, 444 × 497 |

`m1` and `m2` are where the integration area's two plates sit, which places the working stack at the deck end of the unit, under the STAR's reach.

`venus_interop.plr.xfile` (from the scratch `x_to_glb.py`; `docs/notes/HAMILTON_3D_MODELS.md`) reads text `.x`, but it reads no texture coordinates and loads no images: the photo planes come out as flat colour until it does.

### 6.2 Where it stands (deck coordinates, from the base's sites, relative to the base's origin)

The unit stands **left of its base carrier**, off the deck's pipetting area (negative X), like the ODTC.

| Site | Base_Back (NIST deck) | Two-unit base, unit 1 / unit 2 |
|---|---|---|
| MPE body (`[MPE]2.rck`) | X −81.5, Y 364.5, Z 8.3 | X −74.5, Y 358.5 / 167.6, Z 8.3 |
| Filter plate on the stack | X −120.1, Y 339.5, Z 56.3 | X −119.4, Y 339 / 148.1, Z 54.05 |
| Collection plate | X −124.4, Y 345.7, Z 39.4 | X −119.4, Y 339 / 148.1, Z 40.1 |

Plate sites are 127 × 86 mm (SBS). A filter plate sits 13.95–16.9 mm above the collection plate under it.

### 6.3 Moving parts to model

Named after the firmware objects (§3). Travel distances and part sizes are **not** in the sources; estimate them from the photos.

| Part | Firmware axis | Motion | Positions named in firmware |
|---|---|---|---|
| Plate shuttle (carries the working stack) | `PlateShuttleAxis` | Horizontal, between the STAR-accessible front and the inside of the unit | `MoveToIntegrationArea`, `MoveToProcessArea`; flag sensors at both ends |
| Upper lifter | `UpperLifterAxis` | Vertical: lifts the filter plate off the stack and clamps it against the pressure manifold | `ClampFilterPlate(height)`, `UnclampFilterPlate`, `DriveUpUntilStall` |
| Lower lifter | `LowerLifterAxis` | Vertical: raises the collection plate under the clamped filter plate | `MoveRelative(offset, velocity)`, `DriveUpUntilStall` |
| Pressure manifold | none (fixed) | The clamp target; the nozzles sit at `nozzleHeight` | |
| Waste tray | none (fixed) | Under the process area; takes effluent when no collection plate is up | |
| Dispenser (accessory) | `DispenseAxis` | Not needed for the NIST method | |

The integration area is where the STAR's gripper puts and takes plates (the sites in §6.2). The process area is under the manifold, inside the unit.

### 6.4 What each state should show

Drive the animation from the simulator's state (§4); each transition is one motion.

| Transition | Motion |
|---|---|
| Initialize | Shuttle to the integration area; lifters down |
| `FilterPlatePlaced` / `CollectionPlatePlaced` | None (the STAR's gripper placed the plate) |
| Clamp (states 4 / 12) | Shuttle to the process area; upper lifter raises the filter plate to the manifold; the rest of the stack goes back to the integration area (no collection plate) or stays under it (collection) |
| Process (6 / 11) | No motion; show the pressure profile (value and seconds per control point) and the liquid leaving the filter wells into the waste tray or the collection plate |
| Retrieve (7 / 9) | Upper lifter lowers the filter plate onto the stack; shuttle back to the integration area |
| Collection run ends (10) | The collection plate at the bottom of the stack, the filter plate on it, in the integration area |

In the viewer a moving part is a child `Resource` whose `location` the simulator sets; the viewer already redraws on location changes. The plates on the shuttle should be its children, so they ride with it.

### 6.5 Open questions for the modeller

- Shuttle travel and lifter strokes (none in the sources; the photos and the base's footprint bound them).
- Whether the manifold and nozzles are visible from outside (the photos show a windowed front).
- The unit's outer size: the boxes in `[MPE]2.x` give one; check it against the photos.

## 7. Plan for PyLabRobot

1. **Done** (2026-10-16, PLR fork, local branch `mpe2` at `e323b06ee`, worktree `C:\Users\stefa\plr-mpe2`): `pylabrobot/hamilton/mpe2/`.
   - `commands.py`: §3 as `TCPCommand` subclasses, the enums and structs, and `parse_control_points`.
   - `driver.py`: `MPE2Driver` over HOI/TCP, which waits on `CompletionStatus`; `MPE2SimulationDriver`, which walks §4, refuses commands outside their states, waits the control points' durations (scaled by `time_scale`), and reports every state to observers for an animation.
   - `mpe2_tests.py`: wire encoding against the definition, the control-point parser, the driver's waiting, and the NIST method's sequence on the simulation. Not run against hardware.
   - Unverified: whether status replies that return a structure wrap it in one STRUCTURE fragment, as the driver assumes.
2. An `MPE2` resource: the integration-area sites, and the liquid bookkeeping (filter plate wells into the collection plate or waste).
   - **Prototype** (2026-10-17, `examples/mpe2_model.py`, used by `examples/dna_extraction_demo.py --models`): the modeller's animated model (`plr-models/models/hamilton_mpe2_animated.glb`: shuttle, upper and lower lifters, filter and waste carriers; travel and strokes estimated) as a resource whose seven joints follow the simulation's states, with the carriers as `ResourceStack`s the plates ride on. A copy of the GLB nests each carrier under an X node (the viewer drives one axis per node) and moves the model to its bounding-box corner. Its seat goes under the binding plate's Venus position; Venus's own placement of the model (rack corner plus `3D*Offset`) lands within 1.4 mm in X and 0.4 mm in Z of that, 4.4 mm in Y. The liquid moves in the demo, well for well.
3. Serial: a PPP-framed serial transport under the same HOI session (§2), for COM-connected units like NIST's.
4. Hardware check: `GetLastCommandResults` after each command to confirm §4's transitions.
