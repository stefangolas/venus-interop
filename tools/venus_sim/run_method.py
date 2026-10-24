"""Run one staged method (`stage_method.py NAME` first) in Venus's simulation, headless: the tip reload,
then the ComTrace's line count to <work>/<name>_comtrace_start.txt (where `compare_firmware.py
--extract` starts reading), then the method. Prints the method's trace. Run with the 32-bit Python
(paths.PYTHON32):

  python32 run_method.py NAME          (marionette, groq_plate_1, groq_plates_2-5)"""
import sys

import methods
from paths import LOGS
from run_probe import run


def main(m: methods.Method) -> None:
  print(run(str(m.staged / "reload_tips.hsl"), 120))
  trace = max(LOGS.glob("ComTrace_Simulator*.trc"), key=lambda p: p.stat().st_mtime)
  with open(trace, encoding="latin-1") as f:
    start = sum(1 for _ in f)
  m.comtrace_start.write_text(f"{start}\n")
  print(f"{trace.name}: the run starts after line {start}")
  print(run(str(m.hsl), m.timeout))


if __name__ == "__main__":
  if len(sys.argv) != 2:
    raise SystemExit(__doc__)
  main(methods.get(sys.argv[1]))
