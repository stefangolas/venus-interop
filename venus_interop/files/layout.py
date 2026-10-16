"""Typed view of a Venus deck layout: the `DECKLAY,<instrument>` section and its `_COVER` companion.

Every value stays the string Venus wrote, so `Layout.from_cfg(cfg).to_cfg()` reproduces the file
exactly. Typed accessors parse on read and format only when a value is assigned.
"""
from __future__ import annotations

import dataclasses
import re
from typing import Optional

from venus_interop.files import hxcfg

_LABWARE = re.compile(r"Labware\.(\d+)\.(.+)")
_SEQ = re.compile(r"Seq\.(\d+)\.(.+)")
_SEQ_ITEM = re.compile(r"Item\.(\d+)\.(ObjId|PosId)")
_LAYER = re.compile(r"Layer\.(\d+)\.(.+)")
_LAYER_MEMBER = re.compile(r"(\d+)\.(LabwareName|SeqName)")


def fmt(x: float) -> str:
  """Format a number the way Venus does: shortest form, no trailing zeros ("617.5", "63")."""
  s = repr(float(x))
  return s[:-2] if s.endswith(".0") else s


@dataclasses.dataclass
class Placement:
  """One `Labware.N.*` group: a carrier, rack, tool or lid on the deck.

  `fields` holds every subkey verbatim ("Id", "TForm.3.X", "LwProperties.1.Value", ...).
  """

  fields: dict[str, str]
  lid: Optional[Placement] = None  # from the _COVER section, same N

  def _get(self, key: str, default: str = "") -> str:
    return self.fields.get(key, default)

  def _num(self, key: str) -> float:
    return float(self.fields.get(key) or 0)

  @property
  def id(self) -> str:
    return self._get("Id")

  @property
  def file(self) -> str:
    return self._get("File")

  @property
  def template(self) -> str:
    """Id of the carrier this sits on, or "default" for the deck itself."""
    return self._get("Template")

  @property
  def site_id(self) -> str:
    return self._get("SiteId")

  @property
  def clsid(self) -> str:
    return self._get("Clsid")

  @property
  def tform(self) -> tuple[float, float, float]:
    return self._num("TForm.3.X"), self._num("TForm.3.Y"), self._num("TForm.3.Z")

  def set_tform(self, x: float, y: float) -> None:
    self.fields["TForm.3.X"], self.fields["TForm.3.Y"] = fmt(x), fmt(y)

  @property
  def z(self) -> float:
    return self._num("ZTrans")

  @z.setter
  def z(self, value: float) -> None:
    self.fields["ZTrans"] = fmt(value)

  @property
  def z_mode(self) -> int:
    """ZTransValue: 0 or 1 = Z follows the site, 2 = Z set by hand."""
    return int(self._num("ZTransValue"))

  @property
  def angle(self) -> float:
    return self._num("Angle")

  @property
  def def_seq_valid(self) -> bool:
    return self._get("DefSeqValid") == "1"

  @property
  def kind(self) -> str:
    """'carrier', 'rack' or 'other', from the file extension."""
    ext = self.file.rsplit(".", 1)[-1].lower()
    return {"tml": "carrier", "rck": "rack", "lid": "lid"}.get(ext, "other")


@dataclasses.dataclass
class Sequence:
  name: str
  items: list[tuple[str, str]]  # (labware id, position id)
  read_only: Optional[str] = "0"  # None: key absent (older layouts)
  extra: dict[str, str] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class Layer:
  fields: dict[str, str]  # Name, Viz, ...
  labware: list[str]
  sequences: list[str]


