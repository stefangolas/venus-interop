"""Capture logs: what each Venus layout says beyond plain carrier-site assignments.

  python tools/capture_log.py OUT_DIR LAYOUT.lay [LAYOUT.lay ...] [--labware DIR ...] [--kits DIR ...]

Each layout is imported (venus_interop.plr.plr_import), so the log also includes the import's own
interpretations. Writes OUT_DIR/<layout>.md per layout and OUT_DIR/README.md with the summary.
--kits: folders searched for kit 'Labware' folders; the one whose path best matches the layout's
name is searched first, and definitions are also found by file name (recorded in the log).
"""
import argparse
import collections
import hashlib
import json
import logging
import os
import pathlib
import re
import sys
import warnings

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pylabrobot.resources import Deck  # noqa: E402

from venus_interop.rules import capture  # noqa: E402
from venus_interop.files import layout
from venus_interop.plr import plr_export, plr_import
from venus_interop.files.definitions import DEFAULT_VENUS_LABWARE, DefinitionStore  # noqa: E402

STOP = {"labware", "users", "stefa", "protocols", "assets", "program", "files", "hamilton", "ngsstar", "ngsstarmoa",
        "lay", "deck", "methods"}


def toks(p):
  return {t for t in re.split(r"[^a-z0-9]+", str(p).lower()) if len(t) > 2} - STOP


def store_for(lay_path, labware, kits):
  ordered = sorted(kits, key=lambda r: -len(toks(r) & toks(lay_path)))
  roots = ordered[:1] + [pathlib.Path(x) for x in labware] + [DEFAULT_VENUS_LABWARE] + ordered[1:]
  return DefinitionStore(roots, by_name=bool(kits))


