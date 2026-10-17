"""Venus liquid classes: the database reader (tools/liquid_classes.py) and their PLR form.

The reader is checked against PyLabRobot's STAR table, which was generated from Hamilton's own
classes: every class both have must agree, curve and parameters. Needs VENUS_INTEROP_LIQUIDS (a
Venus `ML_STARLiquids.mdb`), access-parser and pylabrobot; the loader's cases need pylabrobot only.
"""
import os
import pathlib

import pytest

pytest.importorskip("pylabrobot.hamilton.liquid_classes.base")

from venus_interop.plr.liquid_classes import VenusLiquidClasses  # noqa: E402

DB = pathlib.Path(os.environ["VENUS_INTEROP_LIQUIDS"]) if os.environ.get("VENUS_INTEROP_LIQUIDS") else None

CLASS = {"name": "Mine_Water", "liquid": "Water", "tip_type": 5, "dispense_mode": 5, "hamilton": False,
         "curve": [[0.0, 0.0], [100.0, 104.5]],
         "parameters": {"aspiration_flow_rate": 250.0, "aspiration_mix_flow_rate": 500.0,
                        "aspiration_air_transport_volume": 5.0, "aspiration_blow_out_volume": 0.0,
                        "aspiration_swap_speed": 2.0, "aspiration_settling_time": 1.0,
                        "aspiration_over_aspirate_volume": 0.0, "aspiration_clot_retract_height": 0.0,
                        "dispense_flow_rate": 120.0, "dispense_mode": 5.0, "dispense_mix_flow_rate": 500.0,
                        "dispense_air_transport_volume": 5.0, "dispense_blow_out_volume": 0.0,
                        "dispense_swap_speed": 2.0, "dispense_settling_time": 0.0,
                        "dispense_stop_flow_rate": 100.0, "dispense_stop_back_volume": 0.0}}


def test_a_class_from_the_database_by_its_venus_name():
  lcs = VenusLiquidClasses([CLASS])
  lc = lcs.get("Mine_Water")
  assert lc.curve == {0.0: 0.0, 100.0: 104.5} and lc.aspiration_mix_flow_rate == 500.0
  assert (lcs.tip_type("Mine_Water"), lcs.dispense_mode("Mine_Water")) == (5, 5)


def test_a_name_the_database_lacks_falls_back_to_plr_and_is_listed_when_neither_has_it():
  lcs = VenusLiquidClasses([])
  assert lcs.get("HighVolumeFilter_Water_DispenseJet_Empty") is not None
  assert lcs.get("Nobody_Has_This") is None and lcs.missing == {"Nobody_Has_This"}


@pytest.mark.skipif(DB is None, reason="VENUS_INTEROP_LIQUIDS not set")
def test_the_database_agrees_with_plr_on_every_class_both_have():
  pytest.importorskip("access_parser")
  import liquid_classes as reader  # tools/

  classes = reader.read(DB)
  assert len(classes) > 100 and all(c["curve"] for c in classes if c["hamilton"])
  assert reader.check_plr(classes) == 0
