"""Placement and sequence rules measured on the 152-layout corpus (see SPEC.md 2.4).

Pure functions plus `rule_report`, which checks every rule on one layout and lists each failure
by labware id, so deviations are reported, never silently corrected.
"""
from __future__ import annotations

import collections
import dataclasses
import re
from typing import Optional

from venus_interop.files.definitions import Carrier, DefinitionStore, Lid, Rack
from venus_interop.files.layout import Layout, Placement

TRACK_WIDTH = 22.5
RAIL_ORIGIN = (100.0, 63.0, 100.0)  # rail 1, front-left corner of a carrier, deck Z
TOL = 0.01
_RAIL_SITE = re.compile(r"(\d+)T-(M?)(\d+)")


# ---------------------------------------------------------------------------------------- geometry


def parse_rail(site_id: str) -> Optional[int]:
  """'6T-24' -> 24, '6T-M3' -> -3, anything else -> None."""
  m = _RAIL_SITE.fullmatch(site_id)
  if m is None:
    return None
  return -int(m.group(3)) if m.group(2) else int(m.group(3))


def rail_location(rail: int) -> tuple[float, float, float]:
  x0, y0, z0 = RAIL_ORIGIN
  return x0 + (rail - 1) * TRACK_WIDTH, y0, z0


def rail_site_id(width_tracks: int, rail: int) -> str:
  return f"{width_tracks}T-{'M' if rail < 0 else ''}{abs(rail)}"


def a1_offset(rack: Rack) -> tuple[float, float]:
  """TForm.3 minus the rack corner: position 1, from BndryX/BndryY at the front-left. Position 1 is
  the back-left (A1), or with IX.Start = 1 the front-left itself (Venus's positions, the sweep of
  2026-10-22: Ans_96_C18_SPE)."""
  bx, by = rack.boundary
  if rack.fields.get("IX.Start", "0") == "1":
    return bx, by
  return bx, by + ((rack.rows or 1) - 1) * rack.dy


def rack_tform(corner: tuple[float, float], rack: Rack) -> tuple[float, float]:
  dx, dy = a1_offset(rack)
  return corner[0] + dx, corner[1] + dy


def rack_corner(tform: tuple[float, float], rack: Rack) -> tuple[float, float]:
  dx, dy = a1_offset(rack)
  return tform[0] - dx, tform[1] - dy


def lid_corner(plate_corner: tuple[float, float], rack: Rack, lid: Lid) -> tuple[float, float]:
  """Lids are centred on the plate footprint. (Lid Z: no rule yet; keep what is stored.)"""
  return (
    plate_corner[0] + (rack.dim[0] - lid.dim[0]) / 2,
    plate_corner[1] + (rack.dim[1] - lid.dim[1]) / 2,
  )


def stack_z(site_z: float, racks_bottom_up: list[Rack]) -> list[float]:
  """Each rack sits on the one below at that one's StackHt."""
  out, z = [], site_z
  for r in racks_bottom_up:
    out.append(z)
    z += r.stack_height
  return out


# ---------------------------------------------------------------------------------------- sequences


def row_name(r: int) -> str:
  s = ""
  while r:
    r -= 1
    s = chr(65 + r % 26) + s
    r //= 26
  return s


class UnsupportedNaming(ValueError):
  pass


# (IX.Index, IX.Inc) -> how a grid rack's positions are named, with the corpus evidence.
#   IX.Index: 1 = letter + number, 0 = number only.   IX.Inc: which way the labels run.
NAMING = {
  ("1", "0"): "letters on rows (A1, B1, ...), column-major",              # 585+ exact sequences
  ("0", "1"): "numbered down the columns, column-major",                  # 1201+ exact sequences
  ("0", "0"): "numbered across the rows, column-major order",             # 2 exact (Nunc 1.3 ml plates)
  ("1", "1"): "letters on columns, numbers on rows, letters fastest",     # 1 sequence (ans_96_c18_spe)
}
VALIDATED = {("1", "0"), ("0", "1"), ("0", "0")}


def naming_confidence(rack: Rack) -> str:
  """'validated' | 'single example' | 'unverified'."""
  if not rack.rows or not rack.columns or rack.rows == 1 or rack.columns == 1:
    return "validated"  # IX.Inc and IX.Start cannot change a single row or column
  if rack.fields.get("IX.Start", "0") not in ("0", "1"):
    return "unverified"
  if rack.fields.get("IX.Start", "0") == "1":
    return "single example"  # one rack, its positions measured in Venus (Ans_96_C18_SPE)
  return "validated" if (rack.index_mode, rack.fields.get("IX.Inc")) in VALIDATED else "single example"


def default_grid(rack: Rack) -> list[tuple[str, int, int]]:
  """A grid rack's default sequence as (name, row, column), named by its IX.* settings. Row 1 is
  position 1's row: the back row, or the front row with IX.Start = 1 (see `a1_offset`)."""
  rows, cols = rack.rows, rack.columns
  key = (rack.index_mode, rack.fields.get("IX.Inc", "0"))
  if key not in NAMING or rack.fields.get("IX.First", "1") != "1":
    raise UnsupportedNaming(f"{rack.path}: IX.Index/Inc/First = {key}, {rack.fields.get('IX.First')}")
  cm = [(r, c) for c in range(1, cols + 1) for r in range(1, rows + 1)]
  if key == ("1", "0"):
    return [(f"{row_name(r)}{c}", r, c) for r, c in cm]
  if key == ("0", "1"):
    return [(str((c - 1) * rows + r), r, c) for r, c in cm]
  if key == ("0", "0"):
    return [(str((r - 1) * cols + c), r, c) for r, c in cm]
  return [(f"{row_name(c)}{r}", r, c) for r in range(1, rows + 1) for c in range(1, cols + 1)]


