"""PyLabRobot deck -> Venus layout, for decks built in PLR (SPEC.md step 4).

Resources imported from a layout keep their Venus fields (`plr_export`). Every other resource gets:
  - a definition file: the stock Hamilton file when one is provably the same labware
    (data/stock_map.json), else files written by `to_venus` under <Labware>\\PLR\\;
  - placement fields from the inverse of the rules in CONVENTIONS.md section 3: carriers on rails get
    `<w>T-<rail>`, racks go on the carrier site they sit on, a rack's TForm.3 is PLR's A1 centre;
  - a default sequence named after it (CONVENTIONS.md section 4).
A deck with no Venus metadata starts from a template layout of the same deck: the header, device
sections and Venus's own waste and teaching labware. PLR's built-in deck parts are left out.
"""
from __future__ import annotations

import dataclasses
import json
import pathlib
from typing import Optional

from pylabrobot.resources import Carrier, Coordinate, ItemizedResource, Lid, Resource, ResourceHolder
from pylabrobot.resources.hamilton import HamiltonSTARDeck

from venus_interop.files import hxcfg
from venus_interop.rules import placement as rules
from venus_interop.plr import to_venus
from venus_interop.files.definitions import Carrier as CarrierDef
from venus_interop.files.definitions import Definition, DefinitionStore, Rack, normalize
from venus_interop.files.layout import Layout, Placement, Sequence, fmt, read_layout
from venus_interop.plr.plr_import import VENUS

HERE = pathlib.Path(__file__).parent
CLSID = {"carrier": "{77DF9B91-671E-4974-8380-38AD0B4E0D86}", "rack": "{8E1D6C02-F939-11D1-8D14-008029ED67EA}",
         "lid": "{6C7C9DC8-B788-4649-AEB7-D97DE84AF6D4}"}
STARLET_SHIFT = -540.0  # 24 tracks: everything tied to the right end of a STAR moves this far on a STARlet
TOL = 1e-3


@dataclasses.dataclass
class Export:
  layout: Layout
  files: dict[str, hxcfg.CfgFile]  # definition files to install, Labware-relative
  deltas: list  # venus_interop.rules.deltas.Delta: everything the export changed or interpreted

  @property
  def notes(self) -> list[str]:
    return [d.line() for d in self.deltas]

  def write(self, lay_path, labware_root) -> list[pathlib.Path]:
    from venus_interop.files.layout import write_layout

    pathlib.Path(lay_path).write_bytes(write_layout(self.layout, binary=True))
    out = [pathlib.Path(lay_path)]
    for rel, cfg in self.files.items():
      p = pathlib.Path(labware_root) / rel.replace("\\", "/")
      p.parent.mkdir(parents=True, exist_ok=True)
      p.write_bytes(hxcfg.write_binary(cfg))
      out.append(p)
    return out


def stock_map() -> dict[str, dict]:
  p = HERE / "data" / "stock_map.json"
  return json.loads(p.read_text()) if p.exists() else {}


def template(num_tracks: int) -> Layout:
  """An empty layout for a STAR (54 tracks) or STARlet (30): header, devices, Venus's waste block."""
  lay = read_layout(HERE / "templates" / "ML_STAR2.lay")
  if num_tracks == 54:
    return lay
  if num_tracks != 30:
    raise ValueError(f"no template for a {num_tracks}-track deck")
  lay.header["Deck"] = "ML_Starlet.dck"
  for p in lay.labware:  # the waste block group sits at the right end of the deck
    x, y, _ = p.tform
    p.set_tform(x + STARLET_SHIFT, y)
    if rules.parse_rail(p.site_id) is not None:
      w, _ = p.site_id.split("T-")
      p.fields["SiteId"] = rules.rail_site_id(int(w), rules.parse_rail(p.site_id) - 24)
  return lay


