"""A Venus layout imported into PLR and addressed the way its method addresses it: by sequences.

`VenusDeck` holds the imported deck, the layout's sequences as live `methods.sequences.Sequence`
objects (one per name, shared by every step and library call, as `ML_STAR.Name` is in Venus), and
resolves a sequence item (labware id, Venus position id) to the PLR well, tip spot or resource.
Labware that moves is one object here, where Venus has a labware per place: `aliases` makes later
references to a placeholder resolve to the object that took its place.
"""

import csv
import pathlib
import re
from typing import Callable, Dict, List, Optional, Sequence

from venus_interop.files import layout as venus_layout
from venus_interop.files.definitions import DEFAULT_VENUS_LABWARE, DefinitionStore
from venus_interop.methods import sequences as sq
from venus_interop.methods.deck_state import absent_at_start
from venus_interop.plr import plr_import
from venus_interop.rules import placement

from pylabrobot.resources import Coordinate, Resource, ResourceHolder


def corpus_index(corpus: pathlib.Path) -> Dict[str, pathlib.Path]:
  """The corpus's definition files by the relative path layouts name them by."""
  index = {}
  with open(corpus / "defs_index.tsv", encoding="utf-8") as f:
    for name, rel, _ in csv.reader(f, delimiter="\t"):
      if (corpus / "defs_raw" / name).exists():
        index[rel] = corpus / "defs_raw" / name
  return index


