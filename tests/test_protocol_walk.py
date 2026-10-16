"""Protocol traces: include closure, call resolution, PTL smart steps, error
policies, abort handlers and the condensed view's cleanup."""
from venus_interop.methods import protocol, stp_pars

from test_protocol import LIB, METHOD, STP_ITEMS, tracer

LIB_CALL = "{C1F3C015-47B3-4514-9407-AC2E65043419}"
ASSIGN = "{B31F3543-5D80-11D4-A5EB-0050DA737D89}"
IF = "{B31F3531-5D80-11d4-A5EB-0050DA737D89}"


def _step(n: int, guid: str, clsid: str, code: str) -> str:
  return f'// {{{{{{ {n} 1 0 "{guid}" "{clsid}"\n{code}\n// }}}} ""\n'


def _method(*steps: str, section: str = "main") -> str:
  head = f'// {{{{{{ 5 "{section}" "Begin"\nnamespace _Method {{ method {section}(  ) void {{\n// }}}} ""\n'
  return head + "".join(steps) + f'// {{{{{{ 5 "{section}" "End"\n}} }}\n// }}}} ""\n'


def test_include_closure_follows_headers_and_skips_comments(tmp_path):
  lib = tmp_path / "Library"
  (lib / "Sub").mkdir(parents=True)
  (lib / "Sub" / "MyLib.hs_").write_text(
    '// 2006: renamed #include "Gone.hs_" --> #include "Base.hsl"\n'
    '#ifndef HSL_RUNTIME\nnamespace MYLIB { function f( variable x ) void { } }\n#endif\n'
    '#ifdef HSL_RUNTIME\n#include __filename__ ".hsi"\n#endif\n', encoding="latin-1")
  (lib / "Sub" / "MyLib.hsi").write_text('#include "Base.hsl"\nnamespace MYLIB {\n' + LIB + "}\n", encoding="latin-1")
  (lib / "Base.hsl").write_text('/* #include "AlsoGone.hsl" */\n', encoding="latin-1")
  meth = tmp_path / "Methods" / "M.hsl"
  meth.parent.mkdir()
  meth.write_text('namespace _Method { #include "Sub\\\\MyLib.hs_" }\n'
                  'namespace _Method { #include "Missing.hsl" }\n' + METHOD, encoding="latin-1")
  files, missing = protocol.include_closure(meth, [lib])
  assert [p.name for p in files] == ["M.hsl", "MyLib.hs_", "MyLib.hsi", "Base.hsl"]
  assert missing == ["Missing.hsl"]  # the commented-out includes are not followed
  mf = protocol.load_method(meth, [lib])
  assert {lb.name: lb.namespace for lb in mf.libraries} == {"MyLib": "MYLIB", "Base": "BASE"}  # .hsi, not the stub .hs_


def test_library_namespace_is_the_declared_one():
  assert protocol.load_library("namespace _Method { }\nnamespace SOMETHING_ELSE {\n}\n", "File Name").namespace == "SOMETHING_ELSE"
  assert protocol.load_library("", "File Name").namespace == "FILE_NAME"


def test_method_section_and_library_function_of_one_name_both_expand():
  method = (_method(_step(1, "c1", LIB_CALL, "simple_aspirate(ML_STAR.A);"))
            + _method(_step(2, "c2", LIB_CALL, "TEST_LIB::simple_aspirate(asp_seq, 8, ML_STAR);"),
                      section="simple_aspirate"))
  text = "\n".join(protocol.render(tracer().section(method, "main")))
  assert "> [method] simple_aspirate(ML_STAR.A)" in text
  assert "> [lab] simple_aspirate(asp_seq = asp_seq, number_channels = 8, STAR = ML_STAR)" in text
  assert "- **TipPickUp (STAR)**" in text


def test_arity_note_and_missing_function_kept_as_code():
  method = _method(_step(1, "c1", LIB_CALL, "TEST_LIB::simple_aspirate(ML_STAR.A, 8, ML_STAR, extra);"),
                   _step(2, "c2", LIB_CALL, "TEST_LIB::not_there(1);"))
  text = "\n".join(protocol.render(tracer().section(method, "main")))
  assert "# note: 4 arguments passed, test-lib defines simple_aspirate with 3" in text
  assert "TEST_LIB::not_there(1);" in text


