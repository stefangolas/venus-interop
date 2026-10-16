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
  "DICTIONARY", "STRING", "FILE", "DIRECTORY", "TIPCOUNT", "FILEDIRECTORYLIB",
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


@dataclasses.dataclass
class Line:
  """One trace line: the IR between the walk and the renderers."""
  depth: int
  kind: str  # heading | call | device | setting | code
  role: str  # robot / equipment / data / config / ui / lab / method / ""
  text: str


# Device settings the condensed view keeps; the full trace keeps everything.
_KEEP_SETTING = re.compile(
  r"volume|mix |LiquidName|LLD|submerge|fluid height|Sequence|ChannelPattern|TipType"
  r"|DispenseMode|mode|grip|speed|press|acceleration|lift up|retract|height"
  r"|TouchOff|LiquidFollowing|detect")
_NOISE = re.compile(r"^\s*(?:MECC::)?Trc?Trace\s*\(")
_GUARD = re.compile(r"MECC::RaiseRuntimeErrorEx\s*\(")
_GETITEM = re.compile(r"HSLExtensions::Dictionary::GetItem\s*\(")
_TRANSLATE = re.compile(r"Translate\(\"([^\"]*)\"\)")


def _params_form(line: str) -> str:
  """Display form: Dictionary::GetItem(d, k) -> params[k]; Translate unwrapped."""
  while True:
    m = _GETITEM.search(line)
    if not m:
      break
    args = split_args(line[m.end() - 1 : _call_close(line, m.end() - 1)])
    key = _TRANSLATE.sub(r"\1", args[-1]).strip() if args else "?"
    line = line[: m.start()] + f"params[{key}]" + line[_call_close(line, m.end() - 1) + 1 :]
  return line


def _heading_text(arg: str) -> str:
  """A TraceComment argument: unwrap Translate, flatten its newlines."""
  t = arg.strip().strip('"')
  if t.startswith("Translate(") and t.endswith(")"):
    t = t[len("Translate(") : -1].strip().strip('"')
  return " ".join(t.split("\\n")).strip()


def _call_close(text: str, open_paren: int) -> int:
  depth = 0
  for i in range(open_paren, len(text)):
    if text[i] == "(":
      depth += 1
    elif text[i] == ")":
      depth -= 1
      if depth == 0:
        return i
  return len(text) - 1


def condense(lines: list[Line]) -> list[Line]:
  """A condensed view: data/config/ui subtrees collapse to their header note,
  trace-file plumbing and uninformative settings drop, parameter reads render
  as params[key]. Nothing is lost that the full trace does not hold."""
  out, skip = [], None
  for ln in lines:
    if skip is not None:
      if ln.depth > skip:
        continue
      skip = None
    if ln.kind == "call" and ln.role in ("data", "config", "ui"):
      out.append(ln)
      skip = ln.depth
      continue
    if ln.kind == "code":
      if _NOISE.search(ln.text) or _GUARD.search(ln.text):
        continue
      text = _params_form(ln.text)
      # pure data-plumbing calls (no assignment) drop; assignments stay
      core = text.split("=", 1)
      if len(core) == 1 and ("  # [data]" in text or "  # [ui]" in text or "  # [config]" in text):
        continue
      if len(core) == 2 and ("  # [ui]" in text or "  # [config]" in text):
        continue
      out.append(Line(ln.depth, ln.kind, ln.role, text))
      continue
    if ln.kind == "setting" and not _KEEP_SETTING.search(ln.text):
      continue
    out.append(ln)
  return out


def render(lines: list[Line], condensed: bool = False) -> list[str]:
  if condensed:
    lines = condense(lines)
  out = []
  for ln in lines:
    indent = "  " * ln.depth
    if ln.kind == "call":
      out.append(f"{indent}> [{ln.role}] {ln.text}")
    elif ln.kind == "device":
      out.append(f"{indent}- **{ln.text}**")
    elif ln.kind == "setting":
      out.append(f"{indent}  - {ln.text}")
    else:
      out.append(indent + ln.text)
  return out


