"""A Venus layout imported into PLR and addressed the way its method addresses it: by sequences.

`VenusDeck` holds the imported deck, the layout's sequences as live `methods.sequences.Sequence`
objects (one per name, shared by every step and library call, as `ML_STAR.Name` is in Venus), and
resolves a sequence item (labware id, Venus position id) to the PLR well, tip spot or resource.
Labware that moves is one object here, where Venus has a labware per place: `aliases` makes later
references to a placeholder resolve to the object that took its place.
"""

import csv
import pathlib
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

  def seq(self, name: str) -> sq.Sequence:
    """The layout sequence `name` as live Venus state: the same object on every call."""
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
