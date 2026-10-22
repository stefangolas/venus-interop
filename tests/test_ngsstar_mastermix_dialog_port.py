"""Hamilton's NGSStar framework, NGSStarLoading's Display_Mastermix_Dialog: the port against the HSL.

After Avenio's own loading calls (its master mixes and their components defined and sized, as in
test_ngsstar_loading_port), the dialog runs in the HSL interpreter (the dialog component answered
by a model that records what it is given) and in the port (a scripted operator). Both must show the
same rows (name, volume, labware text), the same text and picture, and write the same summary file.

Needs VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS.
"""
import pytest

from port_harness import VECTORCUSTOMDIALOGS
from test_ngsstar_loading_port import LIBS, NGS, _Deck, avenio, calls, hsl_side, lay, port_side  # noqa: F401

pytestmark = pytest.mark.skipif(NGS is None or not LIBS,
                                reason="VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS not set")

# What this test checks against the HSL (read by tools/trace_method.py --status)
LIBRARY = "NGSSTARLOADING"
COVERS = ["Display_Mastermix_Dialog", "Retrieve_50mlTrough_ReagentsVolumesAndSequences"]

SUMMARY = "c:\\program files (x86)\\hamilton\\logfiles\\mastermixsummary.csv"


def hsl_dialog(avenio, lay, calls, samples):
  shown = []

  def loading(run, p):
    shown.append((p["i_top"].value, p["i_bottom"].value, p["i_image"].value,
                  list(zip(*(map(str, p[k].value.items) for k in ("i_col1", "i_col2", "i_col3"))))))
    return 1

  run = hsl_side(avenio, lay, calls, samples, after="NGSSTARLOADING::Display_Mastermix_Dialog();",
                 before=VECTORCUSTOMDIALOGS, run_only=True, answers={"functions": {
                   "vectorcustomdialogs::loadingdialogsetresources": lambda run, p: 1,
                   "vectorcustomdialogs::loadingdialog": loading}})
  written = run.written.get(SUMMARY, [])
  return shown, written


def port_dialog(lay, calls, samples, tmp_path):
  from venus_interop.plr.libraries.ngsstar_loading import NGSStarLoading
  from venus_interop.plr.operator import ScriptedOperator

  operator = ScriptedOperator({"Prepare Mastermix": True})
  port = NGSStarLoading(_Deck(lay), operator=operator)
  port.DATA_HandOverDataToSMT_NGSStarLoading("C:\\r\\report.csv", 1, "Roche", "Avenio CGP", 0, 0, "tc50", "tc300",
                                             "tc1000", "MlStar50ulTipWithFilter",
                                             "MlStar300ulStandardVolumeTipWithFilter", "MlStar1000ulHighVolumeTipWithFilter", 0)
  port_side(lay, calls, samples, port=port)
  port.Display_Mastermix_Dialog(log_folder=tmp_path)
  shown = [(text, d["title"], d["images"][0], [tuple(r) for r in d["rows"]])
           for kind, text, d in operator.asked if kind == "show_table"]
  summary = tmp_path / "MastermixSummary.csv"
  return shown, (summary.read_text(encoding="utf-8").splitlines() if summary.exists() else []), port


@pytest.mark.parametrize("samples", [8, 24])
def test_port_shows_the_master_mixes_as_the_library_does(avenio, lay, calls, tmp_path, samples):
  hsl, hsl_file = hsl_dialog(avenio, lay, calls, samples)
  port, port_file, loading = port_dialog(lay, calls, samples, tmp_path)
  assert hsl and len(hsl[0][3]) > 3
  assert port == hsl
  # the records; the port writes a header line too (whether Venus does is open: CONVENTIONS §11)
  assert port_file[0] == "Reagent Name;Volume Required;Description" and port_file[1:] == hsl_file
  names, volumes, seqs = loading.Retrieve_50mlTrough_ReagentsVolumesAndSequences()
  assert (names, volumes) == (loading.rgt_reagent_name, loading.rgt_total_volume) and len(seqs) == len(names)


def test_the_dialog_numbers_and_empty_labware():
  """Port only (Avenio's master mixes reach neither): above 3000 uL two places, else three, cut at
  the point plus the places; no volume where the labware text says Empty."""
  from venus_interop.plr.libraries.ngsstar_loading import NGSStarLoading, _dialog_number
  from venus_interop.plr.operator import ScriptedOperator

  assert [_dialog_number(v) for v in (3456.789, 3456.996, 2999.9876, 47.8, 3500.0)] == [
    "3456.7", "3457", "2999.98", "47.8", "3500"]
  op = ScriptedOperator({"Prepare Mastermix": True})
  port = NGSStarLoading(type("D", (), {})(), operator=op)
  port.pictures = ""
  port.run_data.append(DB_ReagentName="MM", DB_ReagentType="Mastermix", DB_TotalVolume=100.0,
                       DB_ReagentNameANDLabwareType="MM-->Empty tube")
  port.Display_Mastermix_Dialog()
  assert op.asked[0][2]["rows"] == [["MM", "", "Empty tube"]]
