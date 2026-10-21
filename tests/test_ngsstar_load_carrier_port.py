"""Hamilton's NGSStar framework, NGSStarLoading's Load_Carrier: the port against the HSL library.

Roche Avenio CGP's loading calculations run first (as in test_ngsstar_loading_port), then
Evaluate_ResourcesByCarrier and the method's twelve Load_Carrier calls, in its order and with its
arguments, in the HSL interpreter and in the port. They must agree on:
  - the autoload's steps: which carriers are unloaded and loaded, in order, whether barcodes are
    read, and the front cover's monitoring switched off and on when the system locks;
  - the loading dialog, call for call: its text, pictures and table (position, quantity, what);
  - the tip counters' dialogs and the tip sequences the library keeps;
  - the run report's rows for the barcodes read.

The dialogs are VectorCustomDialogs (a compiled component): its functions are declared and
answered here, recording what they were given (port_harness.VECTORCUSTOMDIALOGS); the port asks a
ScriptedOperator. The autoload's barcodes are made up per carrier site, given to both sides alike.
Needs VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS.
"""
import asyncio
import re
import time

import pytest

from port_harness import CLOCK, REPORT_BOOK, VECTORCUSTOMDIALOGS, report_rows  # noqa: E402
from test_ngsstar_loading_port import LIBS, NGS, _Deck, avenio, calls, hsl_side, lay, port_side  # noqa: E402,F401

pytestmark = pytest.mark.skipif(NGS is None or not LIBS,
                                reason="VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS not set")

# What this test checks against the HSL (read by tools/trace_method.py --status)
LIBRARY = "NGSSTARLOADING"
COVERS = ["Load_Carrier", "Evaluate_ResourcesByCarrier", "DATA_TipCounterRead", "DATA_TipCounterWrite"]

TIPS = {50: "MlStar50ulTipWithFilter", 300: "MlStar300ulStandardVolumeTipWithFilter",
        1000: "MlStar1000ulHighVolumeTipWithFilter"}
L = "NGSSTARLOADING::"


@pytest.fixture(scope="module")
def loads(avenio):
  """Avenio's Load_Carrier calls: (carrier constant, loadable, main picture, small picture)."""
  text = (avenio / "Methods" / "Avenio CGP_v1.0.1.sub").read_text(encoding="latin-1")
  out = []
  for m in re.finditer(r"NGSSTARLOADING::Load_Carrier\(ML_STAR, ARW_Global::CarrierType::(\w+), t_blnSkipLoadingRoutine, "
                       r"([\w:]+), ASWGLOBAL::BOOL::FALSE, Translate\(\"([^\"]*)\"\), Translate\(\"([^\"]*)\"\)\);", text):
    out.append((m.group(1), m.group(2), m.group(3), m.group(4)))
  return out


def _carrier(constant):
  from venus_interop.plr.libraries import ngsstar_loading as nl
  return {"CPAC": "MFX_CAR_2HHSF30MTP_HHSF30DWP_CPAC_0001", "RGT1": "RGT_CAR_1", "RGT2": "RGT_CAR_2",
          "Tube_Carrier24": "CAR_VIALS_LARGE", "Vial_Carrier32_01": "CAR_VIALS_SMALL",
          "Vial_Carrier32_02": "CAR_Adapter_Tubes", "ODTC": "MFX_CAR_ODTC_MTP_0001", "PLT_Stack": nl.PLT_STACK,
          "TIP50_01": nl.TIP50_01, "TIP50_02": nl.TIP50_02, "TIP300_01": nl.TIP300_01, "TIP300_02": nl.TIP300_02,
          "PLT_TIP1000": nl.PLT_TIP1000, "HHSx2_PLT": "MFX_CAR_2HHS30NuncDWP_Empty_PCR96_0001"}[constant]


def _barcodes(port, carrier):
  """The made-up barcodes the autoload reads: one per carrier site holding labware, by position."""
  return {i: f"BC-{carrier[-6:]}-{site}" for i, (site, _) in enumerate(port._carrier_sites(carrier))}


