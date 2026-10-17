"""What the NIST LMSF demos share: PLR's wastes and grip tools on an imported layout, gripper moves
to Venus placeholders, and volume helpers. The layout itself is `venus_interop.plr.venus_deck`.

Used by `marionette_demo.py`, `dna_extraction_demo.py` and `kapa_hyperplus_demo.py`. See those for
how to run them.
"""

import re
import pathlib
import sys
from typing import List, Optional, Sequence

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from venus_interop.plr.venus_deck import VenusDeck, corpus_index  # noqa: E402,F401

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
  parent.unassign_child_resource(waste)
  parent.assign_child_resource(
    Trash(v.deck.get_component_name("trash"), size_x=0, size_y=max(ys) - min(ys) + 20, size_z=0),
    location=Coordinate(spots[0].x, min(ys) - 10, spots[0].z))
  if slide_waste is not None:
    box = v.deck.get_resource(slide_waste)
    v.replace(slide_waste, lambda: Trash(v.deck.get_component_name("trash_core96"),
                                         size_x=122.4, size_y=82.6, size_z=box.get_size_z()))
  if grip_tools is not None:
    v.replace(grip_tools,
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
                           into: Optional[Resource] = None, iswap=None,
                           direction: str = "front",
                           elbows: Sequence[Optional[str]] = (None,)) -> Resource:
    """Move `thing` to where the layout has `placeholder`; later sequences naming it find `thing`.

    It goes down exactly where the placeholder stood (its centre-centre-bottom), or `into` a
    resource that stands for that place (a device's carrier). With the CO-RE grip tools, or with
    `iswap` (an `iSWAPTransport`) gripping from `direction`, where the channels do not reach: with
    the first of `elbows` (elbow stops; None is the planner's choice) whose plan it can reach and
    that hits nothing.
    """
    where = self.v.spots[placeholder]
    if self.v.deck.has_resource(placeholder):  # a stand-in still there, not the thing itself
      stand_in = self.v.deck.get_resource(placeholder)
      if stand_in is not thing:
        stand_in.parent.unassign_child_resource(stand_in)
    self.say(f"{thing.name} -> {placeholder}" + (" (iSWAP)" if iswap is not None else ""))
    g = self.star.core_grippers
    if iswap is None:
      await g.pick_up_tools()
      await g.pick_up_resource(thing)
      drop = g.drop_resource
    else:
      await self._iswap_step(iswap, lambda e: iswap.plan_pick_up(thing, direction=direction, elbow=e), elbows)

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
    if iswap is None:
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
