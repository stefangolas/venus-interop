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
  assert out["lld_search_heights"] == [221.0]  # floor + LSHt, lp
  # under cLLD as well: zl = zx + the step's height (Marionette's aspirates: zx + 5.0)
  lld = steps.venus_heights(pip, [well], steps.Pipetting(5, submerge=2.0, fluid_height=5.0), {})
  assert 172.3 + lld["liquid_heights"][0] == pytest.approx(186.0)
  given = steps.venus_heights(pip, [well], step, {"minimum_allowed_z_positions_during": [150.0]})
  assert "minimum_allowed_z_positions_during" not in given  # the port's own value is kept


def test_one_pick_up_command_per_call():
  # Marionette: Venus picks 8 tips over two columns in one C0TP; PLR's planner split it in two
  pytest.importorskip("pylabrobot")
  from pylabrobot.hamilton.star.driver.features import pipettes as module

  planned = []

  class Planned(Pipettes):
    async def pick_up_tips(self, spots, minimum_traverse_height_start=None):
      planned.append(module.plan_batches)

  s = star()
  s.pipettes = Planned()
  original = module.plan_batches
  faithful.apply(s, faithful.VenusProfile.stock())
  asyncio.run(s.pipettes.pick_up_tips([]))
  assert planned[0] is not original  # one batch per call while it runs
  assert module.plan_batches is original  # and the driver's planner back after


def test_venus_following_is_volume_over_area():
  # Marionette's firmware: fp = the volume over the container's area, to 0.1 mm (Growth_Plate: 467.1 uL
  # over 59.29 mm2 is 7.9, a 450 uL mix's mh 7.6); a connected cavity takes all its channels' volume
  # over all its positions (Media_source: 4 x 456.8 uL over 96 x 88.36 mm2 is 0.2)
  from pylabrobot.lib.liquid_handling.mix import Mix
  from pylabrobot.resources import Coordinate, Plate, Well
  from venus_interop.plr import steps

  def plate(n, area, connected):
    wells = {}
    for i in range(n):
      w = Well(f"w{i}", 9, 9, 10)
      w.location = Coordinate(i * 9, 0, 0)
      w.metadata["venus"] = {"area": area, "connected": connected}
      wells[f"A{i + 1}"] = w
    return Plate("p", 9 * n, 9, 12, ordered_items=wells)

  step = steps.Pipetting(5, 2.0, liquid_following=True)
  growth = plate(2, 59.29, False)
  out = steps.venus_following([growth.get_item(0)], [467.1], step, None, [Mix(450.0, 2, 250.0)])
  assert out["surface_following_distances"] == [7.9] and out["auto_surface_following"] is False
  assert out["mixes"][0].surface_following_distance == 7.6
  trough = plate(96, 88.36, True)
  wells = [trough.get_item(i) for i in range(4)]
  assert steps.venus_following(wells, [456.8] * 4, step, None, None)["surface_following_distances"] == [0.2] * 4
  assert steps.venus_following(wells, [456.8] * 4, steps.Pipetting(0, fluid_height=1.0), None, None) == {}
