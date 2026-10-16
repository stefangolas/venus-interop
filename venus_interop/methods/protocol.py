"""Protocol traces: expand a method's main into a readable, faithful walk.

A decompiler front-end plus a markdown back-end. What it does:

- walks the `main` section of a method in step order (markers via `hsl`);
- renders device steps with their HxPars settings (`stp_pars`), volumes kept
  symbolic — `<p_vol>` — because that is what the method computes;
- inlines calls into the lab's libraries (functions via `hsl_code`), binding
  the call-site arguments;
- keeps if/else/loop structure, assignments and TraceComment texts.

What it deliberately does not do: evaluate expressions, resolve sequence
positions, translate error recoveries, or write any file. It renders what the
method says, in order, with the settings the .stp records hold.
"""
from __future__ import annotations

import dataclasses
import re
from typing import Iterable, Optional

from venus_interop.methods import hsl, hsl_code, stp_pars

_DEVICE = re.compile(r'\b([A-Za-z_]\w*)\._([0-9A-Fa-f_]{36})\("([^"]+)"\)')
_CALL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)::([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_BARE = re.compile(r"^\s*(?:([A-Za-z_]\w*)::)?([A-Za-z_]\w*)\s*\(")
_TRACE = re.compile(r"\bMECC::TraceComment\s*\(\s*(.*)\s*\)\s*;", re.S)


def namespace_of(stem: str) -> str:
  """The HSL namespace a library file is called through."""
  return re.sub(r"[^A-Za-z0-9]", "_", stem).upper()


# Vocabulary for post-processing traces: which namespace plays which part.
# The trace itself captures everything inline; these tables never filter.
# Measured on the 10 NIST LMSF methods and their 5 libraries; extend as
# corpora grow.
ROBOT = {
  "GSF_IMS_SHARED_SUBMETHODS", "PLATEANDLIDMOVEMENT", "COMMON96HEADSUBMETHODS",
  "TIP_HANDLING_WITH_96_HEAD", "STAR_OEM_TOOLKIT", "HSLML_STAR",
}
EQUIPMENT = {
  "MPE_LIBRARY", "HSLHAMHEATERSHAKER",  # MPE2, Heater Shaker STAR
  "NGSSTARPREP", "NGSSTARPROCESSES",    # ODTC and process wrappers (Avenio)
}
DATA = {
  "LMSF_UTILITIES",
  "DICTIONARY", "STRING", "FILE", "DIRECTORY", "TIPCOUNT",
  "HSLJSONLIB", "HSLHTTP", "HSLSEQLIB", "HSLSTRLIB", "HSLTRCLIB", "HSLTIMLIB",
  "HSLMETEDLIB", "HSLMECCLIB", "HSLErrLib".upper(),
}
CONFIG = {"PTL"}
UI = {"VECTORCUSTOMDIALOGS"}


def role_of(ns: str) -> str:
  """robot / equipment / data / config / ui, or "" when unclassified."""
  ns = ns.upper()
  for role, names in (("robot", ROBOT), ("equipment", EQUIPMENT), ("data", DATA),
                      ("config", CONFIG), ("ui", UI)):
    if ns in names:
      return role
  return ""


def split_args(text: str) -> list[str]:
  """The arguments of a call, split on top-level commas."""
  out, depth, cur = [], 0, []
  for c in text:
    if c in "([":
      depth += 1
    elif c in ")]":
      depth -= 1
    if c == "," and depth == 0:
      out.append("".join(cur).strip())
      cur = []
    else:
      cur.append(c)
  if cur:
    out.append("".join(cur).strip())
  return [a for a in out if a]


@dataclasses.dataclass
class Library:
  name: str  # file stem
  namespace: str
  functions: dict[str, hsl_code.Function]  # lower-case name -> definition

  def find(self, name: str) -> Optional[hsl_code.Function]:
    f = self.functions.get(name.lower())
    return f if f is not None and not f.prototype_only else None


def load_library(text: str, name: str) -> Library:
  fns = {}
  for f in hsl_code.functions(text):
    fns.setdefault(f.name.lower(), f)
  return Library(name, namespace_of(name), fns)


def load_stps(paths: Iterable) -> dict[str, stp_pars.Record]:
  """All HxPars records from .stp files, keyed by step GUID."""
  from venus_interop.files import hxcfg
  out: dict[str, stp_pars.Record] = {}
  for p in paths:
    try:
      cfg = hxcfg.read(p.read_bytes())
    except Exception:
      continue
    for s in cfg.sections:
      if s.type == "HxPars":
        out[s.name] = stp_pars.record(s)
  return out


def render_settings(rec: stp_pars.Record) -> list[str]:
  """Readable settings lines; identical consecutive values collapse as xN."""
  merged: list[list] = []
  for path, name, val in rec.readable():
    if name.startswith("channel constant") or name in ("NbrOfErrors",):
      continue
    if merged and merged[-1][:3] == [path, name, val]:
      merged[-1][3] += 1
      continue
    merged.append([path, name, val, 1])
  lines = []
  for path, name, val, n in merged:
    where = "" if path in ("", "/channels") else f" [{path}]"
    times = f" x{n}" if n > 1 else ""
    lines.append(f"{name} = {val}{times}{where}")
  return lines


class Tracer:
  """Expands method sections into markdown trace lines."""

  def __init__(self, libraries: list[Library], stps: dict[str, stp_pars.Record], max_depth: int = 4):
    self.libs = libraries
    self.stps = stps
    self.max_depth = max_depth
    self.sections: dict[str, list[hsl.Step]] = {}

  def _find(self, ns: str, name: str) -> Optional[hsl_code.Function]:
    for lib in self.libs:
      if lib.namespace == ns:
        return lib.find(name)
    return None

  def section(self, text: str, name: str) -> list[str]:
    if not self.sections:
      for s in hsl.steps(text):
        if s.section:
          self.sections.setdefault(s.section, []).append(s)
    out: list[str] = []
    self._walk(self.sections.get(name, []), out, depth=0, seen=())
    return out

  def _walk(self, steps: list[hsl.Step], out: list[str], depth: int, seen: tuple):
    indent = "  " * depth
    for s in steps:
      if s.device:
        self._device(s, out, indent)
        continue
      code = s.code.strip()
      if not code:
        continue
      m = _TRACE.search(code)
      if m:
        out.append(f"{indent}### {m.group(1).strip('\"')}")
        continue
      cm = _CALL.search(code)
      if cm is None:
        bm = _BARE.match(code)  # a bare call: the method's own sub-method
        if bm:
          cm = bm
      if cm and depth < self.max_depth:
        fn = self._find(cm.group(1), cm.group(2))
        if fn is not None and fn.name not in seen and not fn.name.startswith("_"):
          args = split_args(self._call_text(code, cm.end() - 1))
          names = [a.name for a in fn.args]
          bound = ", ".join(f"{names[i]} = {args[i]}" for i in range(min(len(args), len(names))))
          tag = role_of(cm.group(1))
          out.append(f"{indent}> [{tag or 'lab'}] {fn.name}({bound})")
          body_steps = hsl.steps(fn.body)
          if body_steps:
            self._walk(body_steps, out, depth + 1, seen + (fn.name,))
          continue
        if cm.group(2) in self.sections and cm.group(2) not in seen:
          # a call to one of the method's own sub-methods
          args = split_args(self._call_text(code, cm.end() - 1))
          out.append(f"{indent}> [method] {cm.group(2)}({', '.join(args)})")
          self._walk(self.sections[cm.group(2)], out, depth + 1, seen + (cm.group(2),))
          continue
      for line in code.splitlines():
        out.append(self._tagged(line, indent))

  @staticmethod
  def _tagged(line: str, indent: str) -> str:
    """A raw code line; calls into classified libraries get a role comment."""
    out = Tracer._indented(line, indent)
    if not out or out.lstrip().startswith("#"):
      return out
    m = _CALL.search(out)
    if m:
      role = role_of(m.group(1))
      if role:
        out = out + f"  # [{role}]"
    return out

  def _call_text(self, code: str, open_paren: int) -> str:
    depth, start = 0, open_paren
    for i in range(open_paren, len(code)):
      if code[i] == "(":
        depth += 1
      elif code[i] == ")":
        depth -= 1
        if depth == 0:
          return code[start + 1 : i]
    return code[start + 1 :]

  @staticmethod
  def _indented(line: str, indent: str) -> str:
    stripped = line.strip()
    if not stripped:
      return ""
    if stripped.startswith("}"):
      return indent[:-2] + stripped if len(indent) >= 2 else stripped
    return indent + stripped

  def _device(self, s: hsl.Step, out: list[str], indent: str):
    m = _DEVICE.search(s.code)
    var, guid = (m.group(1), m.group(3)) if m else ("?", "?")
    line_end = s.code.find("\n", m.start()) if m else -1
    call_line = s.code[m.start() : line_end if line_end >= 0 else None]
    comment = call_line.rsplit("//", 1)[-1].strip() if "//" in call_line else ""
    rec = self.stps.get(guid)
    out.append(f"{indent}- **{comment or s.type}** ({var})")
    if rec is None:
      out.append(f"{indent}  - settings: .stp record not found for {guid}")
      return
    for line in render_settings(rec):
      out.append(f"{indent}  - {line}")


def trace_method(hsl_text: str, libraries: list[Library], stp_paths: Iterable,
                 sub_text: str = "", sections: tuple[str, ...] = ("main", "GetParams")) -> str:
  """The trace of a method's sections as markdown."""
  tr = Tracer(libraries, load_stps(stp_paths))
  text = hsl_text + ("\n" + sub_text if sub_text else "")
  out = ["```", ""]
  for name in sections:
    steps = [s for s in hsl.steps(text) if s.section == name]
    if not steps:
      continue
    out.append(f"## section {name}")
    out.append("")
    out.extend(tr.section(text, name))
    out.append("")
  out.append("```")
  return "\n".join(out)
