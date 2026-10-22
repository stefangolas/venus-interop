"""PLR_VENUS_FAITHFUL_CFG: Venus's defaults filled where a port leaves a setting to the driver."""
import asyncio
import dataclasses
import pathlib
import types

import pytest

from venus_interop.plr import faithful

VENUS_CFG = pathlib.Path(r"C:\Program Files (x86)\HAMILTON\Config\ML_STAR.cfg")


class Pipettes:
  default_minimum_traverse_height = 245.0

  def __init__(self):
    self.calls = []

  async def pick_up_tips(self, spots, minimum_traverse_height_start=None):
    self.calls.append(("pick_up", minimum_traverse_height_start))

  async def drop_tips(self, spots, minimum_traverse_height_start=None, minimum_traverse_height_end=None):
    self.calls.append(("drop", minimum_traverse_height_start, minimum_traverse_height_end))


@dataclasses.dataclass
class HeadConfiguration:
  traversal_z_position: float = 245.0


class CoreGrippers:
  default_minimum_traverse_height = 280.0

  def __init__(self):
    self.heights = []

  async def pick_up_tools_at_location(self, *args, **kwargs):
    self.heights.append(("tools", self.default_minimum_traverse_height))

  async def drop_tools(self, **kwargs):
    self.heights.append(("tools back", self.default_minimum_traverse_height))


def star():
  return types.SimpleNamespace(pipettes=Pipettes(), head96=types.SimpleNamespace(configuration=HeadConfiguration()),
                               core_grippers=CoreGrippers())


def test_unset_changes_nothing(monkeypatch):
  monkeypatch.delenv(faithful.ENV, raising=False)
  s = star()
  assert faithful.apply(s) is None
  assert s.core_grippers.default_minimum_traverse_height == 280.0


def test_stock_fills_only_what_the_port_left_out(monkeypatch):
  monkeypatch.setenv(faithful.ENV, "stock")
  s = star()
  p = faithful.apply(s)
  assert (p.traverse_height, p.core_gripper_traverse_height, p.source) == (245.0, 275.0, "stock")
  assert s.core_grippers.default_minimum_traverse_height == 275.0  # holding a plate
  asyncio.run(s.core_grippers.pick_up_tools_at_location(0, 0, 0, 0))
  asyncio.run(s.core_grippers.drop_tools())
  assert s.core_grippers.heights == [("tools", 245.0), ("tools back", 245.0)]  # a channel move
  assert s.core_grippers.default_minimum_traverse_height == 275.0
  assert s.head96.configuration.traversal_z_position == 245.0
  asyncio.run(s.pipettes.pick_up_tips([]))
  asyncio.run(s.pipettes.pick_up_tips([], minimum_traverse_height_start=260.0))
  asyncio.run(s.pipettes.drop_tips([]))
  assert s.pipettes.calls == [("pick_up", 245.0), ("pick_up", 260.0), ("drop", 245.0, 245.0)]
  faithful.apply(s)  # applying twice wraps once
  asyncio.run(s.pipettes.pick_up_tips([]))
  assert s.pipettes.calls[-1] == ("pick_up", 245.0)


def test_a_missing_cfg_is_an_error(monkeypatch, tmp_path):
  monkeypatch.setenv(faithful.ENV, str(tmp_path / "nope.cfg"))
  with pytest.raises(FileNotFoundError):
    faithful.profile()


@pytest.mark.skipif(not VENUS_CFG.is_file(), reason="no Venus install")
def test_read_from_the_instrument_cfg(monkeypatch):
  monkeypatch.setenv(faithful.ENV, str(VENUS_CFG))
  p = faithful.profile()
  assert (p.traverse_height, p.head96_traverse_height, p.core_gripper_traverse_height) == (245.0, 245.0, 275.0)


def test_venus_heights_from_max_depth():
  # Marionette's dispense not to liquid (0.3 mm, cLLD off): Venus sends zx = floor + MaxDepth and
  # zl = zx as sent + 0.3; without a profile, nothing is added
  from pylabrobot.resources import Coordinate, Plate, Resource, Well
  from venus_interop.plr import steps

  deck = Resource("deck", 1000, 1000, 100)
  well = Well("w", 7, 7, 10, material_z_thickness=1.0)
  well.location = Coordinate(5, 5, 1.3)
  plate = Plate("p", 20, 20, 12, ordered_items={"A1": well})
  deck.assign_child_resource(plate, location=Coordinate(100, 100, 170.0))
  well.metadata["venus"] = {"max_depth": 8.74, "lld_search_height": 48.7}
  step = steps.Pipetting(0, fluid_height=0.3)
  pip = types.SimpleNamespace(venus_profile=None)
  assert steps.venus_heights(pip, [well], step, {}) == {}
  pip.venus_profile = faithful.VenusProfile.stock()
  out = steps.venus_heights(pip, [well], step, {})
  assert out["minimum_allowed_z_positions_during"] == [181.04]  # 170 + 1.3 + 1.0 + 8.74
  assert 172.3 + out["liquid_heights"][0] == pytest.approx(181.3)  # from 181.0 as sent, not 181.34
  assert "liquid_heights" not in steps.venus_heights(pip, [well], steps.Pipetting(5, submerge=2.0), {})
  given = steps.venus_heights(pip, [well], step, {"minimum_allowed_z_positions_during": [150.0]})
  assert "minimum_allowed_z_positions_during" not in given  # the port's own value is kept