def default_positions(rack: Rack) -> list[str]:
  """Positions of a rack's default sequence, named by its IX.* settings."""
  if not rack.rows or not rack.columns:
    return [str(i) for i in range(1, rack.hole_count + 1)]
  return [name for name, _, _ in default_grid(rack)]


def default_sequence(labware_id: str, rack: Rack) -> list[tuple[str, str]]:
  return [(labware_id, p) for p in default_positions(rack)]


# ---------------------------------------------------------------------------------------- report


@dataclasses.dataclass
class RuleResult:
  passed: int = 0
  failures: list[tuple[str, str]] = dataclasses.field(default_factory=list)  # (labware id, detail)
  skipped: int = 0

  @property
  def total(self) -> int:
    return self.passed + len(self.failures)

  def check(self, ok: bool, lid: str, detail: str) -> None:
    if ok:
      self.passed += 1
    else:
      self.failures.append((lid, detail))


RULES = ("carrier_on_rail", "rack_on_rail", "rack_on_site", "rack_z", "stack_step", "lid_name", "lid_xy",
         "default_sequence", "sequence_names")
STAR_DECKS = ("ml_star2.dck", "ml_starlet.dck", "ml_flexstar.dck")


def _close(a, b) -> bool:
  return all(abs(x - y) <= TOL for x, y in zip(a, b))


def rule_report(layout: Layout, store: DefinitionStore) -> dict[str, RuleResult]:
  rep = {r: RuleResult() for r in RULES}
  if layout.header.get("Deck", "").lower() not in STAR_DECKS:
    return rep  # rail geometry measured on STAR-family decks only
  by_id = layout.by_id()

  for p in layout.labware:
    if p.angle != 0:
      continue
    rack = store.rack(p.file)
    rail = parse_rail(p.site_id) if p.template == "default" else None
    if p.lid is not None:
      rep["lid_name"].check(p.lid.id == p.id + "_lid", p.id, p.lid.id)

    if rail is not None and p.kind == "carrier":
      exp = rail_location(rail)
      got = (p.tform[0], p.tform[1], p.z)
      rep["carrier_on_rail"].check(_close(got, exp), p.id, f"{got} != {exp}")

    if rack is None:
      continue
    corner = rack_corner(p.tform[:2], rack)

    if rail is not None:
      exp = rail_location(rail)[:2]
      rep["rack_on_rail"].check(_close(corner, exp), p.id, f"corner {corner} != {exp}")
    elif p.template != "default":
      carrier_p = by_id.get(p.template)
      carrier = store.carrier(carrier_p.file) if carrier_p else None
      site = carrier.sites.get(p.site_id) if carrier else None
      if site is None:
        rep["rack_on_site"].skipped += 1
      else:
        exp = (carrier_p.tform[0] + site.x, carrier_p.tform[1] + site.y)
        rep["rack_on_site"].check(_close(corner, exp), p.id, f"corner {corner} != site {exp}")

    if p.lid is not None:
      lid = store.lid(p.lid.file)
      if lid is not None:
        exp = lid_corner(corner, rack, lid)
        rep["lid_xy"].check(_close(p.lid.tform[:2], exp), p.id, f"{p.lid.tform[:2]} != {exp}")

    if p.def_seq_valid:
      seq = layout.sequence(p.id)
      expected = default_sequence(p.id, rack)
      got = seq.items if seq else None
      rep["default_sequence"].check(got == expected, p.id, _sequence_deviation(layout, p.id, got, expected))
      if got is not None:
        rep["sequence_names"].check(set(got) <= set(expected), p.id, f"{sorted(set(got) - set(expected))[:3]}")

  _check_z(layout, store, by_id, rep)
  return rep


def _sequence_deviation(layout, labware_id, got, expected) -> str:
  """Why a stored default sequence differs from the generated one. All seen so far are user edits."""
  if got is None:
    shared = [s.name for s in layout.sequences if any(o == labware_id for o, _ in s.items)]
    return f"missing; in shared sequence {shared[0]}" if shared else "missing"
  if sorted(got) == sorted(expected):
    return "reordered"
  if set(got) < set(expected):
    return f"subset ({len(got)} of {len(expected)})"
  return f"different positions {got[:3]}"


def _check_z(layout, store, by_id, rep) -> None:
  """Bottom rack on a site sits at site Z; each rack above sits at the lower one's Z + StackHt."""
  groups: dict[tuple[str, str], list[tuple[Placement, Rack]]] = collections.defaultdict(list)
  for p in layout.labware:
    rack = store.rack(p.file)
    if rack is not None and p.template != "default" and p.z_mode in (0, 1) and p.angle == 0:
      groups[(p.template, p.site_id)].append((p, rack))
  for (tpl, sid), members in groups.items():
    carrier_p = by_id.get(tpl)
    carrier = store.carrier(carrier_p.file) if carrier_p else None
    site = carrier.sites.get(sid) if carrier else None
    if site is None:
      continue
    site_z = carrier_p.z + site.z
    members.sort(key=lambda pr: pr[0].z)
    for i, (p, rack) in enumerate(members):
      if i == 0 or abs(p.z - members[i - 1][0].z) <= TOL:  # same Z: alternatives, not a stack
        rep["rack_z"].check(abs(p.z - site_z) <= TOL, p.id, f"z {p.z} != site z {site_z}")
      else:
        lower, lower_rack = members[i - 1]
        exp = lower.z + lower_rack.stack_height
        rep["stack_step"].check(abs(p.z - exp) <= TOL, p.id, f"z {p.z} != {lower.id} + StackHt = {exp}")
