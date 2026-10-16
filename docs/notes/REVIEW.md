# Hamilton shared library (via labautomation.io): review, 2026-09-27

**Entry points.**
- Forum thread "Library Downloads (Links)": https://labautomation.io/t/library-downloads-links/1052 (curated by EricSindelar_Hamilton).
- Hamilton-hosted share: https://download.hamiltonsupport.com/wl/?id=VQY0XAzTfcT7KY29A1YJtZVFwZ7GMOO2 (user uploads: `id=SHSacPZ57a4frXKDKAY8F3UxVB7E8h3j`, same contents as "User Created Content").
- Any file downloads with `...&path=<url-encoded folder/file>&download=1` (plain `curl -L`).
- On .x/.hxx: https://labautomation.io/t/labware-3d-data/2520. Hamilton says the 3D data is cosmetic and has no effect on the labware definition; `.x` is DirectX, exportable from Blender ≤ 2.79 with the plugin, and should be modelled in mm.
- No licence terms are stated anywhere I looked. Treat the files as Hamilton's: fine for our own use and conversion, but ask before redistributing them inside PLR.

Downloaded so far (all local, not in any repo):
- `hamilton_library/labware/`: all 42 "Hamilton Labware" archives, ~120 MB. `labware_inventory.json` lists each one's contents.
- `hamilton_library/tools/`: the Multiflex Carrier Assistant, with its cabinet extracted to `mfx_extracted/` (240 files).

---

## ★ Most valuable

### 1. Multiflex Carrier Assistant v4.10: the MFX kit (Hamilton GUIs and Tools)
An 18 MB installer, `MultiflexCarrierAssistantv4.10.zip`. It is an InstallShield-style EXE with one embedded MS cabinet. The cabinet can be carved out and opened with `expand.exe -F:*` without running anything. Contents:

- **101 DirectX `.x` models, all text format**, so they convert with the same approach as `96channelhead/convert_tube_carrier.py`. Most have a `_P` twin, which is probably the portrait orientation.
  - **Carrier bases:** `MFX_CAR_5_XXX_A00`, `MFX_CAR_7T_XXX_A00`, `MFX_CAR_L4_XXX_A00`, `MFX_CAR_L5_XXX_A00`, `MFX_CAR_P3_XXX_A00`.
  - **Standard modules:** MTPModule, DWPModule, MTPNestCB/RB, DWPNestCB/RB, NTR1Module, NTR1_384Module, NTR4Module, PCR96Module, PCR384Module, TipModule, TipParkModule, TipStackModuleLow/ST, TiltModule, TurnTableModule, StackerModule (+Portrait), TUCUModule (+ABI), RGTModule, RGT8/RGT96REFILL, LIDParkModule (7T, F variants), CoolingModule, HeatingModule (each with or without lid).
  - **Temperature and shaking:** `cpac`, `cpac2mL`, `CPACTubeModule`; Hamilton Heater Shaker nests `HHS_FlatMTP`, `HHS_FlatDWP`, `HHS_DWP_Nunc`, `HHS_Sarstedt`, `HHSPCR96ABI`; `Teleshake95MTP/DWP`; `VariomagShakerMTP/DWP`; brackets `BracketShakerBase`, `BracketShakerBaseCPAC`, `BracketCTHT`.
  - **Hamilton "HP" nests, by part number:**

    | Part no. | Nest |
    |---|---|
    | 58363-01 | MTP raised |
    | 58363-02 | MTP flat |
    | 58364-01 | DWP raised |
    | 58364-02 | DWP flat |
    | 92585-01 | MTP flat, sloped |
    | 92586-01 | DWP flat, sloped |
    | 98552-01 | MTP tab |
    | 98553-01 | DWP tab |
    | 93561-01 | MIDI raised |
    | 95298-01 | MIDI flat |
    | 67540-01 | tall flat |
    | 92882-01 | tip isolator |
    | 992581-01 | gravity waste trough 96 |
    | 188313 | downholder top |

  - **Part-number-only models, to identify:** 10087824 (+R), 10117124, 199085, 819273, 6600518-01, 6601900-01, 6601925-01, 6601987-01, 6601988-01.
  - **Tube modules:** `MFX_EPPENDORF_TUBE_MODUL`, `MFX_ABI_EPPENDORF_TUBE_MODUL`, `MFX_Mrx2DBC_TR_1_4ml_dwnh`, `rackformfx_car_l5_rgt5`.
