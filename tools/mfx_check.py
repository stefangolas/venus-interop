"""Check multiflex carriers (.tml) Venus assembled against the catalogue rule.

  python tools/mfx_check.py FOLDER_OR_TML [...]

Lists every multiflex carrier found, its baseplate, and each site that the rule does not reproduce
exactly. Sites whose id names no catalogue module are fitted to the closest module ("fitted: ...").
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from venus_interop.files.definitions import Carrier, load  # noqa: E402
from venus_interop.multiflex import assembly  # noqa: E402


def main(args):
  paths = []
  for a in map(pathlib.Path, args):
    paths += sorted(a.rglob("*.tml")) if a.is_dir() else [a]
  seen, total = set(), [0, 0]
  for p in paths:
    try:
      d = load(p)
    except Exception:  # noqa: BLE001
      continue
    if not isinstance(d, Carrier) or not assembly.is_multiflex(d):
      continue
    key = (p.name.lower(), tuple(sorted((s.id, s.x, s.y, s.z) for s in d.sites.values())))
    if key in seen:
      continue
    seen.add(key)
    b, checks = assembly.check(d)
    real = [c for c in checks if c.module != "no baseplate position here"]
    exact = sum(c.exact for c in real)
    total[0] += exact
    total[1] += len(real)
    print(f"{p.name}  ({p.parent})\n  baseplate: {b.name if b else 'not a catalogue baseplate'}; exact {exact}/{len(real)}")
    for c in real:
      if not c.exact:
        print(f"    {c.site_id:18} Venus {c.venus}  rule {c.rule}  error {c.error}  ({c.module})")
  print(f"\n{len(seen)} distinct carriers; {total[0]}/{total[1]} sites exact")


if __name__ == "__main__":
  main(sys.argv[1:])
