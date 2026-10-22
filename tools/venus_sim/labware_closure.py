"""The labware files a layout needs that Venus's Labware folder lacks, with every file they refer to
(containers, lids, carriers' sites), from the corpus store (hash names, defs_index.tsv). Prints the
plan; with --copy, copies them in (new files only: an existing path is never overwritten) and adds
them to the manifest (paths.LABWARE_MANIFEST), for removal later.

  python labware_closure.py LAYOUT.lay [--copy]"""
import pathlib
import re
import shutil
import sys

from paths import CORPUS, LABWARE, LABWARE_MANIFEST, REPO

sys.path.insert(0, str(REPO))
from venus_interop.files import layout  # noqa: E402

NAME = re.compile(r"[\w .()\[\]&+-]+\.(?:rck|ctr|lid|tml|hxx|x|tpl|dck)", re.I)

index = {}  # lowercased relative path -> hash file
for line in (CORPUS / "defs_index.tsv").read_text(encoding="utf-8").splitlines():
  h, rel, _ = (line.split("\t") + ["", ""])[:3]
  index[rel.lower().replace("/", "\\")] = h
by_name = {}
for rel in index:
  by_name.setdefault(rel.rsplit("\\", 1)[-1], []).append(rel)


def closure(start: list[str]) -> list[str]:
  todo, seen, unresolved = list(start), set(), set()
  while todo:
    rel = todo.pop().lower().replace("/", "\\")
    if rel in seen or (LABWARE / rel).exists():
      continue
    if rel not in index:
      unresolved.add(rel)
      continue
    seen.add(rel)
    text_file = CORPUS / "defs_text" / index[rel]
    text = text_file.read_text(encoding="latin-1", errors="replace") if text_file.exists() else ""
    for m in NAME.findall(text):
      m = m.strip().lower().replace("/", "\\")
      if "\\" in m:
        todo.append(m)
      else:
        todo.extend(r for r in by_name.get(m, []) if r.rsplit("\\", 1)[0] == rel.rsplit("\\", 1)[0] or len(by_name[m]) == 1)
  if unresolved:
    print("not in the corpus:", sorted(unresolved))
  return sorted(seen)


def copy(need: list[str]) -> None:
  LABWARE_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
  with LABWARE_MANIFEST.open("a", encoding="utf-8") as m:
    for rel in need:
      dest = LABWARE / rel
      if dest.exists():
        continue
      dest.parent.mkdir(parents=True, exist_ok=True)
      shutil.copy2(CORPUS / "defs_raw" / index[rel], dest)
      m.write(str(dest) + "\n")


if __name__ == "__main__":
  lay = layout.read_layout(pathlib.Path(sys.argv[1]))
  # the placements' files and their covers' (the _COVER section): Venus crashes, with no error, on
  # a cover whose .lid is missing (the sweep, 2026-10-22: Nunc binding ontop ... supporting plate.lid)
  files = [p.fields.get("File") for p in lay.labware] + [p.lid.fields.get("File") for p in lay.labware if p.lid]
  need = closure(sorted({str(f) for f in files if f}))
  print(len(need), "files to add, none already present:")
  for rel in need:
    print("  ", rel)
  if "--copy" in sys.argv:
    copy(need)
    print("copied; manifest:", LABWARE_MANIFEST)
