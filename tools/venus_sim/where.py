"""What PLR has at a deck X/Y on Marionette's imported deck, with each resource's Z chain (every
ancestor's location); or one resource by name. Needs the venus-plr PLR worktree on PYTHONPATH.

  python where.py X Y [NAME]"""
import sys

from paths import CORPUS, REPO

sys.path[:0] = [str(REPO), str(REPO / "examples")]
import marionette_demo as demo  # noqa: E402

from venus_interop.plr.venus_deck import VenusDeck  # noqa: E402

v = VenusDeck(CORPUS, demo.LAYOUT)
demo.install(v)
x, y = float(sys.argv[1]), float(sys.argv[2])
for r in v.deck.get_all_resources():
  try:
    c = r.get_location_wrt(v.deck, x="c", y="c", z="b")
  except Exception:  # noqa: BLE001
    continue
  if abs(c.x - x) < 0.6 and abs(c.y - y) < 0.6:
    chain, p = [], r
    while p is not None and p is not v.deck:
      chain.append(f"{p.name}[{type(p).__name__}] loc={p.location} size_z={p.get_size_z()}")
      p = p.parent
    print(f"{r.name}: bottom z={c.z:.2f}")
    for line in chain:
      print("   ", line)
if len(sys.argv) > 3:
  r = v.deck.get_resource(sys.argv[3])
  print(type(r).__name__, "model", getattr(r, "model", None), "size_z", r.get_size_z())
