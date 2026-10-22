"""Sweep a corpus layout with some of its labware taken out: to find what makes a layout fail in
Venus (a crash on loading, a configuration mismatch), and to measure the rest of it anyway. Labware
whose file path contains a pattern goes (or whose id is a pattern written id:<Id>), with everything
placed on it and the sequences naming it. The trimmed layout is <work>/sweep/trim/<hash>_<tag>.lay; its trace is out/<hash>_<tag>.out, which
compare_sweep.py does not read (it pairs with corpus layouts by hash).

  python trim_sweep.py HASH TAG PATTERN [PATTERN ...]     (patterns: case-insensitive substrings)"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import sweep  # noqa: E402
from sweep import OUT, RAW  # noqa: E402

from venus_interop.files import layout  # noqa: E402


def trim(h: str, patterns: list) -> tuple:
  lay = layout.read_layout(RAW / f"{h}.lay")
  ids = {s[3:] for s in patterns if s.startswith("id:")}
  files = [s.lower() for s in patterns if not s.startswith("id:")]
  gone = {p.id for p in lay.labware if p.id in ids or any(s in p.file.lower() for s in files)}
  grew = True
  while grew:  # and what stands on what goes
    more = {p.id for p in lay.labware if p.template in gone} - gone
    gone |= more
    grew = bool(more)
  lay.labware = [p for p in lay.labware if p.id not in gone]
  lay.sequences = [s for s in lay.sequences if not any(i in gone for i, _ in s.items)]
  if lay.layers is not None:
    for x in lay.layers:
      x.labware = [i for i in x.labware if i not in gone]
  return lay, sorted(gone)


if __name__ == "__main__":
  h, tag, patterns = sys.argv[1], sys.argv[2], sys.argv[3:]
  lay, gone = trim(h, patterns)
  folder = OUT / "trim"
  folder.mkdir(parents=True, exist_ok=True)
  path = folder / f"{h}_{tag}.lay"
  path.write_bytes(layout.write_layout(lay))
  print(f"{len(gone)} labware taken out: {', '.join(gone)}")
  print(sweep.run(f"{h}_{tag}", src=path), flush=True)