@dataclasses.dataclass
class Layout:
  cfg: hxcfg.CfgFile
  instrument: str  # section name: ML_STAR, Nimbus8, default, ...
  header: dict[str, str]  # Deck, ActiveLayer, PhoenixVersion, ... (all non-indexed keys)
  labware: list[Placement]
  sequences: list[Sequence]
  layers: Optional[list[Layer]]  # None: the layout has no Layer.Cnt

  # ------------------------------------------------------------------------------ queries

  def by_id(self) -> dict[str, Placement]:
    return {p.id: p for p in self.labware}

  def children(self, parent_id: str) -> list[Placement]:
    return [p for p in self.labware if p.template == parent_id]

  def sequence(self, name: str) -> Optional[Sequence]:
    return next((s for s in self.sequences if s.name == name), None)

  # ------------------------------------------------------------------------------ reading

  @classmethod
  def from_cfg(cls, cfg: hxcfg.CfgFile, instrument: Optional[str] = None) -> Layout:
    main = next(
      s for s in cfg.sections
      if s.type == "DECKLAY" and not s.is_list and not s.name.endswith("_COVER")
      and (instrument is None or s.name == instrument)
    )
    groups: dict[int, dict[str, str]] = {}
    seqs: dict[int, dict] = {}
    layers: dict[int, dict] = {}
    header: dict[str, str] = {}
    for key, value in main.entries:
      if m := _LABWARE.fullmatch(key):
        groups.setdefault(int(m.group(1)), {})[m.group(2)] = value
      elif m := _SEQ.fullmatch(key):
        seq = seqs.setdefault(int(m.group(1)), {"items": {}, "fields": {}})
        if im := _SEQ_ITEM.fullmatch(m.group(2)):
          seq["items"].setdefault(int(im.group(1)), {})[im.group(2)] = value
        else:
          seq["fields"][m.group(2)] = value
      elif m := _LAYER.fullmatch(key):
        layer = layers.setdefault(int(m.group(1)), {"members": {}, "fields": {}})
        if mm := _LAYER_MEMBER.fullmatch(m.group(2)):
          layer["members"].setdefault(mm.group(2), {})[int(mm.group(1))] = value
        else:
          layer["fields"][m.group(2)] = value
      else:
        header[key] = value

    _check_contiguous(groups, header.pop("Labware.Cnt", "0"), "Labware")
    _check_contiguous(seqs, header.pop("Seq.Cnt", "0"), "Seq")
    layer_cnt = header.pop("Layer.Cnt", None)
    if layer_cnt is not None:
      _check_contiguous(layers, layer_cnt, "Layer")

    labware = [Placement(dict(groups[n])) for n in sorted(groups)]
    cover = cfg.section("DECKLAY", main.name + "_COVER")
    if cover is not None:
      for key, value in cover.entries:
        m = _LABWARE.fullmatch(key)
        if m is None:
          raise hxcfg.FormatError(f"unexpected key in cover section: {key}")
        plate = labware[int(m.group(1)) - 1]
        plate.lid = plate.lid or Placement({})
        plate.lid.fields[m.group(2)] = value

    sequences = []
    for n in sorted(seqs):
      f = dict(seqs[n]["fields"])
      items = seqs[n]["items"]
      _check_contiguous(items, f.pop("Cnt"), f"Seq.{n}.Item")
      sequences.append(Sequence(
        name=f.pop("Name"),
        items=[(items[i]["ObjId"], items[i]["PosId"]) for i in sorted(items)],
        read_only=f.pop("ReadOnly", None),
        extra=f,
      ))

    layer_list = None
    if layer_cnt is not None:
      layer_list = []
      for n in sorted(layers):
        f = dict(layers[n]["fields"])
        members = layers[n]["members"]
        lab, seq = members.get("LabwareName", {}), members.get("SeqName", {})
        _check_contiguous(lab, f.pop("LabwareCnt"), f"Layer.{n}.LabwareName")
        _check_contiguous(seq, f.pop("SeqCnt"), f"Layer.{n}.SeqName")
        layer_list.append(Layer(f, [lab[i] for i in sorted(lab)], [seq[i] for i in sorted(seq)]))

    return cls(cfg, main.name, header, labware, sequences, layer_list)

  # ------------------------------------------------------------------------------ writing

  def to_cfg(self) -> hxcfg.CfgFile:
    """A copy of the source file with the DECKLAY sections rebuilt from this model."""
    main: dict[str, str] = dict(self.header)
    cover: dict[str, str] = {}
    main["Labware.Cnt"] = str(len(self.labware))
    for n, p in enumerate(self.labware, 1):
      main.update({f"Labware.{n}.{k}": v for k, v in p.fields.items()})
      if p.lid is not None:
        cover.update({f"Labware.{n}.{k}": v for k, v in p.lid.fields.items()})
    main["Seq.Cnt"] = str(len(self.sequences))
    for n, s in enumerate(self.sequences, 1):
      pre = f"Seq.{n}."
      main[pre + "Name"] = s.name
      main[pre + "Cnt"] = str(len(s.items))
      if s.read_only is not None:
        main[pre + "ReadOnly"] = s.read_only
      main.update({pre + k: v for k, v in s.extra.items()})
      for i, (obj, pos) in enumerate(s.items, 1):
        main[f"{pre}Item.{i}.ObjId"], main[f"{pre}Item.{i}.PosId"] = obj, pos
    if self.layers is not None:
      main["Layer.Cnt"] = str(len(self.layers))
      for n, layer in enumerate(self.layers, 1):
        pre = f"Layer.{n}."
        main.update({pre + k: v for k, v in layer.fields.items()})
        main[pre + "LabwareCnt"] = str(len(layer.labware))
        main[pre + "SeqCnt"] = str(len(layer.sequences))
        main.update({f"{pre}{i}.LabwareName": v for i, v in enumerate(layer.labware, 1)})
        main.update({f"{pre}{i}.SeqName": v for i, v in enumerate(layer.sequences, 1)})

    sections = []
    cover_name = self.instrument + "_COVER"
    for s in self.cfg.sections:
      if s.type == "DECKLAY" and not s.is_list and s.name == self.instrument:
        sections.append(dataclasses.replace(s, entries=sorted(main.items())))
        if cover and self.cfg.section("DECKLAY", cover_name) is None:
          sections.append(hxcfg.Section("DECKLAY", s.version, cover_name, entries=sorted(cover.items())))
      elif s.type == "DECKLAY" and not s.is_list and s.name == cover_name:
        if cover:
          sections.append(dataclasses.replace(s, entries=sorted(cover.items())))
      else:
        sections.append(s)
    return dataclasses.replace(self.cfg, sections=sections)


def _check_contiguous(d: dict[int, object], count: str, what: str) -> None:
  if sorted(d) != list(range(1, int(count) + 1)):
    raise hxcfg.FormatError(f"{what} indexes {sorted(d)[:5]}... do not match count {count}")


def read_layout(source) -> Layout:
  return Layout.from_cfg(hxcfg.read(source))


def write_layout(layout: Layout, binary: Optional[bool] = None) -> bytes:
  return hxcfg.write(layout.to_cfg(), binary)
