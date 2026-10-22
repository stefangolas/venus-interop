"""Phase 1 smoke probe: pyhamilton's STAR_OEM method in Venus simulation, headless (RunHSLExecutor in a
child process, as pyhamilton's default mode does). Initialize, two 1000 uL tips, aspirate 50 uL from
two wells, dispense them into two others, eject. Then: does the ComTrace hold C0TP / C0AS / C0DS?
Run with the 32-bit Python (paths.PYTHON32)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import stubs  # noqa: E402,F401  (GUI/camera stand-ins, also in the spawned child)

from pyhamilton import (HamiltonInterface, Plate96, Tip96, aspirate, dispense, initialize,  # noqa: E402
                        tip_eject, tip_pick_up)

LIQUID_CLASS = "HighVolumeFilter_Water_DispenseJet_Empty_with_transport_vol"

if __name__ == "__main__":
  tips = Tip96("media_formulation_tips")
  plate = Plate96("antibiotics")
  with HamiltonInterface() as ham:
    initialize(ham)
    tip_pick_up(ham, [(tips, 0), (tips, 1)])
    aspirate(ham, [(plate, 0), (plate, 1)], [50, 50], liquidClass=LIQUID_CLASS)
    dispense(ham, [(plate, 8), (plate, 9)], [50, 50], liquidClass=LIQUID_CLASS)
    tip_eject(ham, [(tips, 0), (tips, 1)])
  print("PROBE DONE")