class VenusDeck:
  """A Venus layout imported into PLR, addressed the way its method addresses it: by sequences.

  Venus places labware at positions, so a plate or lid that moves is a different labware at each
  place. Here the object moves: `take_place_of` frees the holder a destination's placeholder stood
  on, and `aliases` makes later sequences that name the placeholder resolve to the object.
  """

  def __init__(self, corpus: pathlib.Path, layout_file: "str | pathlib.Path",
               store: Optional[DefinitionStore] = None):
    """`layout_file` is a name in the corpus's `raw/`, or a path; `store` defaults to the corpus's
    definitions (`corpus_index`) over the Venus install's."""
    self.store = store or DefinitionStore([DEFAULT_VENUS_LABWARE], corpus_index(corpus))
    self.layout = venus_layout.read_layout(corpus / "raw" / layout_file)
    self.deck = plr_import.lay_to_plr(self.layout, self.store)
    self.sequences = {s.name: s.items for s in self.layout.sequences}
    self._placements = self.layout.by_id()
    self._names: Dict[str, List[str]] = {}
    self.aliases: Dict[str, Resource] = {}
    self._tip_positions: Dict[str, int] = {}
    self._live: Dict[str, sq.Sequence] = {}
    # Where each labware and lid of the layout stands, as imported: a move to it goes there even
    # after what stood there has gone, or is the very thing moving back.
    ids = set(self._placements) | {p.lid.id for p in self.layout.labware if p.lid}
    placed = [r for r in self.deck.get_all_children() if r.name in ids]
    self.spots: Dict[str, Coordinate] = {r.name: r.get_location_wrt(self.deck, "c", "c", "b") for r in placed}
    # and the carrier site it stands in, where it has one
    self.sites: Dict[str, ResourceHolder] = {
      r.name: r.parent for r in placed if isinstance(r.parent, ResourceHolder)}
    self.connected = self._connect_cavities()

  def _connect_cavities(self) -> List[str]:
    """Racks whose definition says its positions are connected (`ConnectedCtr=1`: one cavity, such
    as a single-cavity reservoir) share one liquid level, as Venus models them: their wells share
    one volume tracker, the cavity's (each position's capacity times their number), and a well's
    liquid height is its container's height for the cavity's volume spread over the positions."""
    out = []
    for p in self.layout.labware:
      d = self.store.get(p.file)
      if d is None or d.fields.get("ConnectedCtr") != "1" or not self.deck.has_resource(p.id):
        continue
      wells = [w for w in getattr(self.deck.get_resource(p.id), "get_all_items", lambda: [])()
               if hasattr(w, "tracker")]
      if len(wells) < 2:
        continue
      n = len(wells)
      shared = wells[0].tracker
      shared.max_volume = wells[0].max_volume * n
      for w in wells:
        w.tracker = shared
        w.max_volume = shared.max_volume
        h_of_v, v_of_h = w._compute_height_from_volume, w._compute_volume_from_height
        if h_of_v is not None and v_of_h is not None:
          w._compute_height_from_volume = lambda v, f=h_of_v: f(v / n)
          w._compute_volume_from_height = lambda h, f=v_of_h: f(h) * n
      out.append(p.id)
    return out

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

  def seq(self, name) -> sq.Sequence:
    """The layout sequence `name` as live Venus state: the same object on every call. A Sequence
    (one the method built, like Venus's sequence variables) is itself."""
    if isinstance(name, sq.Sequence):
      return name
    if name not in self._live:
      self._live[name] = sq.Sequence(name, list(self.sequences[name]))
    return self._live[name]

  def resolve(self, item: sq.Item) -> Resource:
    """A sequence item as the PLR well, tip spot or resource."""
    return self.at(*item)

  def items(self, sequence: str) -> List[Resource]:
    """Each (labware, position) of a sequence, as the PLR well, tip spot or resource."""
    return [self.at(lab, pos) for lab, pos in self.sequences[sequence]]

  def at(self, lab: str, pos: str) -> Resource:
    """Labware `lab`'s Venus position `pos`, as the PLR well or tip spot (or `lab` itself)."""
    r = self.resource(lab)
    if not hasattr(r, "get_item"):
      return r
    if lab not in self._names:
      self._names[lab] = placement.default_positions(self.store.get(self._placements[lab].file))
    return r.get_item(self._names[lab].index(pos))

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
                           into: Optional[Resource] = None, iswap=None,
                           direction: str = "front",
                           elbows: Sequence[Optional[str]] = (None,),
                           grip: Optional[dict] = None, release: Optional[dict] = None,
                           front_channel: Optional[int] = None, eject: bool = True) -> Resource:
    """Move `thing` to where the layout has `placeholder`; later sequences naming it find `thing`.

    It goes down exactly where the placeholder stood (its centre-centre-bottom), or `into` a
    resource that stands for that place (a device's carrier). With the CO-RE grip tools, or with
    `iswap` (an `iSWAPTransport`) gripping from `direction`, where the channels do not reach: with
    the first of `elbows` (elbow stops; None is the planner's choice) whose plan it can reach and
    that hits nothing. `grip` and `release` are passed to the CO-RE gripper's pick-up and drop
    (a library's grip height, width, force, speeds, plate press), `grip` to the iSWAP's pick-up plan
    (its height below the top, width, opening margin, strength); `front_channel` to its tool
    pick-up, unless the tools are still on from a move that kept them; `eject` False keeps them on
    after this one (a library's eject_gripper 0).
    """
    where = self.v.spots[placeholder]
    if self.v.deck.has_resource(placeholder):  # a stand-in still there, not the thing itself
      stand_in = self.v.deck.get_resource(placeholder)
      if stand_in is not thing:
        stand_in.parent.unassign_child_resource(stand_in)
    self.say(f"{thing.name} -> {placeholder}" + (" (iSWAP)" if iswap is not None else ""))
    g = self.star.core_grippers
    if iswap is None:
      if not g._tools_mounted:
        await g.pick_up_tools(front_channel=front_channel)
      await g.pick_up_resource(thing, **(grip or {}))

      async def drop(to):
        await g.drop_resource(to, **(release or {}))
    else:
      await self._iswap_step(iswap, lambda e: iswap.plan_pick_up(thing, direction=direction, elbow=e, **(grip or {})),
                             elbows)

      async def drop(to):
        await self._iswap_step(iswap, lambda e: iswap.plan_drop(to, direction=direction, elbow=e), elbows)
    # Venus stacks parked lids on what stands there (a plate, a waste plate and its lid): PLR will
    # not put a resource on the deck inside another, so it goes down on top of the stack
    for _ in range(5):
      site = self.v.sites.get(placeholder)
      if into is None and site is not None and site.resource is None:
        into = site  # the layout's own site, now free: as Venus places it
      try:
        await drop(where if into is None else into)
        break
      except ValueError as refused:
        m = re.search(r"is inside '([^']+)'", str(refused))
        if m is None:
          raise
        inside = self.v.deck.get_resource(m.group(1))
        if isinstance(inside, ResourceHolder) and inside.resource is None:
          await drop(inside)  # an empty carrier site: it goes into the site
          break
        top = inside.get_location_wrt(self.v.deck, "c", "c", "t").z
        where = Coordinate(where.x, where.y, max(where.z, top + 0.1))
    else:
      raise RuntimeError(f"no free spot for {thing.name} at {placeholder}")
    if iswap is None and eject:
      await g.return_tools()
    self.v.aliases[placeholder] = thing
    # its lid answers to the destination's lid's name too
    placed = self.v._placements.get(placeholder)
    lid = getattr(thing, "lid", None)
    if placed is not None and placed.lid is not None and lid is not None:
      self.v.aliases[placed.lid.id] = lid
    return thing

  @staticmethod
  async def _iswap_step(iswap, plan_for, elbows: Sequence[Optional[str]]) -> None:
    """Carry out the first plan, over `elbows`, the arm can reach and that hits nothing."""
    why = []
    for elbow in elbows:
      try:
        plan = plan_for(elbow)
      except ValueError as refused:
        why.append(f"elbow {elbow}: {refused}")
        continue
      hits = iswap.collisions(plan) if iswap.check_collisions else []
      if hits:
        why.append(f"elbow {elbow}: hits {', '.join(sorted({h.obstacle.name for h in hits}))}")
        continue
      await iswap.execute(plan)
      return
    raise ValueError("no elbow stop clears: " + "; ".join(why))

  async def onto(self, thing: Resource, target: Resource) -> None:
    self.say(f"{thing.name} -> onto {target.name}")
    await self.move(thing, target)
