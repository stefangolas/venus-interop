"""Method packages (.pkg): a synthetic package always, real ones from VENUS_INTEROP_PKGS
(a folder of .pkg files) when set."""
import os
import pathlib
import struct
import zlib

import pytest

from venus_interop.files import hxcfg, pkg

H = "C:\\Program Files (x86)\\Hamilton\\"
PKGS = sorted(pathlib.Path(os.environ["VENUS_INTEROP_PKGS"]).glob("*.pkg")) if os.environ.get("VENUS_INTEROP_PKGS") else []


def _item(key, eid, name, path, refs=()):
  out = [f"({key}", "1-347734010", "", "3-347734011", "-1", "3-347734012", "2", "1-347734013", eid,
         "1-347734014", name, "3-347734004", "0", "1-347734015", path, "(-347734008", ")", "(-347734009"]
  for k, r in enumerate(refs):
    out += [f"({k}", "1-347734000", r, "3-347733998", "0", ")"]
  return out + [")", ")"]


def build(files, manifest_last=True):
  """files: (id, name, path, data or None, refs). Returns the package's bytes."""
  items = ["(ListInfo", "3-347733952", "0", ")", "(ListItems"]
  for k, (eid, name, path, data, refs) in enumerate(files):
    items += _item(str(100 + k), eid if data is not None else "", name, path, refs)
  items += [")"]
  manifest = hxcfg.write(hxcfg.CfgFile(sections=[hxcfg.Section("HxPars", 3, "McListData", items=items)]))
  blobs = [(eid, 1, data) for eid, _, _, data, _ in files if data is not None]
  blobs.append(("00000ff", 0, manifest) if manifest_last else ("0000000", 0, manifest))
  if not manifest_last:
    blobs = blobs[-1:] + blobs[:-1]
  head = b"HamPkg" + struct.pack("<4HIQ", 0, 2, 1, 0, len(blobs), 133432165000000000)
  head += b"6.0.2.50007".ljust(20, b"\0")
  table, body = [], []
  at = len(head) + 36 * len(blobs)
  for eid, flag, data in blobs:
    z = zlib.compress(data)
    chunk = struct.pack("<II", len(data), len(z)) + z
    table.append(struct.pack("<8sIQQII", eid.encode().ljust(8, b"\0"), flag, 0, 0, at, len(chunk)))
    body.append(chunk)
    at += len(chunk)
  return head + b"".join(table) + b"".join(body)


FILES = [
  ("0000001", "Demo\\Method.hsl", H + "Methods\\Demo\\Method.hsl", b"method main() {}\r\n", ()),
  ("0000002", "Demo\\Method.lay", H + "Methods\\Demo\\Method.lay", b"layout",
   ("ML_STAR\\PLT_CAR_L5AC_A00.tml", "Hamilton\\Plate.rck")),
  ("0000003", "Hamilton\\Plate.rck", H + "Labware\\Hamilton\\Plate.rck", b"rack", ()),
  ("0000004", "SystemConf", "C:\\Users\\someone\\AppData\\Local\\Temp\\{GUID}\\SystemConf", b"conf", ()),
  ("", "HSLMECCLib.hs_", H + "Library\\HSLMECCLib.hs_", None, ()),
]


@pytest.mark.parametrize("manifest_last", [True, False])
def test_read_synthetic(manifest_last):
  p = pkg.read(build(FILES, manifest_last))
  assert p.venus_version == "6.0.2.50007"
  assert p.header_words == (0, 2, 1, 0)
  assert p.created.year == 2023
  assert [f.name for f in p.files] == [f[1] for f in FILES]
  assert [f.carried for f in p.files] == [True, True, True, True, False]
  assert p.file("method.hsl").data == b"method main() {}\r\n"
  assert p.file("Demo\\Method.lay").refs == ["ML_STAR\\PLT_CAR_L5AC_A00.tml", "Hamilton\\Plate.rck"]


def test_install_paths_stay_inside():
  assert str(pkg.install_relpath(H + "Labware\\Hamilton\\Plate.rck")) == "Labware/Hamilton/Plate.rck"
  assert str(pkg.install_relpath("C:\\Temp\\{G}\\SystemConf")) == "_external/SystemConf"
  # ".." is resolved first: climbing out of the Hamilton folder makes the file external
  assert str(pkg.install_relpath(H + "Library\\..\\..\\..\\Windows\\evil.dll")) == "_external/evil.dll"
  assert str(pkg.install_relpath("\\\\server\\share\\Hamilton\\Library\\..\\x.hsl")) == "x.hsl"


def test_extract(tmp_path):
  written = pkg.extract(pkg.read(build(FILES)), tmp_path)
  rel = sorted(p.relative_to(tmp_path).as_posix() for p in written)
  assert rel == ["Labware/Hamilton/Plate.rck", "Methods/Demo/Method.hsl", "Methods/Demo/Method.lay",
                 "_external/0000004_SystemConf"]
  assert (tmp_path / "Labware/Hamilton/Plate.rck").read_bytes() == b"rack"


def test_rejects_damage():
  data = build(FILES)
  with pytest.raises(pkg.FormatError):
    pkg.read(b"NotPkg" + data[6:])
  with pytest.raises(pkg.FormatError):
    pkg.read(data[:-10])  # the last entry runs past the end
  # the manifest names 0000003, but the entry table now calls that entry 000000a
  bad = data.replace(b"0000003\0", b"000000a\0", 1)
  with pytest.raises(pkg.FormatError, match="lacks"):
    pkg.read(bad)


@pytest.mark.parametrize("path", [pytest.param(p, id=p.name) for p in PKGS] or
                         [pytest.param(None, marks=pytest.mark.skip(reason="VENUS_INTEROP_PKGS not set"))])
def test_real_packages(path, tmp_path):
  p = pkg.read(path)
  carried = [f for f in p.files if f.carried]
  assert carried and len(carried) == len(p.entries) - 1  # every entry but the manifest is a listed file
  assert {f.id for f in carried} | {p.manifest_id} == {e.id for e in p.entries}
  assert len(pkg.extract(p, tmp_path)) == len(carried)
