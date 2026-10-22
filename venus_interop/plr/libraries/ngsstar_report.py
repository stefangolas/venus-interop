"""The NGSStar run report: the RuntimeReport sheet NGSStarProcesses and NGSStarLoading append to.

Venus keeps it in an Excel workbook (the method's report file, sheet RuntimeReport), a row per
event: free text in the Date column (`DATA_UpdateInformationIntoReportFile`), or a stamped row with
what a transport or the autoload did. Here it is CSV in the same columns (user, 2026-10-18), written
as rows are added when the report has a path, and kept in `rows` either way.

The libraries write a step's error codes, translated, into the rows (_DATA_Translate*ErrorCodes,
tables of every firmware code). A PLR driver raises on a firmware error, where Venus can recover
and go on, so a step the port reports always went through: only the tables' no-error texts are
kept (TRANSPORT_OK and the rest).
"""
from __future__ import annotations

import csv
import pathlib
import time
from typing import Callable, Optional

COLUMNS = ["Date", "Time", "LabID Source", "PosID Source", "Transfer Volume", "LabID Target", "PosID Target",
           "Barcode", "Transport information", "Aspiration information", "Dispense information"]

# The error translations' text for no error (main, slave and recovery codes all 0)
ISWAP_OK = "transport ok."  # _DATA_TranslateiSWAPErrorCodes
CORE_OK = "transport step ok."  # _DATA_TranslateChannelErrorCodes for a transport
PIPETTING_OK = "pipetting step ok."  # _DATA_TranslateChannelErrorCodes for a pipetting step
AUTOLOAD_OK = "loading step ok."  # _DATA_TranslateAutoLoadErrorCodes


def number_text(v) -> str:
  """A number as HSL's FStr and string concatenation write it, as the interpreter models them: a
  whole float without its point (CONVENTIONS §11)."""
  if isinstance(v, float):
    return str(int(v)) if v.is_integer() else repr(v)
  return str(v)


def trimmed_volume(v) -> str:
  """The libraries' volume text: StrFStr cut one digit past the point. Kept as they have it: with
  no point (a whole volume, as FStr is modelled), StrFind's -1 keeps one character."""
  s = number_text(v)
  return s[:s.find(".") + 2]


class RunReport:
  def __init__(self, path: Optional[pathlib.Path] = None, clock: Callable[[], time.struct_time] = time.localtime):
    """`path`: the CSV to append to (created with a header when missing); none keeps the rows only.
    `clock`: the local time the stamped rows take."""
    self.rows: list[dict[str, str]] = []
    self.path, self.clock = (pathlib.Path(path) if path else None), clock
    if self.path is not None and not self.path.exists():
      with self.path.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(COLUMNS)

  def add(self, cells: dict[str, str]) -> None:
    """A row: the cells named, the rest empty."""
    unknown = set(cells) - set(COLUMNS)
    if unknown:
      raise KeyError(f"not report columns: {sorted(unknown)}")
    row = {c: str(cells.get(c, "")) for c in COLUMNS}
    self.rows.append(row)
    if self.path is not None:
      with self.path.open("a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([row[c] for c in COLUMNS])

  def stamp(self) -> dict[str, str]:
    """Date and Time as the libraries write them (TimGetFormattedDate "%Y_%m_%d", ...Time "%H_%M_%S")."""
    now = self.clock()
    return {"Date": time.strftime("%Y_%m_%d", now), "Time": time.strftime("%H_%M_%S", now)}

  def text(self, text: str) -> None:
    """DATA_UpdateInformationIntoReportFile's row: the text in the Date column."""
    self.add({"Date": text})
