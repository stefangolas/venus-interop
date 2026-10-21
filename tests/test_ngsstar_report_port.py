"""Hamilton's NGSStar framework, the run report: the port's rows against the HSL library's.

NGSStarProcesses' DATA_UpdateInformationIntoReportFile (a line of text) and DATA_IncubationTimer
(a line once a timer is waited for, none in simulation mode) run in the HSL interpreter, which
appends to the report workbook's RuntimeReport sheet, and in the port, whose RunReport keeps the
same columns. The transports' and pipetting functions' rows are compared in their own port tests.

Needs VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS (see test_ngsstar_processes_port.py).
"""
import asyncio
import time

import pytest

from port_harness import CLOCK, REPORT_BOOK, RecordingDeck, hsl_run, report_rows  # noqa: E402
from test_ngsstar_processes_port import LIBS, NGS, avenio, lay  # noqa: E402,F401

pytestmark = pytest.mark.skipif(NGS is None or not LIBS,
                                reason="VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS not set")

# What this test checks against the HSL (read by tools/trace_method.py --status)
LIBRARY = "NGSSTARPROCESSES"
COVERS = ["DATA_UpdateInformationIntoReportFile", "DATA_IncubationTimer"]

TEXTS = [("Process clean up", 1), ("Transport MIDI plate", 0), ("", 1)]
TIMERS = [("t1", 120.7, 1), ("t2", 300, 2), ("t2", 300, 3), ("t3", 45, 1)]


def hsl_report(avenio, lay, simulation):
  N = "NGSSTARPROCESSES::"
  src = (
    'namespace _Method { #include "HSLSeqLib.hsl" }\n'
    'namespace _Method { #include "NGSStarProcesses.hs_" }\n'
    'global device ML_STAR ("x.lay", "ML_STAR", hslTrue);\n'
    'namespace _Method { #include "HSLMECCLib.hs_" }\n'
    "namespace _Method { method main() void {\n"
    "timer t1; timer t2; timer t3;\n"
    f'{N}t_strFullPathReportFile = "{REPORT_BOOK}";\n'
    f"{N}t_blnSimulationModeON = {int(simulation)};\n"
    + "".join(f'{N}DATA_UpdateInformationIntoReportFile("{t}", {s});\n' for t, s in TEXTS)
    + "".join(f"{N}DATA_IncubationTimer({t}, {sec}, {mode});\n" for t, sec, mode in TIMERS)
    + "} }\n")
  run = hsl_run(src, avenio / "Library" / "port_test.hsl", [avenio / "Library", avenio / "Methods", *LIBS],
                (avenio / "Library").glob("*.stp"), {"x.lay": lay}, answers={"clock": time.struct_time(CLOCK)})
  return report_rows(run)


def port_report(lay, simulation):
  from venus_interop.plr.libraries.ngsstar_processes import NGSStarProcesses
  from venus_interop.plr.libraries.ngsstar_report import RunReport
  from venus_interop.plr.operator import ScriptedOperator

  operator = ScriptedOperator()
  procs = NGSStarProcesses(type("Star", (), {"pipettes": None})(), RecordingDeck(lay), {}, {}, say=lambda _: None,
                           report=RunReport(clock=lambda: time.struct_time(CLOCK)), operator=operator,
                           simulation=simulation)

  async def go():
    for text, status in TEXTS:
      procs.DATA_UpdateInformationIntoReportFile(text, status)
    for t, sec, mode in TIMERS:
      await procs.DATA_IncubationTimer(t, sec, mode)

  asyncio.run(go())
  return procs.report.rows, operator.asked


@pytest.mark.parametrize("simulation", [False, True], ids=["run", "simulation"])
def test_report_rows_as_the_library_writes_them(avenio, lay, simulation):
  hsl, (port, asked) = hsl_report(avenio, lay, simulation), port_report(lay, simulation)
  assert len(hsl) == len(TEXTS) + (0 if simulation else 3)
  assert hsl == port
  # the status window: the lines asked for it, and every timer's
  assert [t for kind, t, _ in asked] == [t for t, s in TEXTS if s] + [r["Date"] for r in port[len(TEXTS):]]


def test_report_csv(tmp_path):
  import csv

  from venus_interop.plr.libraries.ngsstar_report import COLUMNS, RunReport

  report = RunReport(tmp_path / "report.csv", clock=lambda: time.struct_time(CLOCK))
  report.text("Process clean up")
  report.add({**report.stamp(), "LabID Source": "HSP_ODTC", "Barcode": "a,b"})
  rows = list(csv.reader((tmp_path / "report.csv").open(encoding="utf-8")))
  assert rows[0] == COLUMNS
  assert rows[1][0] == "Process clean up" and rows[2][:3] == ["2026_10_19", "14_05_09", "HSP_ODTC"]
  assert rows[2][COLUMNS.index("Barcode")] == "a,b"
  with pytest.raises(KeyError):
    report.add({"Volume": 1})
