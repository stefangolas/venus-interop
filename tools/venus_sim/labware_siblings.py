"""Containers and lids that added labware names without a folder (Venus looks beside the file) but
that live elsewhere: copied beside it from the Venus install or the corpus (new files only; added
to the manifest). Run after labware_closure.py --copy.

  python labware_siblings.py"""
import re

from paths import CORPUS, LABWARE, LABWARE_MANIFEST

BARE = re.compile(rb"(?<![\\/\w])([\w .()\[\]&+-]+\.(?:ctr|lid))", re.I)


def main() -> None:
  index = {}
  for line in (CORPUS / "defs_index.tsv").read_text(encoding="utf-8").splitlines():
    h, rel = line.split("\t")[:2]
    index.setdefault(rel.rsplit("/", 1)[-1].lower(), CORPUS / "defs_raw" / h)
  installed = {}
  for f in LABWARE.rglob("*"):
    if f.suffix.lower() in (".ctr", ".lid"):
      installed.setdefault(f.name.lower(), f)
  import pathlib
  added = [pathlib.Path(line) for line in LABWARE_MANIFEST.read_text(encoding="utf-8").splitlines() if line.strip()] \
    if LABWARE_MANIFEST.exists() else []
  new = []
  for f in added:
    if f.suffix.lower() not in (".rck", ".tml", ".lid") or not f.exists():
      continue
    for m in set(BARE.findall(f.read_bytes())):
      name = m.decode("latin-1").strip()
      target = f.parent / name
      if target.exists():
        continue
      src = installed.get(name.lower()) or index.get(name.lower())
      if src is None:
        print("NOT FOUND:", name, "for", f)
        continue
      target.write_bytes(src.read_bytes())
      new.append(str(target))
      print("added", target, "from", src)
  with LABWARE_MANIFEST.open("a", encoding="utf-8") as m:
    for t in new:
      m.write(t + "\n")
  print(len(new), "added")


if __name__ == "__main__":
  main()
