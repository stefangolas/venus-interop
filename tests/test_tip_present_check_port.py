"""The NGSStar kits' Tip Present Check_5ml_1ml: Check_Tips_Present_1ml, the port against the HSL.

The library asks each channel (firmware `P<n>RW`) and reads the tip from its reply's character 5;
the test answers each command with a reply holding the channel's tip there (the reply's other
characters are the instrument's: modelled), and the port's PLR channels with the same tips
(`sense_tip_presence`). Both must return the same result and pattern, for 8 and for 4 channels
(Avenio's call on a deck reduced to a 4-channel system), and nothing in simulation mode.

Needs VENUS_INTEROP_NGS (the Avenio CGP kit holds the library).
"""
import asyncio

import pytest

from port_harness import hsl_run
from test_ngsstar_processes_port import LIBS, NGS, avenio, lay  # noqa: F401

pytestmark = pytest.mark.skipif(NGS is None or not LIBS,
                                reason="VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS not set")

# What this test checks against the HSL (read by tools/trace_method.py --status)
LIBRARY = "TIP_PRESENT_CHECK_5ML_1ML"
COVERS = ["Check_Tips_Present_1ml"]

SRC = ('namespace _Method { #include "Tip Present Check_5ml_1ml.hs_" }\n'
       'global device ML_STAR ("x.lay", "ML_STAR", hslTrue);\n'
       "namespace _Method { namespace TESTINPUT { function Channels() variable { variable v; return(v); } } }\n"
       "namespace _Method { global variable g_result; global variable g_pattern;\n"
       "method main() void { variable p;\n"
       "g_result = TIP_PRESENT_CHECK_5ML_1ML::Check_Tips_Present_1ml(ML_STAR, p, TESTINPUT::Channels());\n"
       "g_pattern = p; } }\n")
CASES = [("00000000", 8, 0), ("10100001", 8, 0), ("11111111", 8, 0), ("01100000", 4, 0), ("00001111", 4, 0),
         ("11111111", 8, 1), ("11110000", 4, 1)]


def hsl_check(avenio, lay, tips, channels, sim):
  def reply(command, params):  # P<n>RW: the tip as the reply's character 5 (0-based), as the library reads it
    n = int(command[1:-2])
    return f"P{n}RWr{tips[n - 1]}"

  run = hsl_run(SRC, avenio / "Library" / "port_test.hsl", [avenio / "Library", *LIBS],
                (avenio / "Library").glob("Tip Present*.stp"), {"x.lay": lay},
                answers={"firmware": reply,
                         "functions": {"hslml_star::issimulatormode": lambda run, p: sim,
                                       "testinput::channels": lambda run, p: channels}})
  cells = {k: c.value for sc in run.globals.values() for k, c in sc.items()}
  asked = [e.settings["firmware command string"] for e in run.events if e.command == "FirmwareCommand"]
  return int(cells["g_result"]), str(cells["g_pattern"]), asked


class _Pipettes:
  def __init__(self, tips):
    self.tips = tips

  async def sense_tip_presence(self):
    return [int(t) for t in self.tips]


@pytest.mark.parametrize("tips,channels,sim", CASES, ids=[f"{t}-{c}{'-sim' if s else ''}" for t, c, s in CASES])
def test_port_checks_tips_as_the_library_does(avenio, lay, tips, channels, sim):
  from venus_interop.plr.libraries.tip_present_check import Check_Tips_Present_1ml

  result, pattern, asked = hsl_check(avenio, lay, tips, channels, sim)
  assert asyncio.run(Check_Tips_Present_1ml(_Pipettes(tips), channels, bool(sim))) == (result, pattern)
  assert asked == ([] if sim else [f"P{n}RW" for n in range(1, channels + 1)])