def write_log(path, lay_path, deck, identical):
  meta = deck.metadata["venus"]
  cap, deltas = meta["capture"], meta["deltas"]
  s = cap["summary"]
  lines = [f"# {lay_path.name}", "", f"Source: `{lay_path}`", "",
           f"- Labware: {s['labware']}; pure carrier-site assignments: {s['pure assignments']}; "
           f"carrying information: {s['carrying information']}",
           f"- LAY -> PLR -> JSON -> LAY byte-identical: **{identical}**", ""]
  groups = collections.defaultdict(list)
  for i in cap["items"]:
    groups[i["field"]].append(i)
  order = ["x/y", "z", "alternative", "position", "rotation", "lid z", "sequence", "definition", "clsid"]
  titles = {"x/y": "Nudges off the site (x/y)", "z": "Heights off the site or stack (z)",
            "alternative": "Alternatives at the same place", "position": "Off any carrier site",
            "rotation": "Rotated", "lid z": "Lid heights (set by hand)", "sequence": "Default sequences edited",
            "definition": "Definitions missing", "clsid": "Unusual class id"}
  for f in order + sorted(set(groups) - set(order)):
    if f not in groups:
      continue
    lines += [f"## {titles.get(f, f)} ({len(groups[f])})", "", "| Labware | What | ZTransValue |", "|---|---|---|"]
    for i in sorted(groups[f], key=lambda i: -(i.get("size") or 0)):
      lines.append(f"| `{i['labware']}` | {i['text']} | {i.get('z_mode', '')} |")
    lines.append("")
  if deltas:
    lines += ["## Import interpretations", "", "| Labware | Kind | Quantity | Decision |", "|---|---|---|---|"]
    for d in deltas:
      lines.append(f"| `{d['resource']}` | {d['kind']} | {d['quantity']} | {d.get('decision', '')} {d.get('detail', '')} |")
  path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("out")
  ap.add_argument("layouts", nargs="+")
  ap.add_argument("--labware", nargs="*", default=[])
  ap.add_argument("--kits", nargs="*", default=[])
  a = ap.parse_intermixed_args()
  logging.disable(logging.WARNING)
  warnings.simplefilter("ignore")
  out = pathlib.Path(a.out)
  out.mkdir(parents=True, exist_ok=True)
  kits = [pathlib.Path(dp, d) for base in a.kits for dp, ds, _ in os.walk(base) for d in ds if d.lower() == "labware"]
  rows = []
  paths = []
  for x in map(pathlib.Path, a.layouts):
    paths += sorted(x.rglob("*.lay")) if x.is_dir() else [x]
  all_items, seen, on_sites = [], set(), collections.Counter()
  for lp in paths:
    data = lp.read_bytes()
    store = store_for(lp, a.labware, kits)
    lay = layout.read_layout(data)
    try:
      deck = plr_import.lay_to_plr(lay, store)
    except plr_import.UnsupportedLayout as e:
      rows.append((lp, None, str(e)))
      continue
    back = Deck.deserialize(json.loads(json.dumps(deck.serialize())))
    identical = layout.write_layout(plr_export.plr_to_lay(back, store)) == data
    name = re.sub(r"[^\w.-]+", "_", str(lp.relative_to(lp.anchor)))[-90:] + ".md"
    write_log(out / name, lp, deck, identical)
    digest = hashlib.sha1(data).hexdigest()[:12]
    if digest not in seen:  # copies of one layout are one piece of evidence
      seen.add(digest)
      all_items += [capture.Item(**{**{k: (tuple(v) if k == "offset" else v) for k, v in i.items()}, "layout": digest})
                    for i in deck.metadata["venus"]["capture"]["items"]]
      for p in lay.labware:
        if p.kind == "rack" and p.template != "default":
          on_sites[capture._name(p.file)] += 1
    rows.append((lp, deck.metadata["venus"]["capture"]["summary"], name, identical))
  fields = sorted({f for r in rows if r[1] for f in r[1]["by field"]})
  lines = ["# Capture logs", "", "What each layout says beyond plain carrier-site assignments (venus_interop/rules/capture.py).", "",
           "| Layout | Labware | Pure | Carrying info | " + " | ".join(fields) + " | Round trip |",
           "|---|---|---|---|" + "---|" * len(fields) + "---|"]
  for r in rows:
    if r[1] is None:
      lines.append(f"| {r[0].name} | {r[2]} |")
      continue
    lp, s, name, identical = r
    lines.append(f"| [{lp.name}]({name}) | {s['labware']} | {s['pure assignments']} | {s['carrying information']} | "
                 + " | ".join(str(s["by field"].get(f, "")) for f in fields) + f" | {'identical' if identical else 'DIFFERS'} |")
  lines += ["", f"Distinct layouts: {len(seen)} (copies count once in the tables below).", "",
            "## Labware that sits off its site", "",
            "Placements on carrier sites, per labware file, and how many are off the site's position (x/y) or "
            "height (z, against the site or the stack below).", "",
            "| Labware | On carrier sites | x/y off | z off | Share off |", "|---|---|---|---|---|"]
  for r in capture.by_labware(all_items, on_sites):
    if r["x/y off"] or r["z off"]:
      lines.append(f"| {r['labware']} | {r['placements']} | {r['x/y off']} | {r['z off']} | {100 * r['share off']:.0f}% |")
  lines += ["", "## Offsets by labware and carrier site", "",
            "Systematic: the same offset (within 0.05 mm) in at least 2 distinct layouts: a missing rule "
            "(a nest, pedestal or module height), not a nudge. The rest are one-off nudges or taught positions.", "",
            "| Systematic | Field | Labware | Carrier, site | Layouts | Placements | Offset (mm) | Spread |",
            "|---|---|---|---|---|---|---|---|"]
  for g in capture.systematic(all_items):
    lines.append(f"| {'yes' if g['systematic'] else ''} | {g['field']} | {g['rack']} | {g['carrier']} | {g['layouts']} | "
                 f"{g['placements']} | {g['offset']} | {g['spread']} |")
  (out / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
  print("\n".join(lines))


if __name__ == "__main__":
  main()
