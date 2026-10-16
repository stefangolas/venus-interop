"""The Chory lab tissue-culture STARlet deck, hand-built in PyLabRobot.

Source: `Robot_Code/tissue_culture/test_environment/scripts/deck.lay` (read with
`hamilton_library/venus_files.py`), with `labware.py`, `sample.py`, `dilute.py` and
`tissue_culture_utils.py` for what the methods do with each position. As for the KAPA deck
(`../kapa/VENUS_TO_PLR.md`): the layout says *what* stands *where*; carrier and labware
positions come from PLR factories. Where no factory exists (the lab's 3D-printed labware, the
instrument trays off the deck) the layout's coordinates are used, and `VENUS_TO_PLR.md` beside
this file records each decision and what is still unknown.

Venus site k on a 5-position carrier counts from the back; PLR's index 5 - k counts from the front.

The three 3D-printed pieces carry their own models (`models/`, built by `build_models.py` from
the lab's STLs). They are lab hardware, so they stay in scratch, never in the repo.
"""

import os
from dataclasses import dataclass
from typing import Dict, List, Optional

from pylabrobot.hamilton.star.device import STARDevice, STARLet
from pylabrobot.resources import (
  Coordinate,
  Lid,
  Plate,
  PlateHolder,
  Resource,
  ResourceHolder,
  Rotation,
  Trash,
  Trough,
  Well,
)
from pylabrobot.resources.greiner.plates import (
  Greiner_384_wellplate_28ul_Fb_Lid,
  greiner_384_wellplate_152uL_Fb_black,
)
from pylabrobot.resources.hamilton import (
  PLT_CAR_L5AC_A00,
  STARLetDeck,
  TIP_CAR_480BC_A00,
  hamilton_96_tiprack_300uL_filter,
  hamilton_96_tiprack_1000uL_filter,
)
from pylabrobot.resources.tip_rack import TipRack
from pylabrobot.resources.corning.plates import cor_96_wellplate_360uL_Fb
from pylabrobot.resources.thermo_fisher.plates import thermo_TS_abgene_96_wellplate_800uL_Vb
from pylabrobot.resources.utils import create_ordered_items_2d
from pylabrobot.resources.well import CrossSectionType, WellBottomType

MODELS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")

DECK_Z = 100.0  # the deck surface, where every carrier stands


def venus(site: int) -> int:
  """PLR's front-first index for Venus's back-first site on a 5-position carrier."""
  return 5 - site


def _mesh(name: str) -> dict:
  """A declared mesh for a model built by `build_models.py`: in the resource's frame, metres, Z up."""
  return {"path": os.path.join(MODELS, f"{name}.glb"), "units": "m", "up": "Z"}


# -- labware without a PLR factory ----------------------------------------------------------------


def hamilton_96_wellplate_1200uL_Ub(name: str, lid: Optional[Lid] = None) -> Plate:
  """Hamilton 1.2 mL deep-well plate, 96 round wells (P/N 235655), from Venus's HAM_DW_12_ml.rck
  and HAM_12_ml.ctr: 127 x 86 x 41, A1 14.0 from the left and 11.5 from the back, wells 6.9 across
  and 36.8 deep with their floor 3.6 above the plate's bottom, 1 mm of plastic under it. The
  container is two segments (7.0 and 6.4 mm) Venus's format does not name here; U-bottom is a guess.
  """
  return Plate(
    name=name,
    size_x=127.0,
    size_y=86.0,
    size_z=41.0,
    lid=lid,
    model="hamilton_96_wellplate_1200uL_Ub",
    ordered_items=create_ordered_items_2d(
      Well,
      num_items_x=12,
      num_items_y=8,
      dx=14.0 - 6.9 / 2,
      dy=(86.0 - 11.5 - 63.0) - 6.9 / 2,
      dz=3.6,
      item_dx=9.0,
      item_dy=9.0,
      size_x=6.9,
      size_y=6.9,
      size_z=36.8,
      bottom_type=WellBottomType.U,
      cross_section_type=CrossSectionType.CIRCLE,
      material_z_thickness=1.0,
      max_volume=1200.0,
      name_prefix=name,
    ),
  )


