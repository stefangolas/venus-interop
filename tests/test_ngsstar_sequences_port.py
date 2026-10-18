"""Hamilton's NGSStar framework, NGSStarProcesses' sequence builder against the HSL library itself.

Roche Avenio CGP's own calls to DATA_CreateNewSequencesOrTransportSequences (pipetting sequences
on a template's labware, and transport sequences), on its layout, with sample positions standing in
for the ones the method reads from its worklist. Every sequence made must match the library's.
Needs VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS.
"""
import os
import pathlib
import re

import pytest

from port_harness import hsl_run  # noqa: E402
from venus_interop.files import layout  # noqa: E402
from venus_interop.methods import sequences as sq  # noqa: E402

NGS = pathlib.Path(os.environ["VENUS_INTEROP_NGS"]) if os.environ.get("VENUS_INTEROP_NGS") else None
LIBS = [pathlib.Path(p) for p in os.environ.get("VENUS_INTEROP_HAMILTON_LIBS", "").split(os.pathsep) if p]
pytestmark = pytest.mark.skipif(NGS is None or not LIBS,
                                reason="VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS not set")

# What this test checks against the HSL (read by tools/trace_method.py --status)
LIBRARY = "NGSSTARPROCESSES"
COVERS = ["DATA_CreateNewSequencesOrTransportSequences"]


def _wells(n, start=0):
  return [f"{'ABCDEFGH'[i % 8]}{i // 8 + 1}" for i in range(start, start + n)]


class _Deck:
  def __init__(self, lay):
    self.sequences = {s.name: list(s.items) for s in lay.sequences}

  def seq(self, name):
    return name if isinstance(name, sq.Sequence) else sq.Sequence(name, list(self.sequences[name]))


@pytest.mark.parametrize("samples", [8, 24])
def test_sequences_match_the_hsl(samples):
  from venus_interop.plr.libraries.ngsstar_processes import NGSStarProcesses

  avenio = NGS / "assets" / "NGSStar" / "Roche" / "Avenio CGP"
  text = (avenio / "Methods" / "Avenio CGP_v1.0.1.sub").read_text(encoding="latin-1")
  calls = re.findall(r"NGSSTARPROCESSES::DATA_CreateNewSequencesOrTransportSequences\((ML_STAR\.\w+), (\w+), \w+, (\d)\);",
                     text)
  assert len(calls) == 25
  arrays = {a: _wells(samples, start=8 * k) for k, a in enumerate(sorted({a for _, a, _ in calls}))}
  fill = "".join(f"{a}.AddAsLast(\"{p}\");\n" for a, ps in arrays.items() for p in ps)
  body = "".join(f"NGSSTARPROCESSES::DATA_CreateNewSequencesOrTransportSequences({t}, {a}, s{i}, {k});\n"
                 for i, (t, a, k) in enumerate(calls))
  src = ('namespace _Method { #include "NGSStarProcesses.hs_" }\n'
         'global device ML_STAR ("x.lay", "ML_STAR", hslTrue);\n'
         + "".join(f"variable {a}[];\n" for a in arrays) + "".join(f"sequence s{i};\n" for i in range(len(calls))) +
         'namespace _Method { #include "HSLMECCLib.hs_" }\n'
         "namespace _Method { method main() void {\n" + fill + body + "} }\n")
  lay = layout.read_layout(avenio / "Methods" / "Avenio CGP.lay")
  run = hsl_run(src, avenio / "Library" / "port_test.hsl", [avenio / "Library", avenio / "Methods", *LIBS], [],
                {"x.lay": lay})
  made = {k.lower(): c.value for cells in run.globals.values() for k, c in cells.items()}
  port = NGSStarProcesses(type("Star", (), {"pipettes": None})(), _Deck(lay), {}, {})
  for i, (template, array, kind) in enumerate(calls):
    got = port.DATA_CreateNewSequencesOrTransportSequences(template.split(".")[1], arrays[array], int(kind))
    want = made[f"s{i}"]
    assert got.items == want.items and (got.cur, got.end) == (want.cur, want.end), (template, array, kind)
