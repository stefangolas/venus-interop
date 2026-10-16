"""Function bodies in method and library code."""
from venus_interop.methods import hsl_code

LIB = """namespace _Method { #include "Common\\\\Common96HeadSubMethods.hs_" }
function simple_aspirate( sequence & asp_seq, variable p_vol = 100, device & STAR ) void ;
function tip_pickup( sequence & tips, variable number_channels, device & STAR ) void ;
// {{{ 5 "tip_pickup" "Begin"
function tip_pickup( sequence & tips, variable number_channels, device & STAR ) void {
// }} ""
// {{ 5 "tip_pickup" "InitLocals"
// }} ""
// {{{ 287 1 0 "c83a0fc9_290d_4c8c_9f5466f0796a3015" "{7C4EF7A7-39BE-406A-897F-71F3A35B4093}"
set_channel_pattern(number_channels);
// }} ""
// {{ 288 1 0 "a511000a_8a13_4a12_83095aaca3842552" "{B31F3531-5D80-11d4-A5EB-0050DA737D89}"
if (number_channels == 8)
{
// }} ""
// {{{ 289 1 0 "a511000a_8a13_4a12_83095aaca3842552" "{9EC997CD-FD3B-4280-811B-49E99DCF062C}"
return;
// }} ""
// {{ 288 1 0 "a511000a_8a13_4a12_83095aaca3842552" "{B31F3531-5D80-11d4-A5EB-0050DA737D89}"
}
// }} ""
// {{{ 5 "tip_pickup" "End"
}
// }} ""
function trailing_comment_test() { string s = "a } b { c"; // } not a brace
x = 1;
}
"""


def test_prototypes_and_definitions():
  fns = hsl_code.functions(LIB)
  names = [f.name for f in fns]
  assert names == ["simple_aspirate", "tip_pickup", "trailing_comment_test"]
  assert fns[0].prototype_only and not fns[1].prototype_only
  assert fns[0].args[1].default == "100"


def test_definition_replaces_prototype():
  fns = hsl_code.functions(LIB)
  tip = [f for f in fns if f.name == "tip_pickup"][0]
  assert tip.args == [hsl_code.Arg("sequence &", "tips"), hsl_code.Arg("variable", "number_channels"), hsl_code.Arg("device &", "STAR")]
  assert tip.ret == "void"
  assert "set_channel_pattern(number_channels);" in tip.body
  assert tip.body.rstrip().endswith("}")


def test_body_braces_skip_strings_and_comments():
  fns = hsl_code.functions(LIB)
  t = [f for f in fns if f.name == "trailing_comment_test"][0]
  assert 'string s = "a } b { c";' in t.body
  assert t.body.rstrip().endswith("}")
  assert "// } not a brace" in t.body


def test_steps_inside_body():
  from venus_interop.methods import hsl
  tip = [f for f in hsl_code.functions(LIB) if f.name == "tip_pickup"][0]
  steps = hsl.steps(tip.body)
  assert [s.type for s in steps] == ["sub-method call", "If / Else", "Return (inferred)", "If / Else"]
  assert steps[0].code == "set_channel_pattern(number_channels);"
