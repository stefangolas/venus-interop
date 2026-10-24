"""The 3D viewer's models for an imported Venus deck: GLBs that already exist, named on the
resources they fit. Nothing is converted; a resource with no GLB here stays a box, and
`models/README.md` lists those.

Two sources:
  - PyLabRobot's own (`resource_model/` in the package), found by the `model` name: tip racks, the
    MultiFlex L5 and 7T bases and their modules, the CO-RE gripper tools on the waste;
  - this repository's `models/`, as a `reference_glb` relative to it, which the viewer is given as
    its `models_root`: the 24-tube and 5-trough carriers, exact named MultiFlex assemblies and
    the MPE2 base. The GROQ demo attaches the existing MPE2 unit through examples/mpe2_model.py.

Each GLB is in its PLR resource's frame (front-left-bottom corner, metres, Z up), so it is named
only to the matching labware definition; authored assemblies may overhang the definition box.
Assemblies already contain their modules. Otherwise a MultiFlex site's module
is drawn as an extra resource under the site's labware, the PLR module whose labware height matches
the site's within `MODULE_TOLERANCE` (Venus's tip sites on the L5 base: 114.7 mm = the base's 18.2 +
the tip rack holder's 96.5; its DWP sites 85.0 against PLR's tabbed holder at 82.4)."""
from __future__ import annotations

import ast
import pathlib
from typing import Optional

MODELS = pathlib.Path(__file__).resolve().parents[2] / "models"

# Venus definition file (lower case, no folder) -> PLR model name, or a GLB under MODELS
BY_FILE = {
  "htf_l.rck": "hamilton_96_tiprack_standard",
  "stf_l.rck": "hamilton_96_tiprack_standard",
  "tip_50ulf_l.rck": "hamilton_96_tiprack_standard",
  "coregriptool_onwaste_1000ul.rck": "hamilton_core_gripper_1000ul_5ml_on_waste",
  "smp_car_24_17x100_a00.rck": MODELS / "Tube_CAR_24_A00.glb",
  "rgt_car_5r60_a00.tml": MODELS / "Trough_CAR_5R60_A00.glb",
  "culture_processing_star_mpe2_base_back.tml": MODELS / "Culture_Processing_STAR_MPE2_Base_Back.glb",
  "fourtitude growth plate with lid.rck": MODELS / "fourtitude_4ti_0255.glb",
  "fourtitude growth plate.rck": MODELS / "fourtitude_4ti_0255.glb",
  "fourtitude growth plate with lid.lid": MODELS / "fourtitude_growth_lid.glb",
  "agilent single cavity 12 col pyr bottom 290 ml reservoir with lid.rck": MODELS / "agilent_201250_100.glb",
  "agilent single cavity 12 col pyr bottom 290 ml reservoir with lid.lid": MODELS / "agilent_201250_lid.glb",
  "agilent 6 well reservoir.rck": MODELS / "agilent_204284_100.glb",
  "agilent 6 well reservoir.lid": MODELS / "agilent_6_column_lid.glb",
  "rgt_cont_60ml_bc_a00.rck": MODELS / "rgt_cont_60ml_BC_A00.glb",
  "wasteblock.tml": MODELS / "WasteBlock.glb",
  "verification.rck": MODELS / "Verification.glb",
  "teachingneedle5ml.rck": MODELS / "TeachingNeedle5ml.glb",
  "teachingneedleblock.rck": MODELS / "TeachingNeedleBlock.glb",
  "core96slidewaste.rck": MODELS / "core96SlideWasteRack.glb",
  "core2_96_tipsupport_ht_filter_l.rck": MODELS / "core2_support_ht.glb",
  "core2_96_tipsupport_st_filter_l.rck": MODELS / "core2_support_st.glb",
  "core2_96_tipsupport_50ultipfilter_l.rck": MODELS / "core2_support_50.glb",
}
# These assemblies already contain their bases and modules. Keep the imported Venus sites;
# the configurator's stock sites do not describe the custom heights in these definitions.
for _stem in ("MFX_CAR_2Empty_2HHSF30DWP", "MFX_CAR_2Low_2HHC", "MFX_CAR_HHC_Empty_2Base HPTab",
              "MFX_CAR_5DWP NestRB", "MFX_CAR_5DWP", "MFX_CAR_5TipBC"):
  BY_FILE[_stem.lower() + ".tml"] = MODELS / (_stem + ".glb")
# MultiFlex baseplates by footprint: PLR's model, and the height its modules stand on (the L5's
# 18.2 mm plate; the 7T shaker plate's 3D origin, 18 in Hamilton's catalogue)
MFX_BASES = {(135.0, 497.0): ("MFX_CAR_L5_base", 18.2), (157.5, 497.0): ("MFX_CAR_7T_shaker", 18.0)}
# the PLR modules a site may get, by the module its label names (the carrier's name spelled per
# position: "TipBC", "DWP", "DWPNestRB"); heater-shakers ("HHS..."), heater-coolers ("HHC") and the
# rest have none here, and stay bare (models/README.md)
MODULES = {"TipBC": ["hamilton_mfx_tiprackholder_standard"],
           "DWP": ["hamilton_mfx_plateholder_DWP_HP_tabbed", "hamilton_mfx_plateholder_DWP_flat",
                   "hamilton_mfx_plateholder_MIDI_HP_tabbed", "hamilton_mfx_plateholder_MTP_HP_tabbed"]}
