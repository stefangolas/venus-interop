"""Run a Venus method's logic to learn what each device step works on: an HSL interpreter.

`protocol` renders what a method says; this executes it, so that every pipetting step's sequence
resolves to the (labware, position) each channel uses. It runs the method's `main` with its own
libraries and Hamilton's (all HSL source, included the way Venus includes them), over the deck
layout's sequences, with the inputs the caller supplies (files the method reads, such as its
parameters CSV, and answers to dialogs). Device steps are not sent anywhere: their `.stp` records
say which variables hold the sequence, channel pattern, counting and channel use, and
`sequences.take` applies Venus's rules. A step returns Venus's success result.

Where the logic depends on something it does not know (a value never supplied, an automation
object, an instrument read-back), it stops and says where, rather than guess: `Run.stopped`.

Status: it preprocesses and parses whole methods with every include (Marionette: 87k lines, 1,390
functions) and runs them until Venus's compiled services are needed (the deck-layout object,
liquid classes, ...), which only a few are modelled for. Its use is running single library
functions - device steps and sequence logic - to check Python ports of them against the HSL.

Standard library only. Grammar and semantics from Hamilton's HSL reference
(HxStandardLanguageEnu.chm: Grammar, Element functions, Library functions).
"""
from __future__ import annotations

import csv
import dataclasses
import io
import math
import pathlib
import re
import sqlite3
from typing import Any, Callable, Iterable, Optional

from venus_interop.methods import sequences as sq
from venus_interop.methods import stp_pars

# -- values ------------------------------------------------------------------------------------


class Unknown:
  """A value the run does not know, with why."""

  def __init__(self, why: str):
    self.why = why

  def __repr__(self):
    return f"<unknown: {self.why}>"


class Stop(Exception):
  """The run cannot go on without guessing."""


class Abort(Exception):
  """The method called `abort`."""


class _Return(Exception):
  def __init__(self, value):
    self.value = value


class _Break(Exception):
  pass


@dataclasses.dataclass
class Cell:
  """A storage location; by-reference parameters share it."""
  value: Any


class HArray:
  """An HSL dynamic array (`variable a[]`, `sequence s[]`)."""

  def __init__(self, items=None, kind="variable"):
    self.items = list(items or [])
    self.kind = kind

  def copy(self):
    return HArray([it.copy() if isinstance(it, sq.Sequence) else it for it in self.items], self.kind)


class HFile:
  """An HSL `file` object over the run's virtual files: fields bound to variables (AddField),
  records read and written as CSV lines; or a sheet of an Excel workbook, `"<file>.xls <Sheet>"`,
  which Venus opens through Jet's Excel driver and libraries query with SQL (`Run.workbooks`)."""

  def __init__(self, run: "Run"):
    self.run = run
    self.fields: list[tuple[str, Cell]] = []
    self.types: dict[str, str] = {}  # field name (lower) -> hslInteger / hslFloat / hslString tag
    self.sheet: Optional[tuple[sqlite3.Connection, str]] = None
    self.rows: list[list[str]] = []
    self.pos = 0
    self.path = ""
    self.mode = None
    self.delimiter = ","
    self.header: list[str] = []


class Device:
  def __init__(self, name: str, sequences: dict[str, sq.Sequence]):
    self.name = name
    self.sequences = sequences  # lower-case name -> Sequence
    self.originals = {k: v.copy() for k, v in sequences.items()}  # as the layout has them
    self.labware: set[str] = set()  # labware ids on the layout, lower case


class Opaque:
  """An object the run models only by name (dialog, timer, event, automation object)."""

  def __init__(self, kind: str):
    self.kind = kind
    self.progid = ""
    self.dict: Optional[dict] = None  # Scripting.Dictionary, modelled


# -- the events a run records ------------------------------------------------------------------


@dataclasses.dataclass
class StepEvent:
  """One device step as it ran."""
  index: int
  command: str  # step name from the .stp record (Aspirate, TipPickUp, Head96Dispense ...)
  guid: str
  device: str
  sequence: str  # the sequence's name
  channels: dict[int, sq.Item]  # channel (or head position) -> (labware, position)
  volumes: dict[int, Any]  # channel -> volume, where the step has one
  first: int  # sequence position of the first item taken
  used: int
  counting: Any
  pattern: str
  stack: tuple[str, ...]  # the function calls it ran under
  note: str = ""
  settings: dict[str, Any] = dataclasses.field(default_factory=dict)  # a transport step's, bound


# -- preprocessing -----------------------------------------------------------------------------

_INCLUDE = re.compile(r'^\s*#\s*include\s+(__filename__\s+)?"([^"]+)"', re.M)


def _strip_comments(text: str) -> str:
  out, i, n = [], 0, len(text)
  while i < n:
    c = text[i]
    if c == '"':
      j = i + 1
      while j < n and text[j] != '"':
        j += 2 if text[j] == "\\" else 1
      out.append(text[i : j + 1])
      i = j + 1
    elif text.startswith("//", i):
      j = text.find("\n", i)
      i = n if j < 0 else j
    elif text.startswith("/*", i):
      j = text.find("*/", i + 2)
      seg = text[i : (n if j < 0 else j + 2)]
      out.append("\n" * seg.count("\n"))
      i = n if j < 0 else j + 2
    else:
      out.append(c)
      i += 1
  return "".join(out)


class Preprocessor:
  """`#include` (with `__filename__`), `#define`, `#ifdef/#ifndef/#endif`, `#pragma once`, with
  HSL_RUNTIME defined, as at run time."""

  def __init__(self, roots: Iterable[pathlib.Path], read: Callable[[pathlib.Path], str]):
    self.roots = [pathlib.Path(r) for r in roots]
    self.read = read
    self.defined = {"HSL_RUNTIME"}
    self.once: set[str] = set()
    self.missing: list[str] = []

  def resolve(self, name: str, here: pathlib.Path) -> Optional[pathlib.Path]:
    """Beside the including file, then under each root; the name as the source spells it, with
    its string escapes (`"..\\HSLTrcLib.hsl"`) undone."""
    from venus_interop.methods.protocol import resolve_include
    return resolve_include(name.replace("\\\\", "\\"), here.parent, self.roots)

  def expand(self, path: pathlib.Path, text: Optional[str] = None) -> str:
    text = _strip_comments(self.read(path) if text is None else text)
    out: list[str] = []
    stack: list[bool] = []  # active flags
    for line in text.split("\n"):
      s = line.strip()
      active = all(stack)
      if s.startswith("#"):
        d = s[1:].strip()
        if d.startswith("ifdef"):
          stack.append(d.split()[1] in self.defined if len(d.split()) > 1 else False)
          continue
        if d.startswith("ifndef"):
          stack.append(d.split()[1] not in self.defined if len(d.split()) > 1 else True)
          continue
        if d.startswith("endif"):
          if stack:
            stack.pop()
          continue
        if d.startswith("else"):
          if stack:
            stack[-1] = not stack[-1]
          continue
        if not active:
          continue
        if d.startswith("define"):
          parts = d.split()
          if len(parts) > 1:
            self.defined.add(parts[1])
          continue
        if d.startswith("pragma"):
          if "once" in d:
            key = str(path).lower()
            if key in self.once:
              return ""
            self.once.add(key)
          continue
        m = re.match(r'include\s+(__filename__\s+)?"([^"]+)"', d)
        if m:
          name = (path.stem + m.group(2)) if m.group(1) else m.group(2)
          if m.group(1):
            target = path.with_name(name)
            target = target if target.exists() else None
          else:
            target = self.resolve(name, path)
          if target is None:
            self.missing.append(name)
            continue
          out.append(self.expand(target))
          continue
        continue
      if active:
        # a line may carry `namespace X { #include "..." }` on one line
        if "#include" in line:
          m = re.match(r'^(.*?)#\s*include\s+(__filename__\s+)?"([^"]+)"(.*)$', line)
          if m:
            name = (path.stem + m.group(3)) if m.group(2) else m.group(3)
            target = path.with_name(name) if m.group(2) else self.resolve(name, path)
            body = ""
            if target is not None and target.exists():
              body = self.expand(target)
            else:
              self.missing.append(name)
            out.append(m.group(1) + "\n" + body + "\n" + m.group(4))
            continue
        out.append(line)
    return "\n".join(out)


# -- lexer -------------------------------------------------------------------------------------

_TOKEN = re.compile(r"""
  (?P<ws>\s+)
 |(?P<num>0[xX][0-9a-fA-F]+|(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)
 |(?P<str>"(?:\\[\s\S]|[^"\\])*")
 |(?P<id>[A-Za-z_][A-Za-z0-9_]*)
 |(?P<op>::|\+\+|--|==|!=|<=|>=|&&|\|\||[-+*/%^<>=!&|(){}\[\],;.:])
""", re.X)


@dataclasses.dataclass
class Tok:
  kind: str
  text: str
  line: int


def lex(text: str) -> list[Tok]:
  out, pos, line = [], 0, 1
  while pos < len(text):
    m = _TOKEN.match(text, pos)
    if not m:
      # an unknown character (e.g. a stray '#' or '\\'): skip it
      pos += 1
      continue
    kind = m.lastgroup
    t = m.group()
    if kind != "ws":
      out.append(Tok(kind, t, line))
    line += t.count("\n")
    pos = m.end()
  out.append(Tok("eof", "", line))
  return out


def _unescape(s: str) -> str:
  """HSL string escapes: a backslash before a newline continues the line, backslash + three
  digits is a decimal character code, backslash n/t/r as in C, anything else stands for itself."""
  def sub(m):
    if m.group(1):
      return chr(int(m.group(1)))
    c = m.group(2)
    if c in "\r\n":
      return ""
    return {"n": "\n", "t": "\t", "r": "\r"}.get(c, c)
  return re.sub(r"\\(?:(\d{3})|([\s\S]))", sub, s[1:-1])


# -- parser ------------------------------------------------------------------------------------

TYPES = {"variable", "sequence", "string", "device", "resource", "dialog", "object", "timer",
         "event", "file", "char", "short", "long", "float"}
