"""The Venus pipetting settings to PLR STAR arguments mapping (`venus_interop.plr.steps`)."""
import pytest

pytest.importorskip("pylabrobot.hamilton.star.driver.lld_mode")

from pylabrobot.hamilton.star.driver.lld_mode import LLDMode  # noqa: E402
from pylabrobot.lib.liquid_handling.mix import Mix  # noqa: E402

from venus_interop.plr.steps import MIX_FLOW, Pipetting, plr_arguments  # noqa: E402


def test_clld_on_searches_and_immerses():
  kw = plr_arguments(Pipetting(2, submerge=0.5, fluid_height=5, liquid_following=True), 3, aspirate=True)
  assert kw == {"auto_surface_following": True, "lld_mode": LLDMode.CAPACITIVE, "immersion_depths": [0.5] * 3}


def test_clld_off_goes_to_the_fluid_height_with_lld_off_given():
  # OFF is given, not left to PLR, whose default under surface following is capacitive
  kw = plr_arguments(Pipetting(0, submerge=2, fluid_height=0.3, liquid_following=True), 2, aspirate=False)
  assert kw == {"auto_surface_following": True, "lld_mode": LLDMode.OFF, "liquid_heights": [0.3] * 2}


def test_a_mix_is_a_pre_mix_at_its_position_or_a_post_mix():
  step = Pipetting(5, submerge=2, liquid_following=True, mix_cycles=3, mix_volume=100, mix_position=8)
  mix = Mix(volume=100, repetitions=3, flow_rate=MIX_FLOW)
  asp = plr_arguments(step, 1, aspirate=True)
  assert asp["pre_mixes"] == [mix] and asp["mix_positions_from_liquid_surface"] == [8]
  assert plr_arguments(step, 1, aspirate=False)["post_mixes"] == [mix]


def test_only_what_takes_effect_counts():
  # the record's fluid height under cLLD, its submerge depth without, a mix volume without cycles
  assert Pipetting(1, 0.5, fluid_height=5).effective() == Pipetting(1, 0.5, fluid_height=0).effective()
  assert Pipetting(0, 2, fluid_height=1).effective() == Pipetting(0, 0.5, fluid_height=1).effective()
  assert Pipetting(1, 0.5, mix_volume=50).effective() == Pipetting(1, 0.5).effective()
  assert Pipetting.from_record({"cLLD sensitivity": 5, "submerge depth": 2, "fluid height": 5, "LiquidFollowing": 1,
                                "mix cycles": 0, "mix volume": 0, "mix position": 2}) == \
    Pipetting(5, 2.0, 5.0, True, 0, 0.0, 2.0)


def test_iswap_grip_directions_follow_pyhamiltons_table():
  """Venus's (large side, inverted) -> where the wrist is in PLR. Not checkable against the HSL
  (Venus has no such direction): pinned to pyhamilton's transport table, whose short-side PCR grip
  (82.5 mm) is "RIGHT" and inverted "LEFT", the large side "FRONT" and inverted "BACK"; and to the
  KAPA demo, whose ODTC moves on the simulator grip from the right."""
  from venus_interop.plr.steps import IswapGrip

  grip = lambda large, inverse: IswapGrip(5, 82.2, 85, 5, inverse=inverse, large_side=large)  # noqa: E731
  assert [grip(False, False).direction, grip(False, True).direction] == ["right", "left"]
  assert [grip(True, False).direction, grip(True, True).direction] == ["front", "back"]
