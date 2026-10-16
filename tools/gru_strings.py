"""Print the error and recovery titles that .stp error blocks refer to.

  python tools/gru_strings.py <folder with .stp files> [HxGruCommandEnu.dll]

A step's `(Errors` block names its errors and recoveries by string-table id
(`ErrorTitle 382`, `RecoveryTitle 420`). The strings are in the RT_STRING
resources of Venus's `Bin\\HxGruCommandEnu.dll`. This reads that table and prints
the titles for every id the given .stp files use, as the literals in
`venus_interop/methods/stp_pars.py` (ERROR_TITLES, RECOVERY_TITLES).
"""
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from venus_interop.files import hxcfg  # noqa: E402
from venus_interop.methods import stp_pars  # noqa: E402

DLL = pathlib.Path(r"C:\Program Files (x86)\HAMILTON\Bin\HxGruCommandEnu.dll")
RT_STRING = 6


def string_table(data: bytes) -> dict[int, str]:
  """RT_STRING entries of a PE file: string id -> text."""
  pe = struct.unpack_from("<I", data, 0x3C)[0]
  if data[:2] != b"MZ" or data[pe : pe + 4] != b"PE\0\0":
    raise ValueError("not a PE file")
  nsec, optsz = struct.unpack_from("<H", data, pe + 6)[0], struct.unpack_from("<H", data, pe + 20)[0]
  opt = pe + 24
  dirs = opt + (96 if struct.unpack_from("<H", data, opt)[0] == 0x10B else 112)
  rva = struct.unpack_from("<I", data, dirs + 8 * 2)[0]  # data directory 2: resources
  secs = [struct.unpack_from("<IIII", data, opt + optsz + 40 * i + 8) for i in range(nsec)]

  def offset(r: int) -> int:
    for vsize, va, rsize, raw in secs:
      if va <= r < va + max(vsize, rsize):
        return r - va + raw
    raise ValueError(f"rva {r:#x} outside every section")

  base = offset(rva)

  def entries(o: int):
    named, ids = struct.unpack_from("<HH", data, o + 12)
    for i in range(named + ids):
      yield struct.unpack_from("<II", data, o + 16 + 8 * i)

  out: dict[int, str] = {}
  for typ, p1 in entries(base):
    if typ != RT_STRING:
      continue
    for block, p2 in entries(base + (p1 & 0x7FFFFFFF)):
      for _lang, p3 in entries(base + (p2 & 0x7FFFFFFF)):
        o = offset(struct.unpack_from("<I", data, base + p3)[0])
        for k in range(16):  # a block holds ids (block-1)*16 .. +15
          n = struct.unpack_from("<H", data, o)[0]
          if n:
            out[(block - 1) * 16 + k] = data[o + 2 : o + 2 + 2 * n].decode("utf-16-le")
          o += 2 + 2 * n
  return out


def main():
  if len(sys.argv) < 2:
    sys.exit(__doc__)
  table = string_table(pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else DLL).read_bytes())
  used = {"ErrorTitle": set(), "RecoveryTitle": set()}
  for p in pathlib.Path(sys.argv[1]).rglob("*.stp"):
    try:
      cfg = hxcfg.read(p.read_bytes())
    except Exception:
      continue
    for s in cfg.sections:
      if s.type == "HxPars":
        for _path, name, val in stp_pars.record(s).readable():
          if name in used:
            used[name].add(int(val))
  for name, var in (("ErrorTitle", "ERROR_TITLES"), ("RecoveryTitle", "RECOVERY_TITLES")):
    print(f"{var} = {{")
    for i in sorted(used[name]):
      print(f"  {i}: {table.get(i, '?')!r},")
    print("}")


if __name__ == "__main__":
  main()
