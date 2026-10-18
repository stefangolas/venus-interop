"""What the port tests share: running HSL in the interpreter, and recording a port's PLR calls.

A port test runs the same calls through the real library (`hsl_run`) and through the port (with
`RecordingDeck` and `RecordingChannels` standing in for the deck and the STAR's channels), then
compares `steps_of(run)` with the recorder's events: per step the command, the (labware, position)
per channel, and for aspirates and dispenses the settings (the record's against the PLR arguments
passed and the Venus settings the port meant, through `venus_interop.plr.steps`).
"""
from __future__ import annotations

import pathlib
from typing import Any, Iterable, Optional

from venus_interop.methods import hsl_eval, protocol, sequences as sq


DISPLAY_ONLY = {"VectorCustomDialogs::AppendStatusText"}  # status-window texts: nothing reads them


def hsl_run(src: str, here: pathlib.Path, roots: Iterable[pathlib.Path], stp_paths: Iterable[pathlib.Path],
            layouts: dict, answers: Optional[dict] = None, allow_unresolved: Iterable[str] = ()) -> hsl_eval.Run:
  """Preprocess, parse and run `src` (a method's text, as if at `here`); it must run to the end and
  call no function that neither the sources nor the run define (the interpreter would carry on
  with an unknown value, so a library missing from the roots goes unnoticed), except those in
  DISPLAY_ONLY and `allow_unresolved`."""
  pre = hsl_eval.Preprocessor(list(roots), lambda p: p.read_text(encoding="latin-1"))
  text = pre.expand(here, text=src)
  parser = hsl_eval.Parser(hsl_eval.lex(text))
  parser.unit()
  run = hsl_eval.Run(parser, protocol.load_stps(sorted(stp_paths)), layouts, answers=answers or {})
  run.src = text.splitlines()
  run.run()
  assert run.stopped is None, run.stopped
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

  def __init__(self, label=lambda command, kw: ""):
    self.events: list[tuple] = []
    self.meant: list = []
    self.label = label

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
