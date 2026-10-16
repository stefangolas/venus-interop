"""Protocol traces: library loading, call binding, device-step rendering."""
from venus_interop.methods import protocol, stp_pars

LIB = """function simple_aspirate( sequence & asp_seq, variable number_channels, device & STAR ) void {
// {{{ 10 "simple_aspirate" "Begin"
function simple_aspirate( sequence & asp_seq, variable number_channels, device & STAR ) void {
// }} ""
// {{{ 11 1 0 "aaaa_1111" "{586C3429-F931-405F-9938-928E22C90BFA}"
MECC::TraceComment("Pipette media into growth plate");
// }} ""
// {{{ 12 1 0 "bbbb_2222" "STAR:{541143FA-7FA2-11D3-AD85-0004ACB1DCB2}"
arrRetValues = STAR._541143FA_7FA2_11D3_AD85_0004ACB1DCB2("bbbb_2222"); // TipPickUp
// }} ""
// {{{ 5 "simple_aspirate" "End"
}
// }} ""
"""

METHOD = """// {{{ 5 "main" "Begin"
namespace _Method { method main(  ) void {
// }} ""
// {{{ 1 1 0 "cccc_3333" "{C1F3C015-47B3-4514-9407-AC2E65043419}"
arrRet = TEST_LIB::simple_aspirate(ML_STAR.Media_source, 8, ML_STAR);
// }} ""
// {{{ 2 1 0 "dddd_4444" "{B31F3543-5D80-11D4-A5EB-0050DA737D89}"
vol = culture_volume / dilution_factor;
// }} ""
// {{{ 5 "main" "End"
} }
// }} ""
"""

STP_ITEMS = [
  "1CommandStepFileGuid", "bbbb_2222",
  "1SequenceObject", "asp_seq",
  "3TipType", "5",
  "1StepName", "TipPickUp",
  "(-534183936", "(3", "3-534183876", "1", ")", "(4", "3-534183876", "1", ")", ")",
  "(Variables",
    "(-534118399", "(asp_seq", "(0", "10", "SequenceObject", ")", ")", ")",
  ")",
]


def tracer() -> protocol.Tracer:
  lib = protocol.load_library(LIB, "test-lib")
  rec = stp_pars.Record("bbbb_2222", stp_pars.parse(STP_ITEMS))
  return protocol.Tracer([lib], {"bbbb_2222": rec})


def test_namespace_of():
  assert protocol.namespace_of("GSF-IMS.shared_submethods") == "GSF_IMS_SHARED_SUBMETHODS"
  assert protocol.namespace_of("Tip Handling with 96-Head") == "TIP_HANDLING_WITH_96_HEAD"


def test_split_args():
  assert protocol.split_args("ML_STAR.Media_source, 8, f(1, 2)") == ["ML_STAR.Media_source", "8", "f(1, 2)"]


def test_load_library_replaces_prototypes():
  lib = protocol.load_library(LIB, "test-lib")
  fn = lib.find("simple_aspirate")
  assert fn is not None and len(fn.body.splitlines()) > 2
  assert lib.namespace == "TEST_LIB"


def test_trace_inlines_and_renders_settings():
  text = "\n".join(protocol.render(tracer().section(METHOD, "main")))
  assert "### Pipette media into growth plate" in text
  assert "> [lab] arrRet = simple_aspirate(asp_seq = ML_STAR.Media_source, number_channels = 8, STAR = ML_STAR)" in text
  assert "- **TipPickUp (STAR)**" in text
  assert "SequenceObject = <asp_seq>" in text
  assert "TipType = 5" in text
  assert "channel constant" not in text
  assert "vol = culture_volume / dilution_factor;" in text


def test_condense_collapses_data_and_keeps_robot():
  lines = tracer().section(METHOD, "main")
  text = "\n".join(protocol.render(lines, condensed=True))
  assert "> [lab] arrRet = simple_aspirate" in text
  assert "- **TipPickUp (STAR)**" in text
  assert "TipType = 5" in text
  assert "channel constant" not in text


def test_raw_call_lines_get_role_tags():
  method = """// {{{ 5 "main" "Begin"
namespace _Method { method main(  ) void {
// }} ""
// {{{ 1 1 0 "cccc_3333" "{C1F3C015-47B3-4514-9407-AC2E65043419}"
Dictionary::CreateDictionary();
LMSF_UTILITIES::Modulo(5, 2);
unknown_lib::Something(1);
// }} ""
// {{{ 5 "main" "End"
} }
// }} ""
"""
  out = "\n".join(protocol.render(tracer().section(method, "main")))
  assert "Dictionary::CreateDictionary();  # [data]" in out
  assert "LMSF_UTILITIES::Modulo(5, 2);  # [data]" in out
  assert "unknown_lib::Something(1);" in out and "unknown_lib::Something(1);  #" not in out


def test_trace_method_skips_missing_sections():
  lib = protocol.load_library(LIB, "test-lib")
  text = protocol.trace_method(METHOD, [lib], [], sections=("main", "GetParams"))
  assert "## section main" in text
  assert "GetParams" not in text