def test_call_inside_a_larger_statement_stays_code():
  method = _method(_step(1, "c1", IF, "if (0 == TEST_LIB::simple_aspirate(ML_STAR.A, 8, ML_STAR))\n{\nx = 1;\n}"))
  text = "\n".join(protocol.render(tracer().section(method, "main")))
  assert "if (0 == TEST_LIB::simple_aspirate(ML_STAR.A, 8, ML_STAR))" in text
  assert "> [lab]" not in text


def test_depth_limit_is_reported():
  tr = tracer()
  tr.max_depth = 0
  text = "\n".join(protocol.render(tr.section(METHOD, "main")))
  assert "# note: simple_aspirate not expanded (call depth limit 0)" in text


PTL_STEP = """{
sequence arrseqAspirate_AB[];
sequence arrseqDispense_AB[];
arrseqAspirate_AB.SetSize(1);
arrseqAspirate_AB.SetAt(0, ML_STAR.Cell_Stocks);
arrseqDispense_AB.SetSize(1);
arrseqDispense_AB.SetAt(0, ML_STAR.Cells_10x);
PTL::ResetPipettingStateAndSequences("");
PTL::SetPipettingState("TipCountingEnabled", hslFalse);
PTL::SetPipettingState("AspiratePrerinsingMixCycles", 3);
PTL::SetPipettingState("AspirateUserDefinedLiquidClass", "HighVolume_Water");
if( 0 == PTL::Pipette3(ML_STAR, ML_STAR.Tips, arrseqAspirate_AB, arrseqDispense_AB, 1, 1, 200, 0, 2, hslInfinite, hslInfinite, 1, "", ML_STAR.Cell_Stocks, ML_STAR.Cells_10x) )
{
    PTL::RaiseRuntimeError(-1573650176, PTL::IDS::smartStepPipette, PTL::IDS::smartStepFailed, "HxGRUCompCmd");
}
}"""


def test_ptl_smart_step_folds_into_one_step():
  lines = tracer().section(_method(_step(1, "p1", "{B558D25C-EB8A-4a43-8878-125E1847965C}", PTL_STEP)), "main")
  full = "\n".join(protocol.render(lines))
  assert "- **PTL Pipette3 (ML_STAR)**" in full
  for s in ("aspirate sequences = ML_STAR.Cell_Stocks", "dispense sequences = ML_STAR.Cells_10x",
            "tipPickupSequence = ML_STAR.Tips", "pipettingVolume = 200", "drivingMode = 2",
            "seqMergedDispense = ML_STAR.Cells_10x", "TipCountingEnabled = hslFalse",
            "AspiratePrerinsingMixCycles = 3", 'AspirateUserDefinedLiquidClass = "HighVolume_Water"'):
    assert f"  - {s}" in full, s
  assert "SetPipettingState" not in full and "arrseq" not in full and "RaiseRuntimeError" not in full
  condensed = "\n".join(protocol.render(lines, condensed=True))
  assert "pipettingVolume = 200" in condensed and "AspiratePrerinsingMixCycles = 3" in condensed
  assert "TipCountingEnabled" not in condensed


def _err(number, title, recs, repeat="0", use_default="0", timeout="0", infinite="0"):
  items = ["(1", "3RepeatCount", repeat, "3UseDefault", use_default, "3Timeout", timeout, "1ErrorSound", "",
           "3AddRecovery", "0", "3Infinite", infinite, "3ErrorDescription", "0", "3ErrorNumber", str(number),
           "(Recoveries"]
  for code, (rid, visible, default) in recs.items():
    items += [f"({code}", "3RecoveryVisible", visible, "3RecoveryDescription", "0", "3RecoveryFlag", "1",
              "3RecoveryTitle", str(rid), "3RecoveryDefault", default, ")"]
  return items + [")", "3NbrOfRecovery", str(len(recs)), "3ErrorTitle", str(title), ")"]


