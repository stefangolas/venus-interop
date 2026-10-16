"""Function bodies in Venus method and library code (.hsl, .sub, .hsi).

Venus writes function prototypes in one block, then each definition as a section:

  function tip_pickup( sequence & tips, ... ) void ;      a prototype (ends in ";")
  // {{{ 5 "tip_pickup" "Begin"                           the definition's section marker
  function tip_pickup( sequence & tips, ... ) void {      the definition
  // {{ ... }} steps, whose code sits inside the body
  }                                                       matching brace

Reading is enough to inventory, inline and walk functions; writing is deliberately
not supported. Brace matching skips strings and comments, so the step markers do
not confuse it.
"""
from __future__ import annotations

import dataclasses
import re
from typing import Optional

_FUNC = re.compile(r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^;{]*)\)\s*([A-Za-z_][A-Za-z0-9_& ]*?)?\s*([;{])")


@dataclasses.dataclass
class Arg:
  type: str  # e.g. "sequence", "variable", "device"; "&" and "[]" kept in type
  name: str
  default: Optional[str] = None  # text of "= value" if the prototype gives one


@dataclasses.dataclass
class Function:
  name: str
  args: list[Arg]
  ret: str  # return type as written, "" if none
  line: int  # 1-based line of the definition line
  body: str  # from the definition line to the matching closing brace, inclusive
  prototype_only: bool = False  # a prototype (";"), not a definition

  @property
  def signature(self) -> str:
    a = ", ".join(f"{x.type} {x.name}" + (f" = {x.default}" if x.default is not None else "") for x in self.args)
    return f"function {self.name}({a})" + (f" {self.ret}" if self.ret else "")


def _args(text: str) -> list[Arg]:
  text = text.strip()
  if not text:
    return []
  out = []
  for part in text.split(","):
    part = part.strip()
    if not part:
      continue
    default = None
    if "=" in part:
      part, _, default = part.partition("=")
      default = default.strip()
    bits = part.replace("&", " & ").split()
    if not bits:
      continue
    name = bits[-1]
    if name.endswith("[]"):
      name = name[:-2]
      bits[-1] = name
      bits.append("[]")
    out.append(Arg(" ".join(bits[:-1]) + ("[]" if bits[-1] == "[]" else ""), name, default))
  return out


def _body_from(lines: list[str], start: int, open_line: str) -> tuple[int, str]:
  """Brace-match from the definition line (0-based index) to its closing brace."""
  depth, end = 0, start
  for i in range(start, len(lines)):
    line, buf, j = lines[i], [], 0
    while j < len(line):
      c = line[j]
      if c == '"':  # string: skip escapes
        j += 1
        while j < len(line) and line[j] != '"':
          j += 2 if line[j] == "\\" else 1
      elif c == "/" and j + 1 < len(line) and line[j + 1] == "/":
        break  # comment to end of line
      elif c == "{":
        depth += 1
      elif c == "}":
        depth -= 1
        if depth == 0:
          end = i
          buf.append(line[: j + 1])
          return end, "\n".join(lines[start : end + 1])
      j += 1
    if depth > 0 or i == start:
      buf.append(line)
  return len(lines) - 1, "\n".join(lines[start:])


def functions(text: str) -> list[Function]:
  lines = text.splitlines()
  out, index = [], {}
  for n, line in enumerate(lines):
    m = _FUNC.match(line)
    if not m:
      continue
    if m.group(4) == ";":  # a prototype: kept only until a definition replaces it
      f = Function(m.group(1), _args(m.group(2)), (m.group(3) or "").strip(), n + 1, line, True)
      if f.name not in index:
        index[f.name] = len(out)
        out.append(f)
      continue
    _, body = _body_from(lines, n, line)
    f = Function(m.group(1), _args(m.group(2)), (m.group(3) or "").strip(), n + 1, body)
    if f.name in index and not out[index[f.name]].prototype_only:
      continue
    if f.name in index:
      out[index[f.name]] = f
    else:
      index[f.name] = len(out)
      out.append(f)
  return out
