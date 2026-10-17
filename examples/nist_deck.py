"""What the NIST LMSF demos share: a Venus layout imported into PLR and addressed by its sequences.

Used by `marionette_demo.py` and `dna_extraction_demo.py`. See those for how to run them.
"""

import csv
import re
import pathlib
import sys
from typing import Callable, Dict, List, Optional, Sequence

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from venus_interop.files import layout as venus_layout  # noqa: E402
from venus_interop.files.definitions import DEFAULT_VENUS_LABWARE, DefinitionStore  # noqa: E402
from venus_interop.methods.deck_state import absent_at_start  # noqa: E402
from venus_interop.plr import plr_import  # noqa: E402
from venus_interop.rules import placement  # noqa: E402

from pylabrobot.resources import Coordinate, Resource, ResourceHolder, Trash  # noqa: E402
from pylabrobot.resources.hamilton.core_grippers import hamilton_core_gripper_1000ul_5ml_on_waste  # noqa: E402


class VenusDeck:
  """A Venus layout imported into PLR, addressed the way its method addresses it: by sequences.

  Venus places labware at positions, so a plate or lid that moves is a different labware at each
  place. Here the object moves: `take_place_of` frees the holder a destination's placeholder stood
  on, and `aliases` makes later sequences that name the placeholder resolve to the object.
  """

  def __init__(self, corpus: pathlib.Path, layout_file: str):
    index = {}
    with open(corpus / "defs_index.tsv", encoding="utf-8") as f:
      for name, rel, _ in csv.reader(f, delimiter="\t"):
        if (corpus / "defs_raw" / name).exists():
          index[rel] = corpus / "defs_raw" / name
    self.store = DefinitionStore([DEFAULT_VENUS_LABWARE], index)
    self.layout = venus_layout.read_layout(corpus / "raw" / layout_file)
    self.deck = plr_import.lay_to_plr(self.layout, self.store)
    self.sequences = {s.name: s.items for s in self.layout.sequences}
    self._placements = self.layout.by_id()
    self._names: Dict[str, List[str]] = {}
    self.aliases: Dict[str, Resource] = {}
    self._tip_positions: Dict[str, int] = {}
    # Where each labware and lid of the layout stands, as imported: a move to it goes there even
    # after what stood there has gone, or is the very thing moving back.
    ids = set(self._placements) | {p.lid.id for p in self.layout.labware if p.lid}
    placed = [r for r in self.deck.get_all_children() if r.name in ids]
    self.spots: Dict[str, Coordinate] = {r.name: r.get_location_wrt(self.deck, "c", "c", "b") for r in placed}
    # and the carrier site it stands in, where it has one
    self.sites: Dict[str, ResourceHolder] = {
      r.name: r.parent for r in placed if isinstance(r.parent, ResourceHolder)}

  def clear(self, names: Sequence[str]) -> None:
    """Take labware off the deck (a lid goes with its plate, so one already gone is skipped)."""
    for name in names:
      if self.deck.has_resource(name):
        r = self.deck.get_resource(name)
        r.parent.unassign_child_resource(r)

  def clear_absent(self, trace: pathlib.Path) -> List[str]:
    """The deck as the method finds it: without what the method first names as a move's destination.

    Args:
      trace: the method's trace (`venus_interop.methods.protocol`, e.g. a `.condensed.md`).
    """
    absent = absent_at_start(trace.read_text(encoding="utf-8").splitlines(), self.sequences)
    self.clear(absent)
    return absent

  def resource(self, name: str) -> Resource:
    return self.aliases.get(name) or self.deck.get_resource(name)

  def labware(self, sequence: str) -> Resource:
    """The labware a one-labware sequence (a move's source or destination) names."""
    return self.resource(self.sequences[sequence][0][0])

  def items(self, sequence: str) -> List[Resource]:
    """Each (labware, position) of a sequence, as the PLR well, tip spot or resource."""
    out = []
    for lab, pos in self.sequences[sequence]:
      r = self.resource(lab)
      if not hasattr(r, "get_item"):
        out.append(r)
        continue
      if lab not in self._names:
        self._names[lab] = placement.default_positions(self.store.get(self._placements[lab].file))
      out.append(r.get_item(self._names[lab].index(pos)))
    return out

  def next_tips(self, sequence: str, n: int) -> list:
    """The next n positions of a tip sequence that hold tips, as the method's tip counters walk it."""
    spots = self.items(sequence)
    i, out = self._tip_positions.get(sequence, 0), []
    while len(out) < n:
      if i >= len(spots):
        raise RuntimeError(f"{sequence} has run out of tips")
      if spots[i].has_tip():
        out.append(spots[i])
      i += 1
    self._tip_positions[sequence] = i
    return out

  def take_place_of(self, placeholder_name: str) -> Resource:
    """Remove the labware Venus places at a destination, and return what it stood on."""
    placeholder = self.deck.get_resource(placeholder_name)
    holder = placeholder.parent
    holder.unassign_child_resource(placeholder)
    return holder

  def replace(self, imported_name: str, make: Callable[[], Resource]) -> Resource:
    """Put a PLR resource where the layout has an imported box, centred on it."""
    box = self.deck.get_resource(imported_name)
    parent = box.parent
    centre = box.location + Coordinate(box.get_size_x() / 2, box.get_size_y() / 2, 0)
    parent.unassign_child_resource(box)
    r = make()
    parent.assign_child_resource(
      r, location=centre - Coordinate(r.get_size_x() / 2, r.get_size_y() / 2, 0))
    return r


