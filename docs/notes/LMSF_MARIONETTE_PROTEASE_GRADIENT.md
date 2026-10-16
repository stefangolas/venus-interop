# NIST LMSF protocol: Marionette protease gradient plate prep v5

Reconstructed 2026-10-16 from `Methods/GSF-IMS Project/E. coli Methods/Marionette Gradient Plate Prep/Marionette protease.gradient plate prep.v5.*` via the decompiler traces (`.local/session_state/analysis/traces/Marionette protease.gradient plate prep.v5.{trace,condensed}.md`). Companion to the GROQ-Seq methods: it prepares **plates 2–5** of the growth-selection workflow. Despite the name, the trace shows the pharmacology is **TMP (selector) + salicylate at two gradient maxima + vancomycin gradient** — "protease" is the strain panel, not a reagent (inference; nothing protease-related appears in the code).

Re-checked 2026-10-16 against the longer trace that includes the shared libraries' `private` functions. The check corrected the channel counts and added the shape checks below.

## What it does

Fills a 96-well Growth Plate with media plus a two-dimensional inducer landscape: a constant TMP background, salicylate gradient segments at two maxima (defaults 35 and 50), and a vancomycin dilution-series gradient — each well group dosed so every well finishes at the same final volume after all additions *and* the dilution-series withdrawals. Per-well inducer/additive concentrations are written back onto the sequence as properties and exported to the worklist + metadata files for the Overlord chain.

## Parameters (`parameters.csv` → defaults/logic)

`worklistFile` · `strain1` · `plasmid1..4` · `inducer1` (vancomycin; +`StockConc/StockUnits`) · `inducer2` (salicylate) with `inducer2_1/2StockConc` (two stocks) · `selector1` (TMP) with `selector1StockConc/StockUnits` · `isPipetting`, `isDebugging` (dialogs) · `cultureVolume` (200–500, default 500) · `plateNum` (2–5; `first_tmp_plate = 3` switches the TMP reference volumes) · `dilutionFactor` · `vanStockDilution` · `salTmpStockDilution` · `dilutionSeriesFactor` · optional `inducer2_1/2_grad_max_conc` (defaults 35 / 50).

## The volume model (all per well)

```
cell_volume            = culture_volume / dilution_factor
media_volume           = culture_volume − cell_volume
multiplier             = f / (f − 1)              where f = dilutionSeriesFactor
dil_series_transf_vol  = media_volume × multiplier − media_volume   (volume moved per gradient step)
tmp_volume             = tmp_ref_volume / sal_tmp_stock_dilution    (0 on no-TMP wells)
van_volume             = inducer_ref_volume / van_stock_dilution
sal_X_grad_start_dil   = sal_X_stock_conc / sal_X_grad_max_conc
sal_X_grad_start_vol   = (inducer_ref_volume / sal_X_grad_start_dil) × multiplier
grad_start_*_volume    = plain well volume × multiplier             (gradient start wells are over-filled
                                                                    because the series withdraws transfer volume)
```

`inducer_ref_volume`/`tmp_ref_volume` reference `culture_volume` on plate 2 and `media_volume` from plate 3 on (`first_tmp_plate = 3`).

## Well groups (sequences on the Growth Plate)

`regular_wells_with_tmp_sal_grad` · `regular_wells_with_tmp_van_grad` · `sal_1_grad_start` · `sal_2_grad_start` · `van_grad_start_wells_with_tmp` · `regular_wells_no_tmp_no_van` · `regular_wells_no_tmp_with_van` · `van_gradient_pipette_from/to` · `sal_grad_pipette_from/to` (+ per-group `calc_*` copies for the concentration bookkeeping).

## The protocol

