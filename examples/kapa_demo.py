"""A slice of KAPA HyperPlus on the simulated STAR: a bead cleanup and a run in the ODTC.

From `HyperPrep_HyperPlus.py` (pyhamilton), on the hand-built deck (`kapa_deck.py`):

  cleanup  96-head transfer of the samples from the HSP plate to the MIDI plate, n columns off the
           CO-RE tip support; beads (see below); a 96-head mix; the MIDI plate onto the magnet;
           supernatant off; an ethanol wash; the MIDI plate off the magnet.
  odtc     the cover opens, the HSP plate goes in and a ComfortLid from the stack onto it, the
           cover closes, (the thermal program), the cover opens, lid and plate go back.

The 96-head aspirates and dispenses with `Head96.aspirate` / `dispense` (C0 EA / ED); the MIDI
plate moves to and from the magnet with the CO-RE grip tools (`COREGripper`), as the method does;
the ODTC, left of the arm's travel, is served by the iSWAP.

Deviations from the method, and why:
  - Beads are added as a volume, not pipetted: the method dispenses them with the 8 channels, and
    the v1 driver's channels have no dispense yet.
  - Supernatant and ethanol go to the 96-head liquid waste. The method dispenses them to
    `MIDI_OffMagnet`, the nest the same plate has just left: in Venus's model the plate on the
    magnet and the plate off it are two labware, so nothing shows the nest is empty.

  python kapa_demo.py            headless: runs, checks the volumes and tips, prints them
  python kapa_demo.py --view     serves the viewer (open the printed URL) and plays the run
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional, Union

sys.path.insert(0, str(Path(__file__).parent))

from kapa_deck import KAPADeck, build_kapa_deck  # noqa: E402

from pylabrobot.hamilton.star.driver.features.core_gripper import COREGripper  # noqa: E402
from pylabrobot.hamilton.star.driver.features.iswap_transport import (  # noqa: E402
  iSWAPCollisionError,
  iSWAPTransport,
)
from pylabrobot.hamilton.star.tip_support import CORE96TipSupport  # noqa: E402
from pylabrobot.lib.liquid_handling.mix import Mix  # noqa: E402
from pylabrobot.resources import Coordinate, Plate, Resource, set_tip_tracking  # noqa: E402
from pylabrobot.resources import set_volume_tracking  # noqa: E402
from pylabrobot.visualizer3D.facility import Facility  # noqa: E402

SAMPLE_VOLUME = 70.0  # uL: DNA + fragmentation, end repair, adapters, ligation master mixes
BEADS = 88.0  # uL, 1.0X
ETHANOL = 150.0  # uL per wash (the method's 200 exceeds a MIDI well with the beads still in)


# The view the STARlet sessions settled on (session.py), for the STAR's own model: its front cover
# left undrawn (the door's label, measure strip and sticker, and its glass in the front plane -
# faces square to y more than 0.2 m ahead of the model's centre, in STAR.glb's own metres), and the
# autoloader's near-black band under the front of the deck (9% and 0% in the file) a dark grey.
STAR_VIEW_EDITS = {
  "STAR": [
    {"material": "Door_Label_STAR.png"},
    {"material": "Shell_glazed", "axis": "y", "below": -0.2},
    {"material": "plattform_door_measure.png"},
    {"material": "biohazard.png"},
    {"material": "XMat.003", "color": "#666666"},
    {"material": "XMat.009", "color": "#666666"},
  ],
}


# Where the view opens: from in front of and above the deck, looking back and down across it
# (facility mm; `plrViewer.camera()` in the page's console prints the current one).
CAMERA = ((1192.58, -1169.67, 1851.30), (1221.82, 3111.65, -437.78))
# How the page lights the scene: "real" (a light over the deck casting shadows) or "technical".
LOOK = "real"


def columns_of(plate: Plate, n: int):
  return [plate.get_item(c * 8 + r) for c in range(n) for r in range(8)]


async def transfer96(k: KAPADeck, support: CORE96TipSupport, source: Resource, target: Resource,
                     volume: float, n: int, source_height: float = 1.0,
                     target_height: float = 2.0) -> None:
  """pyhamilton's `transfer_96`: n columns of tips off the support, aspirate, dispense, discard.
  The tips stand on the head's first n columns, so they work plate columns 1 to n."""
  head = k.star.head96
  deck = k.star.deck
  await support.pick_up_columns(n)
  await head.aspirate(source, volume, liquid_height=source_height)
  await head.dispense(target, volume, liquid_height=target_height, blow_out=True)
  await head.drop_tips(deck.get_resource(deck.get_component_name("trash_core96")))