def hsl_loading(avenio, lay, calls, loads, samples, lock, skip, counters=None, yes=False):
  from venus_interop.plr.libraries.ngsstar_loading import NGSStarLoading

  shown = []
  lookup = NGSStarLoading(_Deck(lay))

  def autoload(rack, wanted):
    if wanted == "":
      return {}
    keep = None if wanted in ("?", "*") else {p for p in wanted.split(",") if p}
    sites = lookup._carrier_sites(rack)
    return {"track": 1, "positions": [(i + 1, bc, sites[i][1], "") for i, bc in _barcodes(lookup, rack).items()
                                      if keep is None or sites[i][0] in keep]}

  def dialog(kind, *fields, answer=1):
    def model(run, p):
      shown.append((kind, *(p[f].value if not hasattr(p[f].value, "items") else list(p[f].value.items)
                            for f in fields)))
      return answer
    return model

  # the method has read its counters into its tip sequences before it hands them over
  handover = "".join(f"ML_STAR.{TIPS[int(n[2:])]}.SetCurrentPosition({pos});\n"
                     for n, pos in (counters or {}).items())
  handover += (f'{L}DATA_HandOverDataToSMT_NGSStarLoading("{REPORT_BOOK}", 1, "Roche", "Avenio CGP", 0, {lock}, '
              f'"tc50", "tc300", "tc1000", ML_STAR.{TIPS[50]}, ML_STAR.{TIPS[300]}, ML_STAR.{TIPS[1000]}, 0);\n')
  after = f"{L}Evaluate_ResourcesByCarrier();\n" + "".join(
    f'{L}Load_Carrier(ML_STAR, ARW_Global::CarrierType::{c}, {skip}, {1 if "BOOL" not in ok else ok}, 0, "{a}", "{b}");\n'
    for c, ok, a, b in loads)
  V = "vectorcustomdialogs::"
  run = hsl_side(avenio, lay, calls, samples, after=after, before=VECTORCUSTOMDIALOGS, handover=handover,
                 stps=[avenio / "Library" / "NGSStarLoading" / "NGSStarLoading.stp"], run_only=True,
                 # STAR Tip Tools calls it; its body is empty, which the parser takes for a header placeholder
                 allow_unresolved=["TIP_OFFSET_GLOBAL::INIT::InitializeVariables"], answers={
                   "clock": time.struct_time(CLOCK), "autoload": autoload, "tip_counters": counters or {},
                   "functions": {V + "loadingdialogsetresources": dialog("columns", "i_columns"),
                                 V + "loadingdialog": dialog("loading", "i_bottom", "i_image", "i_small", "i_col1",
                                                             "i_col2", "i_col3"),
                                 V + "listdialog": dialog("list", "i_top", "i_items"),
                                 V + "messagedialog": dialog("message", "i_text", answer=6 if yes else 7),
                                 V + "errordialog": dialog("error", "i_text")}})
  steps = []
  for e in run.events:
    s = e.settings
    if e.command == "UnloadCarrier":
      steps.append(("unload", s["RackTypeName"]))
    elif e.command == "LoadCarrier":
      steps.append(("load", s["RackTypeName"], s["BarcodesToRead"] != ""))
    elif e.command == "FirmwareCommand":
      steps.append({"C0CD": ("disable_control",), "C0CE": ("enable_control",)}[s["firmware command string"]])
  dialogs = [("loading", d[1], [d[2]] + ([d[3]] if d[3] else []), list(zip(d[4], d[5], d[6])))
             for d in shown if d[0] == "loading"]
  lib = {k.lower(): c.value for ns, cells in run.globals.items() if ns.lower().split("::")[-1] == "ngsstarloading"
         for k, c in cells.items()}
  tips = {t: _left(lib[f"t_seqtips{t}"]) for t in TIPS}
  others = [d[:3] if d[0] == "list" else d[:2] for d in shown if d[0] in ("list", "message", "error")]
  aborted = any(n.startswith("abort") for n in run.notes)
  return (steps, dialogs, others, report_rows(run), tips) + (("aborted",) if aborted else ())


