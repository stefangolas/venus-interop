"""Hamilton's NGSStar framework, NGSStarLoading (`Library\\NGSStarLoading\\NGSStarLoading.hsi`): what to load.

A kit method declares, step by step, how much of each reagent one sample takes
(`Define_VolumePerWell`; a master mix's components with `Define_VolumePerWell_MastermixComponent`),
then asks for each reagent's containers (`Calculate_TotalVolumeAndSequenceToAspirate`): how many
tubes or troughs of the given type, how much in each (samples x volume x (1 + dead %) + the
container's dead volume, split so a container holds at most its volume), the positions they stand
on (a sequence of distinct containers, and one position per sample to aspirate from), and, for a
master mix, how much of each component goes into each of its tubes (the Mastermix_Prep sheet).

The library keeps this in an Excel workbook (`RunData.xls`, sheets RunData and Mastermix_Prep)
through Venus's file object with SQL; here the sheets are `Sheet`s with the same columns, text
matched without case as Jet's Excel driver does. Container sizes, dead volumes and minimum counts
are the method's arguments, as in Venus (Avenio passes them as literals).

Kept as the library has them, though they look unintended:
- with a minimum number of containers that the first sizing misses, sizing repeats with a smaller
  maximum volume, and every pass appends its containers' volumes to the volume list returned (and
  the list the Mastermix_Prep rows read), so the list is longer than the containers;
- the display texts (DB_ReagentNameANDLabwareType) keep one decimal fewer than they round to;
- the site list (DB_SiteID, and DB_PositionID for troughs) is built onto a variable the call never
  assigns before, so it starts with that variable's value: "0", if an unassigned variable is
  integer 0 (CONVENTIONS §11); the library empties it only after a master mix.
A component's own containers (the library's other branch) are not ported: Avenio never asks.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from venus_interop.methods import sequences as sq

LIBRARY = "NGSSTARLOADING"  # the Venus namespace ported

REAGENT, MASTERMIX, COMPONENT = "Reagent", "Mastermix", "MastermixComponent"  # ARW_Global::ReagentType
RUNDATA = ["DB_VolumePerWell", "DB_DeadVolumeLabware", "DB_DeadVolumePercent", "DB_TotalVolume", "DB_CarrierName",
           "DB_SiteID", "DB_Units", "DB_LabwareType", "DB_LabwareName", "DB_PositionID", "DB_ReagentName",
           "DB_MasterMixComponentName", "DB_ReagentType", "DB_PrepareMastermixOnDeck", "DB_Ratio",
           "DB_ReagentNameANDLabwareType"]

class LabwareType:
  """ARW_Global::LabwareType: the names the loading texts show for a container type."""
  HamiltonTrough50mL = "50mL Trough"
  Tube5mL = "tube 4ml Sarstedt"
  Sarstedt_Tube_2mL = "vial 2mL Sarstedt"
  ScrewCap_Tube_1500uL = "Vial 1.5ml Roche (original tube)"
  Sarstedt_Tube_1500uL = "Vial 1.5ml Eppendorf"
  Sarstedt_Tube_500uL = "Vial 0.5ml Sarsdtedt"
  ScrewCap_Tube_500uL = "Vial 0.5ml Roche (original tube)"
  MIDI_Plate = "MIDI Plate"
  HSP_Plate = "HSP Plate"
  Comfortlid = "Comfortlid"
  TIP50 = "50uL Tips"
  TIP300 = "300uL Tips"
  TIP1000 = "1000uL Tips"
  TIPAdapter = "Tip Adapter"


PLT_TIP1000 = "PLT_CAR_2TIP_2PCR_MTP"  # ARW_Global::CarrierType: the carrier with 1000 uL tips and plates
TIP_SLOTS = {LabwareType.TIP50: 10, LabwareType.TIP300: 10, LabwareType.TIP1000: 2}  # ARW_Global::TipLocations

MASTERMIX_PREP = ["Mastermix_ID", "Component_ID", "Ratio", "MastermixTube_ID", "MastermixTube_LabwareID",
                  "VolumeMastermixPerTube", "VolumeComponentPerTube", "SourceComponentTube_ID",
                  "SourceComponentTube_LabwareID", "SourceVolumeComponentPerTube"]


def _same(a, b) -> bool:
  return a.casefold() == b.casefold() if isinstance(a, str) and isinstance(b, str) else a == b


class Sheet:
  """A workbook sheet as the library's SQL uses it: rows of column -> value (None: an empty cell)."""

  def __init__(self, columns: list[str]):
    self.columns, self.rows = columns, []

  def where(self, column: str, value) -> list[dict]:
    return [r for r in self.rows if _same(r[column], value)]

  def update(self, column: str, value, **cells) -> None:
    for r in self.where(column, value):
      r.update(cells)

  def append(self, **cells) -> None:
    self.rows.append({c: cells.get(c) for c in self.columns})


