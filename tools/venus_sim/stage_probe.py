"""Stage a probe method in <work>/oem: the files its #includes reach that live in pyhamilton's
library or star-oem folder are copied beside it (with their .stp/.res/.smt companions), so Venus
finds them from the method's folder; nothing is written into the Venus install. Files Venus's own
Library has are left there.

  python stage_probe.py PROBE.hsl [...]     (copies each probe into <work>/oem first)"""
import pathlib
import re
import shutil
import sys

from paths import LIBRARY, PYHAMILTON, STAR_OEM, WORK

OEM = WORK / "oem"
SOURCES = [STAR_OEM, PYHAMILTON / "library"]
INCLUDE = re.compile(r'#include\s+"([^"]+)"')


def find(name: str, here: pathlib.Path):
  rel = name.replace("\\\\", "\\").replace("\\", "/")
  for root in (here, OEM, LIBRARY, *SOURCES):
    p = root / rel
    if p.exists():
      return root, p
  return None, None


def stage(start: pathlib.Path) -> None:
  todo, seen, missing = [start], set(), set()
  while todo:
    f = todo.pop()
    if f in seen:
      continue
    seen.add(f)
    text = f.read_text(encoding="latin-1", errors="replace")
    text = re.sub(r"__filename__\s*\"([^\"]+)\"", lambda m: '"' + f.stem + m.group(1) + '"', text)
    for name in INCLUDE.findall(text):
      root, p = find(name, f.parent)
      if p is None:
        missing.add(name)
        continue
      if root in SOURCES:
        dest = OEM / p.relative_to(root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        for comp in [p, *(p.with_suffix(s) for s in (".stp", ".res", ".smt", ".hsi", ".hs_"))]:
          if comp.exists() and not (dest.parent / comp.name).exists():
            shutil.copy2(comp, dest.parent / comp.name)
        p = dest
      todo.append(p)
      if p.suffix == ".hs_" and p.with_suffix(".hsi").exists():
        todo.append(p.with_suffix(".hsi"))
  print(f"{len(seen)} files followed; missing: {sorted(missing) or 'none'}")


if __name__ == "__main__":
  OEM.mkdir(parents=True, exist_ok=True)
  for a in sys.argv[1:]:
    src = pathlib.Path(a)
    dest = OEM / src.name
    if src.resolve() != dest.resolve():
      shutil.copy2(src, dest)
    stage(dest)
