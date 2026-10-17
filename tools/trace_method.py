"""Decompile Venus methods into readable traces; count their library calls and how far ports cover them.

  python tools/trace_method.py --roots LIB_DIR [LIB_DIR ...] --out DIR METHOD.hsl [METHOD.hsl ...]
  python tools/trace_method.py --roots ... --calls METHOD.hsl [...]    library calls per method
  python tools/trace_method.py --roots ... --status METHOD.hsl [...]   what the ports cover, per method

`--roots` are the folders `#include`s resolve under (a Venus install's or a repository's `Library`
and `Methods`). Each method is read with exactly the libraries it includes and the .stp records
beside them. `--out` gets `<method>.trace.md` (everything) and `<method>.condensed.md` (for reading:
data plumbing dropped, settings collapsed).

`--calls` prints, for every library function, how many times each method calls it: the place to
start before porting a library.

`--status` walks each method's call tree and gives every library call a status: `checked` (a port
test runs it against the HSL: the test's LIBRARY and COVERS, or COVERS_ALSO {namespace: [...]}), `ported` (a module in
venus_interop/plr/libraries declares the namespace as LIBRARY and defines the entry point), `out`
or `method` (tools/function_notes.json: not protocol logic, or ported with the method that owns
it), else `open`. A call inside one already given a status is part of it and is not counted. It
prints the counts per method, then the open functions by how often they are called.
"""
import argparse
import ast
import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from venus_interop.methods import protocol  # noqa: E402

STATUSES = ("checked", "ported", "out", "method", "open")


def trace(hsl_path: pathlib.Path, roots):
  """The method's files, its sections' lines, and the full and condensed traces."""
  mf = protocol.load_method(hsl_path, roots)
  secs = protocol.method_lines(mf.hsl_text, mf.libraries, mf.stps, mf.sub_text)
  full, con = ["```", ""], ["```", ""]
  for name, lines in secs:
    full += [f"## section {name}", ""] + protocol.render(lines) + [""]
    con += [f"## section {name}", ""] + protocol.render(lines, condensed=True) + [""]
  return mf, secs, full + ["```"], con + ["```"]


def _literal(tree: ast.Module, name: str):
  for node in tree.body:
    if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
      return ast.literal_eval(node.value)
  return None


def ports() -> dict[str, set[str]]:
  """Namespace -> entry points (lower case) the port modules define: their classes' public
  methods and the keys of entry tables (ENTRY, WITH_TAP_ARG)."""
  out: dict[str, set[str]] = collections.defaultdict(set)
  for path in sorted((ROOT / "venus_interop" / "plr" / "libraries").glob("*.py")):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    ns = _literal(tree, "LIBRARY")
    if not ns:
      continue
    for node in tree.body:
      if isinstance(node, ast.ClassDef):
        out[ns] |= {f.name.lower() for f in node.body
                    if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and not f.name.startswith("_")}
      elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict) and \
          any(getattr(t, "id", None) in ("ENTRY", "WITH_TAP_ARG") for t in node.targets):
        out[ns] |= {k.value.lower() for k in node.value.keys if isinstance(k, ast.Constant)}
  return out


def checked() -> dict[str, set[str]]:
  """Namespace -> the functions port tests run against the HSL (their LIBRARY and COVERS)."""
  out: dict[str, set[str]] = collections.defaultdict(set)
  for path in sorted((ROOT / "tests").glob("test_*_port.py")):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    ns, covers = _literal(tree, "LIBRARY"), _literal(tree, "COVERS")
    if ns and covers:
      out[ns] |= {c.lower() for c in covers}
    for ns, covers in (_literal(tree, "COVERS_ALSO") or {}).items():  # a test of more than one library
      out[ns] |= {c.lower() for c in covers}
  return out


def status_of(ns: str, name: str, notes: dict, done: dict, made: dict) -> str:
  if name.lower() in done.get(ns, ()):
    return "checked"
  if name.lower() in made.get(ns, ()):
    return "ported"
  note = notes.get(f"{ns}::{name}") or notes.get(f"{ns}::*") or {}
  return note.get("scope", "open")