def greiner_384_lid(name: str) -> Lid:
  """Greiner's 384 lid. Nesting from Venus's Gre_384_Sq.lid on Gre_384_Sq.rck: the covered stack
  is 15.85 on a 14.5 plate with a 6.15 lid, so the lid sinks 4.8."""
  return Greiner_384_wellplate_28ul_Fb_Lid(name, nesting_z_height=14.5 + 6.15 - 15.85)


def sample_plate(name: str) -> Plate:
  """A CellTiter-Blue sample plate (Venus GREINER\\Gre_384_Sq: 3.75 mm square wells 11.65 deep,
  about 160 uL) with its lid. Greiner's black 781209 is PLR's nearest: 3.8 -> 3.6 mm wells, 11.5
  deep, 152 uL. Which Greiner 384 the lab buys is not in the layout."""
  return greiner_384_wellplate_152uL_Fb_black(name, lid=greiner_384_lid(f"{name}_lid"))


def culture_plate(name: str) -> Plate:
  """The culture plate: a black flat-bottom Costar (Corning 3603) with its lid. Venus stands in a
  Nunc 96 (NUNC\\Nun_96_Fl_Lb) for it."""
  return cor_96_wellplate_360uL_Fb(name, with_lid=True)


def deep_well_plate(name: str) -> Plate:
  """Venus's HAM_DW_12_ml (Hamilton 1.2 mL DWP, 41 tall), drawn as an Abgene MIDI plate for the
  look; the geometry is the MIDI's (`hamilton_96_wellplate_1200uL_Ub` keeps Venus's numbers)."""
  return thermo_TS_abgene_96_wellplate_800uL_Vb(name)


# -- the 3D-printed labware ------------------------------------------------------------------------


class WashStation(Resource):
  """The 96-head's wash station, left of track 1: two printed bodies, 2 x 4 reservoirs, filled by the
  lab's pumps. Frame: `tc_wash_station.glb` (origin at the left, the front, and the bottom of the
  three runners it stands on). The reservoirs, measured on the STL by ray casts: 112 x 72 inside,
  columns 125 apart, rows 90 apart, floor 25.0 above the runners, rim 117.0.

  Rows count from the front. Left column: the four water rinses; right column: the tip-rinse
  waste and bleach on the front two rows. The right column's back two rows are not in the
  layout (unused by the scripts, or not plumbed)."""

  RESERVOIR_X = (13.68, 138.68)  # left walls of the left and right column's reservoirs
  RESERVOIR_Y = (124.05, 214.05, 304.05, 394.05)  # front walls, front row first
  FLOOR_Z = 13.73 + 11.3
  RIM_Z = 105.73 + 11.3

  def __init__(self, name: str):
    super().__init__(name, size_x=260.0, size_y=484.0, size_z=117.03, category="wash_station",
                     model="tc_wash_station")
    self.mesh = _mesh("tc_wash_station")
    names = {
      (0, 0): "water_0", (0, 1): "water_1", (0, 2): "water_2", (0, 3): "water_3",
      (1, 0): "waste", (1, 1): "bleach", (1, 2): "right_2", (1, 3): "right_3",
    }
    self.reservoirs: Dict[str, Trough] = {}
    for (column, row), reservoir in names.items():
      trough = Trough(
        f"{name}_{reservoir}", size_x=112.0, size_y=72.0, size_z=self.RIM_Z - self.FLOOR_Z,
        max_volume=112.0 * 72.0 * (self.RIM_Z - self.FLOOR_Z), material_z_thickness=3.0,
        bottom_type="flat",
      )
      self.assign_child_resource(
        trough, location=Coordinate(self.RESERVOIR_X[column], self.RESERVOIR_Y[row], self.FLOOR_Z)
      )
      self.reservoirs[reservoir] = trough


