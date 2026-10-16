"""The generic multiflex configurator. Needs pylabrobot."""
import pytest

pytest.importorskip("pylabrobot")

from pylabrobot.resources import Resource  # noqa: E402

from venus_interop.multiflex import assembly  # noqa: E402
from venus_interop.multiflex.catalogue import catalogue  # noqa: E402
from venus_interop.multiflex.plr import mfx_carrier  # noqa: E402


def test_sbs_plate_is_centred_on_each_site():
  cat = catalogue()
  nest = next(m for m in cat.modules.values() if m.part_no == "199039")
  carrier = mfx_carrier("shaker", 3, {1: nest, 2: nest})
  assert carrier.get_size_x() == 157.5 and len(carrier.sites) == 2
  front = carrier.sites[0]  # PLR index 0 is the front: position 2
  plate = Resource("plate", 127.76, 85.48, 14)
  front.assign_child_resource(plate)
  c = plate.get_location_wrt(carrier) + plate.get_anchor("c", "c", "b")
  s = assembly.site(cat.baseplates[3], 2, nest)
  assert (c.x, c.y, c.z) == pytest.approx((s.x + 63.5, s.y + 43.0, s.z))
  assert front.metadata["venus"]["site_id"] == s.id
