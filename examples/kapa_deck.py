"""The KAPA HyperPlus deck (Hamilton NGS STAR MOA), hand-built in PyLabRobot.

Source: `NGS-Protocols/protocols/KAPA_HyperPrep/KAPA_HyperPlus_Deck.lay`, read for *what* stands
*where*: which carrier on which track, which labware on which site. Every position comes from the
PLR factories, which are tested against Hamilton's templates and manufacturers' drawings, never
from the layout's coordinates: those are hand-placed or taught in places, and some sites the
method never touches are wrong by centimetres (see VENUS_TO_PLR.md).

Venus site k on an n-position carrier counts from the back; PLR's index n - k counts from the front.

Only what the method uses is loaded, plus the carriers that physically stand on the deck and the
stacks on the stacking carrier. Left out, as unused by `HyperPrep_HyperPlus.py`: the plate and
lid waste chutes at the right (MIDI_Waste, HSP_Waste, Ham_ComfortLid_Waste), the MIDI plate
parked at the left (Stack_02), and the plates declared on the Heater Shakers.
"""

from dataclasses import dataclass
from typing import Dict, List

from pylabrobot.hamilton.star.device import STAR, STARDevice
from pylabrobot.inheco import inheco_cpac_ultraflat
from pylabrobot.inheco.control_box import InhecoTECControlBox
from pylabrobot.legacy.thermocycling.chatterbox import ThermocyclerChatterboxBackend
from pylabrobot.legacy.thermocycling.inheco import InhecoODTC, inheco_odtc
from pylabrobot.resources import (
  Coordinate,
  Plate,
  ResourceStack,
  Trash,
  Trough,
  Tube,
  biorad_96_wellplate_200uL_Vb,
  cor_axy_1_troughplate_300mL_Vb,
  hamilton_pcr_comfort_lid,
)
from pylabrobot.resources.alpaqua import alpaqua_96_plateadapter_magnum_ex
from pylabrobot.resources.hamilton import (
  PLT_CAR_L4ST_LOW_A00,
  STARDeck,
  TIP_CAR_480BC_A00,
  Trough_CAR_5R60_A00,
  Tube_CAR_24_A00,
  hamilton_1_trough_60mL_Vb,
  hamilton_96_tip_support,
  hamilton_96_tiprack_50uL_filter,
  hamilton_96_tiprack_300uL_filter,
  hamilton_96_tiprack_1000uL_filter,
  hamilton_tip_300uL_filter,
  hamilton_tube_carrier_32_a00,
)
from pylabrobot.resources.hamilton.heater_shakers import (
  hamilton_heater_shaker,
  hamilton_heater_shaker_riser,
  hamilton_hhs_nest_flat_dwp_3mm,
  hamilton_hhs_nest_flat_mtp_3mm,
)
from pylabrobot.resources.hamilton.mfx_carriers import (
  hamilton_mfx_carrier_7T_odtc_v2,
  hamilton_mfx_carrier_7T_shaker,
  hamilton_mfx_carrier_L5_2MTP_MIDI_2DWP_HP_tabbed,
)
from pylabrobot.resources.hamilton.mfx_modules import (
  hamilton_cpac_tube_block_2mL,
  hamilton_mfx_cpac_bracket,
  hamilton_mfx_plateholder_DWP_HP_tabbed_old,
)
from pylabrobot.resources.plate_adapter import PlateAdapter
from pylabrobot.resources.thermo_fisher import thermo_TS_abgene_96_wellplate_800uL_Vb
from pylabrobot.resources.tip_rack import TipRack

# Venus's MFX_CAR_ODTC_MTP_V2 template is one track wide at track 1, with every site 201.8 left of
# and 12.5 in front of the carrier's own (V1) frame: the carrier stands left of the deck, in the
# space the missing left side panel leaves. Its lid site stays at V1's height, so it is not raised.
ODTC_CARRIER_LOCATION = Coordinate(100.0 - 201.8, 63.0 - 12.5, 100.0)

# Hamilton's Core96ExternalWaste template ("Tip Waste for CO-RE 96 Probe Head (without tip
# chute)", deck site 96COREExtWaste in ML_STAR2.dck at (-390.7, 11.95)) holds its 122.4 x 82.6
# rack at (148, 32.5), Z 185. Tips are ejected 11.4 above the rack's container floor (185 - 22.5),
# as PLR's default 96-head trash (Hamilton's slide waste) is placed against its own floor: by
# analogy, unverified.
EXTERNAL_96_WASTE = Coordinate(-390.7 + 148.0, 11.95 + 32.5, 185.0 - 22.5 + 11.4)


