"""What the port tests share: running HSL in the interpreter, and recording a port's PLR calls.

A port test runs the same calls through the real library (`hsl_run`) and through the port (with
`RecordingDeck` and `RecordingChannels` standing in for the deck and the STAR's channels), then
compares `steps_of(run)` with the recorder's events: per step the command, the (labware, position)
per channel, and for aspirates and dispenses the settings (the record's against the PLR arguments
passed and the Venus settings the port meant, through `venus_interop.plr.steps`).
"""
from __future__ import annotations

import functools
import pathlib
from typing import Any, Iterable, Optional

from venus_interop.methods import hsl_eval, protocol, sequences as sq


DISPLAY_ONLY = {"VectorCustomDialogs::AppendStatusText"}  # status-window texts: nothing reads them

# Libraries the NGSStar framework includes that are on no machine here: the functions called are
# declared (put the text in the test's source) and answered by models made from their names, not
# checked against the HSL. ArrayTools:
ARRAYTOOLS = ('namespace _Method { namespace ARRAYTOOLS {\n'
              'function get_distinct_from_array(variable & i_arr[], variable & o_arr[]) void { variable stub; }\n'
              'function ArrayVLookUp(variable & i_values[], variable & i_keys[], variable i_key, variable & o_arr[]) void '
              '{ variable stub; }\n'
              'function Lookup(variable & i_arr[], variable i_value) variable { variable v; return(v); }\n'
              'function Update_Value_in_Array(variable & io_arr[], variable i_value, variable i_index) void '
              '{ variable stub; }\n'
              '} }\n'
              # StringTokenizer\StrTokenize.hs_
              'namespace _Method { namespace STRTOKENIZE {\n'
              'function StrTokenize(variable i_str, variable i_delimiter, variable & o_arr[], variable i_flag) void '
              '{ variable stub; }\n} }\n')
# VectorCustomDialogs (a compiled dialog component): the dialogs a test answers, and their constants
VECTORCUSTOMDIALOGS = (
  'namespace _Method { namespace VECTORCUSTOMDIALOGS {\n'
  'namespace IconType { const variable Information(0); const variable Warning(1); const variable Question(2); '
  'const variable Error(3); }\n'
  'namespace ButtonType { const variable Ok(0); const variable OkCancel(1); const variable YesNo(4); '
  'const variable AcceptCancel(5); }\n'
  'namespace RadioButtonDialog { namespace WrapOrientation { const variable Vertical(1); } '
  'namespace SortDirection { const variable Unsorted(0); } }\n'
  'function RadioButtonDialog(variable i_title, variable i_buttons, variable i_x, variable i_y, variable i_top, '
  'variable i_bottom, variable & i_labels[], variable & i_tips[], variable & i_editable[], variable & io_selected[], '
  'variable & i_groups[], variable i_wrap, variable i_sort) variable { variable v; return(v); }\n'
  'function LoadingDialogSetResources(variable & i_columns[]) variable { variable v; return(v); }\n'
  'function LoadingDialog(variable i_title, variable i_buttons, variable i_x, variable i_y, variable i_timeout, '
  'variable i_top, variable i_bottom, variable i_image, variable i_small, variable i_flag, variable & i_col1[], '
  'variable & i_col2[], variable & i_col3[]) variable { variable v; return(v); }\n'
  'function ListDialog(variable i_title, variable i_icon, variable i_buttons, variable i_x, variable i_y, '
  'variable i_timeout, variable i_top, variable i_bottom, variable & i_items[]) variable { variable v; return(v); }\n'
  'function MessageDialog(variable i_title, variable i_icon, variable i_buttons, variable i_x, variable i_y, '
  'variable i_timeout, variable i_text) variable { variable v; return(v); }\n'
  # the status window: TRUE, as the libraries' bind check wants it
  'function AppendStatusText(variable i_text) variable { variable v; v = 1; return(v); }\n'
  'function ErrorDialog(variable i_title, variable i_icon, variable i_buttons, variable i_x, variable i_y, '
  'variable i_timeout, variable i_text, variable i_bottom) variable { variable v; return(v); }\n'
  '} }\n')
# and Create Channel Pattern.hs_ (bodies that are only a return would be dropped as placeholders)
CREATE_CHANNEL_PATTERN = ('namespace _Method { namespace CREATE_CHANNEL_PATTERN {\n'
                          'function Create_Channel_Pattern(variable i_first, variable i_count, variable i_channels, '
                          'variable & o_pattern) void { variable stub; }\n} }\n')

# and Aliquot\Aliquot_for_EasySteps v2.hs_
ALIQUOT = ('namespace _Method { namespace ALIQUOT_FOR_EASYSTEPS_V2 {\n'
           'function CalcAliquot_v2_1(sequence & i_seq, variable i_volume, variable i_pre, variable i_reserve, '
           'variable i_capacity, variable & o_loops, variable i_channels, variable i_rows, variable & o_aspirate[], '
           'variable & o_mix[], variable & o_patterns[], variable & o_pattern) void { variable stub; }\n} }\n')


