"""PLR multiflex factories (fork/viz3d-motion) vs the Venus .tml templates they model.

For each factory: every leaf holder that takes a plate, where an SBS footprint lands on it (centre, and
bottom), relative to the carrier; against the Venus sites (centre of the 127 x 86 site, site Z).
Run with the plr-viz3d venv and a pylabrobot that has the multiflex factories (fork/viz3d-motion)
first on PYTHONPATH, e.g. `git archive fork/viz3d-motion pylabrobot` unpacked somewhere.
"""
import logging
import pathlib
import sys

logging.disable(logging.WARNING)
sys.path.insert(1, r"C:\Users\stefa\pressure_speed")

from pylabrobot.resources import Coordinate, PlateHolder, Resource, ResourceHolder  # noqa: E402
from pylabrobot.resources.hamilton import heater_shakers as H  # noqa: E402
from pylabrobot.resources.hamilton import mfx_carriers as C  # noqa: E402
from pylabrobot.resources.hamilton import mfx_modules as M  # noqa: E402

from venus_interop.files.definitions import load  # noqa: E402
from pylabrobot.inheco import inheco_cpac_ultraflat  # noqa: E402
from pylabrobot.inheco.control_box import InhecoTECControlBox  # noqa: E402

BOX = InhecoTECControlBox()


def cpac(name, adapter="flat", index=1):
  return M.hamilton_mfx_cpac_bracket(name, inheco_cpac_ultraflat(name + "_cpac", control_box=BOX, index=index, adapter=adapter))

NGS = pathlib.Path(r"C:\Users\stefa\NGS-Protocols\assets")


def tml(name):
  hits = sorted(NGS.rglob(name))
  if not hits:
    raise FileNotFoundError(name)
  return load(hits[0])


def leaves(r):
  """Holders that take labware and hold no further holders."""
  out = []
  for c in r.children:
    sub = leaves(c)
    if sub:
      out += sub
    elif isinstance(c, ResourceHolder):
      out.append(c)
  return out


def landing(carrier, holder):
  probe = Resource("probe", 127.76, 85.48, 10)
  try:
    off = holder.get_default_child_location(probe)
  except Exception:  # noqa: BLE001
    off = Coordinate.zero()
  p = holder.get_location_wrt(carrier) + off
  return p.x + 127.76 / 2, p.y + 85.48 / 2, p.z


def compare(title, carrier, venus_file, shift=(0.0, 0.0)):
  d = tml(venus_file)
  sites = sorted(d.sites.values(), key=lambda s: -s.y)
  plr = [(h.name, *landing(carrier, h)) for h in leaves(carrier)]
  print(f"\n{title}\n  Venus: {venus_file}")
  if shift != (0.0, 0.0):
    print(f"  (Venus sites shifted by {shift}: the documented V2 anchor)")
  for s in sites:
    cx, cy = s.x + s.dx / 2 - shift[0], s.y + s.dy / 2 - shift[1]
    best = min(plr, key=lambda p: abs(p[1] - cx) + abs(p[2] - cy)) if plr else None
    if best is None or abs(best[1] - cx) + abs(best[2] - cy) > 30:
      print(f"  site {s.id:16} centre ({cx:7.2f}, {cy:7.2f}) z {s.z:7.2f}   PLR: no holder here")
      continue
    print(f"  site {s.id:16} centre ({cx:7.2f}, {cy:7.2f}) z {s.z:7.2f}   PLR {best[0][:34]:34} "
          f"d = ({best[1] - cx:+.2f}, {best[2] - cy:+.2f}, {best[3] - s.z:+.2f})")


def odtc_holder(name):
  h = ResourceHolder(name, 150, 100, 0)
  h.child_location = Coordinate(0, 0, 0)
  return h


compare("HP Tabbed L5 carrier", C.hamilton_mfx_carrier_L5_2MTP_MIDI_2DWP_HP_tabbed("hp"),
        "MFX_CAR_2MTP HPTab_MIDI HPTab_2DWP HPTab.tml")
compare("ODTC carrier v1 (lid park only; the ODTC is a device)", C.hamilton_mfx_carrier_7T_odtc("o1", odtc_holder("odtc1")),
        "MFX_CAR_ODTC_MTP.tml")
compare("ODTC carrier v2", C.hamilton_mfx_carrier_7T_odtc_v2("o2", odtc_holder("odtc2")), "MFX_CAR_ODTC_MTP_V2.tml",
        shift=(-201.8, -12.5))
shaker = C.hamilton_mfx_carrier_7T_shaker("sh", modules={
  3: H.hamilton_heater_shaker_riser("R1", H.hamilton_heater_shaker("HHS1", nest=H.hamilton_hhs_nest_flat_mtp_3mm("HHS1_nest"))),
  2: H.hamilton_heater_shaker_riser("R2", H.hamilton_heater_shaker("HHS2", nest=H.hamilton_hhs_nest_flat_mtp_3mm("HHS2_nest"))),
  1: H.hamilton_heater_shaker("HHS3", nest=H.hamilton_hhs_nest_flat_dwp_3mm("HHS3_nest")),
  0: cpac("cpac_bracket", "pcr_low_profile"),
})
compare("7T shaker: 2 HHS flat MTP 3mm, HHS flat DWP 3mm, CPAC", shaker, "MFX_CAR_2HHSF30MTP_HHSF30DWP_CPAC.tml")
nunc = C.hamilton_mfx_carrier_7T_shaker("nu", modules={
  3: H.hamilton_heater_shaker("HHSa", nest=H.hamilton_hhs_nest_nunc_dwp_3mm("HHSa_nest")),
  2: H.hamilton_heater_shaker("HHSb", nest=H.hamilton_hhs_nest_nunc_dwp_3mm("HHSb_nest")),
  1: cpac("cpac_a", "flat", 1),
  0: cpac("cpac_b", "flat", 2),
})
compare("7T shaker: 2 HHS Nunc DWP 3mm, 2 CPAC", nunc, "MFX_CAR_2HHS30NuncDWP_2CPACflat.tml")