SPECS = {"global", "static", "private", "const", "synchronized"}


@dataclasses.dataclass
class Func:
  name: str
  ns: str  # qualified namespace, lower case, "::"-joined
  formals: list[tuple[str, str, bool, bool]]  # (type, name, by_ref, is_array)
  body: list
  line: int = 0


class Parser:
  """Builds an AST of nested tuples from the token list; collects functions and globals."""

  def __init__(self, toks: list[Tok]):
    self.t = toks
    self.i = 0
    self.funcs: dict[str, list[Func]] = {}  # lower name -> definitions (any namespace)
    self.globals: list[tuple[str, tuple]] = []  # (namespace, declaration statement)
    self.ns: list[str] = []

  # helpers
  def peek(self, k=0) -> Tok:
    return self.t[min(self.i + k, len(self.t) - 1)]

  def next(self) -> Tok:
    tok = self.t[self.i]
    self.i += 1
    return tok

  def accept(self, text: str) -> bool:
    if self.peek().text == text and self.peek().kind != "str":
      self.i += 1
      return True
    return False

  def expect(self, text: str) -> Tok:
    tok = self.next()
    if tok.text != text:
      raise SyntaxError(f"line {tok.line}: expected {text!r}, got {tok.text!r}")
    return tok

  # translation unit
  def unit(self):
    while self.peek().kind != "eof":
      self.top()

  def top(self):
    tok = self.peek()
    if tok.text == "}":
      self.next()
      if self.ns:
        self.ns.pop()
      return
    if tok.text == ";":
      self.next()
      return
    if tok.text == "namespace":
      self.next()
      name = self.next().text
      self.expect("{")
      self.ns.append(name.lower())
      return
    if tok.text in ("debug", "echo") and self.peek(1).text == "=":
      while self.next().text != ";":
        pass
      return
    if tok.text == "struct":
      depth = 0
      while True:
        x = self.next().text
        depth += (x == "{") - (x == "}")
        if x == ";" and depth == 0:
          return
    specs = []
    while self.peek().text in SPECS:
      specs.append(self.next().text)
    if self.peek().text in ("function", "method"):
      self.function()
      return
    if self.peek().text in TYPES:
      decl = self.declaration()
      self.globals.append(("::".join(self.ns), decl, "global" in specs))
      return
    # anything else at top level (scheduler constructs, stray tokens): skip to ';' or a block
    self.skip_statement()

  def skip_statement(self):
    depth = 0
    while self.peek().kind != "eof":
      x = self.next().text
      if x == "{":
        depth += 1
      elif x == "}":
        depth -= 1
        if depth <= 0:
          return
      elif x == ";" and depth == 0:
        return

  def function(self):
    line = self.next().line  # function / method
    name = self.next().text
    qual = []
    while self.accept("::"):  # `function Util::IsString(...)`: defined in a sub-namespace
      qual.append(name.lower())
      name = self.next().text
    self.expect("(")
    formals = []
    while not self.accept(")"):
      ftype = "variable"
      if self.peek().text in TYPES:
        ftype = self.next().text
      by_ref = self.accept("&")
      fname = self.next().text
      is_array = False
      if self.accept("["):
        self.expect("]")
        is_array = True
      formals.append((ftype, fname.lower(), by_ref, is_array))
      self.accept(",")
    # return type
    while self.peek().text in TYPES or self.peek().text == "void" or self.peek().text in ("[", "]"):
      self.next()
    if self.accept(";"):
      return  # a prototype
    body = self.block()
    if self._is_stub(body):
      return  # `{return(0);}` placeholders of .hs_ headers: the real body is elsewhere
    f = Func(name, "::".join([*self.ns, *qual]), formals, body, line)
    self.funcs.setdefault(name.lower(), []).append(f)

  @staticmethod
  def _is_stub(body) -> bool:
    """The placeholders of .hs_ headers: `{return;}`, `{return(0);}` - an empty body or a lone
    return of a constant. A wrapper whose one line returns an expression is a real body."""
    if not body:
      return True
    return len(body) == 1 and body[0][0] == "return" and (body[0][1] is None or body[0][1][0] == "const")

  def declaration(self) -> tuple:
    vtype = self.next().text
    items = []
    while True:
      self.accept("&")
      name = self.next().text
      is_array = False
      size = None
      init = None
      if self.accept("["):
        if not self.accept("]"):
          size = self.expr()
          self.expect("]")
        is_array = True
      if self.accept("("):
        init = []
        while not self.accept(")"):
          init.append(self.expr())
          self.accept(",")
      items.append((name.lower(), is_array, size, init))
      if not self.accept(","):
        break
    self.accept(";")
    return ("decl", vtype, items)

  # statements
  def block(self) -> list:
    self.expect("{")
    out = []
    while not self.accept("}"):
      st = self.statement()
      if st is not None:
        out.append(st)
    return out

  def statement(self):
    tok = self.peek()
    t = tok.text
    if tok.kind == "eof":
      raise SyntaxError("unexpected end of file")
    if t == "{":
      return ("block", self.block())
    if t == ";":
      self.next()
      return None
    if t in SPECS or (t in TYPES and self.peek(1).kind == "id") or (t in TYPES and self.peek(1).text == "&"):
      while self.peek().text in SPECS:
        self.next()
      if self.peek().text in ("function", "method"):
        self.function()
        return None
      return self.declaration()
    if t == "if":
      self.next()
      self.expect("(")
      cond = self.expr()
      self.expect(")")
      then = self.statement()
      other = None
      if self.accept("else"):
        other = self.statement()
      return ("if", cond, then, other, tok.line)
    if t == "while":
      self.next()
      self.expect("(")
      cond = self.expr()
      self.expect(")")
      return ("while", cond, self.statement(), tok.line)
    if t == "loop":
      self.next()
      self.expect("(")
      n = self.expr()
      self.expect(")")
      return ("loop", n, self.statement(), tok.line)
    if t == "for":
      self.next()
      self.expect("(")
      init = None if self.peek().text == ";" else self.expr()
      self.expect(";")
      cond = None if self.peek().text == ";" else self.expr()
      self.expect(";")
      step = None if self.peek().text == ")" else self.expr()
      self.expect(")")
      return ("for", init, cond, step, self.statement(), tok.line)
    if t == "break":
      self.next()
      self.accept(";")
      return ("break",)
    if t == "return":
      self.next()
      value = None
      if self.peek().text != ";":
        value = self.expr()
      self.accept(";")
      return ("return", value)
    if t == "abort":
      self.next()
      self.accept(";")
      return ("abort", tok.line)
    if t in ("pause", "lock", "unlock"):
      self.next()
      self.accept(";")
      return None
    if t == "onerror":
      while self.next().text != ";":
        pass
      return None
    if t == "resume":
      while self.next().text != ";":
        pass
      return None
    if t == "<" and self.peek(1).text == "<":  # `<< file;`: a string table loaded at run time
      while self.next().text != ";":
        pass
      return None
    if tok.kind == "id" and self.peek(1).text == ":" and self.peek(2).text == "{":
      self.next()
      self.next()
      self.block()  # an error-handler label block: runs only on errors, which a run has none of
      return None
    if t in ("fork", "join"):
      self.skip_statement()
      return None
    e = self.expr()
    self.accept(";")
    return ("expr", e, tok.line)

  # expressions, C precedence
  _BIN = [("||",), ("&&",), ("|",), ("&",), ("==", "!="), ("<", "<=", ">", ">="), ("+", "-"),
          ("*", "/", "%"), ("^",)]

  def expr(self):
    left = self.binary(0)
    if self.peek().text == "=" and self.peek().kind == "op":
      self.next()
      right = self.expr()
      return ("assign", left, right)
    return left

  def binary(self, level):
    if level == len(self._BIN):
      return self.unary()
    left = self.binary(level + 1)
    while self.peek().kind == "op" and self.peek().text in self._BIN[level]:
      op = self.next().text
      right = self.binary(level + 1)
      left = ("bin", op, left, right)
    return left

  def unary(self):
    t = self.peek()
    if t.kind == "op" and t.text in ("-", "!", "+"):
      self.next()
      return ("un", t.text, self.unary())
    if t.kind == "op" and t.text in ("++", "--"):
      self.next()
      return ("preinc", t.text, self.unary())
    return self.postfix()

  def postfix(self):
    e = self.primary()
    while True:
      t = self.peek()
      if t.text == "(" and t.kind == "op":
        self.next()
        args = []
        while not self.accept(")"):
          args.append(self.expr())
          self.accept(",")
        e = ("call", e, args, t.line)
      elif t.text == "[" and t.kind == "op":
        self.next()
        idx = self.expr()
        self.expect("]")
        e = ("index", e, idx)
      elif t.text == "." and t.kind == "op":
        self.next()
        e = ("member", e, self.next().text)
      elif t.text in ("++", "--") and t.kind == "op":
        self.next()
        e = ("postinc", t.text, e)
      else:
        return e

  def primary(self):
    t = self.next()
    if t.kind == "num":
      s = t.text
      if s.lower().startswith("0x"):
        return ("const", int(s, 16))
      return ("const", float(s) if any(c in s for c in ".eE") else int(s))
    if t.kind == "str":
      return ("const", _unescape(t.text))
    if t.text == "(":
      e = self.expr()
      self.expect(")")
      return e
    if t.kind == "id":
      name = t.text
      while self.peek().text == "::":
        self.next()
        name += "::" + self.next().text
      return ("name", name)
    if t.text == "__filename__":
      return ("const", "")
    if t.text == "::":  # `::Name`: the global one (a library wrapper calling the built-in)
      name = "::" + self.next().text
      while self.peek().text == "::":
        self.next()
        name += "::" + self.next().text
      return ("name", name)
    raise SyntaxError(f"line {t.line}: unexpected {t.text!r}")


# -- the run -----------------------------------------------------------------------------------

