"""The delta ledger: every number a conversion changes, and every interpretation it makes, recorded.

A conversion is accounted for when each difference between what went in and what comes back out
matches a ledger entry of the same size. `tools/verify` style checks compare a round trip against the
ledger and fail on anything unexplained. Kinds:

  stock_disagrees  a stock Hamilton file describes the same labware with different numbers
  convention       Venus and PLR measure the same thing from different reference points (exact, no loss)
  approximation    a number Venus cannot hold exactly (e.g. a volume formula), with its error bound
  interpretation   a choice where the source is ambiguous (e.g. rotated labware placed unrotated)
  missing          information that is not available (e.g. a definition file that cannot be found)
"""
from __future__ import annotations

import dataclasses
from typing import Any, Optional

TOL = 1e-3  # mm: below this, numbers are the same (pylabrobot rounds coordinates to 1e-4)


@dataclasses.dataclass
class Delta:
  resource: str
  kind: str
  quantity: str
  plr: Any = None  # the value on the PLR side
  venus: Any = None  # the value on the Venus side
  size: Optional[float] = None  # largest absolute difference, mm, when numeric
  decision: str = ""
  detail: str = ""

  def as_dict(self) -> dict:
    return {k: v for k, v in dataclasses.asdict(self).items() if v not in (None, "")}

  def line(self) -> str:
    size = f" ({self.size:.4g} mm)" if self.size is not None else ""
    return f"{self.resource}: {self.kind}: {self.quantity}{size}. {self.detail} {self.decision}".strip()


def _rel(r, item):
  """An item's centre-bottom relative to the rack's A1 centre (x, y) and the rack's bottom (z)."""
  c = item.get_absolute_location(x="c", y="c", z="b")
  a1 = r.get_item(0).get_absolute_location(x="c", y="c")
  return c.x - a1.x, c.y - a1.y, c.z - r.get_absolute_location().z


def _tip_bottom_offset(spot) -> Optional[float]:
  """Where a tip's bottom ends, relative to its spot's z (PLR: seat minus the part below it)."""
  try:
    tip = spot.make_tip()
  except Exception:  # noqa: BLE001
    return None
  return -(tip.get_size_z() - tip.fitting_depth)


def rack_differences(original, rebuilt, sinking: float = 0.0) -> list[tuple[str, Any, Any, float]]:
  """(quantity, original value, rebuilt value, size) for every way `rebuilt` differs from `original`.

  Both are placed racks. Positions are compared in the frame the exporter preserves: x, y from A1 and
  z from the rack's Venus bottom (PLR bottom + sinking depth for embedded tip racks)."""
  from pylabrobot.resources import ItemizedResource, TipSpot

  out = []
  for q, a, b in (("footprint x", original.get_size_x(), rebuilt.get_size_x()),
                  ("footprint y", original.get_size_y(), rebuilt.get_size_y()),
                  ("height", original.get_size_z(), rebuilt.get_size_z())):
    if abs(a - b) > TOL:
      out.append((q, round(a, 4), round(b, 4), abs(a - b)))
  if not (isinstance(original, ItemizedResource) and isinstance(rebuilt, ItemizedResource)):
    return out
  ia, ib = original.get_all_items(), rebuilt.get_all_items()
  if len(ia) != len(ib):
    return out + [("number of positions", len(ia), len(ib), float("inf"))]
  worst = {"position x/y": 0.0, "position z": 0.0, "item size": 0.0, "item depth": 0.0, "tip bottom": 0.0}
  example = {}
  for a, b in zip(ia, ib):
    (ax, ay, az), (bx, by, bz) = _rel(original, a), _rel(rebuilt, b)
    az -= sinking
    d = {"position x/y": max(abs(ax - bx), abs(ay - by)),
         "item size": max(abs(a.get_size_x() - b.get_size_x()), abs(a.get_size_y() - b.get_size_y()))}
    if isinstance(a, TipSpot):
      ta, tb = _tip_bottom_offset(a), _tip_bottom_offset(b)
      if ta is not None and tb is not None:
        d["tip bottom"] = abs((az + ta) - (bz + tb))
        example.setdefault("tip bottom", (round(az + ta, 4), round(bz + tb, 4)))
    else:
      d["position z"] = abs(az - bz)
      d["item depth"] = abs(a.get_size_z() - b.get_size_z())
      example.setdefault("position z", (round(az, 4), round(bz, 4)))
      example.setdefault("item depth", (round(a.get_size_z(), 4), round(b.get_size_z(), 4)))
    example.setdefault("item size", (round(a.get_size_x(), 4), round(b.get_size_x(), 4)))
    for k, v in d.items():
      worst[k] = max(worst[k], v)
  for k, v in worst.items():
    if v > TOL:
      a, b = example.get(k, (None, None))
      out.append((k, a, b, v))
  return out
