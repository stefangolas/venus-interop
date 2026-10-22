"""Where the Venus-simulation harness finds things. Standard library only: `run_probe.py` imports it
from the 32-bit Python that drives Venus.

Each location can be set by an environment variable; the defaults are this machine's layout:
  VENUS_SIM_WORK          working folder: staged methods, probe outputs, the 32-bit Python, backups
                          of every Venus file changed (default ~/venus-sim)
  HAMILTON_DIR            the Venus install (default C:\\Program Files (x86)\\HAMILTON)
  VENUS_INTEROP_CORPUS    the layout corpus (default <repo>/.local/session_state/corpus)
  VENUS_INTEROP_NIST      NIST's lmsf_hamilton checkout (default <repo>/.local/session_state/nist/repo)
  PYHAMILTON_DIR          pyhamilton's package folder, for RunHSLExecutor (default ~/pyhamilton/pyhamilton)
"""
import os
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent


def _path(var: str, default: pathlib.Path) -> pathlib.Path:
  return pathlib.Path(os.environ[var]) if os.environ.get(var) else default


WORK = _path("VENUS_SIM_WORK", pathlib.Path.home() / "venus-sim")
HAMILTON = _path("HAMILTON_DIR", pathlib.Path(r"C:\Program Files (x86)\HAMILTON"))
CORPUS = _path("VENUS_INTEROP_CORPUS", REPO / ".local" / "session_state" / "corpus")
NIST = _path("VENUS_INTEROP_NIST", REPO / ".local" / "session_state" / "nist" / "repo")
PYHAMILTON = _path("PYHAMILTON_DIR", pathlib.Path.home() / "pyhamilton" / "pyhamilton")

STAR_OEM = PYHAMILTON / "star-oem"  # RunHSLExecutor.dll, the STAR_OEM toolkit
PYTHON32 = WORK / "python32" / "python.exe"  # 32-bit Python with pythonnet: 64-bit HxRun waits for a button
LIBRARY = HAMILTON / "Library"
LABWARE = HAMILTON / "Labware"
CONFIG = HAMILTON / "Config"
LOGS = HAMILTON / "LogFiles"
BACKUP = WORK / "backup"
LABWARE_MANIFEST = BACKUP / "labware_added.txt"  # every file added to the Venus Labware folder