- **84 `.jpg`**, one photo per module, useful to check against the models.
- **Labware definitions:**
  - 15 `.rck`: CPAC_2mLTubes, DownholderTop(_P), FlipTube, GravWasteTrough96(_P), Ham_24_RB_TuR_1.5ml, MFX_24_Tube_MODUL_188263, MFX_ABI_EPPENDORF_TUBE_MODUL, MFX_EPPENDORF_TUBE_MODUL, MFX_Mrx2DBC_TR_1_4ml_dwnh, RGT_REFILL_8channel, RGT_REFILL_for96Head, mfx_lid_l, rackformfx_car_l5_rgt5.
  - 12 `.ctr`: Eppendorf 1.5/2 mL, ABI 5 mL tube, flip tube 1500 µL, RGT refill, downholder, gravity trough, MFX lid, and others.
- **5 `.tml` carrier templates.** Their sites are placeholders (all at X=4, Y=-62, Z=112): the Assistant fills in real positions when it composes a carrier. **Module-to-site offsets are therefore not in these files.** They are probably inside `LabwareAssistant3D.exe` or computed by it. That is the missing piece for assembling carriers exactly.
- **Why this matters:** PLR today has 3 MFX bases (L5, P3, L4/P3 shaker variants) and 5 module types (tip, NTR, DWP flat, DWP metal-tapped, rack-based DWP), with models for 4 of them (`MFX_CAR_L5_base`, the metal-tapped DWP holder, the NTR holder, the tip-rack holder). Everything else in the list above is new to PLR, including every heater, cooler, shaker, CPAC, tilt and stacker module.
- **More assembled MFX models are on local disk**, in `C:/Users/stefa/NGS-Protocols/assets/NGSStarMOA`: `MFX_CAR_2HHS30NuncDWP_2CPACflat`, `MFX_CAR_2HHSF30MTP_HHSF30DWP_CPAC`, `MFX_CAR_2MTP HPTab_MIDI HPTab_2DWP HPTab`, `MFX_CAR_2TipBC_2PCR96_MTP`, `MFX_CAR_2TipBC_DWP_PCR96_DWP NestRB`, `MFX_CAR_2HHS30NuncDWP_Empty_*`, `MFX_CAR_ODTC_MTP.hxx`. These are real configured carriers from a protocol. They can be used to cross-check how modules sit on a base and to recover module offsets.

### 2. Traces from other STARs (Shared Files - Temp)
- `HxUsbComm20240109.trc`, `HxUsbComm20260113_JSfromLabAutomationIO.trc`, `Plate_normalization_HxUsbComm20250520.trc`: firmware-level traces from other people's machines. These are new data for the motion-timing fits (`tools/hxusbcomm_*.py`), and could answer "is it our STAR or all STARs" for the channel speeds and fixed times.
- About 15 Venus `*_Trace.trc` run traces (HitPick, playground ×6, Normalization, LiquidClassVerificationKit, barcode tests, Celigo cell counting, Urine MedPro), several with the matching method `.pkg`/`.hsl`/`.lay`. These pair commands with deck layouts.
- `liquid_following.mp4`: a video of liquid following, a reference for the aspirate surface-following animation.
- `SquareAgar_Spotting.ctr`/`12x8.rck`, `playground.lay`, and `Go Pro Tri Blade NEW Star Arm Mount v1.1.stl` (a camera mount for the STAR arm).

### 3. 3D models in "Hamilton Labware" (55 files)
Mostly text `.x`; the Nimbus/STAR tip boxes are `.x` compressed (`xof 0303tzip`, 10–12 MB each); `.hxx` is Hamilton's gzip-wrapped `.x`, as in the tube carrier converter.

