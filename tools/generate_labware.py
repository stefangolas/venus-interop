"""Generate PyLabRobot resources from Venus labware definitions.

  python tools/generate_labware.py OUT_DIR [--corpus DIR] [--layouts] [--no-models] [DEFINITION ...]

Definitions are relative Labware paths (e.g. "Corning-Costar\\Cos_96_Fl.rck"). With --layouts,
every definition used by the corpus layouts is generated. Writes:

  OUT_DIR/venus_generated.py              one factory per definition (an alias where PLR has it)
  OUT_DIR/resource_model/<name>.glb       a model per generated factory, with <name>.geometry.json
  OUT_DIR/report.json                     per definition: alias / generated, notes, checks

The generated module is then imported and every factory built, as a check.
"""
import argparse
import collections
import csv
import importlib.util
import json
import logging
import pathlib
import sys
import traceback

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from venus_interop.plr import generate, name_match  # noqa: E402
from venus_interop.files import layout
from venus_interop.rules import placement as rules
from venus_interop.files.definitions import (  # noqa: E402
  DEFAULT_VENUS_LABWARE, Carrier, DefinitionStore, Lid, Rack, normalize,
)


def corpus_store(corpus):
  index = {}
  if corpus:
    with open(pathlib.Path(corpus) / "defs_index.tsv", encoding="utf-8") as f:
      for name, rel, src in csv.reader(f, delimiter="\t"):
        if (pathlib.Path(corpus) / "defs_raw" / name).exists():
          index[rel] = pathlib.Path(corpus) / "defs_raw" / name
  roots = [DEFAULT_VENUS_LABWARE] if DEFAULT_VENUS_LABWARE.is_dir() else []
  return DefinitionStore(roots, index)


def layout_definitions(corpus, store):
  used = collections.Counter()
  for f in sorted((pathlib.Path(corpus) / "raw").glob("*.lay")):
    lay = layout.read_layout(f)
    if lay.header.get("Deck", "").lower() not in rules.STAR_DECKS:
      continue
    for p in lay.labware:
      used[normalize(p.file)] += 1
      if p.lid is not None:
        used[normalize(p.lid.file)] += 1
  return [rel for rel, _ in used.most_common()]


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("out")
  ap.add_argument("definitions", nargs="*")
  ap.add_argument("--corpus")
  ap.add_argument("--layouts", action="store_true")
  ap.add_argument("--no-models", action="store_true")
  a = ap.parse_intermixed_args()
  logging.disable(logging.WARNING)

  out = pathlib.Path(a.out)
  out.mkdir(parents=True, exist_ok=True)
  store = corpus_store(a.corpus)
  rels = [normalize(r) for r in a.definitions] + (layout_definitions(a.corpus, store) if a.layouts else [])
  catalogue = name_match.plr_catalogue()

  source, report, names = [generate.HEADER], {}, set()
  for rel in dict.fromkeys(rels):
    d = store.get(rel)
    entry = report.setdefault(rel, {})
    if not isinstance(d, (Rack, Carrier, Lid)):
      entry["status"] = "missing" if d is None else f"skipped ({d.type})"
      continue
    name = generate.factory_name(rel) + ("_lid" if isinstance(d, Lid) else "")
    if name in names:
      name = generate.factory_name(rel.replace("/", "_"))
    names.add(name)
    entry["factory"] = name
    fp = name_match.venus_fingerprint(d, store) if not isinstance(d, Lid) else None
    matches = [m for m in name_match.best_matches(rel, fp, catalogue, 10) if m.verdict == "match"] if fp else []
    plr = {m.candidate.factory for m in matches if "Deprecated alias" not in m.candidate.doc}
    target = name_match.alias_target(rel, fp, matches, plr)
    if target:
      entry.update(status="alias", plr=target[0], why=target[1])
      source.append(generate.emit_alias(name, entry["plr"], rel))
      continue
    entry["candidates"] = sorted(plr)  # same geometry, not shown to be the same product
    try:
      spec = generate.spec_for(d, store, name)
      source.append(generate.emit(spec))
      entry.update(status="generated", kind=spec.kind, notes=spec.notes)
    except Exception as e:  # noqa: BLE001 - report and continue
      entry.update(status="error", error=f"{type(e).__name__}: {e}")
      continue
    if a.no_models:
      continue
    try:
      model = generate.authored_model(d, store, spec)
      if model is None:
        model = generate.model_for(spec)
      generate.write_model(*model, out / "resource_model")
      entry["model"] = model[1]["kind"]
    except Exception as e:  # noqa: BLE001
      entry["model_error"] = f"{type(e).__name__}: {e}"

  module = out / "venus_generated.py"
  module.write_text("".join(source), encoding="utf-8")

  # check: import the module and build every factory
  spec = importlib.util.spec_from_file_location("venus_generated", module)
  mod = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(mod)
  for rel, entry in report.items():
    if "factory" not in entry or entry.get("status") == "error":
      continue
    try:
      r = getattr(mod, entry["factory"])("x")
      r.serialize()
      entry["builds"] = True
      d = store.get(rel)
      if isinstance(d, (Rack, Carrier)) and entry["status"] == "generated":
        venus = name_match.venus_fingerprint(d, store)
        mine = name_match.fingerprint(r)
        if venus and venus.kind != "single" and venus.count == mine.count:
          entry["position_rms_vs_venus"] = round(name_match._rms(venus.positions, mine.positions), 4)
    except Exception as e:  # noqa: BLE001
      entry.update(builds=False, build_error="".join(traceback.format_exception_only(type(e), e)).strip())

  (out / "report.json").write_text(json.dumps(report, indent=1) + "\n")
  counts = collections.Counter(e.get("status") for e in report.values())
  kinds = collections.Counter(e.get("kind") for e in report.values() if e.get("status") == "generated")
  models = collections.Counter(e.get("model") for e in report.values() if e.get("status") == "generated")
  print(f"{len(report)} definitions: {dict(counts)}")
  print(f"generated kinds: {dict(kinds)}; models: {dict(models)}")
  print(f"build failures: {sum(1 for e in report.values() if e.get('builds') is False)}; "
        f"model errors: {sum(1 for e in report.values() if 'model_error' in e)}")
  worst = sorted((e.get("position_rms_vs_venus", 0), r) for r, e in report.items())[-3:]
  print(f"largest position RMS vs Venus: {worst}")


if __name__ == "__main__":
  main()