def calls_of(secs):
  """(namespace, name, depth) of every call line, the method's own sections with namespace ""."""
  for _, lines in secs:
    for ln in lines:
      if ln.kind == "call" and isinstance(ln.data, tuple):
        yield ln.data[0], ln.data[1], ln.depth


def statuses(secs, notes, done, made):
  """(namespace, name, status) of each library call not inside one already given a status.
  The method's own sections are walked through, not counted."""
  stack: list[tuple[int, bool]] = []  # (depth, covers what is below)
  for ns, name, depth in calls_of(secs):
    while stack and stack[-1][0] >= depth:
      stack.pop()
    inside = any(c for _, c in stack)
    if not ns and name.lower() not in {k.split("::", 1)[1].lower() for k in notes if k.startswith("::")}:
      stack.append((depth, inside))  # the method's own section: walk through it
      continue
    st = status_of(ns, name, notes, done, made)
    stack.append((depth, inside or st != "open"))
    if not inside:
      yield ns, name, st


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("methods", nargs="+", type=pathlib.Path)
  ap.add_argument("--roots", nargs="+", type=pathlib.Path, required=True)
  ap.add_argument("--out", type=pathlib.Path)
  ap.add_argument("--calls", action="store_true")
  ap.add_argument("--status", action="store_true")
  a = ap.parse_args()
  sys.stdout.reconfigure(encoding="utf-8")
  notes = {k: v for k, v in json.loads((ROOT / "tools" / "function_notes.json").read_text(encoding="utf-8")).items()
           if not k.startswith("_")}
  done, made = checked(), ports()
  calls = collections.defaultdict(collections.Counter)
  per_method, open_calls = {}, collections.defaultdict(collections.Counter)
  for path in a.methods:
    mf, secs, full, con = trace(path, a.roots)
    if a.out:
      a.out.mkdir(parents=True, exist_ok=True)
      (a.out / (path.stem + ".trace.md")).write_text("\n".join(full), encoding="utf-8")
      (a.out / (path.stem + ".condensed.md")).write_text("\n".join(con), encoding="utf-8")
      print(f"{path.stem}: {len(mf.files)} files, {len(mf.stps)} step records, full {len(full)} lines, "
            f"condensed {len(con)}" + (f"; unresolved includes: {', '.join(mf.missing)}" if mf.missing else ""))
    for ns, name, _ in calls_of(secs):
      if ns:
        calls[f"{ns}::{name}"][path.stem] += 1
    counts = collections.Counter()
    for ns, name, st in statuses(secs, notes, done, made):
      counts[st] += 1
      if st == "open":
        open_calls[f"{ns}::{name}"][path.stem] += 1
    per_method[path.stem] = counts
  if a.calls:
    for fn, per in sorted(calls.items(), key=lambda kv: -sum(kv[1].values())):
      print(f"{sum(per.values()):5}  {fn:55} " + ", ".join(f"{m} {n}" for m, n in per.most_common()))
  if a.status:
    print("library calls by status (a call inside one with a status counts as part of it)")
    print(f"{'':50}" + "".join(f"{s:>9}" for s in STATUSES))
    for method, counts in per_method.items():
      print(f"{method[:50]:50}" + "".join(f"{counts[s]:9}" for s in STATUSES))
    total = sum(per_method.values(), collections.Counter())
    print(f"{'all':50}" + "".join(f"{total[s]:9}" for s in STATUSES))
    print("\nopen, by calls:")
    for fn, per in sorted(open_calls.items(), key=lambda kv: -sum(kv[1].values())):
      note = (notes.get(fn) or {}).get("note", "")
      print(f"{sum(per.values()):5}  {fn:55} " + ", ".join(f"{m[:24]} {n}" for m, n in per.most_common())
            + (f"  [{note}]" if note else ""))


if __name__ == "__main__":
  main()
