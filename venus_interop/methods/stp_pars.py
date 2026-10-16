"""HxPars step-settings records inside Venus .stp files.

A device step's settings live in the .stp beside the file that holds the step,
keyed by the step GUID. `files.hxcfg` reads the sections; this module parses the
item stream into a tree and makes the keys readable.

Three facts make the numeric keys decodable (measured over the 407 HxPars
records in the session corpus, 2026-10-15):

- Item keys carry a type prefix: `1Key` string, `3Key` int, `5Key` double,
  `10Key` object reference. Block names (`(Errors`, `(-534183936`) carry none.
- Every numeric key that ever holds a method variable is named in the record's
  own `(Variables ...)` block: variable -> opcode/value pairs, where `10` points
  at a top-level key, `30` at a block key, `31` at a sub-index and `32` at the
  key inside that block. A key named there is named for every record that has it.
- The keys no record binds to a variable are either constants (same value in
  every record of the corpus) or named by the method variable bound to a
  neighbouring key in the same block (gripper settings).

What stays open is recorded in CONVENTIONS.md §11, not guessed here.
"""
from __future__ import annotations

import dataclasses
import re
from typing import Optional, Union

# Key ids with their measured names. Named by the (Variables) self-documentation
# unless noted; several keys take different prefix names on the aspirate and
# dispense side of the same record (the key is the same, the setting differs).
KEY_NAMES = {
  "-534118376": "command id",  # per-command registry number; mapping to command names is open
  "-534183936": "channels",  # the per-channel pipetting block; sub-blocks keyed by channel
  "-534183935": "gripper",  # iSWAP / CO-RE gripper and wash-station block
  "-534183813": "pLLD sensitivity",
  "-534183908": "dispense volume",
  "-534183909": "dispense mode",
  "-534183913": "mix position",  # also the pre-rinsing mix position of a pre-rinsing block
  "-534183914": "mix cycles",
  "-534183915": "mix volume",
  "-534183918": "max height difference",
  "-534183919": "cLLD sensitivity",
  "-534183924": "aspirate volume",
  "-534183926": "submerge depth",
  "-534183928": "fluid height",
  "-534183933": "aspirate mode",
  # gripper block
  "-534183672": "z speed",
  "-534183774": "grip width",
  "-534183775": "grip force",
  "-534183747": "grip opening",
  "-534183694": "gripper mode 694",  # constant 1 in corpus
  "-534183773": "gripper mode 773",  # constant 2 in corpus
  "-534183743": "lift up height",
  "-534183744": "retract distance",
  "-534183645": "x acceleration",
  "-534183723": "plate press",
  "-534183682": "grip speed",
  "-534183815": "firmware parameter string",
  "-534183816": "firmware command string",
  "-534183808": "wash flow rate 1",
  "-534183809": "wash soak time 1",
  "-534183810": "wash rinse time 1",
  "-534183797": "wash start liquid",
  # constants in the corpus: named for completeness, never vary, not rendered
  "-534183876": "channel constant 876",  # always 1
  "-534183920": "channel constant 920",  # always 0
  "-534183925": "channel constant 925",  # always 0
  "-534183629": "channel constant 629",  # always 0
  "-534183700": "channel constant 700",  # always 0.5
  # open (CONVENTIONS §11): value varies 0/5/7/10/18 in the corpus
  "-534183622": "detect mode (open)",
}

_PREFIX = re.compile(r"^(\d+)(-|[A-Za-z_])(.*)$")
_NUMKEY = re.compile(r"^-?\d{6,}$")
_TYPES = {"1", "3", "5", "10"}

Node = list[tuple[str, Union[str, "Node"]]]


def parse(items: list[str]) -> Node:
  """The flat item stream of a section into a tree of (key, value-or-node) pairs."""
  pos = 0

  def block() -> Node:
    nonlocal pos
    out: Node = []
    while pos < len(items):
      tok = items[pos]
      if tok == ")":
        pos += 1
        return out
      if tok.startswith("("):
        pos += 1
        out.append((tok[1:], block()))
        continue
      key = tok
      pos += 1
      if pos < len(items) and not items[pos].startswith("(") and items[pos] != ")":
        out.append((key, items[pos]))
        pos += 1
      else:
        out.append((key, ""))
    return out

  return block()