_CLSID = re.compile(r"^_[0-9A-Fa-f]{8}_[0-9A-Fa-f]{4}_[0-9A-Fa-f]{4}_[0-9A-Fa-f]{4}_[0-9A-Fa-f]{12}$")
CONSTANTS = {
  "hsltrue": 1, "hslfalse": 0, "hslok": 1, "hslcancel": 2, "hslabort": 3, "hslretry": 4,
  "hslignore": 5, "hslyes": 6, "hslno": 7, "hslinfinite": -1,
  "hslread": 1, "hslwrite": 2, "hslappend": 3,
  "hslinteger": "i", "hslfloat": "f", "hslstring": "s",
  "hslcsvdelimited": ",", "hsltabdelimited": "\t", "hslasciitext": "a",
  "hslfirst": 1, "hsllast": 2, "hslnext": 3, "hslprevious": 4,
  "hslokonly": 0, "hslokcancel": 1, "hslabortretryignore": 2, "hslyesnocancel": 3, "hslyesno": 4,
  "hslretrycancel": 5, "hslerror": 16, "hslquestion": 32, "hslexclamation": 48,
  "hslinformation": 64, "hsldefbutton1": 0, "hsldefbutton2": 256, "hsldefbutton3": 512,
  "hslsynchronous": 0, "hslasynchronous": 1, "hslhide": 0, "hslshow": 5, "hslshownormal": 1,
}


def _num(v):
  """HSL variables are variants: a numeric string converts where a number is expected."""
  if isinstance(v, bool):
    return int(v)
  if isinstance(v, (int, float)):
    return v
  if isinstance(v, str):
    try:
      return int(v)
    except ValueError:
      try:
        return float(v)
      except ValueError:
        return v
  return v


def _clean(x):
  if isinstance(x, float) and x.is_integer() and abs(x) < 1e15:
    return int(x)
  return x


def _typed(x, *operands):
  """An arithmetic result: a float operand makes it a float (HSL keeps a variant's float type, so
  2 * 47.0 is 94.0, not 94: libraries branch on GetType); integers only stay as they were."""
  return float(x) if any(isinstance(o, float) for o in operands) and isinstance(x, (int, float)) else _clean(x)


