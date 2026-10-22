"""What the NIST LMSF demos share: PLR's wastes and grip tools on an imported layout, gripper moves
to Venus placeholders, and volume helpers. The layout itself is `venus_interop.plr.venus_deck`.

Used by `marionette_demo.py`, `groq_seq_demo.py`, `dna_extraction_demo.py` and `kapa_hyperplus_demo.py`. See those for
how to run them.
"""

import csv
import re
import pathlib
import sys
from typing import List, Optional, Sequence

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from venus_interop.plr import steps  # noqa: E402
from venus_interop.plr.venus_deck import Gripper, VenusDeck, corpus_index  # noqa: E402,F401

from pylabrobot.resources import Coordinate, Resource, ResourceHolder, Trash  # noqa: E402
from pylabrobot.resources.hamilton.core_grippers import hamilton_core_gripper_1000ul_5ml_on_waste  # noqa: E402


def install(v: VenusDeck, slide_waste: Optional[str] = None,
            grip_tools: Optional[str] = "COREGripTool_OnWaste_1000ul_0001") -> None:
  """PLR's tip wastes and grip tools where the layout has its own.

  The channels' waste is a strip along the layout's eject positions, as PLR's own STAR deck has it;
  the 96-head's is the layout's slide waste (or other 96-head waste); the grip tools are PLR's
  1000 uL / 5 mL tools on waste, which its CO-RE gripper needs, in place of `grip_tools` (None
  leaves them to the caller).
  """
  waste = v.deck.get_resource("Waste")
  spots = [w.get_location_wrt(waste.parent, "c", "c", "b") for w in waste.get_all_items()]
  ys = [s.y for s in spots]
  parent = waste.parent
  # Venus ejects onto the waste's container floor, over its first to last positions
  items = waste.get_all_items()
  floor = items[0].get_location_wrt(v.deck, "c", "c", "cavity_bottom").z
  first, last = (w.get_location_wrt(v.deck, "c", "c", "b") for w in (items[0], items[-1]))
  parent.unassign_child_resource(waste)
  trash = Trash(v.deck.get_component_name("trash"), size_x=0, size_y=max(ys) - min(ys) + 20, size_z=0)
  trash.metadata[steps.WASTE_EJECT] = steps.waste_eject_geometry((first.x, first.y), (last.x, last.y), floor)
  parent.assign_child_resource(trash, location=Coordinate(spots[0].x, min(ys) - 10, spots[0].z))
  if slide_waste is not None:
    box = v.deck.get_resource(slide_waste)
    v.replace(slide_waste, lambda: Trash(v.deck.get_component_name("trash_core96"),
                                         size_x=122.4, size_y=82.6, size_z=box.get_size_z()))
  if grip_tools is not None:
    v.replace(grip_tools,
              lambda: hamilton_core_gripper_1000ul_5ml_on_waste(name=v.deck.get_component_name("core_grippers")))


def give_room(wells: Sequence[Resource], volume: float) -> None:
  """Let each position supply `volume` and fill it. Positions of one cavity (`VenusDeck` connects
  them) share a tracker, which then gets `volume` for each of them."""
  make_room(wells, volume)
  for tracker, n in _per_tracker(wells):
    tracker.set_volume(volume * n)


def make_room(wells: Sequence[Resource], volume: float) -> None:
  """Let each position hold `volume`; a shared tracker, `volume` for each position on it."""
  for w in wells:
    w.max_volume = max(w.max_volume, volume)
  for tracker, n in _per_tracker(wells):
    tracker.max_volume = max(tracker.max_volume, volume * n)


def _per_tracker(wells: Sequence[Resource]) -> List[tuple]:
  """(tracker, how many of the wells share it), each tracker once."""
  counts: dict = {}
  for w in wells:
    counts.setdefault(id(w.tracker), [w.tracker, 0])[1] += 1
  return [(t, n) for t, n in counts.values()]


def chunks(items: Sequence, n: int) -> List[list]:
  if len(items) % n:
    raise ValueError(f"{len(items)} positions are not a multiple of {n} channels")
  return [list(items[i:i + n]) for i in range(0, len(items), n)]


def write_worklist(path: pathlib.Path, fields: Sequence[str], rows: Sequence[list]) -> None:
  """A method's worklist as Venus's CSV file object writes it: a header of the field names, then a
  row per record (its quoting and number format are not checked against Venus)."""
  with open(path, "w", newline="") as f:
    csv.writer(f).writerows([list(fields), *rows])


def print_plate_map(fields: Sequence[str], rows: Sequence[list], columns: Sequence[str]) -> None:
  """Worklist columns as 8 x 12 grids, from rows carrying "row" and "column" fields."""
  col = {name: i for i, name in enumerate(fields)}
  grid = {(r[col["row"]], r[col["column"]]): r for r in rows}
  for name in columns:
    print(f"plate map, {name}:")
    for row in "ABCDEFGH":
      cells = [f"{x:.4g}" if isinstance(x, (int, float)) else x for x in (grid[row, c][col[name]] for c in range(1, 13))]
      print(f"  {row} " + " ".join(f"{x:>7}" for x in cells))