def _split(key: str) -> tuple[str, str]:
  """(type prefix, key) for `1Name`/`3-534183924`/`10Object`; ("", key) otherwise."""
  m = _PREFIX.match(key)
  if m and m.group(1) in _TYPES:
    return m.group(1), m.group(2) + m.group(3)
  return "", key


def key_name(key: str) -> str:
  _, k = _split(key)
  return KEY_NAMES.get(k, k)


def key_id(key: str) -> str:
  return _split(key)[1]


@dataclasses.dataclass
class Record:
  name: str  # the section name: the step GUID
  tree: Node

  @property
  def top(self) -> dict[str, str]:
    """Scalar top-level keys, without the type prefix."""
    out = {}
    for k, v in self.tree:
      if not isinstance(v, list):
        out[key_id(k)] = v
    return out

  @property
  def step_name(self) -> str:
    return self.top.get("StepName", "")

  @property
  def variable_bindings(self) -> dict[str, list[tuple[str, str, str]]]:
    """(Variables) entries: var name -> [(block id, sub-index, key id), ...].

    Opcode 10 entries become ("", "", key); opcode 30/31/32 describe where the
    variable is stored inside a block.
    """
    out: dict[str, list[tuple[str, str, str]]] = {}
    for k, v in self.tree:
      if key_id(k) != "Variables" or not isinstance(v, list):
        continue
      for _slot, entries in v:
        if not isinstance(entries, list):
          continue
        for var, subs in entries:
          if not isinstance(subs, list):
            continue
          for _op, val in subs:
            if not isinstance(val, list):
              continue
            vd = {a: b for a, b in val}
            if "10" in vd:
              out.setdefault(var, []).append(("", "", vd["10"]))
            elif "30" in vd:
              out.setdefault(var, []).append((vd["30"], vd.get("31", ""), vd.get("32", "")))
    return out

  def resolve(self, var: str) -> Optional[str]:
    """The value a variable-name setting points at, if it is a literal."""
    for block_id, sub, key in self.variable_bindings.get(var, []):
      if block_id == "" and sub == "":
        return self.top.get(key)
      for k, v in self.tree:
        if key_id(k) == block_id and isinstance(v, list):
          for sk, sv in v:
            if key_id(sk) == sub and isinstance(sv, list):
              for kk, vv in sv:
                if key_id(kk) == key:
                  return vv if not isinstance(vv, list) else ""
    return None

  def readable(self) -> list[tuple[str, str, str]]:
    """(path, setting name, value) for every scalar, variables kept symbolic."""
    out: list[tuple[str, str, str]] = []
    binds = self.variable_bindings

    def walk(node: Node, path: str):
      for k, v in node:
        name = key_name(k)
        if isinstance(v, list):
          walk(v, f"{path}/{name}" if not re.match(r"^\d+$", k) else path)
          continue
        if k.startswith("10") or _NUMKEY.match(key_id(k)) and key_id(k) not in KEY_NAMES:
          continue
        if key_id(k) in ("-534118376", "CommandStepFileGuid", "ParsCommandVersion", "Timestamp", "StepName"):
          continue
        if key_id(k) in binds:  # the variable-slot index, not the setting
          continue
        val = v
        var = [b for b in binds if any(kid == key_id(k) and (bid == "" or path.endswith(key_name(bid))) for bid, _s, kid in binds[b])]
        if var:
          val = f"<{var[0]}>" if v == "" or v == var[0] else f"<{var[0]}> {v}"
        out.append((path, name, val))

    walk(self.tree, "")
    return out


def record(section: "object") -> Record:
  """A Record from an hxcfg section that holds HxPars items."""
  return Record(section.name, parse(section.items or []))