def test_error_policies_render_and_condense():
  cut = STP_ITEMS.index("(Variables")
  items = STP_ITEMS[:cut] + ["(Errors"]
  items += _err(4, 382, {1: (370, "1", "0"), 2: (436, "1", "0"), 3: (432, "1", "1"), 4: (434, "0", "0")},
                use_default="1", infinite="1")
  items += _err(2, 372, {1: (370, "1", "0"), 2: (436, "1", "0"), 3: (420, "1", "1")}, repeat="2",
                timeout="userResponseTime")
  items += _err(10, 390, {1: (370, "1", "1"), 2: (436, "1", "0")})
  items += [")"] + STP_ITEMS[cut:]
  rec = stp_pars.Record("bbbb_2222", stp_pars.parse(items))
  errs = rec.errors()
  assert [e.title for e in errs] == ["Insufficient Liquid Error", "Hardware Error", "Execution Error"]
  assert protocol.render_error(errs[0]) == ("on Insufficient Liquid Error (#4): Cancel · Abort · Bottom* "
                                            "(hidden: Air) — use default, timeout infinite")
  assert protocol.render_error(errs[1]).endswith("— repeat count 2, timeout userResponseTime")
  tr = protocol.Tracer([protocol.load_library(LIB, "test-lib")], {"bbbb_2222": rec})
  lines = tr.section(METHOD, "main")
  assert "\n".join(protocol.render(lines)).count("  - on ") == 3
  condensed = "\n".join(protocol.render(lines, condensed=True))
  assert "  - on " not in condensed
  assert ("errors set to default/repeat (2 of 3): Insufficient Liquid (default Bottom); "
          "Hardware (repeat 2×)") in condensed


def test_abort_handler_is_traced():
  method = (_method(_step(1, "r1", LIB_CALL, '::RegisterAbortHandler( "OnAbort");'))
            + _method(_step(2, "a1", ASSIGN, "parked = 1;"), section="OnAbort"))
  secs = dict(protocol.method_lines(method, [], {}))
  assert any("parked = 1;" in ln.text for ln in secs["OnAbort (abort handler)"])


def test_condensed_drops_emptied_blocks_but_keeps_if_else():
  texts = ["if (a == 1)", "{", "TipCount::Read2(x);  # [data]", "}",
           "if (b == 1)", "{", "}", "else", "{", "y = 2;", "}", "z = 3;"]
  out = [ln.text for ln in protocol.condense([protocol.Line(0, "code", "", t) for t in texts])]
  assert out == ["if (b == 1)", "{", "}", "else", "{", "y = 2;", "}", "z = 3;"]


def test_condensed_keeps_the_call_inside_an_error_guard():
  texts = ['if( 0 == hnd.Open(path, hslWrite) )', "{",
           'MECC::RaiseRuntimeErrorEx(-1, MECC::IDS::stepNameFileOpen, 0, path, "HxMetEdCompCmd");', "}",
           "if( 0 != hnd.Close() )", "{", 'MECC::RaiseRuntimeErrorEx(-2, 0, 0, "", "HxMetEdCompCmd");', "}"]
  out = [ln.text for ln in protocol.condense([protocol.Line(0, "code", "", t) for t in texts])]
  assert out == ["hnd.Open(path, hslWrite);", "hnd.Close();"]


def test_disabled_step_is_shown_marked_and_not_run():
  off, on = '/* {{ 1 "" "0" */ if(0){  /* }} "" */\n', '/* {{ 1 "" "1" */ } /* }} "" */\n'
  method = _method(_step(1, "a1", ASSIGN, 'dbg = "true";'), off,
                   _step(2, "a2", ASSIGN, 'dbg = "false";'), on, _step(3, "a3", ASSIGN, "x = 1;"))
  secs = dict(protocol.method_lines(method, [], {}))
  texts = [ln.text for ln in secs["main"]]
  assert texts == ['dbg = "true";', '# [disabled step, never runs] dbg = "false";', "x = 1;"]
