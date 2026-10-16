"""Resolving references inside definitions."""
from venus_interop.files import hxcfg
from venus_interop.files.definitions import DefinitionStore, Rack


def write_def(path, type_, fields):
  cfg = hxcfg.CfgFile(sections=[hxcfg.Section(type_, 3, "default", entries=sorted(fields.items()))])
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_bytes(hxcfg.write_binary(cfg))


def test_stale_absolute_path_falls_back_to_rel_twin(tmp_path):
  lab = tmp_path / "Labware"
  write_def(lab / "Kit" / "plate.ctr", "CONTAINER", {"Depth": "10"})
  write_def(lab / "Kit" / "plate.rck", "RECTRACK", {
    "Cntr.1.file": r"C:\Users\someone\Documents\Labware Definitions\plate.ctr",  # the author's PC
    "Cntr.1.fileRel": r".\plate.ctr",
  })
  store = DefinitionStore([lab])
  rack = store.rack(r"Kit\plate.rck")
  assert isinstance(rack, Rack)
  ctr = store.ref(rack, "Cntr.1.file")
  assert ctr is not None and ctr.num("Depth") == 10
  assert not store.missing


def test_reference_by_name_when_the_folder_moved(tmp_path):
  lab = tmp_path / "Labware"
  write_def(lab / "Moved" / "plate.ctr", "CONTAINER", {"Depth": "7"})
  write_def(lab / "Kit" / "plate.rck", "RECTRACK", {"Cntr.1.file": r"Old\plate.ctr"})
  store = DefinitionStore([lab])
  assert store.ref(store.rack(r"Kit\plate.rck"), "Cntr.1.file").num("Depth") == 7


def test_unresolvable_reference_is_reported(tmp_path):
  lab = tmp_path / "Labware"
  write_def(lab / "plate.rck", "RECTRACK", {"Cntr.1.file": r"Nowhere\gone.ctr"})
  store = DefinitionStore([lab])
  assert store.ref(store.rack("plate.rck"), "Cntr.1.file") is None
  assert "nowhere/gone.ctr" in store.missing
