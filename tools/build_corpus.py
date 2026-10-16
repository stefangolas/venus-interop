"""Build a corpus folder from local sources (see venus_interop/corpora.py).

  python tools/build_corpus.py OUT [--source ngs_protocols] [--source venus] [--layouts DIR ...] [--labware DIR ...]
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from venus_interop import corpora  # noqa: E402


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("out")
  ap.add_argument("--source", action="append", default=[])
  ap.add_argument("--layouts", nargs="*", default=[])
  ap.add_argument("--labware", nargs="*", default=[])
  a = ap.parse_args()
  by_name = {s.name: s for s in corpora.SOURCES}
  for name in a.source:
    s = by_name[name]
    if s.local is None or not s.local.exists():
      sys.exit(f"{name}: not on this machine ({s.url or 'no URL'})")
    print(name, corpora.build(pathlib.Path(a.out), s.layouts(), s.labware_dirs(), source=name))
  if a.layouts or a.labware:
    lays = [p for d in a.layouts for p in sorted(pathlib.Path(d).rglob("*.lay"))]
    print("extra", corpora.build(pathlib.Path(a.out), lays, [pathlib.Path(d) for d in a.labware], source="extra"))


if __name__ == "__main__":
  main()
