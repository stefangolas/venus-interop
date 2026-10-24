"""Build a corpus folder from local sources (see venus_interop/corpora.py).

  python tools/build_corpus.py OUT [--source ngs_protocols] [--source venus] [--layouts DIR ...] [--labware DIR ...]

From a checkout of a method repository (NIST's lmsf_hamilton, or your own Venus folder):

  python tools/build_corpus.py .local/corpus --name lmsf_hamilton \
      --layouts lmsf_hamilton/Methods --labware lmsf_hamilton/LabWare

Layouts are named by their content's hash (`raw/<sha1[:12]>.lay`, listed in `index.tsv` with the
path they came from), so a corpus built anywhere names a layout as the demos and tests do.
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from venus_interop import corpora  # noqa: E402


def main():
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("out")
  ap.add_argument("--source", action="append", default=[], help="a named source in venus_interop/corpora.py")
  ap.add_argument("--layouts", nargs="*", default=[], help="folders searched for .lay files")
  ap.add_argument("--labware", nargs="*", default=[], help="Labware roots (their subpaths name the definitions)")
  ap.add_argument("--name", default="extra", help="the source name recorded for --layouts/--labware")
  a = ap.parse_args()
  out = pathlib.Path(a.out)
  by_name = {s.name: s for s in corpora.SOURCES}
  for name in a.source:
    s = by_name[name]
    if s.local is None or not s.local.exists():
      sys.exit(f"{name}: not on this machine ({s.url or 'no URL'}); pass its folders with --layouts/--labware")
    print(name, corpora.build(out, s.layouts(), s.labware_dirs(), source=name, root=s.local))
  labware = [pathlib.Path(d) for d in a.labware]
  for d in a.layouts:
    folder = pathlib.Path(d).resolve()
    print(a.name, corpora.build(out, sorted(folder.rglob("*.lay")), labware, source=a.name, root=folder.parent))
    labware = []  # copied once
  if labware:
    print(a.name, corpora.build(out, [], labware, source=a.name))


if __name__ == "__main__":
  main()
