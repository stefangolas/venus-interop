"""The position sweep's comparison: Venus's positions (<work>/sweep/out/<hash>.out, from sweep.py) against what
venus_interop's importer (lay_to_plr) puts there, per position: X/Y at the centre, Z at the container
floor (a well's cavity bottom; a tip spot's container base, the spot less the .ctr's MaxDepth).

  python compare_sweep.py [HASH ...]     (all of out/ when none given)

Writes <work>/sweep/deltas.tsv (one row per labware: its worst X/Y and its Z difference, with what may explain
it) and prints the groups: labware sharing a Z difference and a ZTransValue, and every X/Y miss."""
import collections
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from paths import REPO, WORK  # noqa: E402

HERE = WORK / "sweep"
sys.path.insert(0, str(REPO))
from pylabrobot.resources import ItemizedResource, TipSpot, Well  # noqa: E402

from venus_interop.files import layout  # noqa: E402
from venus_interop.files.definitions import Rack  # noqa: E402
from venus_interop.plr import plr_import  # noqa: E402
from venus_interop.rules import placement  # noqa: E402

from sweep import RAW, STORE  # noqa: E402


def venus(h: str):
  labs, pos, errs = {}, collections.defaultdict(dict), []
  for line in (HERE / "out" / f"{h}.out").read_text(encoding="latin-1").splitlines():
    if "; LAB|" in line:
      i, x, y, z, r = line.split("; LAB|", 1)[1].split("|")
      labs[i] = (float(x), float(y), float(z), float(r))
    elif "; POS|" in line:
      i, pid, x, y, z, r = line.split("; POS|", 1)[1].split("|")
      pos[i][pid] = (float(x), float(y), float(z))
    elif "; ERR|" in line:
      errs.append(line.split("; ERR|", 1)[1])
  return labs, pos, errs


def plr_floor(item) -> float:
  if isinstance(item, TipSpot):
    rack = item.parent
    ctr = STORE.ref(STORE.get(rack.metadata["venus"]["fields"]["File"]), "Cntr.1.file") if "venus" in rack.metadata else None
    seat = ctr.num("MaxDepth") if ctr is not None else 0.0
    return item.get_location_wrt(item.get_root(), "c", "c", "b").z - seat
  ref = "cavity_bottom" if isinstance(item, Well) else "b"
  return item.get_location_wrt(item.get_root(), "c", "c", ref).z


def compare(h: str) -> list[dict]:
  lay = layout.read_layout(RAW / f"{h}.lay")
  labs, pos, errs = venus(h)
  try:
    deck = plr_import.lay_to_plr(lay, STORE)
  except Exception as e:  # noqa: BLE001
    return [{"layout": h, "labware": "*", "note": f"import failed: {type(e).__name__}: {e}"[:200]}]
  rows = []
  by_id = lay.by_id()
  for i, places in pos.items():
    p = by_id.get(i)
    d = STORE.get(p.file) if p is not None else None
    row = {"layout": h, "labware": i, "file": p.file if p else "", "ztv": p.fields.get("ZTransValue", "") if p else "",
           "angle": p.fields.get("Angle", "0") if p else "", "template": p.fields.get("Template", "") if p else "",
           "site": p.fields.get("SiteId", "") if p else ""}
    if isinstance(d, Rack):
      ctr = STORE.ref(d, "Cntr.1.file")
      row.update(base=d.num("Cntr.1.base"), base_mm=ctr.num("BaseMM") if ctr is not None else "",
                 tip=d.is_tip_rack)
    try:
      r = deck.get_resource(i)
    except Exception:  # noqa: BLE001
      rows.append({**row, "note": "not in the PLR deck"})
      continue
    if not isinstance(r, ItemizedResource):
      rows.append({**row, "note": f"PLR {type(r).__name__}, no positions"})
      continue
    try:
      names = placement.default_positions(d)
    except Exception:  # noqa: BLE001
      names = []
    items = r.get_all_items()
    dxy, dz, n = [], [], 0
    for k, name in enumerate(names):
      if name not in places or k >= len(items):
        continue
      vx, vy, vz = places[name]
      c = items[k].get_location_wrt(r.get_root(), "c", "c", "b")
      dxy.append(max(abs(c.x - vx), abs(c.y - vy)))
      dz.append(round(plr_floor(items[k]) - vz, 3))
      n += 1
    if not n:
      rows.append({**row, "note": f"no positions paired ({len(items)} PLR items, {len(places)} Venus)"})
      continue
    rows.append({**row, "n": n, "max_dxy": round(max(dxy), 3), "dz": statistics.median(dz),
                 "dz_spread": round(max(dz) - min(dz), 3)})
  rows += [{"layout": h, "labware": e.split("|")[0], "note": "Venus error: " + e[:160]} for e in errs]
  return rows


if __name__ == "__main__":
  hashes = sys.argv[1:] or sorted(f.stem for f in (HERE / "out").glob("*.out"))
  rows = [r for h in hashes for r in compare(h)]
  cols = ["layout", "labware", "file", "ztv", "angle", "template", "site", "tip", "base", "base_mm", "n", "max_dxy",
          "dz", "dz_spread", "note"]
  with open(HERE / "deltas.tsv", "w", encoding="utf-8") as f:
    f.write("\t".join(cols) + "\n")
    for r in rows:
      f.write("\t".join(str(r.get(c, "")) for c in cols) + "\n")
  measured = [r for r in rows if "n" in r]
  ok = [r for r in measured if r["max_dxy"] < 0.05 and abs(r["dz"]) < 0.05 and r["dz_spread"] < 0.05]
  print(f"{len(hashes)} layouts, {len(measured)} labware measured, {len(ok)} exact (0.05 mm); "
        f"{len(rows) - len(measured)} not measured")
  groups = collections.Counter((r["ztv"], r["dz"], bool(r.get("tip"))) for r in measured if abs(r["dz"]) >= 0.05)
  print("Z differences (ZTransValue, PLR - Venus, tip rack): labware")
  for k, v in groups.most_common(25):
    print("  ", k, v)
  xy = [r for r in measured if r["max_dxy"] >= 0.05]
  print(f"X/Y misses: {len(xy)}")
  for r in sorted(xy, key=lambda r: -r["max_dxy"])[:15]:
    print("  ", r["layout"], r["labware"], r["file"], "angle", r["angle"], "max", r["max_dxy"])
  notes = collections.Counter(r["note"].split(":")[0] for r in rows if "note" in r)
  print("not measured:", notes.most_common())
