"""Run examples/marionette_demo.py on PLR's simulated STAR and write every firmware command it sends,
one per line, to <work>/phase3/marionette_plr.fw (the simulator's own exchange log, as a real link
logs it). Needs the venus-plr PLR worktree first on PYTHONPATH.

  python marionette_plr_firmware.py"""
import asyncio
import sys

from paths import CORPUS, NIST, REPO, WORK

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "examples"))
from pylabrobot.hamilton.star.driver import simulator  # noqa: E402

import marionette_demo as demo  # noqa: E402

OUT = WORK / "phase3" / "marionette_plr.fw"


def main() -> None:
  sent = []
  cls = next(c for c in vars(simulator).values() if isinstance(c, type) and "_log_exchange" in vars(c))
  orig = cls._log_exchange

  def log(self, written, read):
    sent.append(written)
    return orig(self, written, read)

  cls._log_exchange = log
  trace = REPO / ".local/session_state/analysis/traces" / demo.TRACE
  liquid_classes = NIST.parent / "liquid_classes.json"  # tools/liquid_classes.py on NIST's Config/ML_STARLiquids.mdb
  try:
    asyncio.run(demo.main(CORPUS, False, demo.Parameters(plate_number=3), trace, None, liquid_classes))
  finally:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(sent) + "\n", encoding="utf-8")
    print(len(sent), "commands ->", OUT)


if __name__ == "__main__":
  main()
