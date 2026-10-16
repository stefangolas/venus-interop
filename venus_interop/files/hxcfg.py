"""Hamilton HxCfgFile container: the format shared by .lay, .rck, .tml, .lid, .ctr, .dck and .med.

Reads and writes both the binary form and the text form without any Hamilton tools.
See SPEC.md section 2.1 for the grammar.
"""
from __future__ import annotations

import dataclasses
import pathlib
import re
import struct
import zlib
from typing import Optional, Union

TEXT_MAGIC = b"HxCfgFile,"
FOOTER_RE = re.compile(
  rb"\* \$\$author=(.*?)\$\$valid=(\d)\$\$time=(.*?)\$\$checksum=([0-9a-f]{8})\$\$length=(\d{3})\$\$"
)
# Footer `length` minus the footer line's own length, as found in Hamilton's files.
DEFAULT_LENGTH_OFFSET = {True: 2, False: 0}  # binary, text


class FormatError(ValueError):
  pass


@dataclasses.dataclass
class Section:
  """One `DataDef,TYPE,VERSION,NAME,` block: a dictionary (entries) or a list (items)."""

  type: str
  version: int
  name: str
  entries: Optional[list[tuple[str, str]]] = None
  items: Optional[list[str]] = None

  @property
  def is_list(self) -> bool:
    return self.items is not None

  def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
    for k, v in self.entries or ():
      if k == key:
        return v
    return default

  def as_dict(self) -> dict[str, str]:
    return dict(self.entries or ())


@dataclasses.dataclass
class Footer:
  author: str = "venus_interop"
  valid: int = 0
  time: str = "2000-01-01 00:00"
  length_offset: Optional[int] = None  # None: use the default for the form being written


@dataclasses.dataclass
class CfgFile:
  version: int = 3
  valid: bool = True
  sections: list[Section] = dataclasses.field(default_factory=list)
  footer: Footer = dataclasses.field(default_factory=Footer)
  binary: bool = True

  def section(self, type_: str, name: Optional[str] = None, is_list: bool = False) -> Optional[Section]:
    for s in self.sections:
      if s.type == type_ and (name is None or s.name == name) and s.is_list == is_list:
        return s
    return None


# ---------------------------------------------------------------------------------------- footer


def _footer_line(body: bytes, prefix: bytes, f: Footer, offset: int) -> bytes:
  head = (
    prefix + b"$$author=" + f.author.encode("latin-1") + b"$$valid=" + str(f.valid).encode()
    + b"$$time=" + f.time.encode("latin-1") + b"$$checksum="
  )
  crc = zlib.crc32(body + head) & 0xFFFFFFFF
  line = head + b"%08x$$length=" % crc
  return line + b"%03d$$" % (len(line) + len(b"000$$") + offset)


def _split_footer(data: bytes) -> tuple[bytes, Footer, bytes]:
  """Return (body before the footer line, footer, stored footer line)."""
  start = data.rfind(b"* $$author=")
  m = FOOTER_RE.match(data, start) if start >= 0 else None
  if m is None:
    raise FormatError("no Venus footer found")
  line = data[start:m.end()]
  footer = Footer(
    author=m.group(1).decode("latin-1"),
    valid=int(m.group(2)),
    time=m.group(3).decode("latin-1"),
    length_offset=int(m.group(5)) - len(line),
  )
  return data[:start], footer, line


def footer_ok(data: bytes) -> bool:
  """True when the stored checksum and length match the file's contents."""
  body, footer, line = _split_footer(data)
  return _footer_line(body, b"* ", footer, footer.length_offset) == line


# ---------------------------------------------------------------------------------------- binary


class _Reader:
  def __init__(self, data: bytes):
    self.d, self.i = data, 0

  def u16(self) -> int:
    (v,) = struct.unpack_from("<H", self.d, self.i)
    self.i += 2
    return v

  def u32(self) -> int:
    (v,) = struct.unpack_from("<I", self.d, self.i)
    self.i += 4
    return v

  def s(self) -> str:
    n = self.d[self.i]
    self.i += 1
    if n == 0xFF:
      n = self.u16()
    if self.i + n > len(self.d):
      raise FormatError(f"string runs past end of file at {self.i}")
    v = self.d[self.i:self.i + n].decode("latin-1")
    self.i += n
    return v


def _read_binary(data: bytes) -> CfgFile:
  body, footer, _ = _split_footer(data)
  r = _Reader(body)
  version, valid = r.u16(), r.u16()
  sections = []

  def header() -> tuple[str, int, str, int]:
    typ, _, name = r.s().partition(",")
    return typ, r.u16(), name, r.u32()

  for _ in range(r.u32()):
    typ, ver, name, n = header()
    sections.append(Section(typ, ver, name, entries=[(r.s(), r.s()) for _ in range(n)]))
  if version >= 3:
    for _ in range(r.u32()):
      typ, ver, name, n = header()
      sections.append(Section(typ, ver, name, items=[r.s() for _ in range(n)]))
  if body[r.i:] != b"\r\n":
    raise FormatError(f"unexpected bytes before footer: {body[r.i:r.i + 20]!r}")
  return CfgFile(version, bool(valid), sections, footer, binary=True)


def _pack_str(s: str) -> bytes:
  b = s.encode("latin-1")
  if len(b) < 0xFF:
    return bytes([len(b)]) + b
  return b"\xff" + struct.pack("<H", len(b)) + b


def _pack_header(s: Section, n: int) -> bytes:
  return _pack_str(f"{s.type},{s.name}") + struct.pack("<HI", s.version, n)