| Archive | Models | Note |
|---|---|---|
| STAR Labware Definitions – Tip Boxes and Accessories (+202306) | Ham_MLTipBox 1000/F1000/F300/F50 + Lid + LidAdapter, RCK_TipBox1000F/300F/50F/Lid, CAR_4/5HamTipBox 1mL & 50/300, **MFX_CAR_5Base HPTab (5.4 MB)**, MFX_CAR_5Empty | Tip-box carriers and MFX base; `.lid` definitions for tip-box lids |
| Nimbus Labware Definitions – Tip Boxes | Nimbus tip-box pedestals, same tip boxes | |
| Installer STAR – All Wide Bore Tips (Jul 2023) | 1mL_FTR, 300uL_FTR (`.x` binary) + 11 `.rck` | Wide-bore tip racks |
| ODTC / ODTC Model 241011 | ODTC.x (8.3 MB) | Inheco ODTC thermocycler; PLR has an ODTC backend |
| MFX_CAR_ODTC_MTP | `.hxx` | MFX carrier holding an ODTC |
| PLT_CAR_L5_DWP | PLT_CAR_L5_DWP.x | Plate carrier for DWPs |
| 50 mL / 200 mL Reagent Carrier | carrier + reservoir `.x` | Reagent carriers (not the blocked RGT_CAR_3R) |
| Trough_12Col, Agilent_2Col_Reservoir | Trough, Column | Troughs |
| Alpaqua_MagEx, Invitrogen Magnetic Stand | magnet stands | PLR has Alpaqua definitions |
| BioRad_ddPCR_96, Bio-Techne (ProteinSimple Jess plate), HST_SDR_096_01 | plates/racks | |
| Agilent Plate Loc (+ `.3ds`, `.blend` source) | sealer | Includes Blender source |
| BioNex_HiG_3Dmodel, SiasCentrifuge (Sias Ixion `.hxx`) | centrifuges | |
| [MPE]2_STAR | MPE² base + unit | Positive-pressure module; PLR has MPE code |
| CO-RE Suction Tool (on 32smp / on Waste) | tool + **`smp_car_32_a00.hxx`** | An independent copy of Hamilton's SMP_CAR_32_A00 mesh, to cross-check the tube carrier import |

**Definitions only** (dimensions, no models):
- the 6/12/96-well "flat and tilted" plates;
- Axygen 24 DWP 10 mL, E&K EK2119, Enzyscreen 24 DW;
- Eppendorf 96 PCR (full blue; semi-skirted opaque 250 µL), FluidX 96 VB TuR 300 µL;
- KingFisher Presto (3 rck + 3 ctr), Micronic (6 nested zips), Nunc 96 round-bottom 0.5 mL;
- Thermo Matrix 0.5 mL rack, Thermo MicroAmp 96 PCR, VWR 96 VB DWP 2200 µL;
- TipSupport CO-RE II (8 rck);
- 14 mL Falcon tube `.ctr`, and `Ham_MLTipBox_Car_Base_1mL_A00.tml`.

The `.rck`/`.ctr` files are Venus's own dimensions (well positions, depths, volume-height segments). They can seed or check PLR resource definitions: compare with PLR, and don't copy blind.

### 4. Liquid classes
- `Hamilton Liquid Classes/LV_LiquidClasses_Surface_Part_2to10.mdb`: an Access database of low-volume surface-dispense classes. PLR's STAR liquid classes (`hamilton/star/liquid_classes/mapping.py`) could be checked against it or extended.
- `Hamilton Libraries/Liquid Class Library`: installer V1.1.1 plus `LiquidClassLibrary.chm` and `LiquidClassLibraryWhiPip.chm`, the help files, which likely document the parameters.
- `HSLLiquidClass and GetLiqClassInfo demo.zip`.

### 5. Manuals and documentation (Hamilton Guides)
- **Programmer's manuals:**
  - VENUS 6.4, 6.3.2, 6.2 and 6;
  - VENUS four operator's and programmer's manuals;
  - VENUS two and three operator's and programmer's manuals;
  - `VENUS Programming Practices v5.pdf`.
- **TADM and scheduling:** `624031_03_TADM_Programmers_Guide.pdf` (pressure monitoring: relevant to PLR TADM and failure detection), and `624030_01_VENUS_Dynamic_Scheduler_Manual.pdf`.
- **Liquid handling:** `eBook_Liquid Handling Reference Guide_Revision2_Final.pdf`, and `Liquid Verification Kit User's Manual Rev A.pdf`.
- **Devices:**
  - `HHC_Users_Manual_RevC` (Hamilton Heater Cooler);
  - `HMotion Robot Operator's and Programmer's Manual`;
  - `STAR UV Light Installation and User's Manual`;
  - Honeywell Orbit scanner documents.
- **Quick guides:** among the 11 are:
  - Teaching Off-Deck With iSWAP (relevant to the iSWAP reach question, targets beyond X 850 mm);
  - Run Two STARs From One PC;
  - RabbitMQ and VENUS;
  - Vector database;
  - Export/Import for VENUS 5 and earlier, and VENUS 6+.
