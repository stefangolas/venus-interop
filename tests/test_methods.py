"""Method code: step markers and text-file footers."""
import pytest

from venus_interop.files import footer
from venus_interop.methods import hsl

METHOD = """// {{{ 5 "main" "Begin"
namespace _Method { method main(  ) void {
// }} ""
// {{{ 1 1 0 "aaaa_1111" "{C1F3C015-47B3-4514-9407-AC2E65043419}"
blnReturn = HSLHttp::Initialize(objHttp);
// }} ""
// {{ 2 1 0 "bbbb_2222" "{B31F3531-5D80-11d4-A5EB-0050DA737D89}"
if (blnReturn != blnSuccess)
{
// }} ""
// {{{ 3 1 0 "cccc_3333" "{9EC997CD-FD3B-4280-811B-49E99DCF062C}"
return;
// }} ""
// {{ 4 1 0 "bbbb_2222" "{B31F3531-5D80-11d4-A5EB-0050DA737D89}"
}
// }} ""
// {{{ 5 "main" "End"
} }
// }} ""
"""


def with_footer(body: str, offset: int = 0) -> bytes:
  data = body.encode("latin-1") + b"// $$author=me$$valid=0$$time=2026-10-15 12:00$$checksum=00000000$$length=000$$\r\n"
  f = footer.read(data)
  # build a valid footer by rewriting with the original time
  out = footer.rewrite(data, time=f.time)
  return out


def test_steps_and_types():
  steps = hsl.steps(METHOD)
  assert [s.row for s in steps] == [1, 2, 3, 4]
  assert [s.type for s in steps] == ["library function call", "If / Else", "Return (inferred)", "If / Else"]
  assert steps[1].part and not steps[0].part and steps[1].guid == steps[3].guid
  assert steps[0].section == "main" and steps[0].code == "blnReturn = HSLHttp::Initialize(objHttp);"
  assert hsl.summary(METHOD) == {"library function call": 1, "If / Else": 1, "Return (inferred)": 1}


def test_footer_rewrite_and_check():
  data = with_footer(METHOD)
  assert footer.ok(data)
  edited = data.replace(b"objHttp", b"objHttp2")
  assert not footer.ok(edited)
  fixed = footer.rewrite(edited, time="2026-10-16 09:00")
  assert footer.ok(fixed) and footer.read(fixed).time == "2026-10-16 09:00"
  assert footer.read(fixed).author == "me"


def test_no_footer():
  with pytest.raises(ValueError):
    footer.read(b"no footer here")


DEVICE = """// {{{ 5 "tip_pickup" "Begin"
function tip_pickup( sequence & tips, variable number_channels, device & STAR ) void {
// }} ""
// {{{ 288 1 0 "a511000a_8a13_4a12_83095aaca3842552" "STAR:{541143FA-7FA2-11D3-AD85-0004ACB1DCB2}"
arrRetValues = STAR._541143FA_7FA2_11D3_AD85_0004ACB1DCB2("a511000a_8a13_4a12_83095aaca3842552"); // TipPickUp
// }} ""
// {{{ 5 "tip_pickup" "End"
}
// }} ""
"""


def test_device_step_markers():
  steps = hsl.steps(DEVICE)
  assert len(steps) == 1
  assert steps[0].device == "STAR"
  assert steps[0].type == "device step (STAR)"
  assert steps[0].code.endswith("// TipPickUp")
  assert hsl.summary(DEVICE) == {"device step (STAR)": 1}


def test_disabled_steps_are_marked():
  text = METHOD.replace('// {{{ 3 1 0', '/* {{ 1 "" "0" */ if(0){  /* }} "" */\n// {{{ 3 1 0', 1)
  text = text.replace('return;\n// }} ""\n', 'return;\n// }} ""\n/* {{ 1 "" "1" */ } /* }} "" */\n', 1)
  steps = hsl.steps(text)
  assert [s.row for s in steps] == [1, 2, 3, 4]
  assert [s.disabled for s in steps] == [False, False, True, False]