def mth_round(x: float, places: int) -> float:
  """HSLMthLibImpl's MthRound: half up, from the floor."""
  whole = math.floor(x)
  r = whole + math.floor(10.0 ** places * (x - whole) + 0.5) / 10.0 ** places
  return math.floor(r) if places == 0 else r


def _text(v) -> str:
  """A number as HSL's string concatenation writes it (as the interpreter models it; unverified)."""
  if isinstance(v, float):
    return str(int(v)) if v.is_integer() else repr(v)
  return str(v)


def _volume_text(v: float) -> str:
  """_GenerateString / _Reformat_ValuesForDialog: mL above 3000 uL; rounded to 3 places (2 above
  3000 uL or 3 mL), then cut at the point's index plus the places, which keeps one fewer."""
  value, units, top = (v / 1000.0, "mL", 3) if v > 3000 else (v, "uL", 3000)
  places = 3 if value <= top else 2
  s = _text(mth_round(value, places))
  i = s.find(".")
  return (s[:i + places] if i != -1 else s) + units


class NGSStarLoading:
  def __init__(self, deck, ngsstar: bool = True):
    """`deck`: `seq(name)` (live sequences) and `layout` (the layout file, for carriers and sites).
    `ngsstar`: an NGS STAR (8 channels) rather than a Clinical NGS STARlet (4)."""
    self.v = deck
    self.DATA_HandOverDataToSMT_NGSStarLoading(ngsstar=ngsstar)

  def DATA_HandOverDataToSMT_NGSStarLoading(self, report_file: str = "", platform: int = 1, kit_provider: str = "",
                                            kit_name: str = "", mph_used: int = 0, lock_unlock: int = 0,
                                            *_tips_and_counters, ngsstar: Optional[bool] = None) -> None:
    """The run's start: the platform, a fresh RunData workbook, the trough bookkeeping emptied.
    The report file, pictures and the operator's tip dialogs are not ported."""
    self.ngsstar = platform == 1 if ngsstar is None else ngsstar
    self.run_data, self.mastermix_prep = Sheet(RUNDATA), Sheet(MASTERMIX_PREP)
    self.rgt_total_volume: list[float] = []  # t_arr_flt_RGT_TotalVolume, ..._RGT_ReagentName
    self.rgt_reagent_name: list[str] = []
    self.rgt_sequences: list[sq.Sequence] = []  # t_arr_seq_RGT_SequencesToAspirate
    self.last_mastermix_name = ""

  # -- what one sample takes -----------------------------------------------------------------

  def Define_VolumePerWell(self, liquid: str, volume_per_sample: float) -> float:
    """Add a use of `liquid` to its row (a new Reagent row when it has none)."""
    rows = self.run_data.where("DB_ReagentName", liquid)
    if rows:
      total = sum((r["DB_VolumePerWell"] or 0) for r in rows) + volume_per_sample
      self.run_data.update("DB_ReagentName", liquid, DB_VolumePerWell=total)
    else:
      self.run_data.append(DB_VolumePerWell=volume_per_sample, DB_ReagentName=liquid, DB_ReagentType=REAGENT)
    return volume_per_sample

  def Define_VolumePerWell_MastermixComponent(self, mastermix: str, component: str, volume_per_sample: float) -> float:
    """Make `mastermix` a master mix (ratio 1) and add a component row, "<component> - <mastermix>",
    with its share of the master mix's volume per sample."""
    self.run_data.update("DB_ReagentName", mastermix, DB_Ratio=1.0, DB_ReagentType=MASTERMIX)
    mm_volume = self.run_data.where("DB_ReagentName", mastermix)[0]["DB_VolumePerWell"]
    self.run_data.append(DB_VolumePerWell=volume_per_sample, DB_ReagentName=f"{component} - {mastermix}",
                         DB_ReagentType=COMPONENT, DB_MasterMixComponentName=component,
                         DB_Ratio=volume_per_sample / mm_volume)
    return volume_per_sample

  # -- what to load --------------------------------------------------------------------------

  def _carrier_and_site(self, labware: str) -> tuple[str, str]:
    """_GetCarrierIDandSiteID_FromLabID: the labware's carrier (itself when it has none) and site."""
    p = next((q for q in self.v.layout.labware if q.id == labware), None)
    carrier = p.fields.get("Template", "") if p is not None else ""
    return (labware if carrier == "default" else carrier), (p.fields.get("SiteId", "") if p is not None else "")

  def _channel_positions(self) -> list[str]:
    """A trough's positions, one per channel: 1-8, or 2, 4, 6, 8 for four channels."""
    return [str(i) for i in (range(1, 9) if self.ngsstar else range(2, 9, 2))]

  def Calculate_TotalVolumeAndSequenceToAspirate(self, ML_STAR, reagent: str, samples: int, labware_type: str,
                                                 max_volume: float, dead_volume_labware: float,
                                                 dead_volume_percent: float, template: str, starting_point: int,
                                                 min_containers: int):
    """The containers for `reagent` on `template`'s positions (from `starting_point`, or its current
    one when 0; the template is moved past them). Returns (the distinct containers, a position per
    sample, the volume per container); RunData gets the totals, a master mix's tubes Mastermix_Prep."""
    return self._calculate(reagent, samples, labware_type, max_volume, dead_volume_labware, dead_volume_percent,
                           template, starting_point, min_containers, fixed=False)

  def Calculate_TotalVolumeAndSequenceToAspirate_FixedTubeNumber(self, ML_STAR, reagent: str, samples: int,
                                                                 labware_type: str, max_volume: float,
                                                                 dead_volume_labware: float, dead_volume_percent: float,
                                                                 template: str, starting_point: int, containers: int):
    """The same with exactly `containers` containers, whatever their volume. Kept as the library has
    it: a count that doesn't divide the samples adds the remainder to them, once, and each container
    is sized for the whole part (10 samples in 4 tubes: 12, 3 each; 11: 14, still 3 each, 12)."""
    return self._calculate(reagent, samples, labware_type, max_volume, dead_volume_labware, dead_volume_percent,
                           template, starting_point, containers, fixed=True)

  def _calculate(self, reagent, samples, labware_type, max_volume, dead_volume_labware, dead_volume_percent, template,
                 starting_point, min_containers, fixed):
    tpl = self.v.seq(template)
    if samples <= min_containers:
      min_containers = samples
    found = self.run_data.where("DB_ReagentName", reagent)
    if not found:
      if any(_same(r["DB_MasterMixComponentName"], reagent) and r["DB_ReagentType"] == COMPONENT
             for r in self.run_data.rows):
        raise NotImplementedError(f"NGSStarLoading: containers for the master mix component {reagent!r}")
      return sq.Sequence("distinct", []), sq.Sequence("samples", []), []  # "Reagent ... DOES NOT EXIST"
    row = found[-1]
    if not row["DB_VolumePerWell"]:
      return sq.Sequence("distinct", []), sq.Sequence("samples", []), []
    names, types, volumes = [reagent], [row["DB_ReagentType"]], [row["DB_VolumePerWell"]]
    per_sample_mix = row["DB_VolumePerWell"]
    components: list[str] = []
    is_reagent = row["DB_ReagentType"] != MASTERMIX
    if not is_reagent:  # the master mix's components: rows naming it, of the component type
      for r in self.run_data.rows:
        if reagent in (r["DB_ReagentName"] or "") and r["DB_ReagentType"] == COMPONENT:
          components.append(r["DB_MasterMixComponentName"])
          names.append(r["DB_ReagentName"])
          volumes.append(r["DB_VolumePerWell"])
          types.append(r["DB_ReagentType"])
    per_container_all, ratios, tube_ids, tube_labware = [], [], [], []
    out_volumes: list[float] = []
    distinct = samples_seq = None
    containers = total_for_mix = 0
    dead_lab, dead_pct, type_id = dead_volume_labware, dead_volume_percent, labware_type
    carrier, site_ids = "", "0"  # the never-assigned site list: integer 0 (see the module docstring)
    define = True
    for k, (name, kind, volume) in enumerate(zip(names, types, volumes), start=1):
      if kind == COMPONENT:
        define = False
      factor = dead_pct / 100.0 + 1.0
      if kind == COMPONENT:  # Calculate_TotalVolume_MastermixComponent
        per_sample = volume
        needed = volume * total_for_mix / per_sample_mix
        ratio = volume / per_sample_mix
        ratios.append(ratio)
        self.run_data.update("DB_ReagentName", name, DB_TotalVolume=needed,
                             DB_ReagentNameANDLabwareType=f"{name}-->[{_volume_text(needed)}]",
                             DB_Ratio=mth_round(ratio, 2))
        update = False
      else:
        self.last_mastermix_name = reagent
        if fixed and min_containers:
          samples += samples % min_containers
        per_sample, needed, update = volume, samples * volume, True
      needed *= factor
      min_containers = min_containers or 1
      top, passes, required, display = max_volume, 0, 0.0, ""
      while containers < min_containers:
        passes += 1
        room = top - dead_lab
        containers = min_containers if fixed else math.ceil(needed / room)
        most = math.floor(room / (per_sample * factor))
        if most == 0:
          each = needed / containers
          sizes = [each] * containers
          required = needed
        else:
          containers = min_containers if fixed else math.ceil(samples / most)
          base, extra = samples // containers, 0 if fixed else samples % containers
          sizes = [mth_round((base + 1) * per_sample * factor + dead_lab, 1)] * extra
          each = mth_round(base * per_sample * factor + dead_lab, 1)
          sizes += [each] * (containers - extra)
          required = 0.0
          for size in sizes:
            required += size
        for size in sizes:
          if k == 1:
            out_volumes.append(size)
          per_container_all.append(size)
          if "RGT" in (tpl.current_item() or ("", ""))[0]:
            self.rgt_total_volume.append(size)
            self.rgt_reagent_name.append(name)
        display = f"{reagent}-->{containers} x {type_id}" + "".join(f" [{_volume_text(s)}]" for s in sizes)
        if containers < min_containers:
          top = each - 0.1
        if passes == 200:  # Venus shows "Cannot define n containers" and goes on
          break
      if define:
        if starting_point:
          tpl.set_current_position(starting_point)
        items, positions, labware_ids = [], "", ""
        for c in range(1, containers + 1):
          lab, pos = tpl.current_item() or ("", "")  # past the end: an empty item, as in Venus
          last = c == containers
          carrier, site = self._carrier_and_site(lab)
          if "RGT" in lab:
            trough = [(lab, p) for p in self._channel_positions()]
            items += trough
            self.rgt_sequences.append(sq.Sequence(f"{lab}_trough", trough))
            pos = trough[-1][1]
            site_ids += site + ("" if last else ",")
            labware_ids += lab + ("" if last else ";")
            positions = site_ids
          else:
            items.append((lab, pos))
            positions += pos + ("" if last else ",")
            site_ids += site + ("" if last else ";")
            labware_ids += lab + ("" if last else ";")
          tube_ids.append(pos)
          tube_labware.append(lab)
          tpl.increment(1)
        distinct = sq.Sequence("distinct", list(items))
        trough_last = bool(items) and "RGT" in items[-1][0]
        samples_seq = sq.Sequence("samples", list(items) if trough_last else
                                  [items[i % len(items)] for i in range(samples)] if items else [])
      if update:
        self.run_data.update("DB_ReagentName", name, DB_DeadVolumeLabware=dead_lab, DB_DeadVolumePercent=dead_pct,
                             DB_TotalVolume=required, DB_Units=containers, DB_LabwareType=type_id,
                             DB_ReagentNameANDLabwareType=display, DB_CarrierName=carrier, DB_SiteID=site_ids,
                             DB_PositionID=positions, DB_LabwareName=labware_ids)
      if k == 1:  # the master mix done: its components follow without dead volumes
        total_for_mix = required
        dead_lab = dead_pct = 0
        containers, type_id, carrier, site_ids = 0, "", "", ""
    distinct = distinct or sq.Sequence("distinct", [])
    if not is_reagent:  # a row per master-mix tube and component
      for i in range(distinct.total):
        for comp, ratio in zip(components, ratios):
          self.mastermix_prep.append(
            Mastermix_ID=reagent, Component_ID=comp, Ratio=ratio, MastermixTube_ID=tube_ids[i],
            MastermixTube_LabwareID=tube_labware[i], VolumeMastermixPerTube=per_container_all[i],
            VolumeComponentPerTube=per_container_all[i] * ratio, SourceComponentTube_ID="",
            SourceComponentTube_LabwareID="", SourceVolumeComponentPerTube="")
    return distinct, samples_seq or sq.Sequence("samples", []), out_volumes

  def Calculate_ReformatSequenceToMatchNumberOfSamples(self, ML_STAR, starting_point: int, template: str,
                                                       samples: int) -> sq.Sequence:
    """A position per sample, cycling as many template positions as its current labware has
    (counted before moving to `starting_point`, or its current one when 0, so a late start runs
    past the end: an empty item, then position 1 again); a trough (an "RGT" labware) gives its
    channel positions and is kept as a trough to aspirate from. The template itself is not moved."""
    tpl = self.v.seq(template).copy()
    count = tpl.position_count_for_current_labware()
    if starting_point:
      tpl.set_current_position(starting_point)
    items = []
    for _ in range(count):
      lab, pos = tpl.current_item() or ("", "")
      if "RGT" in lab:
        trough = [(lab, p) for p in self._channel_positions()]
        items += trough
        self.rgt_sequences.append(sq.Sequence(f"{lab}_trough", trough))
      else:
        items.append((lab, pos))
      tpl.increment(1)
    return sq.Sequence("samples", [items[i % len(items)] for i in range(samples)] if items else [])

  # -- labware a process uses ----------------------------------------------------------------

  def Add_LabwareForCurrentProcess(self, ML_STAR, labware_type: str, labware_name: str, units: int, template: str,
                                   position_in_sequence=0) -> None:
    """RunData rows for `units` of a labware on `template` (plates, lids, tips), for the loading
    display: a row per carrier the template's labware stands on, or, when the row exists, its unit
    count raised (on every row of that type and name). Kept as the library has them: a carrier's
    site is its own distinct sites' entry at the carrier's index; whether the labware is on a tube
    carrier (a site "...T-...": the position is the row's) is judged by the last labware; a tip
    adapter's row keeps the previous carrier's position."""
    if not units:
      return
    tpl = self.v.seq(template)
    found = [r for r in self.run_data.rows if _same(r["DB_LabwareType"], labware_type)
             and _same(r["DB_ReagentName"], labware_name) and _same(r["DB_LabwareName"], template)]
    if found:
      cells = {"DB_Units": (found[-1]["DB_Units"] or 0) + units}
      if "T-" in self._carrier_and_site((tpl.current_item() or ("", ""))[0])[1]:  # not checked against the HSL
        tokens = f"{found[-1]['DB_PositionID'] or ''},{position_in_sequence}".split(",")
        cells["DB_PositionID"] = ",".join(sorted(tokens))
      for r in self.run_data.rows:
        if _same(r["DB_LabwareType"], labware_type) and _same(r["DB_ReagentName"], labware_name):
          r.update(cells)
      return
    labware = list(dict.fromkeys(lab for lab, _ in tpl.items))
    places = [self._carrier_and_site(lab) for lab in labware]
    tube = bool(places) and "T-" in places[-1][1]
    position = ""
    for k, carrier in enumerate(dict.fromkeys(c for c, _ in places)):
      sites = list(dict.fromkeys(s for c, s in places if c == carrier))
      site = sites[k] if k < len(sites) else ""  # ElementAt past the end: CONVENTIONS Â§11
      if tube:
        position = str(position_in_sequence)
      elif "TIP" in carrier and PLT_TIP1000 not in carrier:
        slots = TIP_SLOTS.get(labware_type, 0)  # an unassigned variable otherwise
        if labware_type == LabwareType.TIPAdapter:
          site = "Tip Adapter"
        else:
          position = f"1 - {slots}"
      else:
        position = ",".join(sites)
      self.run_data.append(DB_VolumePerWell=0, DB_DeadVolumeLabware=0, DB_DeadVolumePercent=0, DB_TotalVolume=0,
                           DB_CarrierName=carrier, DB_SiteID=site, DB_Units=units, DB_LabwareType=labware_type,
                           DB_LabwareName=template, DB_PositionID=position, DB_ReagentName=labware_name,
                           DB_MasterMixComponentName="", DB_ReagentType="LabwareResource", DB_PrepareMastermixOnDeck=0,
                           DB_ReagentNameANDLabwareType=labware_name if labware_type == labware_name
                           else f"{labware_type} ({labware_name})")