async def mix96(k: KAPADeck, support: CORE96TipSupport, plate: Plate, volume: float, n: int,
                repetitions: int) -> None:
  """pyhamilton's `mix_plate`."""
  head = k.star.head96
  deck = k.star.deck
  await support.pick_up_columns(n)
  await head.mix(plate, Mix(volume=volume, repetitions=repetitions, flow_rate=100.0))
  await head.drop_tips(deck.get_resource(deck.get_component_name("trash_core96")))


async def cleanup(k: KAPADeck, support: CORE96TipSupport, gripper: COREGripper, n: int,
                  say=print) -> None:
  say(f"cleanup: {n} columns of samples to the MIDI plate")
  await transfer96(k, support, k.hsp_plate, k.midi, SAMPLE_VOLUME, n, source_height=0.5)
  say("beads added (as a volume: the v1 channels have no dispense)")
  for well in columns_of(k.midi, n):
    well.tracker.add_liquid(BEADS)
    well.tracker.commit()
  say("96-head mix")
  await mix96(k, support, k.midi, 80.0, n, repetitions=3)
  say("the MIDI plate onto the magnet, with the CO-RE grip tools, and the tools back")
  # Back before the 96-head works: the channels holding them stand on the same X-arm.
  await gripper.move_resource(k.midi, k.magnet, return_tools=True)
  say("supernatant off, 0.8 above the bottom, to the liquid waste")
  await transfer96(k, support, k.midi, k.liquid_waste, SAMPLE_VOLUME + BEADS, n, source_height=0.8)
  say("ethanol on")
  await transfer96(k, support, k.ethanol, k.midi, ETHANOL, n, source_height=2.0, target_height=10.0)
  say("ethanol off")
  await transfer96(k, support, k.midi, k.liquid_waste, ETHANOL, n, source_height=0.8)
  say("the MIDI plate off the magnet, the grip tools back")
  await gripper.move_resource(k.midi, k.midi_nest, return_tools=True)


async def odtc_run(k: KAPADeck, transport: iSWAPTransport, say=print) -> None:
  """With the iSWAP: the ODTC stands left of the arm's travel, where the channels do not reach.
  Gripped from the right: from the back the arm sweeps through the ODTC's rear body."""
  plate = k.hsp_plate_2
  home = plate.parent
  await k.star.iswap.make_space()
  say("ODTC: cover open")
  await k.odtc.open_lid()
  say("the plate in")
  await transport.move_resource(plate, k.odtc, pickup_direction="right")
  lid = k.odtc_lid_stack.get_top_item()
  say("a ComfortLid from the stack onto it")
  await transport.move_resource(lid, plate, pickup_direction="right")
  say("cover closed; the thermal program runs")
  await k.odtc.close_lid()
  await asyncio.sleep(1.0)
  await k.odtc.open_lid()
  say("the lid back on the stack, the plate back")
  await transport.move_resource(lid, k.odtc_lid_stack, pickup_direction="right")
  await transport.move_resource(plate, home, pickup_direction="right")
  await k.odtc.close_lid()
  await k.star.iswap.park(traverse_height=280.0)


def build_facility(k: KAPADeck) -> Facility:
  facility = Facility(name="facility", size_x=2600, size_y=1400, size_z=1200)
  bench = Resource(name="bench", size_x=2200, size_y=900, size_z=880, category="bench")
  facility.assign_child_resource(k.star, location=Coordinate(300, 0, bench.get_size_z()))
  facility.assign_child_resource(bench, location=Coordinate(0, 0, 0))
  return facility


def fill(k: KAPADeck, n: int) -> None:
  for well in columns_of(k.hsp_plate, n):
    well.set_volume(SAMPLE_VOLUME)
  k.ethanol.get_item(0).set_volume(250_000.0)
  k.beads.set_volume(40_000.0) if hasattr(k.beads, "set_volume") else k.beads.tracker.set_volume(40_000.0)