def venus(site: int) -> int:
  """PLR's front-first index for Venus's back-first site on a 5-position carrier."""
  return 5 - site


def tube_15x75(name: str) -> Tube:
  """A generic 15 x 75 mm round-bottom tube for the master mixes (Venus's `cup_15x75.ctr` is not
  on this machine): a stand-in, not a product definition."""
  return Tube(name=name, size_x=15.0, size_y=15.0, size_z=75.0, max_volume=8000.0,
              material_z_thickness=1.0)


@dataclass
class KAPADeck:
  """The machine and the resources the method addresses, by the names the method gives them."""

  star: STARDevice
  odtc: InhecoODTC
  hsp_plate: Plate  # samples start here (Venus HSP_Pipette)
  hsp_plate_2: Plate  # (HSP_Pipette2)
  midi: Plate  # the one MIDI plate, moved on and off the magnet (MIDI_Pipette / MIDI_OnMagnet)
  midi_nest: object  # where the MIDI plate is pipetted off the magnet
  magnet: PlateAdapter
  odtc_lid_stack: ResourceStack  # five ComfortLids on the ODTC carrier's lid park
  ethanol: Plate
  beads: Trough  # rgt_cont_60ml_BC_A00_0002
  water: Trough  # rgt_cont_60ml_BC_A00_0003
  cold_plate: Plate  # on the CPAC at 4 C (CPAC_HSP_0001)
  master_mix_tubes: Dict[str, Tube]
  tips_50uL: List[TipRack]
  tips_300uL: List[TipRack]
  tip_support: TipRack
  liquid_waste: Trough  # the 96-head's gravity waste trough (LiquidWaste_MPH)


