"""List the steps of a Venus method's code (.hsl / .sub), or count them by type.

  python tools/hsl_steps.py METHOD.hsl [--summary] [--type "sub-method call"]
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from venus_interop.files import footer  # noqa: E402
from venus_interop.methods import hsl  # noqa: E402


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("path")
  ap.add_argument("--summary", action="store_true")
  ap.add_argument("--type")
  a = ap.parse_args()
  data = pathlib.Path(a.path).read_bytes()
  text = data.decode("latin-1")
  try:
    print(f"footer: {'ok' if footer.ok(data) else 'CHECKSUM MISMATCH'}")
  except ValueError:
    print("footer: none")
  if a.summary:
    for t, n in hsl.summary(text).items():
      print(f"{n:6}  {t}")
    return
  for s in hsl.steps(text):
    if a.type and a.type.lower() not in s.type.lower():
      continue
    first = s.code.strip().splitlines()[0] if s.code.strip() else ""
    print(f"{s.row:5} {s.section or '':24} {s.type:32} {first[:90]}")


if __name__ == "__main__":
  main()
