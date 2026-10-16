"""Protocol traces: expand a method's main into a readable, faithful walk.

A decompiler front-end plus a markdown back-end. What it does:

- walks the `main` section of a method in step order (markers via `hsl`),
  then any section the method registers as its abort handler;
- renders device steps with their HxPars settings (`stp_pars`), volumes kept
  symbolic — `<p_vol>` — because that is what the method computes, and their
  error policies (per error: the recoveries offered, the default, repeats);
- folds Pipetting Template Library smart steps (`PTL::Pipette3` with its
  `SetPipettingState` preamble) into one step with named settings;
- inlines calls into the lab's libraries (functions via `hsl_code`), binding
  the call-site arguments; the libraries are the method's own `#include`s,
  followed transitively (`load_method`);
- keeps if/else/loop structure, assignments and TraceComment texts.

What it deliberately does not do: evaluate expressions, resolve sequence
positions, or write any file. It renders what the method says, in order, with
the settings the .stp records hold.
"""
from __future__ import annotations

import dataclasses
import pathlib
import re
from typing import Iterable, Optional

from venus_interop.methods import hsl, hsl_code, stp_pars

_DEVICE = re.compile(r'\b([A-Za-z_]\w*)\._([0-9A-Fa-f_]{36})\("([^"]+)"\)')
_CALL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)::([A-Za-z_][A-Za-z0-9_]*)\s*\(")
# A step whose code is one call statement, optionally assigned: `x = NS::f(...);`
_STMT = re.compile(r"^(?:(?P<lhs>[A-Za-z_][\w.]*(?:\[[^\]]*\])?)\s*=\s*)?"
                   r"(?:(?P<ns>[A-Za-z_]\w*)::)?(?P<fn>[A-Za-z_]\w*)\s*\(")
_TRACE = re.compile(r"\bMECC::TraceComment\s*\(\s*(.*)\s*\)\s*;", re.S)
_ABORT = re.compile(r'RegisterAbortHandler\s*\(\s*"([^"]+)"\s*\)')


def namespace_of(stem: str) -> str:
  """The HSL namespace a library file is called through, by Venus's naming."""
  return re.sub(r"[^A-Za-z0-9]", "_", stem).upper()


# Vocabulary for post-processing traces: which namespace plays which part.
# The trace itself captures everything inline; these tables never filter.
# Measured on the 10 NIST LMSF methods and their libraries; extend as
# corpora grow.
ROBOT = {
  "GSF_IMS_SHARED_SUBMETHODS", "PLATEANDLIDMOVEMENT", "COMMON96HEADSUBMETHODS",
  "TIP_HANDLING_WITH_96_HEAD", "STAR_OEM_TOOLKIT", "HSLML_STAR",
  "TIPHANDLING", "MOVE96HEADANDARM", "WASTECHUTE", "DPXPRECUTTEDTIPSLIB",
}
EQUIPMENT = {
  "MPE_LIBRARY", "HSLMPELIB", "HSLHAMHEATERSHAKER",  # MPE2, Heater Shaker STAR
  "NGSSTARPREP", "NGSSTARPROCESSES",    # ODTC and process wrappers (Avenio)
  "EASYPICKII_STEPS", "EASYPICKII",     # colony picker camera
  "LABWAREHANDLING",                    # labware requests to the scheduler (Overlord)
}
DATA = {
  "LMSF_UTILITIES",
  "DICTIONARY", "STRING", "FILE", "DIRECTORY", "TIPCOUNT", "FILEDIRECTORYLIB",
  "HSLJSONLIB", "HSLHTTP", "HSLSEQLIB", "HSLSTRLIB", "HSLTRCLIB", "HSLTIMLIB",
  "HSLMETEDLIB", "HSLMECCLIB", "HSLErrLib".upper(), "IF_AND_IF_OR",
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
  path: Optional[pathlib.Path] = None

  def find(self, name: str) -> Optional[hsl_code.Function]:
    f = self.functions.get(name.lower())
    return f if f is not None and not f.prototype_only else None


_NAMESPACE = re.compile(r"^\s*namespace\s+([A-Za-z_]\w*)\s*\{", re.M)


def load_library(text: str, name: str, path: Optional[pathlib.Path] = None) -> Library:
  """A library's functions, under the namespace the file declares (its first
  `namespace X {` other than `_Method`), else the one Venus derives from the name."""
  fns = {}
  for f in hsl_code.functions(text):
    fns.setdefault(f.name.lower(), f)
  declared = [n for n in _NAMESPACE.findall(text) if n != "_Method"]
  return Library(name, declared[0].upper() if declared else namespace_of(name), fns, path)


# --- the files a method pulls in -------------------------------------------

_INCLUDE = re.compile(r'#include\s+"([^"]+)"')
_SELF_INCLUDE = re.compile(r'#include\s+__filename__\s+"(\.\w+)"')
_COMMENT = re.compile(r'"(?:\\.|[^"\\\n])*"|/\*.*?\*/|//[^\n]*', re.S)


def _strip_comments(text: str) -> str:
  """HSL text without // and /* */ comments (strings kept), so commented-out
  or changelog `#include` lines are not followed."""
  return _COMMENT.sub(lambda m: m.group(0) if m.group(0).startswith('"') else "", text)


def _read(p: pathlib.Path) -> str:
  return p.read_text(encoding="latin-1")


def resolve_include(name: str, here: pathlib.Path, roots: Iterable[pathlib.Path]) -> Optional[pathlib.Path]:
  """Where `#include "name"` points: beside the including file, then under each
  root (Venus searches its Library and Methods folders)."""
  rel = name.replace("\\", "/")
  for base in (here, *roots):
    p = base / rel
    if p.is_file():
      return p
  return None


def include_closure(path: pathlib.Path, roots: Iterable[pathlib.Path]
                    ) -> tuple[list[pathlib.Path], list[str]]:
  """Every file `path` includes, transitively, in first-include order, plus the
  include names that resolve nowhere. `#include __filename__ ".hsi"` (how a
  `.hs_` header pulls in its body, and a method its `.sub`) is followed too."""
  roots = list(roots)
  order: list[pathlib.Path] = []
  seen: set[str] = set()
  missing: list[str] = []

  def visit(p: pathlib.Path):
    key = str(p.resolve()).lower()
    if key in seen:
      return
    seen.add(key)
    order.append(p)
    text = _strip_comments(_read(p))
    for suffix in _SELF_INCLUDE.findall(text):
      q = p.with_suffix(suffix)
      if q.is_file():
        visit(q)
    for inc in _INCLUDE.findall(text):
      q = resolve_include(inc, p.parent, roots)
      if q is None:
        if inc not in missing:
          missing.append(inc)
      else:
        visit(q)

  visit(path)
  return order, missing


@dataclasses.dataclass
class MethodFiles:
  hsl_text: str
  sub_text: str
  libraries: list[Library]
  stps: dict[str, stp_pars.Record]
  files: list[pathlib.Path]  # the include closure, method first
  missing: list[str]  # include names found nowhere under the roots


def load_method(hsl_path: pathlib.Path, roots: Iterable[pathlib.Path]) -> MethodFiles:
  """A method with exactly the libraries it includes and the .stp records that
  belong to them (each file's settings are in the .stp beside it, same stem)."""
  hsl_path = pathlib.Path(hsl_path)
  files, missing = include_closure(hsl_path, roots)
  own = {hsl_path.with_suffix(s).resolve() for s in (".hsl", ".sub", ".med", ".res")}
  libs, stp_paths = [], [hsl_path.with_suffix(".stp")]
  for p in files:
    if p.resolve() in own:
      continue
    stp_paths.append(p.with_suffix(".stp"))
    if p.suffix.lower() == ".hs_" and p.with_suffix(".hsi").is_file():
      continue  # a header of stub bodies; its .hsi holds the definitions
    libs.append(load_library(_read(p), p.stem, p))
  sub = hsl_path.with_suffix(".sub")
  seen_stp, uniq = set(), []
  for p in stp_paths:
    if p.is_file() and str(p.resolve()).lower() not in seen_stp:
      seen_stp.add(str(p.resolve()).lower())
      uniq.append(p)
  return MethodFiles(_read(hsl_path), _read(sub) if sub.is_file() else "", libs,
                     load_stps(uniq), files, missing)


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


# --- rendering settings ------------------------------------------------------

def render_settings(rec: stp_pars.Record) -> list[str]:
  """Readable settings: per-channel blocks collapse when identical."""
  lines: list[str] = []
  for path, name, val in rec.readable():
    if re.match(r"^\d+$", name):  # (Variables) opcode pairs
      continue
    if name.startswith("channel constant") or name in ("NbrOfErrors",):
      continue
    if path == "/channels":
      continue  # the per-channel block renders below, collapsed
    if path.startswith("/Variables") or path.startswith("/Errors"):
      continue  # error policies render separately (render_errors)
    lines.append(f"{name} = {val} [{path}]" if path else f"{name} = {val}")
  # per-channel block: collapse identical channels
  chan = [v for k, v in rec.tree if stp_pars.key_id(k) == "-534183936"]
  if chan and isinstance(chan[0], list):
    blocks = sorted(((int(stp_pars.key_id(k)), v) for k, v in chan[0] if isinstance(v, list)), key=lambda x: x[0])
    flat = lambda blk: [(stp_pars.key_name(k), v) for k, v in blk
                        if not stp_pars.key_name(k).startswith("channel constant") and not re.match(r"^\d+$", stp_pars.key_name(k))]
    flats = [(ch, flat(blk)) for ch, blk in blocks]
    if flats:
      bound = set(rec.variable_bindings)
      mark = lambda v: f"<{v}>" if isinstance(v, str) and v in bound else v
      ref = flats[0][1]
      differing = {n for n, _ in ref if len({repr(v) for _, f in flats for n2, v in f if n2 == n}) > 1}
      lines.append(f"({len(flats)} channels"
                   + (f" {flats[0][0]}–{flats[-1][0]}" if len(flats) > 1 else "") + ", one shown)")
      lines.extend(f"{n} = {mark(v)}" for n, v in ref if n not in differing)
      for n in (k for k in dict(ref) if k in differing):
        vals = ", ".join(f"{ch}:{mark(dict(f)[n])}" for ch, f in flats)
        lines.append(f"{n}: {vals}")
  return lines


def render_error(e: stp_pars.ErrorPolicy) -> str:
  """One error policy: offered recoveries (default starred), hidden ones, and
  the automatic-handling fields, raw where their meaning is open (§11)."""
  shown = [r.title + ("*" if r.default else "") for r in e.recoveries if r.visible]
  hidden = [r.title + ("*" if r.default else "") for r in e.recoveries if not r.visible]
  text = f"on {e.title} (#{e.number}): " + (" · ".join(shown) or "no recovery offered")
  if hidden:
    text += f" (hidden: {', '.join(hidden)})"
  flags = []
  if e.repeat_count:
    flags.append(f"repeat count {e.repeat_count}")
  if e.use_default:
    flags.append("use default")
  flags.append("timeout infinite" if e.infinite else f"timeout {e.timeout or '0'}")
  if e.add_recovery not in ("0", ""):
    add = stp_pars.RECOVERY_TITLES.get(int(e.add_recovery)) if e.add_recovery.lstrip("-").isdigit() else None
    flags.append(f"add recovery {add or e.add_recovery}")
  if e.sound:
    flags.append(f"sound {e.sound}")
  return text + " — " + ", ".join(flags)


# --- PTL smart steps -----------------------------------------------------------

# Argument names of the PTL calls, from HSLPTLLib.hsl (Pipetting Template Library).
_PTL_COMMON = ["tipPickupSequence", "aspirateSequence", "dispenseSequence", "aspirateMultiplicity",
               "dispenseMultiplicity", "pipettingVolume", "restVolume", "drivingMode",
               "tipRenewalCycleSeq", "tipRenewalCycleMul", "tipRenewalCycleVol", "tipType"]
PTL_ARGS = {
  "Pipette": ["ML_STAR", *_PTL_COMMON],
  "Pipette2": ["ML_STAR", *_PTL_COMMON[:5], "pipettingVolumes", *_PTL_COMMON[6:]],
  "Pipette3": ["ML_STAR", "tipPickupSequence", "aspirateSequences", "dispenseSequences", *_PTL_COMMON[3:],
               "seqMergedAspirate", "seqMergedDispense"],
  "TipPickup": ["ML_STAR", "tipPickupSequence"],
  "TipEject": ["ML_STAR"],
}
_PTL_RUN = re.compile(r"\bPTL::(%s)\s*\(" % "|".join(sorted(PTL_ARGS, key=len, reverse=True)))
_PTL_STATE = re.compile(r'^PTL::Set(\w+?)State(?:Default)?\s*\(\s*"([^"]+)"\s*,\s*(.*)\)\s*;$')
_PTL_SKIP = re.compile(r"^(?:sequence\s+arrseq\w+\[\];|arrseq\w+\.SetSize\(.*\);|PTL::Reset\w*\(.*\);"
                       r"|PTL::RaiseRuntimeError\(.*\);|[{}])$")
_PTL_SEQ = re.compile(r"^arrseq(Aspirate|Dispense)_\w+\.SetAt\(\s*\d+\s*,\s*(.+)\);$")


def _ptl_fold(code: str) -> Optional[tuple[str, list[str], list[str]]]:
  """A PTL smart step: (call name, settings, leftover code lines), or None."""
  m = _PTL_RUN.search(code)
  if not m:
    return None
  fn = m.group(1)
  args = split_args(_call_text(code, m.end() - 1))
  seqs: dict[str, list[str]] = {"Aspirate": [], "Dispense": []}
  states, rest = [], []
  for raw in code.splitlines():
    line = raw.strip()
    if not line or _PTL_SKIP.match(line):
      continue
    if line.startswith(("if( 0 == PTL::", "if (0 == PTL::")) or line.startswith(f"PTL::{fn}("):
      continue
    sm = _PTL_SEQ.match(line)
    if sm:
      seqs[sm.group(1)].append(sm.group(2).strip())
      continue
    st = _PTL_STATE.match(line)
    if st:
      states.append(f"{st.group(2)} = {st.group(3).strip()}")
      continue
    rest.append(line)
  names = PTL_ARGS[fn]
  settings = []
  if seqs["Aspirate"]:
    settings.append(f"aspirate sequences = {', '.join(seqs['Aspirate'])}")
  if seqs["Dispense"]:
    settings.append(f"dispense sequences = {', '.join(seqs['Dispense'])}")
  for i, a in enumerate(args[1:], start=1):
    name = names[i] if i < len(names) else f"arg{i + 1}"
    if name in ("aspirateSequences", "dispenseSequences"):
      continue  # the arrays, listed above by content
    settings.append(f"{name} = {a}")
  return fn, settings + states, rest


def _call_text(code: str, open_paren: int) -> str:
  depth = 0
  for i in range(open_paren, len(code)):
    if code[i] == "(":
      depth += 1
    elif code[i] == ")":
      depth -= 1
      if depth == 0:
        return code[open_paren + 1 : i]
  return code[open_paren + 1 :]


# --- the IR and its renderers -------------------------------------------------------

@dataclasses.dataclass
class Line:
  """One trace line: the IR between the walk and the renderers."""
  depth: int
  kind: str  # heading | call | device | setting | code
  role: str  # robot / equipment / data / config / ui / lab / method / ptl / error / ""
  text: str
  data: object = None  # structured source of the line (an ErrorPolicy), for views


# Device settings the condensed view keeps; the full trace keeps everything.
_KEEP_SETTING = re.compile(
  r"volume|mix |LiquidName|LLD|submerge|fluid height|Sequence|ChannelPattern|TipType"
  r"|DispenseMode|mode|grip|speed|press|acceleration|lift up|retract|height"
  r"|TouchOff|LiquidFollowing|detect")
_KEEP_PTL = re.compile(
  r"^(?:aspirate sequences|dispense sequences|tipPickupSequence|pipettingVolumes?|restVolume"
  r"|aspirateMultiplicity|dispenseMultiplicity|drivingMode|tipRenewalCycle\w+) ="
  r"|LiquidClass|Volume|Mix|LLD|Submerge|FluidHeight|Mode =|LiquidFollowing|TouchOff|Blowout"
  r"|ChannelPattern|ErrorHandling")
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
    close = _call_close(line, m.end() - 1)
    args = split_args(line[m.end() : close])
    key = _TRANSLATE.sub(r"\1", args[-1]).strip() if args else "?"
    line = line[: m.start()] + f"params[{key}]" + line[close + 1 :]
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


def _error_summary(errs: list[stp_pars.ErrorPolicy]) -> Optional[str]:
  """Condensed: only the errors set to repeat or to use their default recovery
  (UseDefault; whether Venus then skips the operator dialog is open, §11)."""
  auto = []
  for e in errs:
    if not (e.repeat_count or e.use_default):
      continue
    default = next((r.title for r in e.recoveries if r.default), "?")
    bits = [f"repeat {e.repeat_count}×"] if e.repeat_count else []
    if e.use_default:
      bits.append(f"default {default}")
    auto.append(f"{e.title.removesuffix(' Error')} ({', '.join(bits)})")
  if not auto:
    return None
  return f"errors set to default/repeat ({len(auto)} of {len(errs)}): " + "; ".join(auto)


_OPENER = re.compile(r"^(?:if\s*\(|else\b|for\s*\(|while\s*\()")


def _drop_empty_blocks(lines: list[Line]) -> list[Line]:
  """Remove `{ }` pairs (and the if/else/for/while that opens them) left empty
  once the condensed view has dropped their contents."""
  code = lambda ln, s=None: ln.kind == "code" and (s is None or ln.text.strip() == s)
  changed = True
  while changed:
    changed = False
    out: list[Line] = []
    i = 0
    while i < len(lines):
      if i + 1 < len(lines) and code(lines[i], "{") and code(lines[i + 1], "}"):
        nxt = lines[i + 2] if i + 2 < len(lines) else None
        followed_by_else = nxt is not None and code(nxt) and nxt.text.strip().startswith("else")
        if out and code(out[-1]) and _OPENER.match(out[-1].text.strip()) and not followed_by_else:
          out.pop()  # the opener of the now-empty block
        elif followed_by_else:
          out.append(lines[i])  # keep `{ }` so the else still has its if
          out.append(lines[i + 1])
          i += 2
          continue
        i += 2
        changed = True
        continue
      out.append(lines[i])
      i += 1
    lines = out
  return lines


def condense(lines: list[Line]) -> list[Line]:
  """A condensed view: data/config/ui subtrees collapse to their header note,
  trace-file plumbing and uninformative settings drop, parameter reads render
  as params[key], error policies reduce to the automatic ones. Nothing is lost
  that the full trace does not hold."""
  out, skip = [], None
  errs: list[stp_pars.ErrorPolicy] = []
  err_depth = 0

  def flush():
    if errs:
      s = _error_summary(errs)
      if s:
        out.append(Line(err_depth, "setting", "error", s))
      errs.clear()

  for ln in lines:
    if ln.role == "error" and isinstance(ln.data, stp_pars.ErrorPolicy):
      errs.append(ln.data)
      err_depth = ln.depth
      continue
    flush()
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
    if ln.kind == "setting":
      keep = _KEEP_PTL if ln.role == "ptl" else _KEEP_SETTING
      if not keep.search(ln.text):
        continue
    out.append(ln)
  flush()
  return _drop_empty_blocks(out)


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


# --- the walk ---------------------------------------------------------------------

class Tracer:
  """Expands method sections into trace lines (the IR)."""

  def __init__(self, libraries: list[Library], stps: dict[str, stp_pars.Record], max_depth: int = 6,
               expand_limit: int = 3):
    self.libs = libraries
    self.stps = stps
    self.max_depth = max_depth
    self.expand_limit = expand_limit
    self.expanded: dict[tuple[str, str], int] = {}
    self.sections: dict[str, list[hsl.Step]] = {}

  def _find(self, ns: str, name: str) -> tuple[Optional[Library], Optional[hsl_code.Function]]:
    """The library function NS::name; HSL names are case-insensitive."""
    for lib in self.libs:
      if lib.namespace == ns.upper():
        fn = lib.find(name)
        if fn is not None:
          return lib, fn
    return None, None

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
      folded = _ptl_fold(code)
      if folded:
        fn, settings, rest = folded
        dev = split_args(_call_text(code, _PTL_RUN.search(code).end() - 1))[:1] or ["?"]
        out.append(Line(depth, "device", "robot", f"PTL {fn} ({dev[0]})"))
        out.extend(Line(depth, "setting", "ptl", t) for t in settings)
        out.extend(Line(depth, "code", "", self._tagged(t)) for t in rest)
        continue
      if self._call(code, out, depth, seen, lib):
        continue
      for line in code.splitlines():
        stripped = line.strip()
        if not stripped:
          continue
        text, d = self._tagged(stripped), depth
        if stripped.startswith("}"):
          d = max(depth - 1, 0)
        out.append(Line(d, "code", "", text))

  def _call(self, code: str, out: list[Line], depth: int, seen: tuple, lib: Optional[Library]) -> bool:
    """Inline a step that is one call to a library function or to one of the
    method's own sections. False when the step is anything else."""
    cm = _STMT.match(code)
    if cm is None:
      return False
    close = _call_close(code, cm.end() - 1)
    if code[close + 1 :].strip() not in ("", ";"):
      return False  # the call is part of a larger statement; render it as code
    ns, name, lhs = cm.group("ns"), cm.group("fn"), cm.group("lhs")
    args = split_args(code[cm.end() : close])
    prefix = f"{lhs} = " if lhs else ""
    if ns:
      flib, fn = self._find(ns, name)
      if fn is None:
        holders = [lb for lb in self.libs if lb.namespace == ns.upper() and lb.path and lb.path.suffix.lower() == ".hsi"]
        if holders:
          out.append(Line(depth, "code", "",
                          f"# note: {holders[0].name} as included defines no {name}; "
                          f"the method and the library as included disagree"))
    else:  # a bare call: a sibling function in the same library, or a method section
      flib, fn = (lib, lib.find(name)) if lib is not None else (None, None)
      if fn is None and name in self.sections:
        key = ("", name.lower())
        if key in seen or self._too_deep(depth, name, out):
          return False
        out.append(Line(depth, "call", "method", f"{prefix}{name}({', '.join(args)})"))
        self._walk(self.sections[name], out, depth + 1, seen + (key,))
        return True
    if fn is None or fn.name.startswith("_"):
      return False
    body_steps = hsl.steps(fn.body)
    if not body_steps:
      return False  # hand-written library code: no steps to walk; keep the call line
    key = (flib.namespace, fn.name.lower())
    if key in seen or self._too_deep(depth, fn.name, out):
      return False
    names = [a.name for a in fn.args]
    bound = ", ".join(f"{names[i]} = {args[i]}" for i in range(min(len(args), len(names))))
    role = role_of(flib.namespace) or "lab"
    out.append(Line(depth, "call", role, f"{prefix}{fn.name}({bound})"))
    if len(args) != len(names):
      out.append(Line(depth + 1, "code", "",
                      f"# note: {len(args)} arguments passed, {flib.name} defines {fn.name} with "
                      f"{len(names)}: the method and the library as included disagree, "
                      f"so the bindings above are by position"))
    n = self.expanded.get(key, 0)
    self.expanded[key] = n + 1
    if n < self.expand_limit:
      # identical structure at every call site (settings are per-GUID):
      # expand the first sites fully, elide the rest
      self._walk(body_steps, out, depth + 1, seen + (key,), flib)
    else:
      out.append(Line(depth + 1, "code", "",
                      f"... body elided; structure as the earlier expansions of {fn.name}"))
    return True

  def _too_deep(self, depth: int, name: str, out: list[Line]) -> bool:
    if depth < self.max_depth:
      return False
    out.append(Line(depth, "code", "", f"# note: {name} not expanded (call depth limit {self.max_depth})"))
    return True

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

  def _device(self, s: hsl.Step, out: list[Line], depth: int):
    m = _DEVICE.search(s.code)
    var, guid = (m.group(1), m.group(3)) if m else ("?", "?")
    line_end = s.code.find("\n", m.start()) if m else -1
    call_line = s.code[m.start() : line_end if line_end >= 0 else None] if m else ""
    comment = call_line.rsplit("//", 1)[-1].strip() if "//" in call_line else ""
    role = "robot" if var.upper() in ("STAR", "ML_STAR") else "equipment"
    out.append(Line(depth, "device", role, f"{comment or s.type} ({var})"))
    rec = self.stps.get(guid)
    if rec is None:
      out.append(Line(depth, "setting", "", f"settings: .stp record not found for {guid}"))
      return
    for line in render_settings(rec):
      out.append(Line(depth, "setting", "", line))
    for e in rec.errors():
      out.append(Line(depth, "setting", "error", render_error(e), e))


def method_lines(hsl_text: str, libraries: list[Library], stps: dict[str, stp_pars.Record],
                 sub_text: str = "", sections: tuple[str, ...] = ("main", "GetParams"),
                 ) -> list[tuple[str, list[Line]]]:
  """The trace IR of a method's sections, then of its registered abort handler."""
  tr = Tracer(libraries, stps)
  text = hsl_text + ("\n" + sub_text if sub_text else "")
  present = {s.section for s in hsl.steps(text)}
  out = []
  for name in sections:
    if name in present:
      out.append((name, tr.section(text, name)))
  for name in dict.fromkeys(_ABORT.findall(text)):
    if name in present and name not in sections:
      out.append((f"{name} (abort handler)", tr.section(text, name)))
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
