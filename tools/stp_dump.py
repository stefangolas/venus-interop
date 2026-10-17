"""Dump the step records of a Venus .stp file: what each device step of a library really does.

  python tools/stp_dump.py LIBRARY.stp                  one line per step: name and top-level settings
  python tools/stp_dump.py LIBRARY.stp GUID [GUID ...]  every setting of those steps (GUID prefixes do)
  python tools/stp_dump.py LIBRARY.stp GUID --errors    with the step's error policies

The GUIDs are the ones in the library's code, `ML_STAR._<CLSID>("<guid>"); // StepName`. A value
`<name>` is bound to that variable; under `/gripper` and similar blocks the bound variable is written
bare (`grip width = grip_width`).
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from venus_interop.methods import protocol  # noqa: E402

# Top-level keys that say nothing about what the step does
_QUIET = {"3", "NbrOfErrors"}


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("path")
  ap.add_argument("guids", nargs="*")
  ap.add_argument("--errors", action="store_true")
  a = ap.parse_args()
  sys.stdout.reconfigure(encoding="utf-8")
  stps = protocol.load_stps([pathlib.Path(a.path)])
  for guid, rec in sorted(stps.items(), key=lambda kv: (kv[1].step_name, kv[0])):
    if a.guids and not any(guid.startswith(g) for g in a.guids):
      continue
    if not rec.step_name:
      continue
    if not a.guids:
      top = {}
      for path, key, value in rec.readable():
        if "Variables" in path or "Errors" in path or key in top or key in _QUIET or value == "":
          continue
        top[key] = value
      print(f"{guid[:8]} {rec.step_name:18} " + ", ".join(f"{k}={v}" for k, v in top.items()))
      continue
    print(f"== {guid} {rec.step_name}")
    for path, key, value in rec.readable():
      if "Variables" not in path and "Errors" not in path:
        print(f"  {path or '/'} | {key} = {value}")
    if a.errors:
      for e in rec.errors():
        print(f"  {protocol.render_error(e)}")


if __name__ == "__main__":
  main()
