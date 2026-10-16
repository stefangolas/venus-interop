"""The footer of Venus's text files: .hsl, .hs_, .hsi, .sub, and text-form HxCfg files.

  ... // $$author=NAME$$valid=0$$time=2025-10-16 10:24$$checksum=9da6c249$$length=089$$

checksum = CRC32 of the file from its first byte up to and including "$$checksum="
length   = the footer line's length plus an offset (0 for .hsl/.hs_/text .med/.lay, 2 for .hsi/.sub and
           binary HxCfg files) that rewriting keeps as found
"""
from __future__ import annotations

import dataclasses
import datetime
import pathlib
import re
import zlib
from typing import Optional, Union

FOOTER = re.compile(rb"\$\$author=(.*?)\$\$valid=(\d)\$\$time=(.*?)\$\$checksum=([0-9a-f]{8})\$\$length=(\d{3})\$\$")


@dataclasses.dataclass
class Footer:
  author: str
  valid: int
  time: str
  checksum: str
  length: int
  offset: int  # length minus the footer line's own length
  prefix: bytes  # what precedes "$$author" on the footer line (e.g. b"// " or b"* ")


def _split(data: bytes) -> tuple[bytes, Footer, int]:
  start = data.rfind(b"$$author=")
  m = FOOTER.match(data, start) if start >= 0 else None
  if m is None:
    raise ValueError("no Venus footer")
  line_start = data.rfind(b"\n", 0, start) + 1
  line = data[line_start:m.end()]
  f = Footer(m.group(1).decode("latin-1"), int(m.group(2)), m.group(3).decode("latin-1"), m.group(4).decode(),
             int(m.group(5)), int(m.group(5)) - len(line), data[line_start:start])
  return data[:line_start], f, m.end()


def _line(body: bytes, f: Footer) -> bytes:
  head = (f.prefix + b"$$author=" + f.author.encode("latin-1") + b"$$valid=" + str(f.valid).encode()
          + b"$$time=" + f.time.encode("latin-1") + b"$$checksum=")
  line = head + b"%08x$$length=" % (zlib.crc32(body + head) & 0xFFFFFFFF)
  return line + b"%03d$$" % (len(line) + len(b"000$$") + f.offset)


def read(data: bytes) -> Footer:
  return _split(data)[1]


def ok(data: bytes) -> bool:
  body, f, end = _split(data)
  return body + _line(body, f) == data[:end]


def rewrite(data: bytes, author: Optional[str] = None, time: Optional[str] = None, valid: Optional[int] = None) -> bytes:
  """The file with a fresh footer (after editing its body). Bytes after the footer are kept."""
  body, f, end = _split(data)
  f = dataclasses.replace(f, author=author if author is not None else f.author,
                          time=time or datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                          valid=f.valid if valid is None else valid)
  return body + _line(body, f) + data[end:]


def check_file(path: Union[str, pathlib.Path]) -> bool:
  return ok(pathlib.Path(path).read_bytes())
