"""Run one HSL method in Venus (simulation mode) headless, through Hamilton's RunHSLExecutor, and wait
for it: StartMethod returns once the run has started and the run lives in this process, so the
process stays until the run's trace file says it ended (or the timeout, then AbortMethod).
Prints the run's trace. Run with the 32-bit Python (paths.PYTHON32):

  python32 run_probe.py METHOD.hsl [TIMEOUT_SECONDS]"""
import glob
import os
import sys
import time

import clr

from paths import LOGS, STAR_OEM

ENDS = ("End method - complete", "complete with error", "Abort method", "- error;")

sys.path.append(str(STAR_OEM))
clr.AddReference(os.path.join(str(STAR_OEM), "RunHSLExecutor"))
from RunHSLExecutor import Class1  # noqa: E402

path, timeout = sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 120
stem = os.path.splitext(os.path.basename(path))[0]
before = set(glob.glob(os.path.join(str(LOGS), f"{stem}_*_Trace.trc")))
c = Class1()
t0 = time.time()
c.StartMethod(path).Wait(int(timeout * 1000))
trace, text = None, ""
while time.time() - t0 < timeout:
  new = set(glob.glob(os.path.join(str(LOGS), f"{stem}_*_Trace.trc"))) - before
  if new:
    trace = max(new, key=os.path.getmtime)
    with open(trace, encoding="latin-1") as f:
      text = f.read()
    if any(e in text for e in ENDS):
      break
  time.sleep(0.5)
else:
  print("TIMED OUT: aborting")
  c.AbortMethod(path)
print(f"{time.time() - t0:.1f}s", trace)
print(text)