class ReagentTrough(Resource):
  """The 4-channel reagent trough on an SBS footprint (`reagent_trough_4.stl`), barbs to the front.

  Channels, left to right on the deck, by the scripts' `trough_column_to_poss`: 0 CellTiter-Blue,
  1 and 2 spare, 3 media (the wide one). V-bottomed, floor 15.0 above the trough's bottom, rim 40.0.
  Measured on the STL (turned 180) by ray casts: openings 10.7 wide from 29.61, 47.61 and 65.61
  from the left, the wide one 22.8 from 86.61; floors 70 long from 8.49 at the front. The pocket
  at the left (3.9..25.9) is open underneath: not a channel.

  Uncovered. Venus puts a Nunc lid over it (`reagent_trough_lid` / `_lid_lid`), but no script moves
  that lid and the channels pipette from the trough throughout: a lid position, not a cover."""

  CHANNELS = ((29.61, 10.7), (47.61, 10.7), (65.61, 10.7), (86.61, 22.8))  # (left edge, width)
  FLOOR_Z = 15.05
  RIM_Z = 40.05

  def __init__(self, name: str):
    super().__init__(name, size_x=127.0, size_y=85.0, size_z=45.0, category="trough_plate",
                     model="tc_reagent_trough")
    self.mesh = _mesh("tc_reagent_trough")
    self.channels: List[Trough] = []
    for i, (left, width) in enumerate(self.CHANNELS):
      depth = self.RIM_Z - self.FLOOR_Z
      trough = Trough(
        f"{name}_channel_{i}", size_x=width, size_y=70.0, size_z=depth,
        max_volume=0.5 * width * 70.0 * depth, material_z_thickness=2.0, bottom_type="V",
      )
      self.assign_child_resource(trough, location=Coordinate(left, 8.49, self.FLOOR_Z))
      self.channels.append(trough)


class SingleChannelBath(Resource):
  """A single-channel bath standing in a one-track gap between carriers
  (`short_single_channel_4.stl`): a 9 mm channel 114 long for 8 channels, overflowing into a moat
  that drains. Its body is one track wide; a keel runs underneath and a handle hangs over the
  deck's front edge, as a carrier's does. Measured on the STL: channel 34.6..43.6 in X and
  117.7..231.7 in Y of this frame, floor 18.96 above the keel, rim 78.96."""

  def __init__(self, name: str):
    super().__init__(name, size_x=38.0, size_y=259.56, size_z=83.0, category="trough_holder",
                     model="tc_single_channel")
    self.mesh = _mesh("tc_single_channel")
    self.channel = Trough(
      f"{name}_channel", size_x=9.0, size_y=114.0, size_z=60.0, max_volume=9.0 * 114.0 * 60.0,
      material_z_thickness=2.0, bottom_type="U",
    )
    self.assign_child_resource(self.channel, location=Coordinate(14.59, 117.73, 18.96))

  # Where the channel's centre is in X, in this frame: set the bath by it, over a track's centre.
  CHANNEL_CENTRE_X = 14.59 + 4.5


# -- the instrument trays off the deck -------------------------------------------------------------

TRAY_Z = 4.0  # a drawn tray's thickness under the plate: a stand-in, the trays are not modelled


def tray(name: str) -> PlateHolder:
  """Where an instrument takes a plate (the Cytomat's transfer station, the reader's tray, the
  microscope's stage), drawn as a 4 mm plate-sized pad under the plate. The trays themselves are
  not modelled; the pad's top is where the layout puts the plate's bottom."""
  return PlateHolder(name, size_x=127.76, size_y=85.48, size_z=TRAY_Z, pedestal_size_z=0,
                     child_location=Coordinate(0, 0, TRAY_Z))


# -- positions --------------------------------------------------------------------------------------

# Venus places a labware by its A1 (the first container's centre): the plate's corner is A1 less
# (BndryX, Dy - BndryY). Nunc 96 low border: (14.0, 86 - 11.5); Greiner 384: (11.75, 86 - 9.25).
NUNC_A1 = Coordinate(14.0, 86.0 - 11.5, 0)
GREINER_A1 = Coordinate(11.75, 86.0 - 9.25, 0)

