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
