"""Field-by-field comparison of the action commands Venus and PLR sent for the same run of a method
(`methods.py`): <work>/phase3/<name>_venus.fw (the ComTrace's sent lines from the run's start line,
which `run_method.py` notes) against <name>_plr.fw (`plr_firmware.py`).
Commands of one code are paired in order; each field (two lowercase letters + value) is compared,
after Venus's shortened lists are expanded and channels off in tm are dropped.

  python compare_firmware.py NAME [CODE ...]       (C0AS C0DS C0TP C0TR C0Z* when none given)
  python compare_firmware.py NAME --extract        (writes <name>_venus.fw from the ComTrace first)"""
import collections
import re
import sys

import methods
from paths import LOGS

FIELD = re.compile(r"([a-z]{2})([^a-z]*)")
CHANNELS = 8


def extract(m: methods.Method) -> None:
  """The commands Venus sent since <work>/<name>_comtrace_start.txt's line, newest ComTrace."""
  trace = max(LOGS.glob("ComTrace_Simulator*.trc"), key=lambda p: p.stat().st_mtime)
  start = int(m.comtrace_start.read_text().strip())
  lines = trace.read_text(encoding="latin-1").splitlines()[start - 1:]
  sent = [re.sub(r"^< [0-9:.]* COM1: ", "", line) for line in lines if line.startswith("< ")]
  m.fw("venus").write_text("\n".join(sent) + "\n", encoding="latin-1")
  print(len(sent), "commands from", trace.name)


def norm(fields):
  """Per-channel lists to their active channels: Venus ends a list early when the rest repeat the
  last value ('as2500&' = every channel), PLR writes them all; a full list of every channel is
  masked the same way; channels off in tm are not compared."""
  tm = fields.get("tm", "").rstrip("&").split()
  if fields.get("tm", "").endswith("&") and tm:
    tm = (tm + tm[-1:] * CHANNELS)[:CHANNELS]
  out = {}
  for k, raw in fields.items():
    vals = raw.rstrip("&").split()
    if tm and k != "tm" and (raw.endswith("&") or len(vals) == CHANNELS):
      vals = (vals + vals[-1:] * len(tm))[:len(tm)]
      vals = [x for x, on in zip(vals, tm) if on == "1"]
    out[k] = " ".join(vals)
  if tm:
    out["tm"] = " ".join(t for t in tm if t == "1")
  return out


def load(path, codes):
  out = collections.defaultdict(list)
  for line in path.read_text(encoding="latin-1").splitlines():
    if line[:4] in codes:
      out[line[:4]].append(norm(dict(FIELD.findall(line[4:]))))
  return out


def main(m: methods.Method, codes) -> None:
  v, p = load(m.fw("venus"), codes), load(m.fw("plr"), codes)
  for code in codes:
    pairs = list(zip(v[code], p[code]))
    diff = collections.Counter()
    example = {}
    for a, b in pairs:
      for k in sorted(set(a) | set(b)):
        if k == "id":
          continue
        if a.get(k) != b.get(k):
          diff[k] += 1
          example.setdefault(k, (a.get(k), b.get(k)))
    print(f"{code}: venus {len(v[code])}, plr {len(p[code])}, paired {len(pairs)}; fields differing: {len(diff)}")
    for k, n in diff.most_common():
      print(f"   {k}: {n}/{len(pairs)}  e.g. venus={example[k][0]!r:.70} plr={example[k][1]!r:.70}")


if __name__ == "__main__":
  if len(sys.argv) < 2:
    raise SystemExit(__doc__)
  m, args = methods.get(sys.argv[1]), sys.argv[2:]
  if "--extract" in args:
    extract(m)
    args.remove("--extract")
  main(m, args or ["C0AS", "C0DS", "C0TP", "C0TR", "C0ZP", "C0ZR", "C0ZS", "C0ZT", "C0ZA"])
