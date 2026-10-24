"""Run one method's PLR translation (its demo, `methods.py`) on PLR's simulated STAR and write every
firmware command it sends, one per line, to <work>/phase3/<name>_plr.fw (the simulator's own exchange
log, as a real link logs it). Needs the venus-plr PLR worktree first on PYTHONPATH. Venus-faithful
defaults are on: PLR_VENUS_FAITHFUL_CFG, when not already set, is the instrument .cfg the Venus run
used (Config/ML_Starlet.cfg), else "stock".

  python plr_firmware.py NAME          (marionette, groq_plate_1, groq_plates_2-5)"""
import asyncio
import os
import sys

from paths import CONFIG, REPO

sys.path.insert(0, str(REPO))
from pylabrobot.hamilton.star.driver import simulator  # noqa: E402

import methods  # noqa: E402


def main(m: methods.Method) -> None:
  cfg = CONFIG / "ML_Starlet.cfg"
  os.environ.setdefault("PLR_VENUS_FAITHFUL_CFG", str(cfg) if cfg.is_file() else "stock")
  print("PLR_VENUS_FAITHFUL_CFG =", os.environ["PLR_VENUS_FAITHFUL_CFG"])
  sent = []
  cls = next(c for c in vars(simulator).values() if isinstance(c, type) and "_log_exchange" in vars(c))
  orig = cls._log_exchange

  def log(self, written, read):
    sent.append(written)
    return orig(self, written, read)

  cls._log_exchange = log
  out = m.fw("plr")
  try:
    asyncio.run(m.plr())
  finally:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(sent) + "\n", encoding="utf-8")
    print(len(sent), "commands ->", out)


if __name__ == "__main__":
  if len(sys.argv) != 2:
    raise SystemExit(__doc__)
  main(methods.get(sys.argv[1]))