async def reset(k: KAPADeck, n: int, channels_y) -> None:
  """The deck as the cleanup found it, so it can be played again: the 300 uL racks full, the tip
  support empty, no liquid but the samples, the ethanol and the beads, and the channels back where
  setup left them - the two that return the grip tools end the cleanup at the tool park, apart from
  the other six. The MIDI plate and the grip tools end the cleanup where they began, and the ODTC step
  puts back everything it moves."""
  await k.star.pipettes.move_to_safe_z()
  await k.star.pipettes.move_to_y_positions(dict(enumerate(channels_y)))
  for rack in k.tips_300uL:
    rack.fill()
  k.tip_support.empty()
  for plate in (k.hsp_plate, k.midi):
    for well in plate.get_all_items():
      well.set_volume(0.0)
  k.liquid_waste.tracker.set_volume(0.0)
  fill(k, n)


async def main(view: bool, n: int, steps=("cleanup", "odtc"), housing: bool = True,
               check_collisions: bool = True, replays: int = 0) -> None:
  logging.disable(logging.WARNING)
  set_volume_tracking(True)
  set_tip_tracking(True)
  k = build_kapa_deck(extension_housing=housing)
  facility = build_facility(k)
  await k.star.setup()
  channels_y = await k.star.pipettes.request_y_positions()  # where a replay puts them back
  await k.odtc.setup()
  fill(k, n)
  support = CORE96TipSupport(k.star.head96, k.tip_support, k.tips_300uL)
  transport = iSWAPTransport(k.star.iswap, check_collisions=check_collisions)
  gripper = COREGripper(k.star.pipettes)

  viewer: Optional[object] = None
  if view:
    from pylabrobot.visualizer3D.server import Viewer3D

    # The models alone: no overlays, hover outlines or page interface; lit a little under the
    # page's own lighting, as the STARlet sessions were.
    viewer = Viewer3D(
      facility, name="kapa_demo.py", open_browser=False, bare=True,
      mesh_edits=STAR_VIEW_EDITS, light=0.8, camera=CAMERA, look=LOOK,
    )
    await viewer.start()
    viewer.attach_motion(k.star.driver)
    print("viewer:", getattr(viewer, "url", ""), flush=True)
    await viewer.wait_for_browser()
    # Nothing moves until every model file is on screen: the first moves are the ones to see.
    await viewer.wait_for_models()
    print("viewer: every model drawn; starting", flush=True)
    await asyncio.sleep(1.0)

  async def run() -> None:
    if "cleanup" in steps:
      await cleanup(k, support, gripper, n)
    if "odtc" in steps:
      try:
        await odtc_run(k, transport)
      except iSWAPCollisionError as refused:
        print("refused:", refused, flush=True)
    print("MIDI A1..H1:", [round(w.tracker.get_used_volume(), 1) for w in columns_of(k.midi, 1)])
    print("HSP A1:", k.hsp_plate.get_item(0).tracker.get_used_volume(),
          "MIDI on", k.midi.parent.name, "| lids on the stack:", len(k.odtc_lid_stack.children),
          "| support columns left:",
          [sum(s.tip is not None for s in k.tip_support.get_all_items()[c * 8:c * 8 + 8])
           for c in range(12)], flush=True)

  await run()
  if viewer is None:
    for _ in range(replays):
      await reset(k, n, channels_y)
      await run()
    return
  # Played again for each page that loads - a refresh - once its models are drawn, from the deck as
  # it was at the start.
  print("done; refresh the page to play it again", flush=True)
  while True:
    await viewer.wait_for_models()
    print("viewer: a page loaded; playing it again", flush=True)
    await reset(k, n, channels_y)
    await asyncio.sleep(1.0)
    await run()
    print("done; refresh to play it again", flush=True)


if __name__ == "__main__":
  parser = argparse.ArgumentParser()
  parser.add_argument("--view", action="store_true")
  parser.add_argument("--columns", type=int, default=3)
  parser.add_argument("--steps", nargs="+", default=["cleanup", "odtc"], choices=["cleanup", "odtc"])
  parser.add_argument("--no-housing", action="store_true", help="leave the left extension housing off")
  parser.add_argument("--no-collision-check", action="store_true",
                      help="run iSWAP plans without checking what they sweep")
  parser.add_argument("--look", choices=["real", "technical"], default="real")
  parser.add_argument("--replays", type=int, default=0,
                      help="headless: reset the deck and play the steps this many more times")
  args = parser.parse_args()
  LOOK = args.look
  asyncio.run(main(args.view, args.columns, tuple(args.steps), housing=not args.no_housing,
                   check_collisions=not args.no_collision_check, replays=args.replays))