def _definition_from_cfg(cfg: hxcfg.CfgFile, rel: str) -> Definition:
  from venus_interop.files.definitions import _CLASSES

  sec = next(s for s in cfg.sections if not s.is_list and s.type != "HxPars")
  return _CLASSES.get(sec.type, Definition)(normalize(rel), sec.type, sec.as_dict())


def _builtin_names(deck: HamiltonSTARDeck) -> set[str]:
  fresh = HamiltonSTARDeck(num_tracks=deck.num_tracks, size_x=deck.get_size_x(), size_y=deck.get_size_y(),
                           size_z=deck.get_size_z(), name=deck.name)
  return {r.name for r in fresh.get_all_resources()} - {deck.name}


class _Exporter:
  def __init__(self, deck, store: DefinitionStore, folder: str, prefer: str = "exact"):
    if prefer not in ("exact", "stock"):
      raise ValueError("prefer is 'exact' or 'stock'")
    self.deck, self.store, self.folder, self.prefer = deck, store, folder, prefer
    self.deltas: list = []
    self.stock = stock_map()
    self.files: dict[str, hxcfg.CfgFile] = {}
    self.defs: dict[int, tuple[str, Optional[Definition]]] = {}  # id(resource) -> (File, definition)

  # ---------------------------------------------------------------------------------------- files

  def definition(self, r: Resource) -> tuple[str, Optional[Definition]]:
    """The Venus file for a resource, deciding between a stock Hamilton file and our own (see `prefer`)."""
    if id(r) in self.defs:
      return self.defs[id(r)]
    model = r.model or ""
    stock = self.stock_file(r)
    out = None
    if stock is not None:
      rel = stock["file"]
      d = self.store.get(rel)
      if d is None:
        self.delta(r, "missing", "stock definition", venus=rel,
                   detail=f"{rel} is the same labware but is not installed here, so it cannot be checked.",
                   decision="Wrote our own file." if self.prefer == "exact" else "Used it unchecked.")
        out = None if self.prefer == "exact" else (rel, None)
      else:
        diffs = self.stock_differences(r, rel, d)
        for q, a, b, size in diffs:
          self.delta(r, "stock_disagrees", q, plr=a, venus=b, size=size,
                     detail=f"{rel} and pylabrobot's {model} are the same labware with different numbers.",
                     decision=(f"Wrote our own file instead (prefer='exact')." if self.prefer == "exact" else
                               "Used the stock file (prefer='stock'): a round trip returns Venus's value."))
        if not diffs or self.prefer == "stock":
          out = (rel, d)
    if out is None:
      vf = self.own_files(r, model or r.name)
      for rel, cfg in vf.files.items():
        self.files.setdefault(rel, cfg)
        self.store.add(rel, _definition_from_cfg(cfg, rel))
      for n in vf.notes:
        self.delta(r, "approximation" if "unverified" not in n else "interpretation", "definition", detail=n)
      out = (vf.main, self.store.get(vf.main))
    self.defs[id(r)] = out
    return out

  def own_files(self, r: Resource, name: str):
    """Our own definition files, named after the model unless that name is taken by different content
    (pylabrobot gives every Hamilton tip rack the model `hamilton_96_tiprack_standard`, whatever its tips):
    then the name gets a hash of the content. Identical content shares one set of files."""
    import hashlib

    def make(n):
      return to_venus.lid_files(r, self.folder, n) if isinstance(r, Lid) else to_venus.venus_files(r, self.folder, n)

    def content(vf):
      return [(rel.rsplit("\\", 1)[-1].rsplit(".", 1)[-1], [(s.type, s.entries) for s in cfg.sections])
              for rel, cfg in vf.files.items()]

    vf = make(name)
    taken = vf.main in self.files
    if taken and content(vf) == content(make(name)) and all(
        self.files.get(rel) is not None and [(s.type, s.entries) for s in self.files[rel].sections] ==
        [(s.type, s.entries) for s in cfg.sections] for rel, cfg in vf.files.items()):
      return vf  # the same files again
    if taken:
      digest = hashlib.sha1(repr(content(vf)).encode()).hexdigest()[:8]
      vf = make(f"{name}_{digest}")
    return vf

  def delta(self, r: Resource, kind: str, quantity: str, **kw) -> None:
    from venus_interop.rules.deltas import Delta

    self.deltas.append(Delta(r.name, kind, quantity, **kw))

  def stock_differences(self, r: Resource, rel: str, d: Definition) -> list:
    """How the importer's reading of a stock file differs from the PLR resource it would stand for."""
    from venus_interop.plr import plr_import
    from venus_interop.rules.deltas import TOL, rack_differences

    if isinstance(r, Carrier) and isinstance(d, CarrierDef):
      sites = list(d.sites.values())
      out = []
      for h in r.sites.values():
        land = to_venus.site_corner(h)
        best = min(sites, key=lambda s: abs(s.x - land.x) + abs(s.y - land.y), default=None)
        if best is None:
          out.append(("site", f"{land}", None, float("inf")))
          continue
        size = max(abs(best.x - land.x), abs(best.y - land.y), abs(best.z - land.z))
        if size > TOL:
          out.append((f"site {best.id} (x, y, z)", (round(land.x, 4), round(land.y, 4), round(land.z, 4)),
                      (best.x, best.y, best.z), size))
      if len(sites) != len(r.sites):
        out.append(("number of sites", len(r.sites), len(sites), float("inf")))
      return out
    rebuilt = plr_import.build_resource(Placement({"Id": "probe", "File": rel}), self.store)
    holder = Resource("probe_holder", 1e4, 1e4, 1e4)
    holder.assign_child_resource(rebuilt, location=Coordinate.zero())
    return rack_differences(r, rebuilt, sinking=getattr(r, "sinking_depth", 0.0) or 0.0)

  def stock_file(self, r: Resource) -> Optional[dict]:
    """The stock Hamilton file for this labware: a stock-mapped factory whose output has the same
    model and is the same labware (positions, size, tip). PLR models often name a base factory
    (`hamilton_96_tiprack_standard` for every Hamilton tip rack), so the model alone is not enough."""
    import importlib

    from venus_interop.plr import name_match

    mine = None
    for entry in self.stock.values():
      if entry.get("model") != r.model:
        continue
      mod, fn = entry["factory"].rsplit(".", 1)
      ref = getattr(importlib.import_module(mod), fn)("probe")
      mine = mine or name_match.fingerprint(r)
      theirs = name_match.fingerprint(ref)
      same = (mine.count == theirs.count and name_match._rms(mine.positions, theirs.positions) < 1e-6
              and all(abs(a - b) < 1e-6 for a, b in zip(mine.size, theirs.size)))
      if same and mine.tip is not None:
        same = theirs.tip is not None and mine.tip[1] == theirs.tip[1] and abs(mine.tip[2] - theirs.tip[2]) < 1e-6 \
          and abs(mine.tip[0] - theirs.tip[0]) < 1e-6
      if same:
        return entry
    return None

  # ---------------------------------------------------------------------------------------- fields

  @staticmethod
  def base_fields(kind: str, rid: str, rel: str) -> dict[str, str]:
    return {"Id": rid, "File": rel, "Angle": "0", "BarcodeCnt": "0", "Clsid": CLSID[kind], "Inst": "",
            "TForm.1.X": "1", "TForm.1.Y": "0", "TForm.1.Z": "0", "TForm.2.X": "0", "TForm.2.Y": "1",
            "TForm.2.Z": "0", "TForm.3.Z": "1"}

  def carrier(self, c: Carrier) -> Placement:
    rel, d = self.definition(c)
    loc = c.get_absolute_location()
    f = self.base_fields("carrier", c.name, rel)
    f.update({"Template": "default", "DefSeqValid": "0", "ZTransValue": "2", "ZTrans": fmt(round(loc.z, 4)),
              "TForm.3.X": fmt(round(loc.x, 4)), "TForm.3.Y": fmt(round(loc.y, 4))})
    rail = round((loc.x - rules.RAIL_ORIGIN[0]) / rules.TRACK_WIDTH) + 1
    rx, ry, rz = rules.rail_location(rail)
    if abs(loc.x - rx) < TOL and abs(loc.y - ry) < TOL:
      width = (d.properties.get("MlStarCarWidthAsT") if isinstance(d, Definition) and hasattr(d, "properties") else None)
      w = int(width) if width else round(c.get_size_x() / rules.TRACK_WIDTH)
      f["SiteId"] = rules.rail_site_id(w, rail)
    else:
      f["SiteId"] = ""
      self.delta(c, "interpretation", "rail", plr=(round(loc.x, 4), round(loc.y, 4)),
                 detail="Not on a rail position.", decision="Placed by its coordinates, with no rail site id.")
    return Placement(f)

  def site_of(self, holder: ResourceHolder, carrier: Carrier, r: Resource) -> tuple[str, Optional[float]]:
    """The Venus site the rack sits on (by where it actually is), and that site's absolute Z."""
    sid = holder.metadata.get(VENUS, {}).get("site_id")
    _, d = self.definition(carrier)
    sites = d.sites if isinstance(d, CarrierDef) else {}
    c = carrier.get_absolute_location()
    if sid is not None and sid in sites:
      return sid, c.z + sites[sid].z
    corner = to_venus.site_corner(holder)  # the site, independent of how PLR seats this item on it
    for s in sites.values():
      if abs(s.x - corner.x) < 1.0 and abs(s.y - corner.y) < 1.0:
        return s.id, c.z + s.z
    return sid or "", None

  def rack(self, r: Resource, layout: Layout) -> Placement:
    rel, d = self.definition(r)
    loc = r.get_absolute_location()
    f = self.base_fields("rack", r.name, rel)
    if isinstance(r, ItemizedResource) and r.num_items:
      a1 = r.get_item(0).get_absolute_location(x="c", y="c")
      tx, ty = a1.x, a1.y
    elif isinstance(d, Rack):
      tx, ty = rules.rack_tform((loc.x, loc.y), d)
    else:
      tx, ty = loc.x, loc.y
    # PLR sets an embedded tip rack `sinking_depth` below its site; Venus's ZTrans is the site
    sink = getattr(r, "sinking_depth", 0.0) or 0.0
    venus_z = loc.z + sink
    if sink:
      self.delta(r, "convention", "rack Z", plr=round(loc.z, 4), venus=round(venus_z, 4), size=sink,
                 detail="PLR's embedded tip rack sits sinking_depth into its carrier; Venus measures from the site.",
                 decision="ZTrans = PLR z + sinking depth (exact; reversed on import).")
    f.update({"TForm.3.X": fmt(round(tx, 4)), "TForm.3.Y": fmt(round(ty, 4)), "ZTrans": fmt(round(venus_z, 4)),
              "IsCovered": "0", "Template": "default", "SiteId": "", "ZTransValue": "2"})
    holder, carrier = r.parent, None
    p = r.parent
    while p is not None and not isinstance(p, Carrier):
      if isinstance(p, ResourceHolder) and isinstance(p.parent, Carrier):
        holder = p
      p = p.parent
    carrier = p if isinstance(p, Carrier) and p.parent is self.deck else None
    if carrier is not None and isinstance(holder, ResourceHolder):
      sid, site_z = self.site_of(holder, carrier, r)
      f.update({"Template": carrier.name, "SiteId": sid})
      if site_z is not None and abs(venus_z - site_z) < TOL:
        f["ZTransValue"] = "1"
      elif site_z is not None:
        self.delta(r, "convention", "rack Z on its site", plr=round(venus_z, 4), venus=round(site_z, 4),
                   size=abs(venus_z - site_z),
                   detail="PLR seats this labware off its site's height (a plate lowered onto the site's pedestal); "
                          "Venus puts labware at the site's height.",
                   decision="ZTrans = PLR's height, ZTransValue 2 (set by hand), so Venus places it where PLR does.")
    elif r.parent is self.deck:
      rail = round((loc.x - rules.RAIL_ORIGIN[0]) / rules.TRACK_WIDTH) + 1
      rx, ry, _ = rules.rail_location(rail)
      if isinstance(d, Rack):
        cx, cy = rules.rack_corner((tx, ty), d)
        if abs(cx - rx) < TOL and abs(cy - ry) < TOL:
          f.update({"SiteId": rules.rail_site_id(max(1, round(r.get_size_x() / rules.TRACK_WIDTH)), rail),
                    "ZTransValue": "1"})
    positions = rules.default_positions(d) if isinstance(d, Rack) and d.rows and d.columns else (
      [it.get_identifier() if hasattr(it, "get_identifier") else str(i + 1)
       for i, it in enumerate(r.get_all_items())] if isinstance(r, ItemizedResource) else [])
    if positions:
      f["DefSeqValid"] = "1"
      layout.sequences.append(Sequence(r.name, [(r.name, pos) for pos in positions], "0"))
    else:
      f["DefSeqValid"] = "0"
    return Placement(f)

  def lid(self, lid: Lid, plate: Resource) -> Placement:
    rel, _ = self.definition(lid)
    loc = lid.get_absolute_location()
    f = self.base_fields("lid", lid.name, rel)
    f.update({"TForm.3.X": fmt(round(loc.x, 4)), "TForm.3.Y": fmt(round(loc.y, 4)), "ZTrans": fmt(round(loc.z, 4)),
              "ZTransValue": "0", "DefSeqValid": "1"})
    return Placement(f)


