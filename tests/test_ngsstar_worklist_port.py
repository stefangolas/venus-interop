"""Hamilton's NGSStar framework, NGSStarLoading's Read_InputWorklist_ExcelOrCSVFormat: the port
against the HSL.

The worklist reader runs in the HSL interpreter (the CSV as one of the run's files) and in the
port (the same CSV on disk), as Avenio calls it (the sample template HSP_Pipette2): worklists with
index plates or index tubes, a sample with no position (skipped), ids with leading zeros, no
index 2 ids. Both must return the same counts, positions, ids, labware and index format.

Needs VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS.
"""
import pytest

from port_harness import RecordingDeck, VECTORCUSTOMDIALOGS, hsl_run
from test_ngsstar_processes_port import LIBS, NGS, avenio, lay  # noqa: F401

pytestmark = pytest.mark.skipif(NGS is None or not LIBS,
                                reason="VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS not set")

# What this test checks against the HSL (read by tools/trace_method.py --status)
LIBRARY = "NGSSTARLOADING"
COVERS = ["Read_InputWorklist_ExcelOrCSVFormat", "Display_Error_Dialog"]

HEADER = "Sample_ID;Sample_Position;Index1_ID;Index1_Pos;Index2_ID;Index2_Pos"
WORKLISTS = {
  "plate": [HEADER, "S01;A1;I7_01;A1;I5_01;A1", "S02;B1;I7_02;B1;I5_02;B1", "S03;C1;I7_03;C1;I5_03;C1"],
  "tubes": [HEADER, "007;A1;IDX1;1;;", "008;B1;IDX2;2;;", "009;C1;IDX3;3;;", "010;D1;IDX4;4;;"],
  "a-gap": [HEADER, "S1;A1;I1;A2;;", "S2;;I2;B2;;", "S3;C1;I3;C2;;"],
}
OUTPUTS = ["n", "used", "i1pos", "i1id", "i2pos", "i2id", "labs", "pos", "fmt"]
PATH = "C:\\NGSStarInputFiles\\worklist.csv"
SRC = ('namespace _Method { #include "HSLSeqLib.hsl" }\n'
       'namespace _Method { #include "NGSStarLoading\\\\NGSStarLoading.hs_" }\n'
       'global device ML_STAR ("x.lay", "ML_STAR", hslTrue);\n'
       'namespace _Method { #include "HSLMECCLib.hs_" }\n' + VECTORCUSTOMDIALOGS +
       "namespace _Method { " + "".join(f"global variable g_{k}; " for k in OUTPUTS) +
       "method main() void { variable n; variable used; variable fmt; variable a[]; variable b[]; variable c[]; "
       "variable d[]; variable e[]; variable f[];\n"
       f'NGSSTARLOADING::Read_InputWorklist_ExcelOrCSVFormat("{PATH.replace(chr(92), chr(92) * 2)}", '
       "ML_STAR.HSP_Pipette2, n, used, a, b, c, d, e, f, fmt);\n"
       "g_n = n; g_used = used; g_i1pos = a; g_i1id = b; g_i2pos = c; g_i2id = d; g_labs = e; g_pos = f; "
       "g_fmt = fmt; } }\n")


def hsl_read(avenio, lay, rows):
  run = hsl_run(SRC, avenio / "Library" / "port_test.hsl", [avenio / "Library", avenio / "Methods", *LIBS],
                (avenio / "Library" / "NGSStarLoading").glob("*.stp"), {"x.lay": lay},
                files={PATH: "\n".join(rows) + "\n"},
                # the status window: TRUE, as the library's bind check wants it
                answers={"functions": {"vectorcustomdialogs::appendstatustext": lambda run, p: 1}})
  cells = {k: c.value for sc in run.globals.values() for k, c in sc.items() if k.startswith("g_")}
  out = []
  for k in OUTPUTS:
    v = cells[f"g_{k}"]
    out.append([str(x) for x in v.items] if hasattr(v, "items") else v)
  return tuple(out)


def port_read(lay, rows, tmp_path):
  from venus_interop.plr.libraries.ngsstar_loading import NGSStarLoading

  f = tmp_path / "worklist.csv"
  f.write_text("\n".join(rows) + "\n", encoding="utf-8")
  loading = NGSStarLoading(RecordingDeck(lay))
  return loading.Read_InputWorklist_ExcelOrCSVFormat(f, "HSP_Pipette2"), loading.sample_ids


@pytest.mark.parametrize("case", list(WORKLISTS))
def test_port_reads_the_worklist_as_the_library_does(avenio, lay, tmp_path, case):
  hsl = hsl_read(avenio, lay, WORKLISTS[case])
  port, ids = port_read(lay, WORKLISTS[case], tmp_path)
  assert tuple(port) == hsl
  assert ids == [r.split(";")[0] for r in WORKLISTS[case][1:] if r.split(";")[1]]


def test_tubes_keep_their_ids_and_double_indexing_is_always_reported(lay, tmp_path):
  (n, used, *_, fmt), ids = port_read(lay, WORKLISTS["tubes"], tmp_path)
  assert (n, used, fmt) == (4, 2, "tube") and ids[0] == "007"


def test_an_unknown_format_aborts(lay, tmp_path):
  from venus_interop.plr.libraries.ngsstar_loading import NGSStarLoading
  from venus_interop.plr.operator import RunAborted, ScriptedOperator

  f = tmp_path / "worklist.txt"
  f.write_text(HEADER + "\n", encoding="utf-8")
  op = ScriptedOperator({"Not supported format": True})
  with pytest.raises(RunAborted, match="Not supported"):
    NGSStarLoading(RecordingDeck(lay), operator=op).Read_InputWorklist_ExcelOrCSVFormat(f, "HSP_Pipette2")
