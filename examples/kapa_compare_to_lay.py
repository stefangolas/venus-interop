"""Where the hand-built PLR deck puts each labware the method uses, against KAPA_HyperPlus_Deck.lay.

Venus records a labware's A1 position (X, Y) and its bottom (ZTrans). Differences are reported,
not asserted: the layout is partly hand-placed.

  python compare_to_lay.py   (from the plr-viz3d repo, with its .venv)
"""

import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, r"C:\Users\stefa\plr-viz3d-scratch\hamilton_library")
logging.disable(logging.WARNING)

import venus_files  # noqa: E402
from kapa_deck import build_kapa_deck  # noqa: E402

LAY = r"C:\Users\stefa\NGS-Protocols\protocols\KAPA_HyperPrep\KAPA_HyperPlus_Deck.lay"


def lay_entries():
  d = venus_files.read(LAY)
  out = {}
  for k, v in d.items():
    m = re.match(r"Labware\.(\d+)\.Id$", k)
    if m:
      n = m.group(1)
      out[v] = tuple(float(d[f"Labware.{n}.{f}"]) for f in ("TForm.3.X", "TForm.3.Y", "ZTrans"))
  return out


def main():
  k = build_kapa_deck()
  deck = k.star.deck
  lay = lay_entries()

  def a1_and_bottom(resource):
    item = resource.get_item("A1") if hasattr(resource, "get_item") else resource
    a1 = item.get_location_wrt(deck, "c", "c", "b")
    return a1.x, a1.y, resource.get_location_wrt(deck).z

  rows = [
    ("HSP_Pipette", k.hsp_plate), ("HSP_Pipette2", k.hsp_plate_2), ("MIDI_Pipette", k.midi),
    ("RGT_Ethanol", k.ethanol), ("CPAC_HSP_0001", k.cold_plate), ("TipSupport_0001", k.tip_support),
  ]
  rows += [(r.name, r) for r in k.tips_50uL + k.tips_300uL]
  # the MIDI plate as it would sit on the magnet
  midi_on_magnet = type(k.midi)  # noqa: F841
  print(f"{'labware':22s} {'dX':>7s} {'dY':>7s} {'dZ':>7s}   (PLR - Venus, mm)")
  for venus_id, resource in rows:
    x, y, z = a1_and_bottom(resource)
    vx, vy, vz = lay[venus_id]
    print(f"{venus_id:22s} {x - vx:7.2f} {y - vy:7.2f} {z - vz:7.2f}")

  k.midi.unassign()
  k.magnet.assign_child_resource(k.midi)
  x, y, z = a1_and_bottom(k.midi)
  vx, vy, vz = lay["MIDI_OnMagnet"]
  print(f"{'MIDI_OnMagnet':22s} {x - vx:7.2f} {y - vy:7.2f} {z - vz:7.2f}")

  plate = k.hsp_plate
  plate.unassign()
  k.odtc.assign_child_resource(plate)
  x, y, z = a1_and_bottom(plate)
  vx, vy, vz = lay["HSP_ODTC"]
  print(f"{'HSP_ODTC':22s} {x - vx:7.2f} {y - vy:7.2f} {z - vz:7.2f}")

  lid = k.odtc_lid_stack.get_top_item()
  at = lid.get_location_wrt(deck)
  centre = (at.x + lid.get_size_x() / 2, at.y + lid.get_size_y() / 2)
  for n in range(1, 6):
    vx, vy, vz = lay[f"Ham_ComfortLid_Stack_{n:04d}"]
    if n == 5:
      print(f"{'top of the lid stack':22s} {centre[0] - vx:7.2f} {centre[1] - vy:7.2f} {at.z - vz:7.2f}"
            "   (lid .rck origin: its centre)")

  trash = deck.get_resource(deck.get_component_name("trash_core96"))
  t = trash.get_location_wrt(deck)
  vx, vy, vz = lay["core96externalwaste_0001"]
  print(f"{'96 external waste':22s} {t.x + 11.7 - vx:7.2f} {t.y + 82.6 - 9.8 - vy:7.2f}"
        "      -   (rack corner from its A1 via Bndry 11.7 / 9.8)")


if __name__ == "__main__":
  main()
