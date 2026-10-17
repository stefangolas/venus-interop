"""Decompile Venus methods into readable traces, and count the library calls they make.

  python tools/trace_method.py --roots LIB_DIR [LIB_DIR ...] --out DIR METHOD.hsl [METHOD.hsl ...]
  python tools/trace_method.py --roots ... --calls METHOD.hsl [...]   library calls per method

`--roots` are the folders `#include`s resolve under (a Venus install's or a repository's `Library`
and `Methods`). Each method is read with exactly the libraries it includes and the .stp records
beside them. `--out` gets `<method>.trace.md` (everything) and `<method>.condensed.md` (for reading:
data plumbing dropped, settings collapsed). `--calls` prints, for every library function a method
calls, how many times each method calls it: the place to start before porting a library.
"""
import argparse
import collections
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from venus_interop.methods import protocol  # noqa: E402

_CALL = re.compile(r"^\s*> \[\w+\] ([A-Za-z_]\w*)\(")


def trace(hsl_path: pathlib.Path, roots):
  mf = protocol.load_method(hsl_path, roots)
  secs = protocol.method_lines(mf.hsl_text, mf.libraries, mf.stps, mf.sub_text)
  full, con = ["```", ""], ["```", ""]
  for name, lines in secs:
    full += [f"## section {name}", ""] + protocol.render(lines) + [""]
    con += [f"## section {name}", ""] + protocol.render(lines, condensed=True) + [""]
  return mf, full + ["```"], con + ["```"]


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("methods", nargs="+", type=pathlib.Path)
  ap.add_argument("--roots", nargs="+", type=pathlib.Path, required=True)
  ap.add_argument("--out", type=pathlib.Path)
  ap.add_argument("--calls", action="store_true")
  a = ap.parse_args()
  sys.stdout.reconfigure(encoding="utf-8")
  calls = collections.defaultdict(collections.Counter)
  for path in a.methods:
    mf, full, con = trace(path, a.roots)
    if a.out:
      a.out.mkdir(parents=True, exist_ok=True)
      (a.out / (path.stem + ".trace.md")).write_text("\n".join(full), encoding="utf-8")
      (a.out / (path.stem + ".condensed.md")).write_text("\n".join(con), encoding="utf-8")
      print(f"{path.stem}: {len(mf.files)} files, {len(mf.stps)} step records, full {len(full)} lines, "
            f"condensed {len(con)}" + (f"; unresolved includes: {', '.join(mf.missing)}" if mf.missing else ""))
    for line in con:
      m = _CALL.match(line)
      if m:
        calls[m.group(1)][path.stem] += 1
  if a.calls:
    for fn, per in sorted(calls.items(), key=lambda kv: -sum(kv[1].values())):
      print(f"{sum(per.values()):5}  {fn:40} " + ", ".join(f"{m} {n}" for m, n in per.most_common()))


if __name__ == "__main__":
  main()