MODULES["DWPNestRB"] = MODULES["DWP"]
MODULE_TOLERANCE = 3.0  # mm between the site's labware height and the module's


def venus_file(resource) -> str:
  """The resource's Venus definition, lower case, with / between folders; "" when imported without."""
  fields = getattr(resource, "metadata", {}).get("venus", {}).get("fields")
  if not fields:
    return ""
  fields = fields if isinstance(fields, dict) else ast.literal_eval(fields)
  return fields.get("File", "").replace("\\", "/").lower()


def _name(resource, model) -> bool:
  if isinstance(model, pathlib.Path):
    if not model.is_file():
      return False
    resource.reference_glb = model.relative_to(MODELS).as_posix()
  else:
    resource.model = model
  return True


def _modules(carrier, top: float) -> int:
  """The MultiFlex modules under a base's sites, as resources of their own on the carrier."""
  from pylabrobot.resources import Coordinate, Resource
  from pylabrobot.resources.hamilton import mfx_modules

  added = 0
  for site in list(carrier.children):
    if any(c.name == f"{site.name}_module" for c in carrier.children):
      continue  # attach can be called again without duplicating cosmetic resources
    # a site named only by its number ("..._site_2") is an empty position: no module to draw
    label = site.name.rsplit("_site_", 1)[-1] if "_site_" in site.name else ""
    kinds = MODULES.get(label.split("_", 1)[-1]) if "_" in label else None
    if not kinds:
      continue
    modules = [getattr(mfx_modules, m)(f"_{m}") for m in kinds]
    height = site.location.z - top
    module = min(modules, key=lambda m: abs(m.child_location.z - height))
    if abs(module.child_location.z - height) > MODULE_TOLERANCE:
      continue
    drawn = Resource(f"{site.name}_module", module.get_size_x(), module.get_size_y(), module.get_size_z(),
                     category="mfx_module", model=module.model)
    at = site.location - module.child_location
    Resource.assign_child_resource(carrier, drawn, location=Coordinate(at.x, at.y, top))
    added += 1
  return added


def attach(deck) -> str:
  """Name the GLBs on the deck's resources; the `models_root` to give the viewer. Prints what was
  named."""
  named, modules = 0, 0
  for resource in deck.get_all_resources():
    path = venus_file(resource)
    model = BY_FILE.get(path.rsplit("/", 1)[-1])
    base = MFX_BASES.get((resource.get_size_x(), resource.get_size_y())) if "/multiflexcarrier/" in path else None
    if model is not None and _name(resource, model):
      named += 1
    elif base is not None:
      resource.model = base[0]
      named += 1
      modules += _modules(resource, base[1])
  print(f"viewer models: {named} resources named, {modules} MultiFlex modules drawn")
  return str(MODELS)


def attach_star_base(star) -> None:
  """Attach the 54-track STAR chassis in deck coordinates, without moving the device or deck."""
  if star.deck.num_tracks != 54:
    raise ValueError('The GROQ chassis visual is registered for the 54-track STAR')
  source = MODELS / 'star_base_deck_frame.glb'
  if not source.is_file():
    raise FileNotFoundError('Build the chassis visual with tools/build_groq_star_base.py')
  star.reference_glb = source.name
  _place_extension_housing(star)


def _place_extension_housing(star) -> None:
  """Hang the left extension housing where PLR's `STAR()` has it, against the chassis.

  `STARDevice` hangs it flush with the device's own top and back at x = -its width. PLR's `STAR()`
  makes the device the chassis (deck at `STAR_DECK_LOCATION` in it); an imported deck's device is
  the deck itself, so the housing came out against the deck's corner instead: 110 mm into the
  chassis in X and off in Y and Z. Placed in the chassis frame and shifted as the chassis visual is.
  """
  from pylabrobot.hamilton.star import device
  from pylabrobot.resources import Coordinate
  from venus_interop.rules.deltas import Delta

  housing = star.left_extension_housing
  if housing is None:
    return
  origin = device.STAR_DECK_LOCATION
  width, depth, height = device.EXTENSION_HOUSING_SIZE
  housing.location = Coordinate(-width - origin.x, device.MANUAL_SIZE_Y - depth - origin.y,
                                device.SIZE_Z - height - origin.z)
  chassis = [-width, device.MANUAL_SIZE_Y - depth, device.SIZE_Z - height]
  housing.metadata['viewer_frame_delta'] = Delta(
    resource=housing.name, kind='convention', quantity='extension housing frame (mm)',
    venus=chassis, plr=[housing.location.x, housing.location.y, housing.location.z],
    decision='Translate chassis coordinates by -STAR_DECK_LOCATION into the deck frame.',
    detail='Visual registration against PLR STAR(); not a Venus cabinet measurement.',
  ).as_dict()


def missing(deck) -> dict:
  """The deck's Venus labware drawn as boxes: definition file -> resource names."""
  out: dict = {}
  for resource in deck.get_all_resources():
    path = venus_file(resource)
    if (path and not getattr(resource, "model", None) and not getattr(resource, "reference_glb", None)
        and not getattr(resource, "mesh", None)):
      out.setdefault(path, []).append(resource.name)
  return out