class Tracer:
  """Expands method sections into trace lines (the IR)."""

  def __init__(self, libraries: list[Library], stps: dict[str, stp_pars.Record], max_depth: int = 4,
               expand_limit: int = 3):
    self.libs = libraries
    self.stps = stps
    self.max_depth = max_depth
    self.expand_limit = expand_limit
    self.expanded: dict[str, int] = {}
    self.sections: dict[str, list[hsl.Step]] = {}

  def _find(self, ns: str, name: str) -> Optional[hsl_code.Function]:
    for lib in self.libs:
      if lib.namespace == ns:
        return lib.find(name)
    return None

  def _lib_of(self, ns: str) -> Optional[Library]:
    for lib in self.libs:
      if lib.namespace == ns:
        return lib
    return None

  def section(self, text: str, name: str) -> list[Line]:
    if not self.sections:
      for s in hsl.steps(text):
        if s.section:
          self.sections.setdefault(s.section, []).append(s)
    out: list[Line] = []
    self._walk(self.sections.get(name, []), out, depth=0, seen=())
    return out

  def _walk(self, steps: list[hsl.Step], out: list[Line], depth: int, seen: tuple, lib: Optional[Library] = None):
    for s in steps:
      if s.device:
        self._device(s, out, depth)
        continue
      code = s.code.strip()
      if not code:
        continue
      m = _TRACE.search(code)
      if m:
        out.append(Line(depth, "heading", "", f"### {_heading_text(m.group(1))}"))
        continue
      cm = _CALL.search(code)
      if cm is None:
        cm = _BARE.match(code)  # a bare call: the method's own sub-method or a sibling function
      if cm and depth < self.max_depth:
        fn = self._find(cm.group(1), cm.group(2))
        ctx = self._lib_of(cm.group(1)) if cm.group(1) else lib
        if fn is None and ctx is not None and not cm.group(1):
          fn = ctx.find(cm.group(2))  # a bare call inside the same library
        if fn is not None and fn.name not in seen and not fn.name.startswith("_"):
          args = split_args(self._call_text(code, cm.end() - 1))
          names = [a.name for a in fn.args]
          bound = ", ".join(f"{names[i]} = {args[i]}" for i in range(min(len(args), len(names))))
          ns = cm.group(1) or (ctx.namespace if ctx else "")
          out.append(Line(depth, "call", role_of(ns) or "lab", f"{fn.name}({bound})"))
          body_steps = hsl.steps(fn.body)
          n = self.expanded.get(fn.name, 0)
          self.expanded[fn.name] = n + 1
          if body_steps and n < self.expand_limit:
            # identical structure at every call site (settings are per-GUID):
            # expand the first sites fully, elide the rest
            self._walk(body_steps, out, depth + 1, seen + (fn.name,), ctx or lib)
          elif body_steps:
            out.append(Line(depth + 1, "code", "",
                            f"... body elided; structure as the earlier expansions of {fn.name}"))
          continue
        if cm.group(2) in self.sections and cm.group(2) not in seen:
          # a call to one of the method's own sub-methods
          args = split_args(self._call_text(code, cm.end() - 1))
          out.append(Line(depth, "call", "method", f"{cm.group(2)}({', '.join(args)})"))
          self._walk(self.sections[cm.group(2)], out, depth + 1, seen + (cm.group(2),))
          continue
      for line in code.splitlines():
        stripped = line.strip()
        if not stripped:
          continue
        text, d = self._tagged(stripped), depth
        if stripped.startswith("}"):
          d = max(depth - 1, 0)
        out.append(Line(d, "code", "", text))

  @staticmethod
  def _tagged(line: str) -> str:
    """A raw code line; calls into classified libraries get a role comment."""
    if line.lstrip().startswith("#"):
      return line
    m = _CALL.search(line)
    if m:
      role = role_of(m.group(1))
      if role:
        line = line + f"  # [{role}]"
    return line

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

  def _device(self, s: hsl.Step, out: list[Line], depth: int):
    m = _DEVICE.search(s.code)
    var, guid = (m.group(1), m.group(3)) if m else ("?", "?")
    line_end = s.code.find("\n", m.start()) if m else -1
    call_line = s.code[m.start() : line_end if line_end >= 0 else None]
    comment = call_line.rsplit("//", 1)[-1].strip() if "//" in call_line else ""
    role = "robot" if var.upper() in ("STAR", "ML_STAR") else "equipment"
    out.append(Line(depth, "device", role, f"{comment or s.type} ({var})"))
    rec = self.stps.get(guid)
    if rec is None:
      out.append(Line(depth, "setting", "", f"settings: .stp record not found for {guid}"))
      return
    for line in render_settings(rec):
      out.append(Line(depth, "setting", "", line))


def method_lines(hsl_text: str, libraries: list[Library], stps: dict[str, stp_pars.Record],
                 sub_text: str = "", sections: tuple[str, ...] = ("main", "GetParams"),
                 ) -> list[tuple[str, list[Line]]]:
  """The trace IR of a method's sections."""
  tr = Tracer(libraries, stps)
  text = hsl_text + ("\n" + sub_text if sub_text else "")
  out = []
  for name in sections:
    if not [s for s in hsl.steps(text) if s.section == name]:
      continue
    out.append((name, tr.section(text, name)))
  return out


def trace_method(hsl_text: str, libraries: list[Library], stp_paths: Iterable,
                 sub_text: str = "", sections: tuple[str, ...] = ("main", "GetParams")) -> str:
  """The full trace of a method's sections as markdown."""
  stps = load_stps(stp_paths)
  out = ["```", ""]
  for name, lines in method_lines(hsl_text, libraries, stps, sub_text, sections):
    out.append(f"## section {name}")
    out.append("")
    out.extend(render(lines))
    out.append("")
  out.append("```")
  return "\n".join(out)