def install(v: VenusDeck, slide_waste: Optional[str] = None) -> None:
  """PLR's tip wastes and grip tools where the layout has its own.

  The channels' waste is a strip along the layout's eject positions, as PLR's own STAR deck has it;
  the 96-head's is the layout's slide waste; the grip tools are PLR's 1000 uL / 5 mL tools on waste,
  which its CO-RE gripper needs.
  """
  waste = v.deck.get_resource("Waste")
  spots = [w.get_location_wrt(waste.parent, "c", "c", "b") for w in waste.get_all_items()]
  ys = [s.y for s in spots]
  parent = waste.parent
  parent.unassign_child_resource(waste)
  parent.assign_child_resource(
    Trash(v.deck.get_component_name("trash"), size_x=0, size_y=max(ys) - min(ys) + 20, size_z=0),
    location=Coordinate(spots[0].x, min(ys) - 10, spots[0].z))
  if slide_waste is not None:
    box = v.deck.get_resource(slide_waste)
    v.replace(slide_waste, lambda: Trash(v.deck.get_component_name("trash_core96"),
                                         size_x=122.4, size_y=82.6, size_z=box.get_size_z()))
  v.replace("COREGripTool_OnWaste_1000ul_0001",
            lambda: hamilton_core_gripper_1000ul_5ml_on_waste(name=v.deck.get_component_name("core_grippers")))


def give_room(wells: Sequence[Resource], volume: float) -> None:
  """Reservoir positions share one cavity in reality: let each hold `volume` and fill it."""
  make_room(wells, volume)
  for w in wells:
    w.tracker.set_volume(volume)


def make_room(wells: Sequence[Resource], volume: float) -> None:
  for w in wells:
    w.max_volume = max(w.max_volume, volume)
    w.tracker.max_volume = max(w.tracker.max_volume, volume)


def chunks(items: Sequence, n: int) -> List[list]:
  if len(items) % n:
    raise ValueError(f"{len(items)} positions are not a multiple of {n} channels")
  return [list(items[i:i + n]) for i in range(0, len(items), n)]


class Gripper:
  """The method's plate and lid moves, with the CO-RE grip tools, as `say`s them."""

  def __init__(self, star, v: VenusDeck, say=print):
    self.star, self.v, self.say = star, v, say

  async def move(self, thing: Resource, to: "Resource | Coordinate") -> None:
    g = self.star.core_grippers
    await g.pick_up_tools()
    await g.pick_up_resource(thing)
    await g.drop_resource(to)
    await g.return_tools()

  async def to_placeholder(self, thing: Resource, placeholder: str,
                           into: Optional[Resource] = None) -> Resource:
    """Move `thing` to where the layout has `placeholder`; later sequences naming it find `thing`.

    It goes down exactly where the placeholder stood (its centre-centre-bottom), or `into` a
    resource that stands for that place (a device's carrier).
    """
    where = self.v.spots[placeholder]
    if self.v.deck.has_resource(placeholder):  # a stand-in still there, not the thing itself
      stand_in = self.v.deck.get_resource(placeholder)
      if stand_in is not thing:
        stand_in.parent.unassign_child_resource(stand_in)
    self.say(f"{thing.name} -> {placeholder}")
    g = self.star.core_grippers
    await g.pick_up_tools()
    await g.pick_up_resource(thing)
    # Venus stacks parked lids on what stands there (a plate, a waste plate and its lid): PLR will
    # not put a resource on the deck inside another, so it goes down on top of the stack
    for _ in range(5):
      site = self.v.sites.get(placeholder)
      if into is None and site is not None and site.resource is None:
        into = site  # the layout's own site, now free: as Venus places it
      try:
        await g.drop_resource(where if into is None else into)
        break
      except ValueError as refused:
        m = re.search(r"is inside '([^']+)'", str(refused))
        if m is None:
          raise
        inside = self.v.deck.get_resource(m.group(1))
        if isinstance(inside, ResourceHolder) and inside.resource is None:
          await g.drop_resource(inside)  # an empty carrier site: it goes into the site
          break
        top = inside.get_location_wrt(self.v.deck, "c", "c", "t").z
        where = Coordinate(where.x, where.y, max(where.z, top + 0.1))
    else:
      raise RuntimeError(f"no free spot for {thing.name} at {placeholder}")
    await g.return_tools()
    self.v.aliases[placeholder] = thing
    # its lid answers to the destination's lid's name too
    placed = self.v._placements.get(placeholder)
    lid = getattr(thing, "lid", None)
    if placed is not None and placed.lid is not None and lid is not None:
      self.v.aliases[placed.lid.id] = lid
    return thing

  async def onto(self, thing: Resource, target: Resource) -> None:
    self.say(f"{thing.name} -> onto {target.name}")
    await self.move(thing, target)