def export(deck: HamiltonSTARDeck, store: DefinitionStore, folder: str = "PLR", prefer: str = "exact") -> Export:
  """A Venus layout for a PLR deck, and the definition files it needs that Venus doesn't have.

  prefer="exact": a stock Hamilton file is used only if the importer, reading it back, reproduces
    the PLR resource exactly; otherwise our own file is written. Round trips are exact.
  prefer="stock": stock files are used wherever they are the same labware; where their numbers differ
    from PLR's, a round trip returns Venus's numbers. Every such difference is in `Export.deltas`.
  """
  from venus_interop.plr import plr_export

  ex = _Exporter(deck, store, folder, prefer)
  if VENUS in deck.metadata:
    layout = plr_export.plr_to_lay(deck, store, allow_unmapped=True)
  else:
    layout = template(deck.num_tracks)
  known = {p.id for p in layout.labware}
  builtins = _builtin_names(deck)
  new: list[Placement] = []

  def visit(r: Resource):
    if r.name in known or r.name in builtins or VENUS in r.metadata:
      for c in r.children:
        if not isinstance(r, ItemizedResource):
          visit(c)
      return
    if isinstance(r, Carrier):
      new.append(ex.carrier(r))
      for h in r.sites.values():
        for c in h.children:
          visit(c)
      return
    if isinstance(r, ResourceHolder):
      for c in r.children:
        visit(c)
      return
    if isinstance(r, Lid):
      return  # placed with its plate
    p = ex.rack(r, layout)
    new.append(p)
    lid = next((c for c in r.children if isinstance(c, Lid)), None)
    if lid is not None:
      p.fields["IsCovered"] = "1"
      p.lid = ex.lid(lid, r)
    for c in r.children:  # stacked labware (a plate on an adapter)
      if not isinstance(c, Lid) and not (isinstance(r, ItemizedResource) and c in r.get_all_items()):
        visit(c)

  for child in deck.children:
    visit(child)
  layout.labware.extend(new)
  if layout.layers:
    base = next((x for x in layout.layers if x.fields.get("Name") == layout.header.get("ActiveLayer")), layout.layers[0])
    base.labware.extend(p.id for p in new)
  return Export(layout, ex.files, ex.deltas)
