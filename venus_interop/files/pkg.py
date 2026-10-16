"""Hamilton method packages (.pkg, "HamPkg"): list and extract them without Venus.

A package is what Venus's Method Editor exports with File > Package (the Package Wizard,
`HxPackager`) and imports again: a method with its libraries, labware, deck layout and
configuration files, each stored zlib-compressed under an id. Layout, as measured on
`Deck Animations Library Demo 231101.pkg` (Venus 6.0.2.50007, 301 entries):

  0x00  "HamPkg"
  0x06  u16 0, u16 2, u16 1, u16 0      (kept as `header_words`; meaning unverified)
  0x0e  u32 entry count
  0x12  FILETIME                        (when the package was made)
  0x1a  Venus version, 20 bytes, NUL-padded
  0x2e  entries, 36 bytes each:
          id      8 bytes, NUL-padded hex ("000012c")
          flag    u32 (1 for files, 0 for the manifest)
          time_a  FILETIME
          time_b  FILETIME
          offset  u32, from the start of the file
          size    u32, bytes at offset
  data  at each offset: u32 unpacked size, u32 packed size, zlib stream

One entry is the manifest: a binary HxCfgFile with one HxPars list section, `McListData`,
read with `files.hxcfg` and `methods.stp_pars`. Its `ListItems` name every file the
package lists. Each item carries:
  -347734013  the entry id holding the file's bytes, empty when the package lists the
              file but does not carry it (stock Venus files, expected on the target)
  -347734014  the name, relative to its Hamilton folder
  -347734015  the full path it was packed from, and is installed to
  -347734009  the files it refers to (-347734000 each), e.g. a layout's labware
The other item keys are kept in `PackedFile.fields` unnamed (CONVENTIONS §11).

Reading only: nothing here writes a package or touches a Venus install.
"""
from __future__ import annotations

import dataclasses
import datetime
import ntpath
import pathlib
import struct
import zlib
from typing import Optional, Union

from venus_interop.files import hxcfg
from venus_interop.methods import stp_pars

MAGIC = b"HamPkg"
_ENTRY = struct.Struct("<8sIQQII")
_ENTRIES_AT = 0x2E

ID = "1-347734013"
NAME = "1-347734014"
PATH = "1-347734015"
REFS = "-347734009"
REF_PATH = "1-347734000"


class FormatError(ValueError):
  pass


