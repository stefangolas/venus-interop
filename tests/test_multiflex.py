"""Multiflex catalogue and assembly rule."""
import os
import pathlib

import pytest

from venus_interop.files.definitions import Carrier, load
from venus_interop.multiflex import assembly
from venus_interop.multiflex.catalogue import catalogue

NGS = pathlib.Path(os.environ["VENUS_INTEROP_NGS"]) if os.environ.get("VENUS_INTEROP_NGS") else None


def by_part(part):
  return next(m for m in catalogue().modules.values() if m.part_no == part)


def test_catalogue_contents():
  cat = catalogue()
  assert len(cat.baseplates) == 4 and len(cat.modules) == 99
  shaker = cat.baseplates[3]
  assert (shaker.origin_x, shaker.origin_y, shaker.pitch_y, shaker.width) == (15.25, 375.05, -120.0, 157.5)


def test_worked_example_hhs_nunc_dwp_on_shaker_position_2():
  # docs/notes/MULTIFLEX_ASSEMBLY.md: matches MFX_CAR_2HHS30NuncDWP_2CPACflat.tml site 2
  s = assembly.site(catalogue().baseplates[3], 2, by_part("199039"))
  assert (s.x, s.y, s.z, s.dx, s.dy) == pytest.approx((15.25, 253.5, 83.0, 127.0, 86.0))


def test_companion_module_adds_a_second_site():
  cat = catalogue()
  host = next(m for m in cat.modules.values() if m.add_module and m.add_module in cat.modules
              and cat.baseplates[1].index not in m.not_valid_for)
  sites = assembly.sites(1, {3: host})
  assert len(sites) == 2 and sites[0].position == sites[1].position == 3
  assert sites[1].z == cat.modules[host.add_module].base


def test_invalid_module_is_refused():
  cat = catalogue()
  module = next(m for m in cat.modules.values() if 3 in m.not_valid_for)
  with pytest.raises(ValueError):
    assembly.sites(3, {1: module})


def test_check_a_synthetic_carrier():
  b = catalogue().baseplates[3]
  nest = by_part("199039")
  fields = {"Dim.Dx": "157.5", "Dim.Dy": "497", "Dim.Dz": "130"}
  for n, (sid, z) in enumerate((("2_" + nest.id_name, 83), ("3_" + nest.id_name, 90)), 1):
    s = assembly.site(b, int(sid[0]), nest)
    fields.update({f"Site.{n}.Id": sid, f"Site.{n}.X": str(s.x), f"Site.{n}.Y": str(s.y), f"Site.{n}.Z": str(z),
                   f"Site.{n}.Dx": "127", f"Site.{n}.Dy": "86"})
  baseplate, checks = assembly.check(Carrier("x.tml", "TEMPLATE", fields))
  assert baseplate.index == 3
  by_id = {c.site_id: c for c in checks}
  assert by_id["2_" + nest.id_name].exact
  assert by_id["3_" + nest.id_name].error == pytest.approx(7.0)  # Z 90 against the module's 83


@pytest.mark.skipif(NGS is None, reason="VENUS_INTEROP_NGS not set")
def test_ngs_carriers_match_the_rule_except_known_points():
  known = {"4_CPAC", "3", "3_PCR96", "4_PCR96", "5_MIDI", "3_DWP"}  # docs/CONVENTIONS.md 3b, multiflex
  exact = total = 0
  for p in sorted((NGS / "assets").rglob("*.tml")):
    try:
      d = load(p)
    except Exception:  # noqa: BLE001
      continue
    if not isinstance(d, Carrier) or not assembly.is_multiflex(d):
      continue
    b, checks = assembly.check(d)
    for c in checks:
      if b is None or c.module == "no baseplate position here":
        continue
      total += 1
      exact += c.exact
      assert c.exact or c.site_id in known, (p.name, c)
  assert exact >= 31 and total >= 43