# The wash station. Where the layout's water_0..3, waste and bleach put the 96-head (their A1
# plus half the head, (49.5, -31.5)) fits the model's reservoir centres to +-1.5 mm in Y at
# (dx, dy) = (-59.7, 301.0) from the STL's own frame. In X the fit would stand the station 3.6 into
# track 4, where the tip carrier is; it is set flush against it instead (dx -63.3), leaving the
# waters 4.6 and the waste and bleach 1.7 left of where the head is taught.
# Z: it stands on its three runners on the deck.
WASH_STATION = Coordinate(-29.18 - 63.32, -228.25 + 301.0, DECK_Z)

# The single-channel baths stand in the one-track gaps the carriers leave: track 10 (Venus
# single_channel_bleach, A1 X 310) and track 17 (ethanol_waste, A1 X 470). The body is one track
# wide, so the bath is centred on the track; the layout's A1 is 3.75 left of that, as the trough's
# columns are (the scripts add `xDisplacement=3.75` there). Y: the channel's middle where the
# layout's A1..H1 are centred. Z: the keel on the deck (a keel in a deck slot would put it 8 lower).
SINGLE_CHANNEL_Y = {10: 223.5 - 31.5, 17: 217.5 - 31.5}  # the layout's A1..H1 middle


def single_channel_location(track: int, deck) -> Coordinate:
  track_centre = deck.track_to_location(track).x + 22.5 / 2
  return Coordinate(
    track_centre - SingleChannelBath.CHANNEL_CENTRE_X,
    SINGLE_CHANNEL_Y[track] - (117.73 + 114.0 / 2),
    DECK_Z,
  )


# The Cytomat transfer station, left of the deck: Venus transfer_station (Nunc, A1 -214.5, 487,
# Z 210.7), transfer_station_384 (Greiner, A1 -216.2, 489, Z 210.4) and transfer_station_flipped
# (the same Nunc footprint turned 180) are one tray. Its plate corner, the mean of the three:
TRANSFER_STATION = Coordinate(-228.4, 412.4, 210.55 - TRAY_Z)

# The ClarioStar's plate-out tray, right of the waste block: Venus reader_tray_384 (Greiner, A1
# 985.5, 458.3, Z 249.1, angle 180, its lid's corner (997.25, 535.05)). The tray is turned 180: the
# reader takes the plate A1 at the front right. A turned resource hangs from its origin, so the
# tray stands at its far corner.
READER_TRAY = Coordinate(985.5 + 11.75, 458.3 + (86.0 - 9.25), 249.1 - TRAY_Z)

# The microscope's stage: Venus microscope_96 (Nunc, A1 936.1, 143.9, Z 239.8, angle 90). Venus's
# sense of 90 is taken as counter-clockwise seen from above (unchecked): the plate's A1 then sits
# at its back right. Not used by sample.py or dilute.py.
MICROSCOPE_STAGE = Coordinate(936.1 + (86.0 - 11.5), 143.9 - 14.0, 239.8 - TRAY_Z)

# Venus `ethanol` (a Nunc stand-in, A1 (-232.6, 119.8), Z 135): an ethanol washer the lab has a
# model of but took out of the process. bleach_and_rinse_stdvol_tips still ends with an air
# blow-out there (C0 ED at that X/Y in the May traces), so it is a position, not an object:
# the head's A1 for that blow-out.
ETHANOL_BLOWOUT_A1 = Coordinate(-232.6, 119.8, 135.0)

# The 96-head's waste. The layout moves Hamilton's slide waste (core96slidewaste_0001) from its
# deck site (channel A1 at (-42.0, 120.3), under the wash station here) to A1 (-232.1, 110.3):
# above the ethanol washer. PLR's trash_core96 is set there, at PLR's slide-waste eject height.
TRASH_96_A1 = Coordinate(-232.1, 110.3, 216.4)


