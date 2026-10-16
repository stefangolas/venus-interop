"""PLR -> Venus definitions, and definition round trips in both directions."""
import importlib
import logging
import math
import pathlib
import sys

import pytest

pytest.importorskip("pylabrobot")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
import roundtrip_definitions as rt  # noqa: E402

from conftest import CORPUS  # noqa: E402
from venus_interop.plr import generate, name_match, to_venus  # noqa: E402
from venus_interop.files.definitions import DefinitionStore  # noqa: E402

logging.getLogger("pylabrobot").setLevel(logging.ERROR)

# what Venus cannot hold, or where the difference is understood (CONVENTIONS.md section 10)
EXPECTED = {
  "Wash_Station_Cleaner_shallow", "Wash_Station_Waste", "Wash_Station_Cleaner_deep",  # trash, not labware
  "opentrons_10_tuberack_falcon_4x50ml_6x15ml_conical",  # mixed tube sizes: not a single-container grid
  "opentrons_10_tuberack_nest_4x50ml_6x15ml_conical",
  "alpaqua_12_tuberack_5mL_eppis",  # empty holders: the Venus container is sized to the holder
  "Eppendorf_96_wellplate_250ul_Vb",  # PLR's volume at height 0 is 0.89 uL; Venus volumes start at 0
}


def roundtrip(resource, name, tmp_path):
  files = to_venus.venus_files(resource, name=name)
  to_venus.write(files, tmp_path)
  store = DefinitionStore([tmp_path])
  back = rt.build(generate.spec_for(store.get(files.main), store, name))
  return files, rt.compare(resource, back)


def within(d):
  return all(v is None or (k in rt.TOL and v <= rt.TOL[k]) or (k == "tip" and v == 0.0) or k not in rt.TOL | {"tip": 0}
             for k, v in d.items())


def test_cubic_is_exact_for_a_cone():
  r, h_total = 3.0, 6.0
  cone = lambda h: math.pi / 3 * (r * h / h_total) ** 2 * h  # noqa: E731
  a, b, c = to_venus._cubic(cone(0), cone(2), cone(4), cone(6), 6.0)
  assert a * 5 + b * 25 + c * 125 == pytest.approx(cone(5), rel=1e-9)


def test_a_step_in_the_well_gets_its_own_segment_boundary():
  from pylabrobot.resources import Well

  def volume(h):  # 1.85 mm outlet for 8.5 mm, then 6.9 mm wide
    return 2.688 * min(h, 8.5) + 37.3928 * max(h - 8.5, 0)

  w = Well("w", 6.9, 6.9, 37.5, compute_volume_from_height=volume)
  f = to_venus._container_fields(w, "x.ctr")
  ctr = generate.container(generate.Definition("x.ctr", "CONTAINER", f))
  for h in (4, 8.5, 12, 30, 37.5):
    assert ctr.volume(h) == pytest.approx(volume(h), abs=1e-3 * volume(37.5))  # 0.1 % of full
  assert int(f["Segments"]) <= to_venus.MAX_SEGMENTS


CATALOGUE = None


def catalogue():
  global CATALOGUE
  if CATALOGUE is None:
    CATALOGUE = [c for c in name_match.plr_catalogue() if "Deprecated alias" not in c.doc]
  return CATALOGUE


def test_plr_catalogue_round_trips_through_venus_files(tmp_path):
  failures = []
  for c in catalogue():
    fn = c.factory.rsplit(".", 1)[-1]
    if fn in EXPECTED:
      continue
    a = getattr(importlib.import_module(c.factory.rsplit(".", 1)[0]), fn)("x")
    try:
      _, d = roundtrip(a, fn, tmp_path / fn)
    except Exception as e:  # noqa: BLE001
      failures.append((fn, f"{type(e).__name__}: {e}"))
      continue
    bad = {k: v for k, v in d.items() if k in rt.TOL and v is not None and v > rt.TOL[k]}
    if d.get("tip") not in (None, 0.0):
      bad["tip"] = d["tip"]
    if bad:
      failures.append((fn, bad))
  assert not failures, failures


@pytest.mark.skipif(CORPUS is None, reason="VENUS_INTEROP_CORPUS not set")
def test_corpus_definitions_round_trip(tmp_path):
  results = rt.venus_roundtrip(CORPUS)
  bad = {}
  for rel, (cls, d, _) in results.items():
    if "error" in d:
      bad[rel] = d["error"]
      continue
    off = {k: v for k, v in d.items() if k in rt.TOL and v is not None and v > rt.TOL[k]}
    if d.get("tip") not in (None, 0.0):
      off["tip"] = d["tip"]
    if off:
      bad[rel] = off
  assert len(results) > 150
  assert not bad, bad