def write_binary(cfg: CfgFile) -> bytes:
  dicts = [s for s in cfg.sections if not s.is_list]
  lists = [s for s in cfg.sections if s.is_list]
  if lists and cfg.version < 3:
    raise FormatError("list sections need HxCfgFile version 3")
  out = [struct.pack("<HHI", cfg.version, int(cfg.valid), len(dicts))]
  for s in dicts:
    out.append(_pack_header(s, len(s.entries)))
    out.extend(_pack_str(k) + _pack_str(v) for k, v in s.entries)
  if cfg.version >= 3:
    out.append(struct.pack("<I", len(lists)))
    for s in lists:
      out.append(_pack_header(s, len(s.items)))
      out.extend(_pack_str(i) for i in s.items)
  out.append(b"\r\n")
  return _with_footer(b"".join(out), cfg.footer, binary=True)


def _with_footer(body: bytes, footer: Footer, binary: bool) -> bytes:
  offset = footer.length_offset if footer.length_offset is not None else DEFAULT_LENGTH_OFFSET[binary]
  return body + _footer_line(body, b"* ", footer, offset)


# ---------------------------------------------------------------------------------------- text


_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}
_UNESCAPES = {"n": "\n", "r": "\r", "t": "\t"}


def _escape(s: str) -> str:
  # other bytes outside printable ASCII are written as \0xhh
  return "".join(
    _ESCAPES.get(c) or (c if " " <= c < "\x7f" else f"\\0x{ord(c):02x}") for c in s
  )


class _Text:
  def __init__(self, text: str):
    self.t, self.i = text, 0

  def ws(self):
    while self.i < len(self.t) and self.t[self.i] in " \t\r\n":
      self.i += 1

  def expect(self, s: str):
    self.ws()
    if not self.t.startswith(s, self.i):
      raise FormatError(f"expected {s!r} at {self.i}: {self.t[self.i:self.i + 40]!r}")
    self.i += len(s)

  def peek(self, s: str) -> bool:
    self.ws()
    return self.t.startswith(s, self.i)

  def until(self, stop: str) -> str:
    j = self.t.index(stop, self.i)
    v, self.i = self.t[self.i:j], j + len(stop)
    return v

  def quoted(self) -> str:
    self.expect('"')
    out = []
    while True:
      c = self.t[self.i]
      if c == "\\":
        c = self.t[self.i + 1]
        if self.t.startswith("0x", self.i + 1):
          out.append(chr(int(self.t[self.i + 3:self.i + 5], 16)))
          self.i += 5
          continue
        out.append(_UNESCAPES.get(c, c))
        self.i += 2
      elif c == '"':
        self.i += 1
        return "".join(out)
      else:
        out.append(c)
        self.i += 1


def _read_text(data: bytes) -> CfgFile:
  body, footer, _ = _split_footer(data)
  p = _Text(body.decode("latin-1"))
  p.expect("HxCfgFile,")
  version = int(p.until(";"))
  p.expect("ConfigIsValid,")
  valid = p.until(";").strip() == "Y"
  sections = []
  while p.peek("DataDef,"):
    p.expect("DataDef,")
    typ = p.until(",")
    ver = int(p.until(","))
    name = p.until(",")
    if p.peek("{"):
      p.expect("{")
      entries = []
      while not p.peek("}"):
        key = p.until(",").strip()
        entries.append((key, p.quoted()))
        if p.peek(","):
          p.expect(",")
      p.expect("};")
      sections.append(Section(typ, ver, name, entries=entries))
    else:
      p.expect("[")
      items = []
      while not p.peek("]"):
        items.append(p.quoted())
        if p.peek(","):
          p.expect(",")
      p.expect("];")
      sections.append(Section(typ, ver, name, items=items))
  p.ws()
  if p.i != len(p.t):
    raise FormatError(f"unexpected text before footer: {p.t[p.i:p.i + 40]!r}")
  return CfgFile(version, valid, sections, footer, binary=False)


def write_text(cfg: CfgFile) -> bytes:
  lines = [f"HxCfgFile,{cfg.version};", "", f"ConfigIsValid,{'Y' if cfg.valid else 'N'};", ""]
  for s in cfg.sections:
    lines.append(f"DataDef,{s.type},{s.version},{s.name},")
    if s.is_list:
      rows = [f'"{_escape(i)}"' for i in s.items]
      open_, close = "[", "];"
    else:
      rows = [f'{k}, "{_escape(v)}"' for k, v in s.entries]
      open_, close = "{", "};"
    lines.append(open_)
    lines.extend(r + ("," if n < len(rows) - 1 else "") for n, r in enumerate(rows))
    lines += [close, ""]
  body = ("\r\n".join(lines) + "\r\n").encode("latin-1")
  return _with_footer(body, cfg.footer, binary=False)


# ---------------------------------------------------------------------------------------- entry points


def read(source: Union[str, pathlib.Path, bytes]) -> CfgFile:
  """Read a binary or text HxCfgFile from a path or bytes."""
  data = source if isinstance(source, bytes) else pathlib.Path(source).read_bytes()
  return _read_text(data) if data.startswith(TEXT_MAGIC) else _read_binary(data)


def write(cfg: CfgFile, binary: Optional[bool] = None) -> bytes:
  """Write in the form the file was read from, unless `binary` says otherwise."""
  if binary is None or binary == cfg.binary:
    return write_binary(cfg) if cfg.binary else write_text(cfg)
  # the stored length offset belongs to the other form
  other = dataclasses.replace(cfg, footer=dataclasses.replace(cfg.footer, length_offset=None))
  return write_binary(other) if binary else write_text(other)
