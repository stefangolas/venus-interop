"""Hamilton's NGSStar framework, NGSStarLoading's Display_SelectProcesses_Dialog: the port against
the HSL.

The workflow dialogs (where to start, where to stop) run in the HSL interpreter (the radio-button
dialog answered by a model that records what it is shown and selects by label) and in the port (a
scripted operator choosing the same labels): Avenio's own processes and combinations, taking the
preselected start or another, and an illustrative set with deactivated start and stop points.
Both must show the same choices and texts and return the same start, stop and activation list.

Needs VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS.
"""
import functools

import pytest

from port_harness import ARRAYTOOLS, ARRAYTOOLS_MODELS, VECTORCUSTOMDIALOGS, RecordingDeck, hsl_eval, hsl_run
from test_ngsstar_processes_port import LIBS, NGS, avenio, lay  # noqa: F401

pytestmark = pytest.mark.skipif(NGS is None or not LIBS,
                                reason="VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS not set")

# What this test checks against the HSL (read by tools/trace_method.py --status)
LIBRARY = "NGSSTARLOADING"
COVERS = ["Display_SelectProcesses_Dialog"]

AVENIO = (["Section 1: DNA Polishing, Fragmentation and preparation of Adapter Ligation",
           "Section 2: Ligation CleanUp, PCR amplificatiion and PCR CleanUp", "Section 3: Prepare Hybridization",
           "Section 4: Prepare Capture Beads & Perform Hybridization Cleanup",
           "Section 5: Amplify enriched FFPE DNA sample & Cleanup"], ["1", "2", "3", "4.5", "5"], [], [])
ILLUSTRATIVE = (["P1", "P2", "P3", "P4"], ["1.2.3.4", "2.3.4", "3.4", "4"], [1], [2, 4])
# (processes, combinations, no start, no stop, the start chosen (None: the preselected), the stop chosen)
OPEN = (["Q1", "Q2", "Q3", "Q4"], ["1.2.3.4", "2.3.4", "3.4", "4"], [], [])  # a stop before the combination's end
CASES = [(*AVENIO, None, None), (*AVENIO, AVENIO[0][3], AVENIO[0][4]), (*AVENIO, AVENIO[0][2], None),
         (*ILLUSTRATIVE, None, None), (*ILLUSTRATIVE, "P3", "P3"), (*OPEN, "Q1", "Q2")]


def _list(values):
  return "".join(f"a.AddAsLast({v!r});".replace("'", '"') if isinstance(v, str) else f"a.AddAsLast({v});"
                 for v in values)


@functools.lru_cache(maxsize=8)
def _source(ids, combinations, no_start, no_stop):
  arrays = [("ids", ids), ("comb", combinations), ("nostart", no_start), ("nostop", no_stop)]
  fill = "".join(f"{name}.SetSize(0);" + _list(vals).replace("a.AddAsLast", f"{name}.AddAsLast")
                 for name, vals in arrays)
  return ('namespace _Method { #include "HSLSeqLib.hsl" }\n'
          'namespace _Method { #include "NGSStarLoading\\\\NGSStarLoading.hs_" }\n'
          'global device ML_STAR ("x.lay", "ML_STAR", hslTrue);\n'
          'namespace _Method { #include "HSLMECCLib.hs_" }\n' + ARRAYTOOLS + VECTORCUSTOMDIALOGS +
          "namespace _Method { global variable g_start; global variable g_stop; global variable g_on[];\n"
          "method main() void { variable ids[]; variable comb[]; variable nostart[]; variable nostop[]; "
          "variable start; variable stop; variable on[];\n" + fill +
          "NGSSTARLOADING::Display_SelectProcesses_Dialog(1, ids, comb, nostart, nostop, start, stop, on);\n"
          "g_start = start; g_stop = stop; g_on = on; } }\n")


def hsl_select(avenio, lay, case):
  ids, comb, no_start, no_stop, pick_start, pick_stop = case
  shown = []

  def radio(run, p):
    labels = [str(x) for x in p["i_labels"].value.items]
    editable = [int(x) for x in p["i_editable"].value.items]
    selected = p["io_selected"].value.items
    shown.append((p["i_top"].value, [lab for lab, e in zip(labels, editable) if e]))
    pick = pick_start if len(shown) == 1 else pick_stop
    if pick is not None:
      for k, lab in enumerate(labels):
        selected[k] = int(lab == pick and editable[k] == 1)
    return 1

  src = _source(tuple(ids), tuple(comb), tuple(no_start), tuple(no_stop))
  run = hsl_run(src, avenio / "Library" / "port_test.hsl", [avenio / "Library", avenio / "Methods", *LIBS],
                (avenio / "Library" / "NGSStarLoading").glob("*.stp"), {"x.lay": lay},
                answers={"functions": {"vectorcustomdialogs::radiobuttondialog": radio, **ARRAYTOOLS_MODELS}})
  g = {k: c.value for sc in run.globals.values() for k, c in sc.items() if k.startswith("g_")}
  return shown, (int(g["g_start"]), int(g["g_stop"]), [bool(x) for x in g["g_on"].items])


def port_select(lay, case):
  from venus_interop.plr.libraries.ngsstar_loading import NGSStarLoading
  from venus_interop.plr.operator import ScriptedOperator

  ids, comb, no_start, no_stop, pick_start, pick_stop = case
  picks = iter([pick_start, pick_stop])
  operator = ScriptedOperator({"Define Workflow": lambda kind, text, **d: next(picks) or True})
  result = NGSStarLoading(RecordingDeck(lay), operator=operator).Display_SelectProcesses_Dialog(
    1, ids, comb, no_start, no_stop)
  shown = [(text, d["options"]) for kind, text, d in operator.asked if kind == "choose"]
  return shown, result


@pytest.mark.parametrize("case", CASES, ids=["avenio", "avenio-4-to-5", "avenio-3", "deactivated", "deactivated-P3", "stop-early"])
def test_port_selects_the_workflow_as_the_library_does(avenio, lay, case):
  hsl, port = hsl_select(avenio, lay, case), port_select(lay, case)
  assert port == hsl