@dataclass
class TCDeck:
  """The machine and the resources the methods address, by the names `labware.py` gives them."""

  star: STARDevice
  culture_plate: Plate
  sample_plates: List[Plate]  # sample_plate_0..3
  reagent_trough: ReagentTrough  # channels 0 CellTiter-Blue .. 3 media
  reagent_plate: Plate  # Venus reagent_plate (labware.py: treatment_plate)
  ethanol_plate: Plate
  wash_station: WashStation
  single_channel_bleach: SingleChannelBath
  ethanol_waste: SingleChannelBath
  high_volume_tips: TipRack
  standard_volume_tips_0: TipRack
  standard_volume_tips_1: TipRack
  ethanol_tips: TipRack
  dirty_tips: TipRack  # Venus dirty_tips_high_vol / dirty_tips_std_vol: one site, two names
  # plate sites the methods move plates between
  culture_plate_site: PlateHolder  # Venus culture_plate
  plate_384_park: PlateHolder
  sample_plate_sites: List[PlateHolder]
  transfer_station: PlateHolder
  reader_tray: PlateHolder
  microscope_stage: PlateHolder
  # where lids are parked
  culture_lid_park: Plate  # Venus culture_plate_park
  sample_lid_park: Plate  # Venus sample_park


def build_tc_deck(name: str = "STARlet", extension_housing: bool = True) -> TCDeck:
  deck = STARLetDeck(name=f"{name}_deck", with_trash96=False)
  deck.assign_child_resource(
    Trash(deck.get_component_name("trash_core96"), size_x=121.0, size_y=85.0, size_z=0),
    location=Coordinate(TRASH_96_A1.x - (121.0 - 99.0) / 2, TRASH_96_A1.y - (85.0 + 63.0) / 2,
                        TRASH_96_A1.z),
  )
  star = STARLet(deck=deck, simulation=True, name=name, extension_housing=extension_housing)

  # -- tips: TIP_CAR_480BC_A00 at track 4 --------------------------------------------------------
  tips = TIP_CAR_480BC_A00("TIP_CAR_480BC_A00_0001")
  # Venus lists dirty_tips_high_vol (HTF) and dirty_tips_std_vol (STF) on the same site 1; a site
  # holds one rack. The high-volume one is loaded.
  tips[venus(1)] = dirty = hamilton_96_tiprack_1000uL_filter("dirty_tips_high_vol")
  tips[venus(2)] = high = hamilton_96_tiprack_1000uL_filter("high_volume_tips")
  tips[venus(3)] = ethanol_tips = hamilton_96_tiprack_1000uL_filter("ethanol_tips")
  tips[venus(4)] = std_1 = hamilton_96_tiprack_300uL_filter("standard_volume_tips_1")
  tips[venus(5)] = std_0 = hamilton_96_tiprack_300uL_filter("standard_volume_tips_0")
  deck.assign_child_resource(tips, track=4)

  # -- PLT_CAR_L5AC_A00_0003 at track 11: reagents, lid park, the culture plate's site -------------
  car_11 = PLT_CAR_L5AC_A00("PLT_CAR_L5AC_A00_0003")
  reagent_plate = deep_well_plate("reagent_plate")
  # Uncovered: Venus's ethanol_washer_lid_lid over it is never moved, and both the 96-head and the
  # channels pipette from the plate, so it is a lid position, as on the reagent trough.
  ethanol_plate = deep_well_plate("ethanol_plate")
  # sample_park: an empty 384 plate the sample plates' lids are parked on (the layout's lid Z there
  # is the lid-on-a-plate Z, 1 mm higher).
  sample_lid_park = greiner_384_wellplate_152uL_Fb_black("sample_park")
  plate = culture_plate("culture_plate")
  car_11[venus(1)] = reagent_plate
  car_11[venus(2)] = ethanol_plate
  car_11[venus(3)] = sample_lid_park
  # site 4: plate_384_park, where a 384 plate is pipetted and turned for the reader; empty
  car_11[venus(5)] = plate
  deck.assign_child_resource(car_11, track=11)

  # -- PLT_CAR_L5AC_A00_0001 at track 18: the sample plates' sites ----------------------------------
  car_18 = PLT_CAR_L5AC_A00("PLT_CAR_L5AC_A00_0001")
  samples = []
  for i in range(4):  # sample_plate_0..3 on Venus sites 5..2
    car_18[venus(5 - i)] = p = sample_plate(f"sample_plate_{i}")
    samples.append(p)
  # Venus site 1 holds sample_plate_4, which labware.py does not define: left empty.
  deck.assign_child_resource(car_18, track=18)

  # -- PLT_CAR_L5AC_A00_0002 at track 25: the culture lid park and the reagent trough ---------------
  car_25 = PLT_CAR_L5AC_A00("PLT_CAR_L5AC_A00_0002")
  # culture_plate_park: Venus puts a plate at Z 227 here, 40.85 above the site: the height of a
  # 1.2 mL deep-well plate (41). An empty Costar the lid is parked on, standing on a deep-well
  # plate (drawn as a MIDI, so lower than the real one).
  riser = deep_well_plate("culture_plate_park_riser")
  culture_lid_park = cor_96_wellplate_360uL_Fb("culture_plate_park")
  car_25[venus(1)] = riser
  riser.assign_child_resource(culture_lid_park, location=Coordinate(0, 0, riser.get_size_z()))
  trough = ReagentTrough("reagent_trough")
  # Into the site's 4.74 recess, as anything on an SBS footprint: the May traces put the channels'
  # tips at Z 198.6 in it (C0 AS zl), below where its floor would be standing on the recess's rim
  # (201.2). Sunk, the floor is 196.5.
  car_25.sites[venus(5)].assign_child_resource(trough, location=Coordinate(0, 0, -4.74))
  deck.assign_child_resource(car_25, track=25)

  # -- the 3D-printed pieces on the deck ---------------------------------------------------------------
  wash = WashStation("wash_station")
  # Its right wall stands flush against the tip carrier's footprint (see WASH_STATION).
  deck.assign_child_resource(wash, location=WASH_STATION)
  bleach_bath = SingleChannelBath("single_channel_bleach")
  ethanol_waste = SingleChannelBath("ethanol_waste")
  # The handle hangs over the neighbouring carriers' footprints at the front, as the carriers'
  # own front parts do, so the footprint check is waived for the baths.
  deck.assign_child_resource(bleach_bath, location=single_channel_location(10, deck),
                             ignore_collision=True)
  deck.assign_child_resource(ethanol_waste, location=single_channel_location(17, deck),
                             ignore_collision=True)


  # -- the instruments' trays --------------------------------------------------------------------------
  transfer_station = tray("transfer_station")
  deck.assign_child_resource(transfer_station, location=TRANSFER_STATION)
  reader_tray = tray("reader_tray_384")
  reader_tray.rotation = Rotation(z=180)
  deck.assign_child_resource(reader_tray, location=READER_TRAY, ignore_collision=True)
  microscope = tray("microscope_96")
  microscope.rotation = Rotation(z=90)
  deck.assign_child_resource(microscope, location=MICROSCOPE_STAGE, ignore_collision=True)

  return TCDeck(
    star=star, culture_plate=plate, sample_plates=samples, reagent_trough=trough,
    reagent_plate=reagent_plate, ethanol_plate=ethanol_plate, wash_station=wash,
    single_channel_bleach=bleach_bath, ethanol_waste=ethanol_waste,
    high_volume_tips=high, standard_volume_tips_0=std_0, standard_volume_tips_1=std_1,
    ethanol_tips=ethanol_tips, dirty_tips=dirty,
    culture_plate_site=car_11.sites[venus(5)], plate_384_park=car_11.sites[venus(4)],
    sample_plate_sites=[car_18.sites[venus(5 - i)] for i in range(4)],
    transfer_station=transfer_station, reader_tray=reader_tray, microscope_stage=microscope,
    culture_lid_park=culture_lid_park, sample_lid_park=sample_lid_park,
  )


if __name__ == "__main__":
  tc = build_tc_deck()
  deck = tc.star.deck
  for r in [tc.wash_station, tc.reagent_trough, tc.single_channel_bleach, tc.ethanol_waste,
            tc.transfer_station, tc.reader_tray, tc.microscope_stage, tc.culture_plate]:
    lo = r.get_location_wrt(deck)
    print(f"{r.name:24s} origin {lo}  abs rotation z {r.get_absolute_rotation().z}")