def _left(s):
  """A tip sequence's tips left: the positions from the current one to the end."""
  return list(s.items[s.cur - 1:s.end]) if s.cur > 0 else []


class _Autoload:
  def __init__(self, port, log):
    self.port, self.log = port, log

  async def unload_carrier(self, carrier):
    self.log.append(("unload", carrier))

  async def load_carrier(self, carrier, barcode_reading=False):
    self.log.append(("load", carrier, barcode_reading))
    return {"carrier_barcode": None, "container_barcodes": _barcodes(self.port, carrier) if barcode_reading else {}}


class _Cover:
  def __init__(self, log):
    self.log = log

  async def request_state(self):
    return "closed"

  async def enable_control(self):
    self.log.append(("enable_control",))

  async def disable_control(self):
    self.log.append(("disable_control",))


class _LoadDeck(_Deck):
  def seq(self, name):  # a sequence the library holds is itself (VenusDeck's way)
    return name if not isinstance(name, str) else super().seq(name)

  def resource(self, name):
    return name


def port_loading(lay, calls, loads, samples, lock, skip, counters=None, yes=False):
  from venus_interop.plr.libraries import ngsstar_loading as nl
  from venus_interop.plr.libraries.ngsstar_report import RunReport
  from venus_interop.plr.libraries.tip_count import OCCUPIED
  from venus_interop.plr.operator import ScriptedOperator

  log = []
  operator = ScriptedOperator({"Press OK to Continue": True, "Preventative tip exchange": yes,
                               "Not enough tips": True})
  deck = _LoadDeck(lay)
  port = nl.NGSStarLoading(deck, operator=operator, report=RunReport(clock=lambda: time.struct_time(CLOCK)))
  port.star = type("Star", (), {"autoload": _Autoload(port, log), "front_cover": _Cover(log)})()
  for name, position in (counters or {}).items():  # a stored counter: the tips from `position` on
    deck.seq(TIPS[int(name[2:])]).set_current_position(position)
    tips = deck.sequences[TIPS[int(name[2:])]]
    port.planner.counters.write(name, [(tuple(it), OCCUPIED) for it in tips[position - 1:]])
  port.DATA_HandOverDataToSMT_NGSStarLoading(REPORT_BOOK, 1, "Roche", "Avenio CGP", 0, lock, "tc50", "tc300", "tc1000",
                                             TIPS[50], TIPS[300], TIPS[1000], 0)
  port_side(lay, calls, samples, port=port)
  port.Evaluate_ResourcesByCarrier()

  async def go():
    for c, ok, a, b in loads:
      await port.Load_Carrier(None, _carrier(c), skip, 0 if ok.endswith("FALSE") else 1, 0, a, b)

  asyncio.run(go())
  dialogs = [("loading", text, d["images"], [tuple(r) for r in d["rows"]])
             for kind, text, d in operator.asked if kind == "show_table"]
  others = [("message", text) if d.get("yes_no") else ("list", text, d["items"])
            for kind, text, d in operator.asked if kind == "confirm"]
  tips = {t: _left(s) for t, s in port.tips.items()}
  return log, dialogs, others, port.report.rows, tips


def test_covers_avenios_calls(loads):
  assert len(loads) == 12


@pytest.fixture
def fits(monkeypatch):
  """Plate counts the stacker holds (test_ngsstar_loading_port's are added per process: 10 HSP
  plates on its one HSP site of 4 is the library's error): MIDI plates on two sites, one lid."""
  import test_ngsstar_loading_port as tl
  monkeypatch.setitem(tl.UNITS, "l_intNumberOfHSPPlates", 0)
  monkeypatch.setitem(tl.UNITS, "l_intNumberOfMIDIPlates", 1)