def _filetime(v: int) -> Optional[datetime.datetime]:
  if not v:
    return None
  return datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(microseconds=v // 10)


@dataclasses.dataclass
class Entry:
  id: str
  flag: int
  time_a: Optional[datetime.datetime]
  time_b: Optional[datetime.datetime]
  offset: int
  size: int
  data: bytes  # unpacked


@dataclasses.dataclass
class PackedFile:
  key: str  # the item's key in ListItems
  id: str  # entry id; "" when listed but not carried
  name: str
  path: str  # Windows path it installs to
  refs: list[str]
  fields: list[tuple[str, object]]  # every key of the item, as parsed
  data: Optional[bytes]  # None when not carried

  @property
  def carried(self) -> bool:
    return self.data is not None


@dataclasses.dataclass
class Package:
  header_words: tuple[int, int, int, int]
  created: Optional[datetime.datetime]
  venus_version: str
  entries: list[Entry]
  manifest_id: str
  files: list[PackedFile]

  def file(self, name: str) -> PackedFile:
    """A listed file by its name or the tail of its path, ignoring case."""
    want = name.replace("/", "\\").lower()
    for f in self.files:
      if f.name.lower() == want or f.path.lower().endswith("\\" + want):
        return f
    raise KeyError(name)


def _is_manifest(data: bytes) -> bool:
  try:
    cfg = hxcfg.read(data)
  except (hxcfg.FormatError, struct.error, IndexError, UnicodeDecodeError, ValueError):
    return False
  return any(s.type == "HxPars" and s.name == "McListData" for s in cfg.sections)


def read(source: Union[str, pathlib.Path, bytes]) -> Package:
  data = source if isinstance(source, bytes) else pathlib.Path(source).read_bytes()
  if not data.startswith(MAGIC):
    raise FormatError("not a HamPkg file")
  words = struct.unpack_from("<4H", data, 6)
  (count,) = struct.unpack_from("<I", data, 0x0E)
  (created,) = struct.unpack_from("<Q", data, 0x12)
  version = data[0x1A:_ENTRIES_AT].split(b"\0")[0].decode("latin-1")
  entries = []
  for k in range(count):
    raw_id, flag, ta, tb, off, size = _ENTRY.unpack_from(data, _ENTRIES_AT + k * _ENTRY.size)
    if off + size > len(data) or size < 8:
      raise FormatError(f"entry {k} runs past the end of the file")
    unpacked, packed = struct.unpack_from("<II", data, off)
    if packed + 8 > size:
      raise FormatError(f"entry {k}: packed size {packed} exceeds its slot {size}")
    body = zlib.decompress(data[off + 8:off + 8 + packed]) if packed else b""
    if len(body) != unpacked:
      raise FormatError(f"entry {k}: {len(body)} bytes unpacked, header says {unpacked}")
    eid = raw_id.split(b"\0")[0].decode("ascii")
    entries.append(Entry(eid, flag, _filetime(ta), _filetime(tb), off, size, body))
  by_id = {e.id: e for e in entries}
  manifests = [e for e in entries if e.flag == 0 and _is_manifest(e.data)] or [e for e in entries if _is_manifest(e.data)]
  if len(manifests) != 1:
    raise FormatError(f"expected one McListData manifest, found {len(manifests)}")
  man = manifests[0]
  sec = hxcfg.read(man.data).section("HxPars", "McListData", is_list=True)
  tree = dict(stp_pars.parse(sec.items))
  files = []
  for key, item in tree.get("ListItems", []):
    d = dict(item)
    refs = [dict(r).get(REF_PATH, "") for _, r in d.get(REFS, []) or [] if isinstance(r, list)]
    eid = d.get(ID, "")
    if eid and eid not in by_id:
      raise FormatError(f"{d.get(NAME)!r} names entry {eid}, which the package lacks")
    files.append(PackedFile(key, eid, d.get(NAME, ""), d.get(PATH, ""), refs, item,
                            by_id[eid].data if eid else None))
  return Package(words, _filetime(created), version, entries, man.id, files)


def install_relpath(path: str) -> pathlib.PurePosixPath:
  """Where a packed file goes under an extraction folder: its path below the Hamilton
  folder ("Library/…", "Labware/…"), else "_external/<file name>". Never absolute and
  never above the folder, whatever the package says."""
  parts = ntpath.normpath(path).split("\\")
  low = [p.lower() for p in parts]
  if "hamilton" in low:
    rest = parts[low.index("hamilton") + 1:]  # the first: "Labware\Hamilton\…" exists too
  else:
    rest = ["_external", parts[-1]]
  rest = [p for p in rest if p not in ("", ".", "..") and ":" not in p]
  if not rest:
    raise FormatError(f"no file name in {path!r}")
  return pathlib.PurePosixPath(*rest)


def extract(pkg: Package, out_dir: Union[str, pathlib.Path]) -> list[pathlib.Path]:
  """Write every carried file under `out_dir` by `install_relpath`. Returns the paths."""
  out = pathlib.Path(out_dir).resolve()
  written = []
  for f in pkg.files:
    if not f.carried:
      continue
    rel = install_relpath(f.path)
    if rel.parts[0] == "_external":
      rel = pathlib.PurePosixPath("_external", f"{f.id}_{rel.name}")
    dst = (out / rel).resolve()
    if out not in dst.parents:
      raise FormatError(f"{f.path!r} would land outside {out}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(f.data)
    written.append(dst)
  return written


def main(argv: Optional[list[str]] = None) -> int:
  import argparse

  ap = argparse.ArgumentParser(prog="python -m venus_interop.files.pkg", description=__doc__.splitlines()[0])
  sub = ap.add_subparsers(dest="cmd", required=True)
  p_list = sub.add_parser("list", help="the files a package lists")
  p_list.add_argument("pkg")
  p_list.add_argument("--all", action="store_true", help="also the files it lists but does not carry")
  p_x = sub.add_parser("extract", help="write the carried files under a folder")
  p_x.add_argument("pkg")
  p_x.add_argument("out")
  a = ap.parse_args(argv)
  pkg = read(a.pkg)
  if a.cmd == "list":
    carried = [f for f in pkg.files if f.carried]
    print(f"Venus {pkg.venus_version}, made {pkg.created:%Y-%m-%d %H:%M} UTC: "
          f"{len(carried)} files carried, {len(pkg.files) - len(carried)} listed only")
    for f in sorted(pkg.files, key=lambda f: install_relpath(f.path).as_posix().lower()):
      if f.carried or a.all:
        size = f"{len(f.data):>10}" if f.carried else "         -"
        print(f"{f.id or '-':>8} {size}  {install_relpath(f.path)}")
  else:
    for p in extract(pkg, a.out):
      print(p)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
