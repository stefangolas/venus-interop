"""Hamilton's HSLTipCountingLib (`TipCount::Read2` / `Write2`): tip racks that carry over between runs.

A Venus tip counter is a named, persisted record of which positions of a tip rack still hold tips. A
method reads its counters into its tip sequences at the start (`Read2`) and writes them back at
the end (`Write2`), so the next run starts where this one stopped. Read2: no counter stored, -1
and the sequence untouched; else the sequence reset to the layout's and set from the counter, and a
rack with no tips left gets end and current position 0. Write2: the sequence into the counter,
created if new.

Venus keeps counters in its compiled element counter (HxElementCounter), an Access database made
from `Config\\HxElementCounter_template.mdb`: table ElementCounters (ID, Name, InstrumentClass,
LabwareType, Modified, SimulationModified), Positions and SimulationPositions (ElementCounterID,
PositionID, Status), Status 0 empty / 1 occupied (`HxECPositionStatus`). `TipCounters` keeps the
same tables in SQLite, with each position's labware and order added (STAR Tip Tools' counters span
racks). How Venus applies the statuses to a sequence is open (CONVENTIONS §11): here a sequence
starts at its first occupied position, which is the same while tips are taken in order.
"""
from __future__ import annotations

import pathlib
import sqlite3
import time
from typing import Optional, Sequence

from venus_interop.methods import sequences as sq

LIBRARY = "TIPCOUNT"  # the Venus namespace ported

EMPTY, OCCUPIED = 0, 1  # HxECPositionStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS Control (ID INTEGER PRIMARY KEY, Version INTEGER);
CREATE TABLE IF NOT EXISTS ElementCounters (ID INTEGER PRIMARY KEY, Name TEXT UNIQUE NOT NULL,
  InstrumentClass TEXT, LabwareType TEXT, Modified REAL DEFAULT 0, SimulationModified REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS Positions (ElementCounterID INTEGER, Ord INTEGER, LabwareID TEXT,
  PositionID TEXT, Status INTEGER, PRIMARY KEY (ElementCounterID, Ord));
CREATE TABLE IF NOT EXISTS SimulationPositions (ElementCounterID INTEGER, Ord INTEGER, LabwareID TEXT,
  PositionID TEXT, Status INTEGER, PRIMARY KEY (ElementCounterID, Ord));
INSERT OR IGNORE INTO Control VALUES (1, 2);
"""

Statuses = list[tuple[sq.Item, int]]  # each position, in order, with its status


def statuses(items: Sequence[sq.Item], cur: int) -> Statuses:
  """A tip sequence's positions as a counter stores them: those before the current one used (all
  of them when the sequence is completed, cur 0)."""
  first = cur - 1 if cur > 0 else len(items)
  return [(tuple(it), EMPTY if i < first else OCCUPIED) for i, it in enumerate(items)]


class TipCounters:
  """Persisted tip counters (SQLite; in memory when `path` is None). `simulation`: read and write
  the simulation statuses, as Venus does in simulation mode, so simulated runs leave the real
  counters alone."""

  def __init__(self, path: Optional[pathlib.Path] = None, simulation: bool = False,
               instrument: str = "ML_STAR"):
    self.db = sqlite3.connect(str(path) if path is not None else ":memory:")
    self.db.executescript(_SCHEMA)
    self.table = "SimulationPositions" if simulation else "Positions"
    self.modified = "SimulationModified" if simulation else "Modified"
    self.instrument = instrument

  def _id(self, name: str) -> Optional[int]:
    row = self.db.execute("SELECT ID FROM ElementCounters WHERE Name = ?", (name,)).fetchone()
    return row[0] if row else None

  def exists(self, name: str) -> bool:
    return self._id(name) is not None

  def read(self, name: str) -> Optional[Statuses]:
    """The counter's positions and statuses, in order; None when it is not stored."""
    cid = self._id(name)
    if cid is None:
      return None
    rows = self.db.execute(f"SELECT LabwareID, PositionID, Status FROM {self.table} "
                           "WHERE ElementCounterID = ? ORDER BY Ord", (cid,)).fetchall()
    return [((lab, pos), status) for lab, pos, status in rows]

  def write(self, name: str, positions: Statuses, labware_type: str = "") -> None:
    """Replace the counter's positions (creating the counter), in one transaction."""
    with self.db:
      cid = self._id(name)
      if cid is None:
        cid = self.db.execute("INSERT INTO ElementCounters (Name, InstrumentClass, LabwareType) VALUES (?, ?, ?)",
                              (name, self.instrument, labware_type)).lastrowid
      self.db.execute(f"DELETE FROM {self.table} WHERE ElementCounterID = ?", (cid,))
      self.db.executemany(f"INSERT INTO {self.table} VALUES (?, ?, ?, ?, ?)",
                          [(cid, i, lab, pos, status) for i, ((lab, pos), status) in enumerate(positions)])
      self.db.execute(f"UPDATE ElementCounters SET {self.modified} = ? WHERE ID = ?", (time.time(), cid))


class TipCount:
  def __init__(self, deck, counters: TipCounters):
    self.v, self.counters = deck, counters  # deck: `seq(name)` live, `sequences[name]` the layout's

  def Read2(self, sequence: str, tip_counter: str, device=None) -> int:
    stored = self.counters.read(tip_counter)
    if stored is None:
      return -1
    s = self.v.seq(sequence)
    s.assign(sq.Sequence(sequence, list(self.v.sequences[sequence])))
    status = dict(stored)
    used = [it for it in s.items if status.get(it) == EMPTY]
    first = next((i + 1 for i, it in enumerate(s.items) if status.get(it, OCCUPIED) == OCCUPIED), 0)
    if first > 0:
      s.set_current_position(first)
    else:
      s.set_count(0)
      s.set_current_position(0)
    self._mark_used(used)
    return 1

  def Write2(self, sequence: str, tip_counter: str, device=None) -> int:
    s = self.v.seq(sequence)
    self.counters.write(tip_counter, statuses(s.items, s.cur))
    return 1

  def _mark_used(self, items: Sequence[sq.Item]) -> None:
    """Those positions' tips gone, where the deck tracks tips."""
    resolve = getattr(self.v, "resolve", None)
    if resolve is None:
      return
    for item in items:
      spot = resolve(item)
      if getattr(spot, "has_tip", lambda: False)():
        spot.tracker.remove_tip()