def build_kapa_deck(name: str = "STAR", extension_housing: bool = True) -> KAPADeck:
  """`extension_housing=False` leaves the left extension's housing off the model, to see the ODTC
  and the waste standing under it."""
  deck = STARDeck(name=f"{name}_deck", with_trash96=False)
  deck.assign_child_resource(
    Trash(deck.get_component_name("trash_core96"), size_x=122.4, size_y=82.6, size_z=0),
    location=EXTERNAL_96_WASTE,
  )
  star = STAR(deck=deck, simulation=True, name=name, extension_housing=extension_housing)

  # -- tips: TIP_CAR_480BC_A00 on tracks 6, 12, 18, 24 -------------------------------------------
  tips_50, tips_300 = [], []
  carriers = [TIP_CAR_480BC_A00(f"tip_carrier_{i}") for i in range(1, 5)]
  for i in range(5):  # TIP_50uLF_L_0001..0005 on sites 1..5
    carriers[0][venus(i + 1)] = r = hamilton_96_tiprack_50uL_filter(f"TIP_50uLF_L_{i + 1:04d}")
    tips_50.append(r)
  for i in range(3):  # TIP_50uLF_L_0006..0008 on sites 1..3
    carriers[1][venus(i + 1)] = r = hamilton_96_tiprack_50uL_filter(f"TIP_50uLF_L_{i + 6:04d}")
    tips_50.append(r)
  placements_300 = [(1, 4), (1, 5), (2, 2), (2, 3), (2, 4), (2, 5), (3, 1), (3, 2)]
  for n, (carrier, site) in enumerate(placements_300, start=1):  # STF_L_0001..0008
    carriers[carrier][venus(site)] = r = hamilton_96_tiprack_300uL_filter(f"STF_L_{n:04d}")
    tips_300.append(r)
  for n, site in ((1, 3), (2, 4), (3, 5)):  # HTF_L_0001..0003, unused by the method
    carriers[3][venus(site)] = hamilton_96_tiprack_1000uL_filter(f"HTF_L_{n:04d}")
  # The CO-RE II tip support on carrier 3's site 1, empty: the 96-head fills it from a rack.
  support = hamilton_96_tip_support("TipSupport_0001", "300uL", hamilton_tip_300uL_filter,
                                    core_ii=True)
  carriers[2][venus(1)] = support
  for carrier, track in zip(carriers, (6, 12, 18, 24)):
    deck.assign_child_resource(carrier, track=track)

  # -- reagents: RGT_CAR_5R60_A00 on tracks 30, 31 ------------------------------------------------
  troughs = {}
  for c, track in enumerate((30, 31)):
    carrier = Trough_CAR_5R60_A00(f"RGT_CAR_{c + 1}")
    for site in range(1, 6):
      n = 5 * c + site
      carrier[venus(site)] = troughs[n] = hamilton_1_trough_60mL_Vb(f"rgt_cont_60ml_BC_A00_{n:04d}")
    deck.assign_child_resource(carrier, track=track)

  # SMP_CAR_24_15x75_A00 (track 32): Venus's one labware for the carrier and its tubes. Here the
  # 24-position carrier with tubes where the method's master mixes are: its positions [1], [2],
  # [3] (0-based), Venus positions 2..4 from the back.
  tube_carrier = Tube_CAR_24_A00("SMP_CAR_24_15x75_A00_0001")
  tubes = {}
  for key, position in (("EndRepairMasterMix", 2), ("LigationMasterMix", 3), ("KAPA_Adapters", 4)):
    tube_carrier[24 - position] = tubes[key] = tube_15x75(key)
  deck.assign_child_resource(tube_carrier, track=32)
  for n, track in ((1, 33), (2, 34)):  # RGT_TUBE_1, _2: bare 32-tube carriers, unused
    deck.assign_child_resource(hamilton_tube_carrier_32_a00(f"RGT_TUBE_{n}"), track=track)

  # -- the pipetting carrier: MFX_CAR_2MTP HPTab_MIDI HPTab_2DWP HPTab, track 35 -------------------
  hp = hamilton_mfx_carrier_L5_2MTP_MIDI_2DWP_HP_tabbed("MFX_CAR_2MTP_HPTab_MIDI_HPTab_2DWP_HPTab")
  hsp_plate = biorad_96_wellplate_200uL_Vb("HSP_Plate")
  hsp_plate_2 = biorad_96_wellplate_200uL_Vb("HSP_Plate_2")
  midi = thermo_TS_abgene_96_wellplate_800uL_Vb("MIDI")
  ethanol = cor_axy_1_troughplate_300mL_Vb("Ethanol")  # Venus Ham_DW_Rgt_96L: same container
  magnet = alpaqua_96_plateadapter_magnum_ex("Magnet")
  hp.sites[venus(1)].assign_child_resource(hsp_plate)  # 1_HSP
  hp.sites[venus(2)].assign_child_resource(hsp_plate_2)  # 2_HSP
  hp.sites[venus(3)].assign_child_resource(midi)  # 3_DWP: the MIDI nest
  hp.sites[venus(4)].assign_child_resource(ethanol)  # 4_Trough
  hp.sites[venus(5)].assign_child_resource(magnet)  # 5_MagPlate: the magnet in the DWP nest
  deck.assign_child_resource(hp, track=35)

  # -- MFX_CAR_2HHSF30DWP_DWP HPTab OLD_CPAC, track 41: the cold plate on the CPAC ----------------
  control_box = InhecoTECControlBox()
  cpac = inheco_cpac_ultraflat("CPAC_1", control_box=control_box, index=1, adapter="pcr_low_profile")
  old_cpac = hamilton_mfx_carrier_7T_shaker(
    "MFX_CAR_2HHSF30DWP_DWP_HPTab_OLD_CPAC",
    modules={
      3: hamilton_heater_shaker("HHS4", nest=hamilton_hhs_nest_flat_dwp_3mm("HHS4_nest")),
      2: hamilton_heater_shaker("HHS5", nest=hamilton_hhs_nest_flat_dwp_3mm("HHS5_nest")),
      1: hamilton_mfx_plateholder_DWP_HP_tabbed_old("DWP_HPTab_OLD"),
      0: hamilton_mfx_cpac_bracket("CPAC_1_bracket", cpac),
    },
  )
  cold_plate = biorad_96_wellplate_200uL_Vb("CPAC_HSP")
  cpac.assign_child_resource(cold_plate)
  deck.assign_child_resource(old_cpac, track=41)

  # -- MFX_CAR_2HHSF30MTP_HHSF30DWP_CPAC, track 48: unused by the method, on the deck -------------
  cpac_2 = inheco_cpac_ultraflat("CPAC_2", control_box=control_box, index=2, adapter="tubes_2mL")
  cpac_2.assign_child_resource(hamilton_cpac_tube_block_2mL("CPAC_2mLTubes"))
  hhs_carrier = hamilton_mfx_carrier_7T_shaker(
    "MFX_CAR_2HHSF30MTP_HHSF30DWP_CPAC",
    modules={
      3: hamilton_heater_shaker_riser(
        "HHS1_riser", hamilton_heater_shaker("HHS1", nest=hamilton_hhs_nest_flat_mtp_3mm("HHS1_nest"))
      ),
      2: hamilton_heater_shaker_riser(
        "HHS2_riser", hamilton_heater_shaker("HHS2", nest=hamilton_hhs_nest_flat_mtp_3mm("HHS2_nest"))
      ),
      1: hamilton_heater_shaker("HHS3", nest=hamilton_hhs_nest_flat_dwp_3mm("HHS3_nest")),
      0: hamilton_mfx_cpac_bracket("CPAC_2_bracket", cpac_2),
    },
  )
  deck.assign_child_resource(hhs_carrier, track=48)

  # -- the stacking carrier, 7T-M1 (X 55): PLT_CAR_L4ST, the low one --------------------------------
  # Stacks of fresh plates, unused by the method. The NGS kits' copy of the template raises the
  # front site to 53 (Hamilton's own PLT_CAR_L4ST_LOW_A00 and the GEM-X kit: 18); nothing says
  # what stands under it, so the library's 18 is kept.
  stacker = PLT_CAR_L4ST_LOW_A00("PLT_CAR_L4ST")
  stacks = {
    4 - 1: ResourceStack("AbgeneMIDI_Stack1", "z",
                            [thermo_TS_abgene_96_wellplate_800uL_Vb(f"AbgeneMIDI_Stack1_{i:04d}") for i in range(3, 0, -1)]),
    4 - 3: ResourceStack("Stack_03", "z",
                            [biorad_96_wellplate_200uL_Vb(f"Stack_03_{i:04d}") for i in range(3, 0, -1)]),
    4 - 4: ResourceStack("BioRadHardShell_Stack4", "z",
                            [biorad_96_wellplate_200uL_Vb(f"BioRadHardShell_Stack4_{i:04d}") for i in range(5, 0, -1)]),
  }
  for index, stack in stacks.items():
    stacker.sites[index].assign_child_resource(stack)
  deck.assign_child_resource(stacker, location=Coordinate(55.0, 63.0, 100.0))

  # -- the ODTC carrier, left of track 1 ----------------------------------------------------------
  odtc = inheco_odtc("ODTC", ThermocyclerChatterboxBackend())
  odtc_carrier = hamilton_mfx_carrier_7T_odtc_v2("MFX_CAR_ODTC_MTP_V2", odtc)
  # Venus lists the five ComfortLids as separate labware at the lid park's position, 6.7 apart;
  # pyhamilton takes the highest-numbered first. A z stack's list is given top first.
  lids = ResourceStack("Ham_ComfortLid_Stack", "z",
                       [hamilton_pcr_comfort_lid(f"Ham_ComfortLid_Stack_{i:04d}") for i in range(5, 0, -1)])
  odtc_carrier.sites[0].assign_child_resource(lids)
  # Its 7-track footprint (157.5) ends at X 55.7, 0.7 into the stacking carrier's at track -1 (55):
  # Venus's V2 offset is 201.8, not the 202.5 of nine tracks. The bodies clear: the carrier's
  # model ends 1.5 short of its footprint. So the nominal-footprint check is waived here.
  deck.assign_child_resource(odtc_carrier, location=ODTC_CARRIER_LOCATION, ignore_collision=True)

  # The 96-head's gravity waste trough (GravWasteTrough96.rck, not on this machine): where the
  # layout puts it, A1 at (-73.2, 515.5), bottom at Z 179, as an SBS-footprint trash. Position
  # from the layout only; geometry unknown. The method never uses it (see kapa_demo.py).
  liquid_waste = Trough(
    "LiquidWaste_MPH", size_x=127.0, size_y=86.0, size_z=40.0, max_volume=2_000_000.0,
    material_z_thickness=1.0,
  )  # a container, so the 96-head can dispense into it; depth and volume placeholders
  deck.assign_child_resource(
    liquid_waste, location=Coordinate(-73.2 - 14.0, 515.5 - (86.0 - 11.5), 179.0)
  )

  return KAPADeck(
    star=star, odtc=odtc, hsp_plate=hsp_plate, hsp_plate_2=hsp_plate_2, midi=midi,
    midi_nest=hp.sites[venus(3)], magnet=magnet, odtc_lid_stack=lids, ethanol=ethanol,
    beads=troughs[2], water=troughs[3], cold_plate=cold_plate, master_mix_tubes=tubes,
    tips_50uL=tips_50, tips_300uL=tips_300, tip_support=support, liquid_waste=liquid_waste,
  )
