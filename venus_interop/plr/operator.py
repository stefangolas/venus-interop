"""The operator: what a Venus method asks or shows the person at the instrument, as calls.

Venus libraries talk to the operator through dialogs (VectorCustomDialogs' MessageDialog, ListDialog
and LoadingDialog, HSL's MessageBox and InputBox, file pickers) and a status window. A port calls an
`Operator` at the same place with the dialog's own text:

- `message`: a dialog with only OK;
- `confirm`: OK / Cancel or Yes / No, True for OK or Yes;
- `choose`: one of several options (several when `multiple`);
- `show_table`: a table to act on, such as what to load onto a carrier (columns, rows, pictures),
  confirmed or cancelled;
- `ask_file`: a path;
- `status`: a line for the status window, nothing to answer.

`ScriptedOperator` answers from a table keyed by text (tests and unattended runs); a question it has
no answer for is an error, so nothing is answered by accident. `ConsoleOperator` asks on the
terminal. Both keep what was asked, in order, in `asked`.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence


class RunAborted(Exception):
  """Venus's `abort`: the operator cancelled, or the library ended the run."""


class Operator:
  """What a port calls. Subclasses answer; `asked` keeps every call: (kind, text, details)."""

  def __init__(self):
    self.asked: list[tuple[str, str, dict]] = []

  def _note(self, kind: str, text: str, **details) -> None:
    self.asked.append((kind, text, details))

  def message(self, text: str, title: str = "", kind: str = "information") -> None:
    self._note("message", text, title=title, kind=kind)
    self._show(text, title)

  def status(self, text: str) -> None:
    self._note("status", text)

  def confirm(self, text: str, title: str = "", yes_no: bool = False, items: Sequence[str] = ()) -> bool:
    self._note("confirm", text, title=title, yes_no=yes_no, items=list(items))
    return bool(self._answer("confirm", text, title=title, yes_no=yes_no, items=list(items)))

  def choose(self, text: str, options: Sequence[str], title: str = "", multiple: bool = False):
    self._note("choose", text, title=title, options=list(options), multiple=multiple)
    return self._answer("choose", text, title=title, options=list(options), multiple=multiple)

  def show_table(self, text: str, columns: Sequence[str], rows: Iterable[Sequence[Any]], title: str = "",
                 images: Sequence[str] = ()) -> bool:
    rows = [list(r) for r in rows]
    self._note("show_table", text, title=title, columns=list(columns), rows=rows, images=list(images))
    return bool(self._answer("show_table", text, title=title, columns=list(columns), rows=rows,
                             images=list(images)))

  def ask_file(self, text: str, title: str = "", pattern: str = "") -> str:
    self._note("ask_file", text, title=title, pattern=pattern)
    return str(self._answer("ask_file", text, title=title, pattern=pattern))

  def _show(self, text: str, title: str) -> None:
    pass

  def _answer(self, kind: str, text: str, **details):
    raise NotImplementedError


class ScriptedOperator(Operator):
  """Answers by text: the first key of `answers` found in the question's text or title (without
  case), its value the answer (a callable is called with the kind, text and details). Unanswered:
  a LookupError naming the question."""

  def __init__(self, answers: Optional[dict[str, Any]] = None):
    super().__init__()
    self.answers = dict(answers or {})

  def _answer(self, kind: str, text: str, **details):
    where = f"{details.get('title', '')}\n{text}".casefold()
    for key, value in self.answers.items():
      if key.casefold() in where:
        return value(kind, text, **details) if callable(value) else value
    raise LookupError(f"the operator was asked ({kind}) and has no answer: {text!r}")


class ConsoleOperator(Operator):
  """Asks on the terminal."""

  def _show(self, text: str, title: str) -> None:
    print(f"[{title}] {text}" if title else text)

  def status(self, text: str) -> None:
    super().status(text)
    print(text)

  def _answer(self, kind: str, text: str, **details):
    self._show(text, details.get("title", ""))
    if kind == "show_table":
      print(" | ".join(details["columns"]))
      for row in details["rows"]:
        print(" | ".join(str(c) for c in row))
      for image in details["images"]:
        print(f"(picture: {image})")
    for item in details.get("items", ()):
      print(f"  {item}")
    if kind == "choose":
      for i, option in enumerate(details["options"], start=1):
        print(f"  {i}. {option}")
      picked = [details["options"][int(i) - 1] for i in input("> ").replace(",", " ").split()]
      return picked if details["multiple"] else picked[0]
    if kind == "ask_file":
      return input("path> ")
    prompt = "[y/n]> " if details.get("yes_no") else "[ok/cancel]> "
    return input(prompt).strip().lower() in ("y", "yes", "ok", "")