@pytest.mark.parametrize("lock", [0, 1], ids=["unlocked", "locked"])
@pytest.mark.parametrize("samples", [8, 24])
def test_load_carrier_as_the_library_does(avenio, lay, calls, loads, samples, lock, fits):
  h_steps, h_dialogs, h_others, h_report, h_tips = hsl_loading(avenio, lay, calls, loads, samples, lock, 0)
  p_steps, p_dialogs, p_others, p_report, p_tips = port_loading(lay, calls, loads, samples, lock, 0)
  assert h_steps and h_steps == p_steps
  assert len(h_dialogs) == len(p_dialogs)
  for i, (x, y) in enumerate(zip(h_dialogs, p_dialogs)):
    assert x[0] == y[0] and x[1] == y[1], i
    assert [p.split("\\")[-1] for p in x[2]] == [p.split("\\")[-1] for p in y[2]], i
    assert x[3] == y[3], (i, x[3], y[3])
  assert h_others == p_others
  assert h_report == p_report
  assert h_tips == p_tips


def _same(avenio, lay, calls, loads, **kw):
  h = hsl_loading(avenio, lay, calls, loads, 8, 1, 0, **kw)
  p = port_loading(lay, calls, loads, 8, 1, 0, **kw)
  for name, x, y in zip(("steps", "loading dialogs", "tip dialogs", "report", "tips"), h, p):
    if name == "loading dialogs":
      x, y = [d[:2] + d[3:] for d in x], [d[:2] + d[3:] for d in y]  # pictures: compared above
    assert x == y, f"{name}: library {x}, port {y}"
  return h


@pytest.mark.parametrize("yes", [False, True], ids=["refill 300 uL", "refill every type"])
def test_too_few_tips_left_are_refilled(avenio, lay, calls, loads, fits, yes):
  """A stored 300 uL counter with 61 tips for 480: the refill list, the question whether to refill
  every type, then each type's first carrier out, its counter edited, and in again."""
  steps, _, asked, _, _ = _same(avenio, lay, calls, loads, counters={"tc300": 900}, yes=yes)
  assert [a[0] for a in asked] == ["list", "message"]
  assert "Please load more 300ul tips" in asked[0][2][1]
  unloads = [s[1] for s in steps if s[0] == "unload" and "TIP" in s[1]]
  # loading the 50 and 300 uL pairs, the refills while the 300 uL pair is out (each type's first
  # carrier), then the 1000 uL carrier
  assert unloads[-1] == "PLT_CAR_2TIP_2PCR_MTP" and unloads[4:-1] == (["TIP_CAR_480BC_TIP_STF_YELLOW_0001"] if not yes else
                         ["TIP_CAR_480BC_TIP_50F_PINK_0001", "TIP_CAR_480BC_TIP_STF_YELLOW_0001", "PLT_CAR_2TIP_2PCR_MTP"])


def test_more_tips_than_the_deck_holds_schedule_a_reload(avenio, lay, calls, loads, fits, monkeypatch):
  import test_ngsstar_loading_port as tl
  monkeypatch.setitem(tl.UNITS, "l_intNumberOf300uLTips", 1000)
  _, _, asked, _, _ = _same(avenio, lay, calls, loads)
  assert [(a[0], a[1]) for a in asked] == [("list", "Not enough tips available.")]


def test_more_plates_than_the_stacker_holds_end_the_run(avenio, lay, calls, loads):
  """test_ngsstar_loading_port's counts: 10 HSP plates for the stacker's one HSP site of 4."""
  from venus_interop.plr.operator import RunAborted
  hsl = hsl_loading(avenio, lay, calls, loads, 8, 0, 0)
  assert hsl[-1] == "aborted" and hsl[2][-1][0] == "error" and "exceeds" in hsl[2][-1][1]
  with pytest.raises(RunAborted, match="exceeds"):
    port_loading(lay, calls, loads, 8, 0, 0)