class Run:
  """One execution of a method. Build with `Run.prepare`, then `run()`."""

  def __init__(self, parser: Parser, stps: dict[str, stp_pars.Record], layouts: dict[str, Any],
               files: Optional[dict[str, str]] = None, answers: Optional[dict[str, Any]] = None,
               max_steps: int = 2_000_000):
    self.p = parser
    self.stps = stps
    self.layouts = layouts  # layout file name (lower) -> files.layout.Layout
    self.files = {k.lower().replace("/", "\\"): v for k, v in (files or {}).items()}
    self.written: dict[str, list[str]] = {}
    # Excel workbooks a library keeps state in (NGSStarLoading's RunData.xls): file (lower) -> an
    # in-memory SQLite database, a table per sheet, created when the library first writes the sheet
    self.workbooks: dict[str, sqlite3.Connection] = {}
    self.answers = answers or {}
    self.events: list[StepEvent] = []
    self.notes: list[str] = []  # assumptions the run made
    self.unresolved: dict[str, int] = {}  # functions called that neither the source nor the run defines
    self.stopped: Optional[str] = None
    self.globals: dict[str, dict[str, Cell]] = {}  # namespace -> name -> cell
    self.stack: list[str] = []
    self.budget = max_steps
    self.static: dict[tuple, dict[str, Cell]] = {}
    self.everywhere: dict[str, Cell] = {}  # `global` declarations
    self.src: list[str] = []  # the preprocessed source, for messages
    self.err = Opaque("error")
    self.dicts: dict[int, dict] = {}

  # -- setup --------------------------------------------------------------------------------

  def _declare(self, scope: dict[str, Cell], decl, env=None):
    _, vtype, items = decl
    for name, is_array, size, init in items:
      if is_array:
        val = HArray(kind=vtype)
        if size is not None:
          n = _num(self.eval(size, env)) if env is not None else 0
          if isinstance(n, int):
            val.items = [self._default(vtype) for _ in range(n)]
      elif vtype == "device":
        args = [self.eval(a, env) for a in (init or [])]
        val = self._device(args)
      elif init:
        val = self._construct(vtype, [self.eval(a, env) for a in init])
      else:
        val = self._default(vtype)
      scope[name] = Cell(val)

  def _default(self, vtype):
    if vtype == "sequence":
      return sq.Sequence("", [])
    if vtype == "string":
      return ""
    if vtype == "file":
      return HFile(self)
    if vtype in ("dialog", "timer", "event", "object", "resource", "device"):
      return Opaque(vtype)
    # an uninitialised variable reads as integer 0: the HSL reference says "undefined", but a
    # typeless value would make HSLStrLib's StrStr raise (CONVENTIONS §11)
    return 0

  def _construct(self, vtype, args):
    if vtype in ("variable", "string", "char", "short", "long", "float"):
      return args[0] if args else 0
    return self._default(vtype)

  def _device(self, args) -> Device:
    lay_name = str(args[0]) if args else ""
    dev_name = str(args[1]) if len(args) > 1 else "ML_STAR"
    lay = self.layouts.get(pathlib.Path(lay_name).name.lower())
    if lay is None and len(self.layouts) == 1:
      lay = next(iter(self.layouts.values()))
    seqs = {}
    if lay is not None:
      for s in lay.sequences:
        seqs[s.name.lower()] = sq.Sequence(s.name, list(s.items))
    else:
      self.notes.append(f"device {dev_name}: layout {lay_name!r} not given; its sequences are unknown")
    dev = Device(dev_name, seqs)
    if lay is not None:
      dev.labware = {p.id.lower() for p in lay.labware}
    return dev

  def run(self, entry: str = "main") -> "Run":
    try:
      for ns, decl, is_global in self.p.globals:
        scope = self.globals.setdefault(ns, {})
        self._declare(scope, decl, env=({}, ns))  # initialisers see their own namespace
        if is_global:  # `global`: visible from every namespace
          for name, *_ in decl[2]:
            self.everywhere[name] = scope[name]
      f = self._lookup_func(entry, "_method") or self._lookup_func(entry, "")
      if f is None:
        raise Stop(f"no function {entry}")
      self._call(f, [], [], None, 0)
    except Stop as e:
      self.stopped = str(e)
    except Abort as e:
      self.notes.append(f"abort: {e}")
    except sq.SequenceError as e:
      self.stopped = f"step error: {e}"
    except RecursionError:
      self.stopped = "recursion too deep"
    return self

  # -- name lookup ---------------------------------------------------------------------------

  def _lookup_func(self, qname: str, ns: str) -> Optional[Func]:
    if qname.startswith("::"):  # global scope only
      want = qname[2:].lower().split("::")
      for f in self.p.funcs.get(want[-1], []):
        if f.ns == "::".join(want[:-1]):
          return f
      return None
    parts = qname.lower().split("::")
    name, qual = parts[-1], parts[:-1]
    cands = self.p.funcs.get(name, [])
    if not cands:
      return None
    nsparts = ns.split("::") if ns else []
    # from the current namespace outward, the qualifier appended
    for k in range(len(nsparts), -1, -1):
      want = "::".join([*nsparts[:k], *qual])
      for f in cands:
        if f.ns == want:
          return f
    # by qualifier suffix
    if qual:
      tail = "::".join(qual)
      for f in cands:
        if f.ns.endswith(tail):
          return f
    else:
      for f in cands:
        if f.ns.startswith("::".join(nsparts)):
          return f
    return cands[0] if len(cands) == 1 or not qual else None

  def _cell(self, name: str, env, create=False) -> Optional[Cell]:
    low = name.lower()
    if env is not None:
      locs, ns = env
      if low in locs:
        return locs[low]
    else:
      ns = ""
    parts = low.split("::")
    base, qual = parts[-1], parts[:-1]
    nsparts = ns.split("::") if ns else []
    for k in range(len(nsparts), -1, -1):
      key = "::".join([*nsparts[:k], *qual])
      g = self.globals.get(key)
      if g is not None and base in g:
        return g[base]
    if qual:
      for key, g in self.globals.items():
        if key.endswith("::".join(qual)) and base in g:
          return g[base]
    elif base in self.everywhere:
      return self.everywhere[base]
    if create and env is not None:
      env[0][low] = Cell(0)
      return env[0][low]
    return None

  # -- calls ---------------------------------------------------------------------------------

  def _call(self, f: Func, arg_exprs, arg_vals, env, line):
    if len(self.stack) > 60:
      raise Stop("call depth over 60")
    locs: dict[str, Cell] = {}
    for i, (ftype, fname, by_ref, is_array) in enumerate(f.formals):
      if i < len(arg_vals):
        v = arg_vals[i]
        if by_ref and isinstance(v, Cell):
          locs[fname] = v
        else:
          v = v.value if isinstance(v, Cell) else v
          if isinstance(v, sq.Sequence):
            v = v.copy()
          elif isinstance(v, HArray):
            v = v.copy()
          locs[fname] = Cell(v)
      else:
        locs[fname] = Cell(self._default(ftype) if not is_array else HArray(kind=ftype))
    # A function Venus runs through a compiled service (the liquid-class database, the deck object,
    # SQL over files) can be replaced by a Python model: answers["functions"]["ns::name"] (lower
    # case; the namespace's tail will do), called with this run and the parameters as cells by
    # lower-case name (by-reference ones bound to the caller's); what it returns is the call's value.
    full = f"{f.ns}::{f.name}".lower()
    model = next((m for k, m in self.answers.get("functions", {}).items()
                  if full == k or full.endswith("::" + k)), None)  # the namespace's tail will do
    if model is not None:
      self.notes.append(f"line {line}: {f.ns}::{f.name} run by its Python model")
      return model(self, {k.lower(): c for k, c in locs.items()})
    self.stack.append(f.name)
    try:
      self._block(f.body, (locs, f.ns), new_scope=False)
    except _Return as r:
      return r.value
    finally:
      self.stack.pop()
    return 0

  def _args(self, arg_exprs, env):
    """Evaluate arguments, keeping cells for names (by-reference parameters bind to them)."""
    out = []
    for a in arg_exprs:
      if a[0] == "name":
        c = self._cell(a[1], env)
        if c is not None:
          out.append(c)
          continue
      if a[0] == "member" and a[1][0] == "name":
        obj = self._value_of(a[1], env)
        if isinstance(obj, Device):
          s = obj.sequences.get(a[2].lower())
          if s is not None:
            out.append(Cell(s))  # ML_STAR.Seq passed by reference: the device's own object
            continue
      out.append(self.eval(a, env))
    return out

  # -- statements ----------------------------------------------------------------------------

  def _tick(self):
    self.budget -= 1
    if self.budget <= 0:
      raise Stop("step budget exhausted (an endless loop?)")

  def _block(self, stmts, env, new_scope=True):
    for st in stmts:
      self._stmt(st, env)

  def _truth(self, v, what, line) -> bool:
    v = v.value if isinstance(v, Cell) else v
    if isinstance(v, Unknown):
      src = self.src[line - 1].strip() if 0 < line <= len(self.src) else ""
      raise Stop(f"line {line} in {'/'.join(self.stack[-3:])}: {what} depends on an unknown ({v.why}): {src}")
    v = _num(v)
    if isinstance(v, str):
      return v != ""
    return bool(v)

  def _stmt(self, st, env):
    self._tick()
    kind = st[0]
    if kind == "expr":
      self.eval(st[1], env, line=st[2])
    elif kind == "decl":
      self._declare(env[0], st, env)
    elif kind == "block":
      self._block(st[1], env)
    elif kind == "if":
      if self._truth(self.eval(st[1], env, line=st[4]), "a condition", st[4]):
        if st[2] is not None:
          self._stmt(st[2], env)
      elif st[3] is not None:
        self._stmt(st[3], env)
    elif kind == "while":
      try:
        while self._truth(self.eval(st[1], env, line=st[3]), "a loop condition", st[3]):
          self._tick()
          if st[2] is not None:
            self._stmt(st[2], env)
      except _Break:
        pass
    elif kind == "loop":
      n = _num(self.eval(st[1], env))
      if not isinstance(n, (int, float)):
        raise Stop(f"line {st[3]}: loop count unknown")
      try:
        for _ in range(int(n)):
          if st[2] is not None:
            self._stmt(st[2], env)
      except _Break:
        pass
    elif kind == "for":
      _, init, cond, step, body, line = st
      if init is not None:
        self.eval(init, env)
      try:
        while cond is None or self._truth(self.eval(cond, env, line=line), "a loop condition", line):
          self._tick()
          if body is not None:
            self._stmt(body, env)
          if step is not None:
            self.eval(step, env)
      except _Break:
        pass
    elif kind == "break":
      raise _Break()
    elif kind == "return":
      raise _Return(self.eval(st[1], env) if st[1] is not None else 0)
    elif kind == "abort":
      raise Abort(f"line {st[1]} in {'/'.join(self.stack[-3:])}")

  # -- expressions ---------------------------------------------------------------------------

  def _value_of(self, e, env):
    v = self.eval(e, env)
    return v.value if isinstance(v, Cell) else v

  def _lvalue(self, e, env) -> Callable[[Any], None]:
    kind = e[0]
    if kind == "name":
      c = self._cell(e[1], env, create=True)
      if c is None:
        raise Stop(f"assignment to unknown name {e[1]}")

      def put(v, c=c):
        cur = c.value
        if isinstance(cur, sq.Sequence) and isinstance(v, sq.Sequence):
          cur.assign(v)  # `s = t`: the object keeps its identity, its state is copied
        elif isinstance(cur, HArray) and isinstance(v, HArray):
          c.value = v.copy()
        else:
          c.value = v
      return put
    if kind == "index":
      arr = self._value_of(e[1], env)
      idx = _num(self._value_of(e[2], env))

      def put(v, arr=arr, idx=idx):
        if isinstance(arr, HArray) and isinstance(idx, int):
          while len(arr.items) <= idx:
            arr.items.append(0)
          if isinstance(arr.items[idx], sq.Sequence) and isinstance(v, sq.Sequence):
            arr.items[idx] = v.copy()
          else:
            arr.items[idx] = v
      return put
    if kind == "member":
      return lambda v: None  # object properties: not modelled
    raise Stop(f"cannot assign to {kind}")

  def eval(self, e, env, line=0):
    kind = e[0]
    if kind == "const":
      return e[1]
    if kind == "name":
      c = self._cell(e[1], env)
      if c is not None:
        return c.value
      low = e[1].lower().split("::")[-1]
      if low in CONSTANTS:
        return CONSTANTS[low]
      if low == "err":  # the built-in error object: a run raises no error inside onerror
        return self.err
      return Unknown(f"name {e[1]}")
    if kind == "assign":
      v = self.eval(e[2], env, line)
      v = v.value if isinstance(v, Cell) else v
      self._lvalue(e[1], env)(v)
      return v
    if kind == "bin":
      return self._binary(e[1], e[2], e[3], env, line)
    if kind == "un":
      v = _num(self._value_of(e[2], env))
      if isinstance(v, Unknown):
        return v
      if e[1] == "-":
        return -v if isinstance(v, (int, float)) else Unknown("negated string")
      if e[1] == "!":
        return int(not (v != "" if isinstance(v, str) else v))
      return v
    if kind in ("preinc", "postinc"):
      return self._incdec(e, env)
    if kind == "index":
      arr = self._value_of(e[1], env)
      idx = _num(self._value_of(e[2], env))
      if isinstance(arr, HArray) and isinstance(idx, int):
        if 0 <= idx < len(arr.items):
          return arr.items[idx]
        raise Stop(f"line {line}: array index {idx} out of bounds ({len(arr.items)})")
      return Unknown("index into unknown")
    if kind == "member":
      obj = self._value_of(e[1], env)
      if isinstance(obj, Device):
        s = obj.sequences.get(e[2].lower())
        if s is not None:
          return s
        return Unknown(f"{obj.name}.{e[2]}")
      if isinstance(obj, Opaque) and obj.kind == "object":  # obj.RemoveAll; obj.Count
        return self._object_element(obj, e[2].lower(), [], line)
      return Unknown(f"member {e[2]}")
    if kind == "call":
      return self._call_expr(e, env)
    raise Stop(f"cannot evaluate {kind}")

  def _incdec(self, e, env):
    target = e[2]
    cur = self._value_of(target, env)
    if isinstance(cur, sq.Sequence):
      cur.increment(cur.used if e[1] == "++" else -cur.used)
      return cur.cur
    v = _num(cur)
    if not isinstance(v, (int, float)):
      return Unknown("increment of non-number")
    new = v + (1 if e[1] == "++" else -1)
    self._lvalue(target, env)(new)
    return new if e[0] == "preinc" else v

  def _binary(self, op, le, re_, env, line):
    if op in ("&&", "||"):
      a = self._value_of(le, env)
      if not isinstance(a, Unknown):
        ta = self._truth(a, "", line)
        if op == "&&" and not ta:
          return 0
        if op == "||" and ta:
          return 1
        b = self._value_of(re_, env)
        if isinstance(b, Unknown):
          return b
        return int(self._truth(b, "", line))
      b = self._value_of(re_, env)
      if not isinstance(b, Unknown):
        tb = self._truth(b, "", line)
        if op == "&&" and not tb:
          return 0
        if op == "||" and tb:
          return 1
      return a
    a = self._value_of(le, env)
    b = self._value_of(re_, env)
    if isinstance(a, Unknown):
      return a
    if isinstance(b, Unknown):
      return b
    if isinstance(a, sq.Sequence) or isinstance(b, sq.Sequence):
      return Unknown("arithmetic on a sequence")
    if op == "+":
      if isinstance(a, str) or isinstance(b, str):
        na, nb = _num(a), _num(b)
        if isinstance(a, str) and isinstance(b, str):
          return a + b
        return f"{_fmt(a)}{_fmt(b)}"
      return _typed(a + b, a, b)
    na, nb = _num(a), _num(b)
    if op in ("==", "!=", "<", "<=", ">", ">="):
      if isinstance(na, (int, float)) and isinstance(nb, (int, float)):
        x, y = na, nb
      else:
        x, y = str(a), str(b)
      r = {"==": x == y, "!=": x != y, "<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y}[op]
      return int(r)
    if not isinstance(na, (int, float)) or not isinstance(nb, (int, float)):
      return Unknown(f"{op} on strings")
    if op == "-":
      return _typed(na - nb, na, nb)
    if op == "*":
      return _typed(na * nb, na, nb)
    if op == "/":
      if nb == 0:
        raise Stop(f"line {line}: division by zero")
      return _typed(na / nb, na, nb)  # integers by integers: unverified (CONVENTIONS §11)
    if op == "%":
      return _typed(math.fmod(na, nb), na, nb) if nb else Unknown("mod by zero")
    if op == "^":
      return _typed(na ** nb, na, nb)
    if op == "&":
      return int(na) & int(nb)
    if op == "|":
      return int(na) | int(nb)
    raise Stop(f"operator {op}")

  # -- calls: functions, element functions, built-ins, device steps -------------------------

  def _call_expr(self, e, env):
    _, target, arg_exprs, line = e
    if target[0] == "member":
      obj_expr, method = target[1], target[2]
      if _CLSID.match(method):
        dev = self._value_of(obj_expr, env)
        args = [self._value_of(a, env) for a in arg_exprs]
        return self._device_step(dev, method, args, env, line)
      obj = self.eval(obj_expr, env)
      obj = obj.value if isinstance(obj, Cell) else obj
      if isinstance(obj, Opaque) and obj.kind == "object":
        cells = self._args(arg_exprs, env)
        args = [c.value if isinstance(c, Cell) else c for c in cells]
        return self._object_element(obj, method.lower(), args, line, cells)
      args = [self._value_of(a, env) for a in arg_exprs]
      return self._element(obj, method, args, obj_expr, arg_exprs, env, line)
    if target[0] == "name":
      name = target[1]
      ns = env[1] if env is not None else ""
      low = name.lower()
      if low.endswith("raiseruntimeerrorex") or low.endswith("error::raiseex") or low.endswith("error::raise"):
        args = [self._value_of(a, env) for a in arg_exprs]
        raise Stop(f"line {line}: the method raises an error ({name}: {', '.join(_fmt(a) for a in args)})")
      if low.endswith("hsllabwraccess::relativepositionvaluessetforlabwareid"):
        # Moves a labware on the deck-layout object, a compiled service: recorded as an event
        _dev, lab, x, y, z, r = [self._value_of(a, env) for a in arg_exprs]
        self._event("LabwareShift", "", getattr(_dev, "name", "?"), None, {}, {}, 0, 0, "", "", env,
                    settings={"labware": lab, "x": x, "y": y, "z": z, "r": r})
        return 1
      if low.endswith("virtuallabware::moveseq"):
        # Hamilton's VirtualLabware: the sequence's current labware moved by a delta on the
        # deck-layout object, a compiled service: recorded as an event
        _dev, seq, x, y, z = [self._value_of(a, env) for a in arg_exprs]
        item = seq.current_item() if isinstance(seq, sq.Sequence) else None
        self._event("LabwareShift", "", getattr(_dev, "name", "?"), None, {}, {}, 0, 0, "", "", env,
                    settings={"labware": item[0] if item else Unknown("labware of the sequence"),
                              "x": x, "y": y, "z": z, "r": 0})
        return 0
      f = self._lookup_func(name, ns)
      if f is not None:
        return self._call(f, arg_exprs, self._args(arg_exprs, env), env, line)
      return self._builtin(name, arg_exprs, env, line)
    raise Stop(f"line {line}: call of {target[0]}")

  def _builtin(self, name, arg_exprs, env, line):
    low = name.lower().split("::")[-1]
    vals = lambda: [self._value_of(a, env) for a in arg_exprs]  # noqa: E731
    if low in ("trace", "formattrace", "registerabouthandler", "registerabortHandler".lower(),
               "unregisterabortHandler".lower(), "settimescalefactor"):
      return 0
    if name.lower() == "stringtable":  # a library's error texts, defined in its language file (…Enu.hs_)
      return 0
    if low == "translate":
      v = vals()
      return v[0] if v else ""
    if low == "fstr":
      v = vals()
      return _fmt(v[0]) if v else ""
    if low == "istr":
      v = _num(vals()[0])
      return str(int(v)) if isinstance(v, (int, float)) else Unknown("IStr of unknown")
    if low == "ival":
      v = _num(vals()[0])
      return int(v) if isinstance(v, (int, float)) else Unknown("IVal of non-number")
    if low == "fval":
      v = _num(vals()[0])
      return float(v) if isinstance(v, (int, float)) else Unknown("FVal of non-number")
    if low == "getfilename":
      return "method"
    if low == "getfunctionname":
      return self.stack[-1] if self.stack else ""
    if low == "getlinenumber":
      return line
    if low == "getmethodfilename":
      return "method"
    if low == "getuniquerunid":
      return "run"
    if low == "getsimulationmode":
      return int(self.answers.get("simulation", 0))
    if low == "messagebox":
      ans = self.answers.get("MessageBox", 1)
      self.notes.append(f"line {line}: MessageBox answered {ans}")
      return ans
    if low == "inputbox":
      key = str(vals()[1]) if len(arg_exprs) > 1 else "InputBox"
      return self.answers.get(key, Unknown(f"InputBox {key!r}"))
    if low == "aligntsequences" or low == "alignsequences":
      v = [self._value_of(a, env) for a in arg_exprs]
      pairs = [(v[i], int(_num(v[i + 1]))) for i in range(1, len(v) - 1, 2) if isinstance(v[i], sq.Sequence)]
      if len(pairs) * 2 != len(v) - 1:
        return Unknown("AlignSequences arguments")
      return sq.align(pairs, bool(_num(v[0])))
    if low == "isdbnull":
      return 0
    if low in ("floor", "ceiling", "abs", "sqrt", "exp", "log", "log10", "sin", "cos", "tan", "atan"):
      vs = vals()
      v = _num(vs[0])
      if not isinstance(v, (int, float)):
        return Unknown(f"{name} of a non-number")
      if low in ("floor", "ceiling") and len(vs) > 1 and _num(vs[1]):  # Floor(x, hslTrue): as a float
        return float(math.floor(v) if low == "floor" else math.ceil(v))
      f = {"floor": math.floor, "ceiling": math.ceil, "abs": abs, "sqrt": math.sqrt, "exp": math.exp,
           "log": math.log, "log10": math.log10, "sin": math.sin, "cos": math.cos, "tan": math.tan,
           "atan": math.atan}[low]
      return _clean(f(v))
    if low == "getvectordbtrackerobject":
      o = Opaque("object")
      o.progid = "Hamilton.HxVectorDbTracker"
      return o
    if low == "searchpath":  # library string tables and such: taken as found
      v = vals()
      return v[0] if v else ""
    if low == "getlanguage":
      return "Enu"
    if low == "gettype":  # the type tag, compared against hslInteger / hslFloat / hslString
      v = vals()[0] if arg_exprs else 0
      if isinstance(v, bool) or isinstance(v, int):
        return CONSTANTS["hslinteger"]
      if isinstance(v, float):
        return CONSTANTS["hslfloat"]
      if isinstance(v, str):
        return CONSTANTS["hslstring"]
      return Unknown("GetType of an unknown")
    if low in ("getdeviceref",):
      return Unknown("device reference")
    if low == "getlasterror":
      return Opaque("error")
    if low == "shell":
      return Unknown("Shell")
    if low in ("getcurrenttime", "gettime", "getdate"):
      return Unknown("time")
    self.unresolved[name] = self.unresolved.get(name, 0) + 1
    return Unknown(f"function {name}")

  def _element(self, obj, method, args, obj_expr, arg_exprs, env, line):
    m = method.lower()
    if isinstance(obj, Unknown):
      return obj
    if isinstance(obj, sq.Sequence):
      return self._seq_element(obj, m, args, line)
    if isinstance(obj, HArray):
      return self._array_element(obj, m, args, obj_expr, env, line)
    if isinstance(obj, str):
      return self._string_element(obj, m, args, obj_expr, env)
    if isinstance(obj, HFile):
      return self._file_element(obj, m, args, arg_exprs, env)
    if isinstance(obj, Device):
      if m == "getsequenceref":
        return obj.sequences.get(str(args[0]).lower(), Unknown(f"sequence {args[0]}"))
      if m == "copyresetsequence":  # the layout's sequence, reset, into the given one
        orig = obj.originals.get(str(args[0]).lower())
        if orig is not None and isinstance(args[1], sq.Sequence):
          args[1].assign(orig)
        return 0
      if m == "getcfgvaluewithkey":
        return self.answers.get(f"cfg.{_fmt(args[0])}", 0)
      if m == "getlabwaredata":
        # (labware id, keys[], values[]): from answers["labware_data"](labware id, key), the
        # caller's reading of the labware definitions; empty where it has nothing
        lookup = self.answers.get("labware_data")
        if lookup and len(args) > 2 and isinstance(args[1], HArray) and isinstance(args[2], HArray):
          vals = [lookup(str(args[0]), str(k)) for k in args[1].items]
          args[2].items = ["" if v is None else v for v in vals]
        return 0
      if m == "isvalidlabwareforcurrentdecklayout":
        return int(str(args[0]).lower() in obj.labware)
      if m == "getinstrumentname":
        return obj.name
      if m == "getlabwareposition":  # (labware id, values[]): x, y, z, r on the deck, not modelled
        if len(args) > 1 and isinstance(args[1], HArray):
          args[1].items = [Unknown(f"position of {args[0]}") for _ in range(4)]
        return 0
      return Unknown(f"device.{method}")
    if isinstance(obj, (int, float)):
      return self._string_element(str(obj), m, args, obj_expr, env)
    if isinstance(obj, Opaque) and obj.kind == "object":
      return self._object_element(obj, m, args, line)
    if isinstance(obj, Opaque):
      if obj.kind == "timer" and m in ("settimer", "waittimer", "restarttimer", "setabstimer", "settimerviewname"):
        return 1
      if obj.kind == "event" and m in ("setevent", "waitevent", "resetevent"):
        return 1
      if obj.kind == "dialog":
        return self.answers.get(f"dialog.{method}", 1)
      if obj.kind == "error":  # no error is ever pending in a run
        if m == "getid":
          return 0
        if m in ("getdescription", "getdata"):
          return ""
        return 0
      return Unknown(f"{obj.kind}.{method}")
    return Unknown(f"{type(obj).__name__}.{method}")

  # Automation objects with a stand-in. Each answers only what the run knows; anything else is
  # unknown, and a condition on it stops the run.
  MODELLED = {"scripting.dictionary", "msscriptcontrol.scriptcontrol", "hxparamslib.hxpars",
              "hamilton.hxcoreliquidclass", "hamilton.hxcoretiptypes",
              "hamilton.hxservicesgeneralsettings", "hamilton.hxvectordbtracker",
              "hamilton.hxelementcounter", "scripting.filesystemobject"}

  def _object_element(self, o: Opaque, m, args, line, arg_cells=None):
    """Automation objects. Scripting.Dictionary and HxPars (Venus's keyed settings container) are
    dicts; the liquid-class service answers from `answers["liquid_classes"]` (class name -> dict
    of HxCoreLiquidClass fields); the rest are created and queried for interfaces, nothing more.
    Creating and querying return success (1), as with Venus installed."""
    pid = o.progid.lower()
    if m == "createobject":
      o.progid = str(args[0]) if args else ""
      pid = o.progid.lower()
      if pid in ("scripting.dictionary", "hxparamslib.hxpars"):
        o.dict = {}
      elif pid not in self.MODELLED:
        self.notes.append(f"line {line}: automation object {o.progid} is not modelled")
      return 1
    if m in ("getobject", "getobject2"):
      # query another interface of the same object into the by-reference argument
      if arg_cells and len(arg_cells) > 1 and isinstance(arg_cells[1], Cell):
        target = arg_cells[1].value
        if isinstance(target, Opaque):
          target.progid, target.dict = o.progid, o.dict
        else:
          arg_cells[1].value = o
      return 1
    if m == "releaseobject":
      o.progid, o.dict = "", None
      return 0
    if m == "isnull":
      return int(not o.progid)
    if pid == "scripting.filesystemobject":
      # files the run knows: supplied, written, or a workbook it created; folders always exist
      path = str(args[0]).lower().replace("/", "\\") if args else ""
      if m == "fileexists":
        return int(path in self.files or path in self.written or path in self.workbooks)
      if m in ("folderexists", "createfolder"):
        return 1
      if m == "deletefile":
        for known in (self.files, self.written, self.workbooks):
          known.pop(path, None)
        return 1
      return Unknown(f"Scripting.FileSystemObject.{m}")
    if pid == "hamilton.hxcoreliquidclass":
      if m == "initcoreliquidclass":
        return 0
      if m.startswith("liq"):  # field ids (liqMaxAspirateVolume ...): the field's own name
        return m
      if m == "getliquidclass":
        name = str(args[0]) if args else ""
        table = self.answers.get("liquid_classes", {})
        fields = table.get(name)
        if fields is None:
          raise Stop(f"line {line}: liquid class {name!r} is needed and was not supplied")
        if arg_cells and len(arg_cells) > 1 and isinstance(arg_cells[1], Cell):
          pars = arg_cells[1].value
          if isinstance(pars, Opaque):
            pars.progid, pars.dict = "HXPARAMSLib.HxPars", {k.lower(): v for k, v in fields.items()}
        return 1
    if pid == "hamilton.hxvectordbtracker" and m == "getelementcounter":
      ec = Opaque("object")
      ec.progid = "Hamilton.HxElementCounter"
      return ec
    if pid == "hamilton.hxelementcounter":
      # Venus's persisted tip counters. Supplied ones come from answers["tip_counters"]
      # (counter name -> current position); none supplied means none stored, the library's own
      # "no counter" path, which leaves the tip sequence as the layout has it.
      counters = self.answers.get("tip_counters", {})
      if m == "elementcounternameisvalid":
        return 1
      if m == "getvalidelementcountername":
        return args[0] if args else ""
      if m == "elementcounterexists":
        name = _fmt(args[0]) if args else ""
        if name not in counters:
          self.notes.append(f"line {line}: tip counter {name!r} not supplied: taken as not stored (fresh racks)")
        return int(name in counters)
      if m == "readelementcounterintosequence":
        name = _fmt(args[0])
        seq = args[4] if len(args) > 4 else None
        if isinstance(seq, sq.Sequence) and name in counters:
          if int(counters[name]) > 0:
            seq.set_current_position(int(counters[name]))
          else:  # no tips left: the counter reads as no positions
            seq.set_count(0)
        return 1
      if m in ("writesequenceintoelementcounter", "createelementcounter", "resetelementcounter"):
        return 1
      if m == "getlistofelementcounternames":
        return 1
    if pid == "hxparamslib.hxpars" and o.dict is not None:
      d = o.dict
      if m in ("item1", "item"):
        key = _fmt(args[0]).lower()
        return d[key] if key in d else Unknown(f"HxPars key {args[0]!r}")
      if m in ("add1", "additem", "add"):
        d[_fmt(args[1] if len(args) > 1 else args[0]).lower()] = args[0] if len(args) > 1 else 0
        return 0
      if m == "clear":
        d.clear()
        return 0
      if m in ("count", "itemcount"):
        return len(d)
      if m == "loadfile":
        return Unknown("HxPars.LoadFile")
    if o.progid.lower() == "msscriptcontrol.scriptcontrol":
      if m == "language":
        return "VBScript"
      if m == "eval":
        # Hamilton's libraries use it for VBScript Split("text", "delimiter") only
        mm = re.fullmatch(r'\s*Split\("(.*)",\s*"(.*)"\)\s*', str(args[0]), re.S)
        if mm:
          return HArray(mm.group(1).split(mm.group(2)) if mm.group(2) else [mm.group(1)])
        return Unknown(f"VBScript {str(args[0])[:40]!r}")
    if o.dict is not None:
      d = o.dict
      if m == "exists":
        return int(_fmt(args[0]) in d)
      if m == "add":
        d[_fmt(args[0])] = args[1]
        return 0
      if m == "item":
        return d.get(_fmt(args[0]), Unknown(f"dictionary key {args[0]!r}"))
      if m == "remove":
        d.pop(_fmt(args[0]), None)
        return 0
      if m == "removeall":
        d.clear()
        return 0
      if m == "count":
        return len(d)
      if m == "comparemode":
        return 0
    return Unknown(f"{o.progid or 'object'}.{m}")

  def _seq_element(self, s: sq.Sequence, m, args, line):
    a = [_num(x) for x in args]
    if m == "gettotal":
      return s.total
    if m == "getcount":
      return s.end
    if m == "setcount":
      return s.set_count(int(a[0])) if isinstance(a[0], (int, float)) else self._unknown_arg(s, m)
    if m == "getcurrentposition":
      return s.cur
    if m == "setcurrentposition":
      return s.set_current_position(int(a[0])) if isinstance(a[0], (int, float)) else self._unknown_arg(s, m)
    if m == "getnext":
      return s.get_next()
    if m == "getmax":
      return s.max
    if m == "setmax":
      return s.set_max(int(a[0])) if isinstance(a[0], (int, float)) else self._unknown_arg(s, m)
    if m == "increment":
      return s.increment(int(a[0])) if isinstance(a[0], (int, float)) else self._unknown_arg(s, m)
    if m == "getusedpositions":
      return s.used
    if m == "setusedpositions":
      s.set_used(int(a[0]))
      return 0
    if m == "copysequence":
      if isinstance(args[0], sq.Sequence):
        s.assign(args[0])
      elif args[0] in (0, None) or isinstance(args[0], Unknown):
        s.assign(sq.Sequence(s.name, []))  # CopySequence(null): emptied
      return 0
    if m == "removeat":
      s.remove_at(int(a[0]))
      return 0
    if m == "insertat":
      s.insert_at(int(a[0]), str(args[1]), str(args[2]))
      return 0
    if m == "add":
      if isinstance(args[0], Unknown) or isinstance(args[1], Unknown):
        raise Stop(f"line {line}: {s.name or 'a sequence'}.Add of an unknown position")
      s.add(str(args[0]), str(args[1]))
      return 0
    if m == "deletelabware":
      s.delete_labware(str(args[0]))
      return 0
    if m == "lookupposition":
      return s.lookup_position(str(args[0]), str(args[1]), int(a[2]), bool(a[3]))
    if m == "getlabwareid":
      it = s.current_item()
      return it[0] if it else ""
    if m == "getpositionid":
      it = s.current_item()
      return it[1] if it else ""
    if m == "getname":
      return s.name
    if m == "getsequenceobject":
      return s
    if m == "getpositioncountforcurrlabware":
      it = s.current_item()
      return sum(1 for x in s.items if it and x[0] == it[0])
    if m == "getlabwareids":  # the distinct labware, in order, into the array; their number
      ids = list(dict.fromkeys(lab for lab, _ in s.items))
      if args and isinstance(args[0], HArray):
        args[0].items = ids
      return len(ids)
    if m in ("edit", "edit2"):
      self.notes.append(f"line {line}: {s.name}.{m}: the operator's edit is taken as no change")
      return 0
    if m == "setsequenceproperty":
      s.set_property(int(_num(args[0])), str(args[1]), args[2])
      return 0
    if m == "setsequencepropertyrange":
      s.set_property_range(int(_num(args[0])), int(_num(args[1])), str(args[2]), args[3])
      return 0
    if m == "getsequenceproperty":
      try:
        return s.get_property(int(_num(args[0])), str(args[1]))
      except sq.SequenceError as e:
        raise Stop(f"line {line}: {e}") from None
    if m == "removesequenceproperty":
      s.remove_property(int(_num(args[0])), str(args[1]))
      return 0
    if m == "removeallsequenceproperties":
      s.remove_all_properties(int(_num(args[0])))
      return 0
    return Unknown(f"sequence.{m}")

  def _unknown_arg(self, s, m):
    raise Stop(f"{s.name}.{m} with an unknown argument")

  def _array_element(self, arr: HArray, m, args, obj_expr, env, line):
    a = [_num(x) for x in args]
    if m == "getsize":
      return len(arr.items)
    if m == "setsize":
      n = a[0]
      if not isinstance(n, int):
        return Unknown("SetSize")
      if n < len(arr.items):
        del arr.items[n:]
      else:
        arr.items += [self._default(arr.kind) for _ in range(n - len(arr.items))]
      return 0
    if m == "addaslast":
      v = args[0]
      arr.items.append(v.copy() if isinstance(v, sq.Sequence) else v)
      return 0
    if m == "elementat" or m == "getat":
      i = a[0]
      if isinstance(i, int) and 0 <= i < len(arr.items):
        return arr.items[i]
      raise Stop(f"line {line}: ElementAt({i}) out of bounds ({len(arr.items)})")
    if m == "setat":
      i = a[0]
      if isinstance(i, int):
        while len(arr.items) <= i:
          arr.items.append(self._default(arr.kind))
        v = args[1]
        arr.items[i] = v.copy() if isinstance(v, sq.Sequence) else v
      return 0
    if m == "insertelementat":
      i = a[1] if len(a) > 1 else 0
      arr.items.insert(int(i), args[0])
      return 0
    if m == "removeat" or m == "removeelementat":
      i = a[0]
      if isinstance(i, int) and 0 <= i < len(arr.items):
        del arr.items[i]
      return 0
    if m == "removeall" or m == "removeallelements":
      arr.items.clear()
      return 0
    return Unknown(f"array.{m}")

  def _string_element(self, s: str, m, args, obj_expr, env):
    a = [_num(x) for x in args]
    if m == "getlength":
      return len(s)
    if m == "mid":
      start = int(a[0])
      n = int(a[1]) if len(a) > 1 else len(s)
      return s[start : start + n]
    if m == "left":
      return s[: int(a[0])]
    if m == "right":
      return s[len(s) - int(a[0]):] if int(a[0]) else ""
    if m == "find":
      return s.find(str(args[0]))
    if m == "makeupper":
      v = s.upper()
      self._lvalue(obj_expr, env)(v)
      return v
    if m == "makelower":
      v = s.lower()
      self._lvalue(obj_expr, env)(v)
      return v
    if m == "compare":
      o = str(args[0])
      return (s > o) - (s < o)
    if m == "comparenocase":
      x, y = s.lower(), str(args[0]).lower()
      return (x > y) - (x < y)
    if m == "spanexcluding":
      cs = str(args[0])
      i = 0
      while i < len(s) and s[i] not in cs:
        i += 1
      return s[:i]
    if m == "spanincluding":
      cs = str(args[0])
      i = 0
      while i < len(s) and s[i] in cs:
        i += 1
      return s[:i]
    if m == "reversefind":
      return s.rfind(str(args[0]))
    return Unknown(f"string.{m}")

  # -- files ---------------------------------------------------------------------------------

  def _file_element(self, f: HFile, m, args, arg_exprs, env):
    if m == "addfield":
      name = str(args[0])
      cell = self._args(arg_exprs[1:2], env)[0] if len(arg_exprs) > 1 else Cell(0)
      if not isinstance(cell, Cell):
        cell = Cell(cell)
      f.fields.append((name, cell))
      f.types[name.lower()] = str(args[2]) if len(args) > 2 else "s"
      return 1
    if m == "removefields":
      f.fields.clear()
      f.types.clear()
      return 1
    if m == "setdelimiter":
      f.delimiter = str(args[0]) if args else ","
      return 1
    if m == "open":
      sheet = re.match(r"^(.*\.xlsx?)\s+(\S+)$", str(args[0]), re.I)
      if sheet:
        return self._open_sheet(f, sheet.group(1), sheet.group(2), _num(args[1]) if len(args) > 1 else 1,
                                str(args[2]) if len(args) > 2 else "")
      f.sheet = None
      path = str(args[0]).lower().replace("/", "\\")
      mode = _num(args[1]) if len(args) > 1 else 1
      f.path, f.mode, f.pos = path, mode, 0
      if mode == 1:
        text = self._file_text(path)
        if text is None:
          return self._missing_file(path)
        if f.delimiter == "a":  # hslAsciiText: one field, the whole line; no header
          f.header, f.rows = [], [[ln] for ln in text.splitlines()]
          return 1
        rows = list(csv.reader(io.StringIO(text), delimiter=f.delimiter if f.delimiter in (",", "\t", ";") else ","))
        f.header, f.rows = (rows[0], rows[1:]) if rows else ([], [])
        return 1
      self.written.setdefault(path, [])
      return 1
    if m == "close":
      return 0  # Close returns 0 on success (the editor's code raises on != 0)
    if m == "eof":
      return int(f.pos >= len(f.rows)) if f.mode == 1 else 1
    if m == "readrecord":
      if f.pos >= len(f.rows):
        return 0
      row = f.rows[f.pos]
      f.pos += 1
      by_name = {h.strip().lower(): i for i, h in enumerate(f.header)}
      for k, (name, cell) in enumerate(f.fields):
        i = int(name) - 1 if name.isdigit() else by_name.get(name.lower(), k)
        if f.sheet is not None:  # a sheet's cell as the field's type; an empty one 0 or "" (unverified)
          typ = f.types.get(name.lower(), "s")
          v = row[i] if i < len(row) else None
          cell.value = (0 if typ in ("i", "f") else "") if v is None else (_fmt(v) if typ == "s" else v)
          continue
        cell.value = _num(row[i]) if i < len(row) else ""
      return 1
    if m == "readstring":
      if f.pos >= len(f.rows):
        return Unknown("ReadString past end")
      row = f.rows[f.pos]
      f.pos += 1
      return f.delimiter.join(row)
    if m == "writerecord" and f.sheet is not None:
      conn, table = f.sheet
      cols = {r[1].lower() for r in conn.execute(f"PRAGMA table_info([{table}])")}
      named = [(n, c) for n, c in f.fields if n.lower() in cols]
      conn.execute(f"INSERT INTO [{table}] ({', '.join(f'[{n}]' for n, _ in named)}) VALUES "
                   f"({', '.join('?' for _ in named)})",
                   [c.value if isinstance(c.value, (int, float, str)) else _fmt(c.value) for _, c in named])
      return 1
    if m in ("writerecord", "writestring", "updaterecord"):
      self.written.setdefault(f.path, []).append(
        str(args[0]) if args else ",".join(_fmt(c.value) for _, c in f.fields))
      return 1
    if m == "seek":
      f.pos = 0
      return len(f.rows)
    return Unknown(f"file.{m}")

  def _open_sheet(self, f: HFile, book: str, sheet: str, mode, sql: str):
    """Open a workbook sheet: write (2) creates it from the fields, read (1) runs `sql` (all rows
    when none; `[Sheet$]` names the sheet, Jet's way), append (3) adds the records written. Text
    compares without case, as Jet's does."""
    conn = self.workbooks.setdefault(book.lower().replace("/", "\\"), sqlite3.connect(":memory:"))
    table = sheet.rstrip("$")
    f.sheet, f.mode, f.pos, f.header, f.rows = (conn, table), mode, 0, [], []
    if mode == 2:
      kind = {"i": "INTEGER", "f": "REAL"}
      conn.execute(f"DROP TABLE IF EXISTS [{table}]")
      conn.execute(f"CREATE TABLE [{table}] ("
                   + ", ".join(f"[{n}] {kind.get(f.types.get(n.lower()), 'TEXT COLLATE NOCASE')}" for n, _ in f.fields) + ")")
      return 1
    if mode == 1:
      try:
        cur = conn.execute(re.sub(r"\[(\w+)\$\]", r"[\1]", sql or f"SELECT * FROM [{table}]"))
      except sqlite3.Error as e:
        self.notes.append(f"workbook {book} {sheet}: {e}")
        return 0
      if cur.description:
        f.header, f.rows = [d[0] for d in cur.description], [list(r) for r in cur.fetchall()]
      return 1
    return 1

  def _file_text(self, path: str) -> Optional[str]:
    if path in self.files:
      return self.files[path]
    name = pathlib.PureWindowsPath(path).name.lower()
    for k, v in self.files.items():
      if pathlib.PureWindowsPath(k).name.lower() == name:
        return v
    return None

  def _missing_file(self, path):
    raise Stop(f"the method reads {path}, which was not supplied")

  # -- device steps --------------------------------------------------------------------------

  def _binding(self, rec: stp_pars.Record, raw: str, env):
    """A record value: a literal, or `<expr>` naming a method variable, evaluated here."""
    if raw.startswith("<") and raw.endswith(">"):
      expr = raw[1:-1]
      try:
        p = Parser(lex(expr))
        e = p.expr()
      except SyntaxError:
        return Unknown(f"binding {raw}")
      if e[0] == "index" and e[2][0] == "un":  # `arr[*1]`: from element 1 on
        return Unknown(f"array binding {raw}")
      v = self.eval(e, env)
      return v.value if isinstance(v, Cell) else v
    return _num(raw)

  def _device_step(self, dev, method, args, env, line):
    guid = str(args[0]) if args else ""
    rec = self.stps.get(guid)
    name = getattr(dev, "name", "?")
    if rec is None:
      self.notes.append(f"line {line}: step {guid} has no .stp record")
      return HArray([name, "?", "0"])
    top = {}
    for path, key, value in rec.readable():
      if path == "" and key not in top:
        top[key] = value
    command = rec.step_name
    iswap_plate = command in ("GetPlate", "PutPlate", "MovePlate", "OpenGripper") and top.get("PlateObject")
    if command in ("ZSwapGetPlate", "ZSwapPlacePlate") or iswap_plate:
      return self._transport_step(rec, command, guid, name, top, env, line)
    if command in ("Head96Move", "MoveToPosition", "FirmwareCommand") or (
        command == "Head96TipEject" and not top.get("SequenceObject")):
      return self._move_step(rec, command, guid, name, top, env, line)
    seq_raw = top.get("SequenceObject", "")
    if not seq_raw or command in ("GetPlate", "PutPlate", "MovePlate",
                                   "Initialize", "LoadCarrier", "UnloadCarrier", "FirmwareCommand"):
      self._event(command, guid, name, None, {}, {}, 0, 0, "", "", env, note=self._move_note(top, env))
      return self._success(name, command, {})
    seq = self._binding(rec, seq_raw, env)
    if not isinstance(seq, sq.Sequence):
      raise Stop(f"line {line}: {command} on {seq_raw}, which is not a known sequence ({seq!r})")
    counting = self._binding(rec, top.get("SequenceCounting", "1"), env)
    if isinstance(counting, Unknown):
      raise Stop(f"line {line}: {command}: sequence counting unknown ({counting.why})")
    head = command.startswith("Head96") or command.startswith("Head384")
    if head:
      pattern = top.get("ChannelPattern", "1" * 96)
      pat = self._binding(rec, pattern, env) if pattern.startswith("<") else pattern
      positions = str(pat).count("1") if isinstance(pat, str) and pat else 96
      taken = sq.take_head96(seq, int(counting), positions=positions or 96)
      pat_s = str(pat)
    else:
      pat = self._binding(rec, top.get("ChannelPattern", "11111111"), env)
      if isinstance(pat, Unknown):
        raise Stop(f"line {line}: {command}: channel pattern unknown ({pat.why})")
      pat_s = str(pat)
      use = self._binding(rec, top.get("Optimizing channel use", "1"), env)
      if isinstance(use, Unknown):
        raise Stop(f"line {line}: {command}: channel use unknown ({use.why})")
      if command in ("TipEject", "XLTipEject") and not seq.items:
        self._event(command, guid, name, seq, {}, {}, 0, 0, counting, pat_s, env, note="default waste")
        return self._success(name, command, {})
      taken = sq.take(seq, pat_s[:16], int(counting), int(use))
    vols = self._volumes(rec, taken.channels, env)
    settings = self._channel_settings(rec, taken.channels, top, env)
    self._event(command, guid, name, seq, taken.channels, vols, taken.first, taken.used, counting, pat_s, env,
                settings=settings)
    return self._success(name, command, taken.channels)

  # Top-level settings of a pipetting step worth recording beside its per-channel ones
  STEP_SETTINGS = ("TipType", "DispenseMode", "SameLiquid", "SideTouchMode")

  def _channel_settings(self, rec: stp_pars.Record, channels, top, env) -> dict[str, Any]:
    """A pipetting step's settings, bound: the per-channel block's for the channels it used, one
    value where they agree and a list (channel order) where they do not, plus STEP_SETTINGS."""
    per: dict[str, list] = {}
    block = next((v for k, v in rec.tree if stp_pars.key_id(k) == "-534183936" and isinstance(v, list)), None)
    for ch_key, sub in block or []:
      if not isinstance(sub, list):
        continue
      try:
        ch = int(stp_pars.key_id(ch_key))
      except ValueError:
        continue
      if ch not in channels:
        continue
      for k, v in sub:
        if isinstance(v, list) or stp_pars.key_id(k).lstrip("-").isdigit() and stp_pars.key_name(k) == stp_pars.key_id(k):
          continue
        val = self._channel_value(rec, str(v).strip('"'), sub, ch, env)
        per.setdefault(stp_pars.key_name(k), []).append(val)
    out: dict[str, Any] = {k: (vs[0] if all(x == vs[0] for x in vs) else vs) for k, vs in per.items()}
    for k in self.STEP_SETTINGS:
      if k in top:
        out[k] = self._setting(rec, top[k], env)
    return out

  # A CO-RE gripper step's settings, by the names `_transport_step` records them under
  TRANSPORT_SETTINGS = ("GripperAccessHeight", "ZSwapPlateCheck", "ToolUpperChannel", "ToolEject",
                        "grip width", "grip force", "grip speed", "grip opening", "z speed",
                        "x acceleration", "plate press",
                        # the iSWAP's (GetPlate / PutPlate)
                        "InversGripping", "GrippLargeSite", "LabwareOrientation", "TransportMode",
                        "lift up height", "retract distance")

  def _transport_step(self, rec, command, guid, name, top, env, line):
    """A CO-RE gripper or iSWAP get or place: the plate (`PlateObject`) or lid (`CapObject`) sequence's
    current item, not consumed (the library's steps count manually), and the settings bound."""
    raw = top.get("PlateObject") or top.get("CapObject", "")
    seq = self._binding(rec, raw, env)
    if not isinstance(seq, sq.Sequence):
      raise Stop(f"line {line}: {command} on {raw}, which is not a known sequence ({seq!r})")
    item = seq.current_item()
    settings = {}
    for path, key, value in rec.readable():
      if path in ("", "/gripper") and key in self.TRANSPORT_SETTINGS and key not in settings:
        settings[key] = self._setting(rec, value, env)
    self._event(command, guid, name, seq, {1: item} if item else {}, {}, seq.cur, 0, 0, "", env,
                settings=settings)
    return self._success(name, command, {})

  MOVE_SETTINGS = ("MoveType", "MoveDirection", "MoveAbsDistance", "MoveRelDistance", "MoveZEndMode",
                   "UsePickUpPosition", "firmware command string", "firmware parameter string")

  def _move_step(self, rec, command, guid, name, top, env, line):
    """A move (96-head or channels), firmware command or 96-head eject to a known position: its
    sequence's current item, not consumed, and its settings bound."""
    seq, item = None, None
    if top.get("SequenceObject"):
      seq = self._binding(rec, top["SequenceObject"], env)
      if not isinstance(seq, sq.Sequence):
        raise Stop(f"line {line}: {command} on {top['SequenceObject']}, not a known sequence ({seq!r})")
      item = seq.current_item()
    settings = {}
    for path, key, value in rec.readable():
      if key in self.MOVE_SETTINGS and key not in settings:
        v = self._setting(rec, value, env)
        settings[key] = v.strip('"') if isinstance(v, str) else v
    self._event(command, guid, name, seq, {1: item} if item else {}, {}, seq.cur if seq else 0, 0, 0, "",
                env, settings=settings)
    return self._success(name, command, {})

  def _setting(self, rec, raw: str, env):
    """A record value, where a bare name a variable holds (as the `/gripper` block keeps them) is
    that variable's value."""
    if re.fullmatch(r"[A-Za-z_]\w*", raw or ""):
      c = self._cell(raw, env)
      if c is not None:
        return c.value
    return self._binding(rec, raw, env)

  def _volumes(self, rec: stp_pars.Record, channels, env) -> dict[int, Any]:
    out: dict[int, Any] = {}
    tree = rec.tree
    block = next((v for k, v in tree if stp_pars.key_id(k) == "-534183936" and isinstance(v, list)), None)
    if not block:
      return out
    for ch_key, sub in block:
      if not isinstance(sub, list):
        continue
      try:
        ch = int(stp_pars.key_id(ch_key))
      except ValueError:
        continue
      d = {stp_pars.key_id(k): v for k, v in sub if not isinstance(v, list)}
      raw = d.get("-534183924") or d.get("-534183908")
      if raw is None or ch not in channels:
        continue
      out[ch] = self._channel_value(rec, raw.strip('"'), sub, ch, env)
    return out

  _SERIES = re.compile(r"^<?([A-Za-z_]\w*)\[\*(\w*)\]>?$")

  def _channel_value(self, rec, raw: str, sub, ch: int, env):
    """A per-channel value: a literal, a bound variable, or a series of an array (`arr[*]`,
    `arr[*k]`): the HSL help's "multiple array value", element one to channel one from the start
    index, the record giving each channel's offset (ArrayAddIndex) and start (ArrayStartIndex)."""
    m = self._SERIES.match(raw)
    if m is None:
      return self._setting(rec, raw, env)
    name, start_txt = m.group(1), m.group(2)
    add, start = ch, None
    for k, v in sub:
      if isinstance(v, list) and stp_pars.key_name(k).lower() == name.lower():
        for _kid, entries in v:
          if isinstance(entries, list):
            e = {stp_pars.key_name(a).lstrip("3"): b for a, b in entries}
            add = int(e.get("ArrayAddIndex", add))
            start = e.get("ArrayStartIndex")
    if start is None:
      start = start_txt or 1
    start = self._setting(rec, str(start), env)
    c = self._cell(name, env)
    arr = c.value if c is not None else None
    if not isinstance(arr, HArray) or not isinstance(start, (int, float)):
      return Unknown(f"array series {raw}")
    i = int(start) + add - 2  # one-based start, one-based channel offset
    return arr.items[i] if 0 <= i < len(arr.items) else Unknown(f"{name}[{i + 1}] past the array's end")

  def _move_note(self, top, env) -> str:
    return ", ".join(f"{k}={v}" for k, v in top.items() if "Sequence" in k and v)

  def _event(self, command, guid, dev, seq, channels, vols, first, used, counting, pattern, env, note="",
             settings=None):
    self.events.append(StepEvent(len(self.events) + 1, command, guid, dev, seq.name if seq else "",
                                 dict(channels), vols, first, used, counting, pattern,
                                 tuple(self.stack), note, settings or {}))

  @staticmethod
  def _success(dev, command, channels) -> HArray:
    blocks = "".join(f"[{ch},0,0,0,,{lab},{pos}" for ch, (lab, pos) in sorted(channels.items()))
    return HArray([dev, command, "0" + blocks])


def _fmt(v) -> str:
  if isinstance(v, float):
    return repr(v) if not v.is_integer() else str(int(v))
  if isinstance(v, Unknown):
    return "?"
  return str(v)


# -- entry points ------------------------------------------------------------------------------


def prepare(hsl_path: pathlib.Path, roots: Iterable[pathlib.Path], stps: dict[str, stp_pars.Record],
            layouts: dict[str, Any], files: Optional[dict[str, str]] = None,
            answers: Optional[dict[str, Any]] = None) -> Run:
  """Preprocess and parse a method with its includes; a Run ready to `run()`."""
  def read(p: pathlib.Path) -> str:
    return p.read_text(encoding="latin-1")

  pre = Preprocessor(roots, read)
  text = pre.expand(hsl_path)
  parser = Parser(lex(text))
  parser.unit()
  run = Run(parser, stps, layouts, files, answers)
  run.src = text.splitlines()
  if pre.missing:
    run.notes.append("includes not found: " + ", ".join(sorted(set(pre.missing))))
  return run


def render(run: Run, limit: Optional[int] = None) -> list[str]:
  """The run as lines: each device step with what each channel used."""
  out = []
  for ev in run.events[:limit]:
    where = " > ".join(ev.stack[-3:])
    head = f"{ev.index:4d} {ev.command}"
    if ev.sequence:
      head += f" on {ev.sequence} [{ev.first}..{ev.first + ev.used - 1}]" if ev.used else f" on {ev.sequence} (none)"
    out.append(f"{head}   ({where})" + (f"  {ev.note}" if ev.note else ""))
    if ev.channels:
      parts = []
      for ch, (lab, pos) in sorted(ev.channels.items()):
        vol = ev.volumes.get(ch)
        parts.append(f"{ch}:{lab},{pos}" + (f" {_fmt(vol)}uL" if vol is not None else ""))
      out.append("       " + "  ".join(parts))
  if run.stopped:
    out.append(f"STOPPED: {run.stopped}")
  return out