- **HSL:** HSL overview slides and `HSL_and_DLLs_Overview.pptx`, `Vector_HSL_LibraryIntegration.pdf`.
- **Release notes** (VENUS Version History): VENUS 4→6 change history, 6.0.1 through 6.3.2, NIMBUS ≤ v8.

### 6. Device libraries (drivers), for PLR backends
Each is an HSL driver: PLR could port the protocol from it or check a backend against it.
- **Heating and shaking:** Hamilton Heater Cooler (HHC) HSL v2.0; Hamilton Heater Shaker (HHS) v4.4.1; Hamilton Hx Fan v1.0.
- **Liquid handling peripherals:** MPE² HSL driver v2.1; MediaFill module HSL v2.0; Media Line v3.2.1.
- **Other devices:** ApH 2.0/2.2; LabElite DeCapper; STAR UV Light v2.3.2.1; tilt module integration.
- **Methods folder:** device tests for HHC, MPE² (GUI 2.2.4) and the tilt module; `CORE_SuctionTool_v1.pkg`; `HEPA_Control_v2.00.pkg`; `Deck Animations Library Demo`; `Add Labware at Runtime`; `Clot Detection with Retry`; `Loading with Barcode Recovery`; `TipConsolidation`; `VENUS Programming Challenges`.

### 7. Libraries and tools (less relevant to PLR, but good references)
- **Hamilton Libraries:**
  - `HSLLabwrAccess` v2.04/v3.1 (reading labware definitions, which could help parse `.rck`/`.ctr`/`.tml` precisely);
  - `STAR Tools Demo` V4.0.1 plus pkg versions (220421, 230914, 240507);
  - `Get Touchoff Z Height 250915.pkg`, `Labware_Property_Query 240823.pkg`, `QueryAspiratedVolumes`, `TADM_Export_Curves`, `ChannelPatterns 231116.pkg`, `CheckCarrierPresence_V3`;
  - `Visual_NTRv1.46`, `Visual_PlateStackv1.3`, `VirtualLabware_V2`, `PlateEditor96v21`;
  - `Advanced Tip Management Library (ATML)` V3.0.2/V3.1.0;
  - `ASW Standard v16`;
  - HSL Json/Http/Xml/RabbitMQ/Time/Random libraries;
  - `Hamilton Driver Tools 4.7`;
  - `ErrorSimulator 1.0.0`, which may list firmware error codes: useful for PLR's error mapping.
- **GUIs and Tools:** `TadmCurvesExport`, `Star_Type_Converter_VENUS`, `HSM USB Serial Driver 3.5.26`, `MethodManager2`, `CustomDialogTemplateCreator`, `Convert VENUS6 File`.
- **VENUS Power Steps** v1.0.27.0 Rev C.
- **Videos:** 3 MagPip training videos (2- and 8-channel, 96- and 384-well formats).
- **SLAS 2023:** "New VENUS" and Bionano Longstring slides.

