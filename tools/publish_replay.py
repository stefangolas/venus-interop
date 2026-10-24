"""Copy a recorded replay bundle for public hosting, with the viewer's own UI hidden by default.

  python tools/publish_replay.py .local/replays/groq-demo-2 site/groq-seq
  python tools/publish_replay.py <bundle> <output> --option ui=1   # keep the viewer's UI

A link's own query still overrides any default (`?ui=1` shows the navbar and tree again).
"""
from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from venus_interop.plr.replay import publish  # noqa: E402

# Public pages open on the scene and the replay controls alone.
PUBLIC_DEFAULTS = dict(ui='0', overlays='0', hover='0')


def main():
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument('bundle', type=pathlib.Path)
  parser.add_argument('output', type=pathlib.Path, help='a new directory; existing ones are refused')
  parser.add_argument('--option', action='append', default=[], metavar='KEY=VALUE',
                      help='a view default to set, e.g. ui=1 or light=0.8')
  args = parser.parse_args()
  options = dict(PUBLIC_DEFAULTS)
  options.update(dict(o.split('=', 1) for o in args.option))
  publish(args.bundle, args.output, **options)
  print(f'published {args.bundle} -> {args.output} with {options}')


if __name__ == '__main__':
  main()