def _aliquot(run, p):  # the port's reading of it
  from venus_interop.plr.libraries.ngsstar_processes import CalcAliquot_v2_1

  s = p["i_seq"].value
  a = CalcAliquot_v2_1(s.end - s.cur + 1 if s.cur > 0 else 0,
                       *(float(p[k].value) for k in ("i_volume", "i_pre", "i_reserve", "i_capacity")),
                       int(p["i_channels"].value), int(p["i_rows"].value))
  p["o_loops"].value, p["o_pattern"].value = a.loops, a.aspirate_pattern
  for k, v in (("o_aspirate", a.aspirate), ("o_mix", a.mix), ("o_patterns", a.dispense_patterns)):
    p[k].value = hsl_eval.HArray(list(v))
  return 0


def _distinct(run, p):  # the distinct values, in order of first appearance
  p["o_arr"].value = hsl_eval.HArray(list(dict.fromkeys(p["i_arr"].value.items)))
  return 0


def _vlookup(run, p):  # the values whose key is the one looked up, in order
  keys, values = p["i_keys"].value.items, p["i_values"].value.items
  p["o_arr"].value = hsl_eval.HArray([v for k, v in zip(keys, values) if k == p["i_key"].value])
  return 0


def _channel_pattern(run, p):  # the port's reading of it
  from venus_interop.plr.libraries.ngsstar_processes import NGSStarProcesses
  p["o_pattern"].value = NGSStarProcesses.CREATE_CHANNEL_PATTERN(
    *(int(p[k].value) for k in ("i_first", "i_count", "i_channels")))
  return 0


def _update_value(run, p):  # the element at the 1-based index set to the value (inferred from its name)
  p["io_arr"].value.items[int(p["i_index"].value) - 1] = p["i_value"].value
  return 0


def _lookup(run, p):  # the 1-based index of the first element equal to the value; 0 when none
  items = p["i_arr"].value.items
  return next((i for i, v in enumerate(items, start=1) if v == p["i_value"].value), 0)


def _tokenize(run, p):  # as its source (VenusPackages): tokens trimmed, appended; FALSE drops empty ones
  text, delim = str(p["i_str"].value), str(p["i_delimiter"].value)
  tokens = [t.strip() for t in text.split(delim)] if text and delim else []
  keep = bool(int(_num_or_0(p["i_flag"].value)))
  out = p["o_arr"].value
  items = list(out.items) if isinstance(out, hsl_eval.HArray) else []
  p["o_arr"].value = hsl_eval.HArray(items + [t for t in tokens if t or keep])
  return 0


def _num_or_0(v):
  try:
    return float(v)
  except (TypeError, ValueError):
    return 0


ARRAYTOOLS_MODELS = {"arraytools::get_distinct_from_array": _distinct, "arraytools::arrayvlookup": _vlookup,
                     "arraytools::lookup": _lookup, "strtokenize::strtokenize": _tokenize,
                     "arraytools::update_value_in_array": _update_value,
                     "create_channel_pattern::create_channel_pattern": _channel_pattern,
                     "aliquot_for_easysteps_v2::calcaliquot_v2_1": _aliquot}


@functools.lru_cache(maxsize=4)
def _parsed(src: str, here: pathlib.Path, roots: tuple, stp_paths: tuple):
  pre = hsl_eval.Preprocessor(list(roots), lambda p: p.read_text(encoding="latin-1"))
  text = pre.expand(here, text=src)
  parser = hsl_eval.Parser(hsl_eval.lex(text))
  parser.unit()
  return parser, protocol.load_stps(list(stp_paths)), text.splitlines()


def hsl_run(src: str, here: pathlib.Path, roots: Iterable[pathlib.Path], stp_paths: Iterable[pathlib.Path],
            layouts: dict, answers: Optional[dict] = None, allow_unresolved: Iterable[str] = (),
            max_steps: int = 2_000_000, stops: Optional[str] = None, files: Optional[dict] = None) -> hsl_eval.Run:
  """Preprocess, parse and run `src` (a method's text, as if at `here`); it must run to the end and
  call no function that neither the sources nor the run define (the interpreter would carry on
  with an unknown value, so a library missing from the roots goes unnoticed), except those in
  DISPLAY_ONLY and `allow_unresolved`. The same source is parsed once: a test whose cases differ
  only in their inputs can give them through functions answered per run (`answers["functions"]`).
  `stops`: the run is to stop on an error whose text holds this (what Venus would raise). `files`:
  the run's virtual files (path -> text), for what the library reads."""
  parser, stps, lines = _parsed(src, here, tuple(roots), tuple(sorted(stp_paths)))
  run = hsl_eval.Run(parser, stps, layouts, files=files, answers=answers or {}, max_steps=max_steps)
  run.src = lines
  run.run()
  if stops is None:
    assert run.stopped is None, run.stopped
  else:
    assert run.stopped is not None and stops in run.stopped, run.stopped
  missing = set(run.unresolved) - DISPLAY_ONLY - set(allow_unresolved)
  assert not missing, f"functions the library calls that nothing defines: {sorted(missing)}"
  return run


