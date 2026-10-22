"""Which corpus layouts the position sweep still learns from: the fewest layouts that cover every
(rack file, ZTransValue, angle, carrier file) not yet measured in <work>/sweep/out. The corpus repeats
itself (copies of the same NIST decks), so sweeping it in order mostly re-measures known labware
(docs/FIRMWARE_EQUIVALENCE.md section 5).

  python select_sweep.py [HASH ...]      (candidates; all STAR-family corpus layouts when none given)

Prints the chosen hashes, in the order of how much each adds, ready for sweep.py."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from paths import CORPUS, REPO, WORK  # noqa: E402

sys.path.insert(0, str(REPO))
from venus_interop.files import layout  # noqa: E402
from venus_interop.plr.plr_import import DECKS  # noqa: E402

RAW = CORPUS / "raw"
OUT = WORK / "sweep" / "out"


def name(f: str) -> str:
  return f.replace("/", "\\").rsplit("\\", 1)[-1].lower()


def combos(h: str) -> set:
  """What a layout's racks are measured as: file, ZTransValue, angle, the carrier (or deck) under it."""
  lay = layout.read_layout(RAW / f"{h}.lay")
  by_id = lay.by_id()
  return {(name(p.file), p.fields.get("ZTransValue"), p.angle,
           name(by_id[p.template].file) if p.template in by_id else "deck")
          for p in lay.labware if p.kind == "rack"}


def star_layouts() -> list:
  out = []
  for f in sorted(RAW.glob("*.lay")):
    try:
      if layout.read_layout(f).header.get("Deck", "").lower() in DECKS:
        out.append(f.stem)
    except Exception:  # noqa: BLE001
      pass
  return out


def select(candidates: list) -> list:
  done = {p.stem for p in OUT.glob("*.out") if p.stat().st_size > 0}
  seen = set()
  for h in done:
    try:
      seen |= combos(h)
    except Exception:  # noqa: BLE001
      pass
  new = {}
  for h in candidates:
    if h in done:
      continue
    try:
      k = combos(h) - seen
    except Exception:  # noqa: BLE001
      continue
    if k:
      new[h] = k
  chosen, left = [], set().union(*new.values()) if new else set()
  while left:  # greedy set cover
    h = max(new, key=lambda h: len(new[h] & left))
    print(f"{h}: {len(new[h] & left)} new", file=sys.stderr)
    chosen.append(h)
    left -= new[h]
  return chosen


if __name__ == "__main__":
  print(" ".join(select(sys.argv[1:] or star_layouts())))