1. **Deck setup:** the Growth Plate moves from Handoff to its position with its lid (`MovePlateWithLidAndTap`: grip height 11, width 80, force 5, placed 1 mm high; see the plate-move notes in `LMSF_DNA_EXTRACTION.md`). Then its lid comes off; media trough lid off; reagent stock plate lid off.
2. **Media fills** (1000 µL filtered tips, **4 channels**, `pipette_media` with pre-wet on the first fill; the media volume for each group is `media_volume` **minus** every additive that will arrive later, so final volumes equalise):
   - TMP+sal-gradient wells: `media_volume − tmp_volume`
   - TMP+van-gradient wells: `media_volume − van_grad_add_sal_vol − tmp_volume`
   - sal-1 / sal-2 gradient starts: `grad_start_media_volume_0 − grad_start_sal_X_volume − grad_start_tmp_volume`
   - van gradient start: `grad_start_media_volume_0 − grad_start_van_volume − van_grad_start_add_sal_vol − grad_start_tmp_volume`
   - plain wells: `media_volume` (± van on `no_tmp_with_van`)
3. **Salicylate** (300 µL filtered tips, **4 channels**; tips are *reused* across the three target groups, with fresh tips for Sal-2; `add_reagent_reuse_tips` = pre-wet, aspirate, dispense): Sal-1 stock → `sal_1_grad_start`, van-gradient-start wells, and the sal-1 regular wells; then the same with Sal-2 stock.
4. **TMP** (300 µL filtered tips, **8 channels**, new tips per group; `add_reagent_replace_tips`): into both regular TMP groups and both gradient-start groups at `tmp_volume` / `grad_start_tmp_volume`.
5. **Vancomycin** (1000 µL filtered tips, new tips): van gradient start at `grad_start_van_volume` on **8 channels** from `Van_stock_1`; regular no-TMP wells at `van_volume` on **4 channels** from `Van_stock_1_4`.
6. **The gradients** (`pipette_dil_series`, 1000 µL filtered tips, **8 channels**, liquid class `HighVolumeFilter_Water_FastMixing_DispenseSurface_Empty`, with a mix of 2 × the transfer volume done as part of the aspirate): transfer `dil_series_transf_vol` well-to-well along `van_gradient_pipette_from→to` and `sal_grad_pipette_from→to`, diluting by `dilutionSeriesFactor` per step.
7. **Bookkeeping:** sequence indexes reset, lids back (media trough, reagent stock, growth plate).
8. **CalculateOutputs:** zeroes `inducer_1_conc`/`inducer_2_conc`/`additive_conc` on all 96 wells, then stamps per-group concentrations (`tmp_conc = selector1StockConc / sal_tmp_stock_dilution`; `sal_X = stock/dil` at starts, `/(f)` per gradient step; `van_conc` likewise) and copies plasmid/strain IDs from the short sequences onto the Growth Plate properties.
9. **SaveWorklistAndMetadata:** writes the worklist CSV (inducer1/inducer2/selector concentrations) and the metadata file for the Overlord chain.
10. **CleanUp:** tip counters written, head/arm parked.

## Notes

- **Channel counts are mixed.** Media and salicylate run on 4 channels, as does vancomycin into the regular wells. TMP, the vancomycin gradient start and both dilution series run on 8 channels. (The first version of this note said everything was 4-channel; that was wrong.)
- **Shape checks before each media, reagent and dilution transfer** (private helpers in the shared sub-method library):
  - `check_seq_lengths_and_channels` raises an error unless the source sequence has exactly `number_channels` positions and the destination a whole multiple of it. So the 4-channel trough sequences (`*_4`) are four positions and every well group comes in multiples of 4 or 8.
  - `check_same_seq_lengths` requires the dilution series' from and to sequences to be the same length.
  - `set_channel_pattern` turns `number_channels` into the first-N pattern (`11110000`, `11111111`).
- The two pipetting helper libraries (`tip_pickup`/`pipette_media`/`pipette_dil_series`, `add_reagent_*`) carry all the error handling, so the method body is pure volume logistics.
- The **gradient-start multiplier** trick (over-fill by `f/(f−1)`) keeps every well's final volume equal after the series withdraws `media_volume/(f−1)` per step — the arithmetic centre of the method.
- Same operator fallbacks as the rest of the lab's methods (`isPipetting=false` → dialogs), same tip counters, same `LMSF_FrontEnd` parameters contract.