def pipetting(command: str, settings: dict, volumes: dict, channels) -> dict[str, Any]:
  """A recorded aspirate's or dispense's settings, as a port's would be recorded."""
  from venus_interop.plr import steps

  step = steps.Pipetting.from_record(settings)
  out = steps.plr_arguments(step, len(channels), command == "Aspirate")
  out["venus"] = step.effective()
  vols = [volumes.get(c) for c in sorted(channels)]
  # "Drain tip in jet mode" (dispense mode 9): the tip emptied, the record's volume 0 (Venus's help);
  # a port dispenses what its tips hold, which its own test checks
  drain = command == "Dispense" and int(settings.get("dispense mode", 0) or 0) == 9
  if all(isinstance(v, (int, float)) for v in vols) and not drain:
    out["volumes"] = [float(v) for v in vols]
  return out


def steps_of(run: hsl_eval.Run, label=lambda e: "") -> list[tuple]:
  """(command, channel -> item, label(event), settings) per device step of the run."""
  out = []
  for e in run.events:
    settings = pipetting(e.command, e.settings, e.volumes, e.channels) if e.command in ("Aspirate", "Dispense") else {}
    out.append((e.command, dict(e.channels) if e.command != "TipEject" else {}, label(e), settings))
  return out


REPORT_BOOK = "report.xls"  # the run report a test points the NGSStar libraries at (t_str*FullPathReportFile)
CLOCK = (2026, 10, 19, 14, 5, 9, 0, 292, -1)  # the time stamped report rows take, on both sides


def report_rows(run: hsl_eval.Run, book: str = REPORT_BOOK) -> list[dict[str, str]]:
  """The rows the run appended to the report's RuntimeReport sheet, every cell as text."""
  conn = run.workbooks.get(book)
  if conn is None:
    return []
  cur = conn.execute("SELECT * FROM [RuntimeReport]")
  names = [d[0] for d in cur.description]
  return [{n: hsl_eval._fmt(v) if v is not None else "" for n, v in zip(names, r)} for r in cur.fetchall()]


class RecordingDeck:
  """The layout's sequences as live state, one object per name; an item stands for its resource."""

  def __init__(self, lay):
    self.sequences = {s.name: list(s.items) for s in lay.sequences}
    self.live = {name: sq.Sequence(name, list(items)) for name, items in self.sequences.items()}

  def seq(self, name):
    return name if isinstance(name, sq.Sequence) else self.live[name]

  def resolve(self, item):
    return item

  def resource(self, name):
    return name


class RecordingChannels:
  """The STAR's channels, recording; `with` it to see the Venus settings the port meant."""

  def __init__(self, label=lambda command, kw: "", measured: float = 0.0):
    self.events: list[tuple] = []
    self.meant: list = []
    self.label = label
    self.measured = measured  # what a liquid search finds in every container, in uL

  def __enter__(self):
    from venus_interop.plr import steps
    steps.OBSERVERS[:] = [lambda command, channels, step: self.meant.append(step.effective())
                          if command in ("Aspirate", "Dispense") else None]
    return self

  def __exit__(self, *exc):
    from venus_interop.plr import steps
    steps.OBSERVERS.clear()

  def _log(self, command, items, channels, label="", settings=None):
    self.events.append((command, dict(zip([c + 1 for c in channels], items)), label, settings or {}))

  async def pick_up_tips(self, spots, use_channels):
    self._log("TipPickUp", spots, use_channels)

  async def discard_tips(self, use_channels):
    self.events.append(("TipEject", {}, "", {}))

  async def probe_liquid_volumes(self, containers, use_channels, **kw):
    self._log("Probe", containers, use_channels)
    return [self.measured] * len(containers)

  def _pipette(self, command, wells, vols, use_channels, kw):
    settings = {k: v for k, v in kw.items() if k not in ("hamilton_liquid_classes", "empty")}
    settings["venus"] = self.meant.pop(0)
    settings["volumes"] = [float(v) for v in vols]
    self._log(command, wells, use_channels, self.label(command, kw), settings)

  async def aspirate(self, wells, vols, use_channels, **kw):
    self._pipette("Aspirate", wells, vols, use_channels, kw)

  async def dispense(self, wells, vols, use_channels, **kw):
    self._pipette("Dispense", wells, vols, use_channels, kw)


def assert_same_steps(library: list[tuple], port: list[tuple]) -> None:
  """Step for step; a volume the interpreter left unresolved (none here) is not compared."""
  assert len(library) == len(port), f"{len(library)} steps in the library, {len(port)} in the port"
  for i, (a, b) in enumerate(zip(library, port)):
    if a[3] and "volumes" not in a[3]:
      b = (*b[:3], {k: v for k, v in b[3].items() if k != "volumes"})
    assert a == b, f"step {i}: library {a}, port {b}"
