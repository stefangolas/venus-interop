"""Steps in Venus method code (.hsl, .sub): the markers the Method Editor writes around each step.

  // {{{ 5 "main" "Begin"                       a section begins (a sub-method, the include block)
  // {{{ 12 1 0 "<guid>" "{<step type>}"        a step: row, column, 0, its GUID, its type
  // {{ 13 1 0 "<guid>" "{<step type>}"         one part of a compound step (If/Else/End, loop begin/end),
                                                 parts share the GUID
  // }} ""                                       end of the marker's code

A step switched off in the Method Editor stays in the code, wrapped in

  /* {{ 1 "" "0" */ if(0){  /* }} "" */           the disabled steps follow ...
  /* {{ 1 "" "1" */ } /* }} "" */                 ... up to here

so it never runs. `Step.disabled` marks the steps inside.

The .med holds the steps' parameters and is authoritative; the code here is what Venus generated from
it. Reading is enough to list, find and diff steps; writing steps is deliberately not supported.
"""
from __future__ import annotations

import dataclasses
import re
from typing import Optional

# Step type CLSIDs. "inferred" ones are named from the code Venus generates for them.
STEP_TYPES = {
  "{C1F3C015-47B3-4514-9407-AC2E65043419}": "library function call",
  "{7C4EF7A7-39BE-406A-897F-71F3A35B4093}": "sub-method call",
  "{B31F3531-5D80-11D4-A5EB-0050DA737D89}": "If / Else",
  "{B31F3532-5D80-11D4-A5EB-0050DA737D89}": "Loop",
  "{B31F3533-5D80-11D4-A5EB-0050DA737D89}": "Break (inferred)",
  "{B31F3543-5D80-11D4-A5EB-0050DA737D89}": "Assignment (inferred)",
  "{B31F3544-5D80-11D4-A5EB-0050DA737D89}": "Assignment with calculation",
  "{586C3429-F931-405F-9938-928E22C90BFA}": "Comment / blank",
  "{3293659E-F71E-472F-AFB4-6A674E32B114}": "Error handling (inferred: onerror goto)",
  "{9EC997CD-FD3B-4280-811B-49E99DCF062C}": "Return (inferred)",
}

_STEP = re.compile(r'^// \{\{(\{?) (\d+) (\d+) (\d+) "([^"]*)" "((?:[A-Za-z_][A-Za-z0-9_]*:)?\{[^"]*\})"\s*$')
_SECTION = re.compile(r'^// \{\{\{ (\d+) "([^"]*)" "([^"]*)"\s*$')
_END = re.compile(r'^// \}\} ""\s*$')
_OFF = re.compile(r'^/\* \{\{ \d+ "" "0" \*/\s*if\s*\(\s*0\s*\)\s*\{')
_ON = re.compile(r'^/\* \{\{ \d+ "" "1" \*/\s*\}')


@dataclasses.dataclass
class Step:
  row: int
  column: int
  guid: str
  clsid: str
  part: bool  # one part of a compound step ("// {{" rather than "// {{{")
  section: Optional[str]  # the sub-method it is in
  line: int  # 1-based line of its marker
  code: str
  disabled: bool = False  # switched off in the Method Editor: inside `if(0){ ... }`, never runs

  @property
  def device(self) -> Optional[str]:
    """The device variable for a device step ("STAR"), None for other steps."""
    return self.clsid.split(":", 1)[0] if ":" in self.clsid else None

  @property
  def type(self) -> str:
    if self.device is not None:
      return f"device step ({self.device})"
    return STEP_TYPES.get(self.clsid.upper(), f"unknown {self.clsid}")


def steps(text: str) -> list[Step]:
  out: list[Step] = []
  section: Optional[str] = None
  current: Optional[Step] = None
  buf: list[str] = []
  off = 0  # depth of disabled-step wrappers
  for n, line in enumerate(text.splitlines(), 1):
    if current is not None:
      if _END.match(line):
        current.code = "\n".join(buf)
        out.append(current)
        current, buf = None, []
      else:
        buf.append(line)
      continue
    m = _SECTION.match(line)
    if m:
      section = m.group(2) if m.group(3) != "End" else None
      continue
    if _OFF.match(line):
      off += 1
      continue
    if off and _ON.match(line):
      off -= 1
      continue
    m = _STEP.match(line)
    if m:
      current = Step(int(m.group(2)), int(m.group(3)), m.group(5), m.group(6), m.group(1) == "", section, n, "",
                     off > 0)
  return out


def summary(text: str) -> dict[str, int]:
  """How many steps of each type (compound steps counted once)."""
  seen, counts = set(), {}
  for s in steps(text):
    if s.guid in seen:
      continue
    seen.add(s.guid)
    counts[s.type] = counts.get(s.type, 0) + 1
  return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