### 8. The local Venus install on this PC: the richest source, and already on disk
`C:\Program Files (x86)\HAMILTON` (not part of the shared folder, but the same family of data).
- **`LabWare\`** (546 files, 35 MB): **29 Hamilton `.hxx` models**:
  - plate carriers PLT_CAR_L4ST B00/C00/HIGH/LOW, L5AC_A00, L5MD_A00, P3AC_A00, P3MD_A01, P3LI_A00;
  - tip carriers TIP_CAR_288_C00, 384_A00, 384BC_A00, 480_A00, 480BC_A00;
  - waste: WasteBlock, Waste2, StarPlusCore96/384Waste, Core96/384SlideWaste (+ racks);
  - TeachingNeedle5ml, TeachingNeedleBlock, Verification.
  
  Also **117 `.tml` carrier templates with real site positions** (every PLT_CAR / TIP_CAR variant, including HT/LT/ST/filter, 50 µL, slim and piercing tips), 148 `.rck`, 73 `.ctr`, 8 `.lid`, `Category.dat`/`Index.dat`, and a few `.x` (300 mL reservoir with liquid, 1000 µL and 300 µL tips). These are the authoritative Venus definitions of the carriers PLR already has; several PLR carriers (L5AC, TIP_CAR_480) already have models, and the others can come from here.
- **`Config\`:**
  - `ML_Starlet.dck`, `ML_STAR.dck`, `ML_STAR2.dck`, `ML_FlexStar.dck` (+ `.tpl`): the system deck definitions (track positions, waste, fixed sites);
  - `ML_Starlet.cfg`, `ML_STAR.cfg` and `*_Simulator.cfg`: instrument configuration, likely arm travel ranges and installed modules;
  - `HamHeaterShakerUsb.cfg`;
  - **`ML_STARLiquids.mdb`**: Hamilton's full default liquid-class database. PLR's STAR liquid classes probably came from it; it's the reference for checking them.
  - `HxCoreLiquidClassesTemplate_3.mdb`, `HxCoreTadmCurvesTemplate_2.mdb` (TADM tolerance bands).
- **`Bin\*.chm` help files:**
  - **`Hxlabwr3enu.chm`**: the labware file format (`.rck`/`.ctr`/`.tml` fields), the reference for parsing definitions exactly;
  - **`HxGruCommandEnu.chm`**: GRU command reference;
  - `HxStarConfigEnu.chm`, `HxSysDeckEnu.chm` (deck), `HxTraceEnu.chm` (trace format), `HxCoreLiquidEditorEnu.chm`, `HxLabwrEdEnu.chm`, `HxProtocolSimulatorEnu.chm`, `HxStarMaintAndVerRunEnu.chm`, `HxStandardLanguageEnu.chm`.
- A second Hamilton share, "STAR Tools Suite", from the forum request thread: https://download.hamiltonsupport.com/wl/?id=XoCJWguPY7b9izjKUO524jQ2iRIu7Hbd. It holds `STAR Tools Demo 220421.pkg` (6.1 MB), which contains `STAR_MPH96_Tools.smt` (96-head tip-presence check).

### 9. Rest of the share, for completeness
- **Libraries/Previous versions:** ASW Custom Vector Dialogs v1.1.2, ErrorSimulatorLibraryv20, StepTracker v1.61.
- **Guides:**
  - Vector Database (2 ppt + model pdf);
  - SQL Materials (2 pptx);
  - Honeywell Orbit 7120 guide + MetroSelect config guide (barcode scanner);
  - Microcide SQ (disinfectant efficacy + MSDS).
- **User Created Content:** DynamicTipCondenserNoSkip.pkg, ED300 Pipetting.zip, GetRegistryValue(s).pkg, StepTracker HSL Library.zip, "Position out of permitted area.7z" (an error case, possibly with a trace), archivo.zip. `goodFaithTesting.php` looks like a stray upload; ignore it.
- **Forum:** the Venus labware editor takes `.x`/`.hxx`. Blender ≤ 2.8 exports `.x` (a VM is suggested). Hamilton documents little else; the installed `Hxlabwr3enu.chm` is the real reference.

---

## Suggested next steps, in order
0. **Local Venus library first:** convert its 29 `.hxx` carriers/waste/tip carriers with the existing converter, and check PLR carrier definitions against the 117 `.tml` templates. No downloads needed.
1. **MFX import** (set aside for now, at the user's request).
   - Convert the MFX bases and modules from the Assistant's `.x` files with a generic `.x`/`.hxx` → GLB converter, extended from `convert_tube_carrier.py`: handle frames, text `.x` and `xof 0303tzip`.
   - Recover module-on-base offsets from the local assembled `MFX_CAR_*` models (they contain the bases and modules already placed).
   - Start with the modules PLR already defines (tip, NTR, DWP) so the models can be checked against known numbers, then add the heater-shaker (HHS), CPAC and heating/cooling nests.
2. **Tip boxes and lids:** `Ham_MLTipBox_*` and `Ham_MLTipBox_Lid` (`xof 0303tzip`), and their `.lid` definitions, which cover the "lids" question for tip boxes.
3. **ODTC and MFX_CAR_ODTC_MTP**, for the ODTC backend.
4. **Motion timing:** feed the three shared `HxUsbComm*.trc` into `tools/hxusbcomm_timing.py` and `hxusbcomm_fixed.py`. Ask first, since this means pulling more trace data.
5. **Check `SMP_CAR_32_A00`** against the independent copy in the CO-RE Suction Tool archive.
6. **Liquid classes:** compare PLR's classes with `LV_LiquidClasses_Surface_Part_2to10.mdb` and the Liquid Class Library help.
