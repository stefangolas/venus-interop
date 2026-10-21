"""Hamilton's NGSStar framework, NGSStarLoading: the port against the HSL library itself.

Roche Avenio CGP's own calls, in the method's order: every Define_VolumePerWell and
Define_VolumePerWell_MastermixComponent, then every container calculation and sequence reformat,
with the method's arguments, on its layout, for several sample counts. The HSL runs in the
interpreter, its RunData.xls workbook modelled as SQLite sheets (`hsl_eval.Run.workbooks`); both
sheets must match the port's cell for cell, and so must the sequences, the volumes per container,
the trough bookkeeping and where each template is left.

The deck-layout object (carrier and site of a labware) is answered from the layout on both sides,
by the port's own lookup. Needs VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS.
"""
import os
import pathlib
import re

import pytest

from port_harness import ARRAYTOOLS, ARRAYTOOLS_MODELS, hsl_run  # noqa: E402
from venus_interop.files import layout  # noqa: E402
from venus_interop.methods import sequences as sq  # noqa: E402

NGS = pathlib.Path(os.environ["VENUS_INTEROP_NGS"]) if os.environ.get("VENUS_INTEROP_NGS") else None
LIBS = [pathlib.Path(p) for p in os.environ.get("VENUS_INTEROP_HAMILTON_LIBS", "").split(os.pathsep) if p]
pytestmark = pytest.mark.skipif(NGS is None or not LIBS,
                                reason="VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS not set")

# What this test checks against the HSL (read by tools/trace_method.py --status)
LIBRARY = "NGSSTARLOADING"
COVERS = ["Define_VolumePerWell", "Define_VolumePerWell_MastermixComponent",
          "Calculate_TotalVolumeAndSequenceToAspirate", "Calculate_TotalVolume_MastermixComponent",
          "Calculate_ReformatSequenceToMatchNumberOfSamples", "DATA_HandOverDataToSMT_NGSStarLoading",
          "Add_LabwareForCurrentProcess", "Calculate_TotalVolumeAndSequenceToAspirate_FixedTubeNumber"]

# the method's variables in these calls: the sample count, and two minimum tube counts
MINIMUMS = {"l_intNumberOfBeadWashBufferTubes": 2, "l_intNumberOfStringentWashBufferTubes": 3,
            "l_intNumberOfCleanUpBeadTubes": 4}  # a fixed count (the method sets 2 or 4)
# and the labware counts it adds per process (illustrative: the method works them out)
UNITS = {"l_intNumberOfHSPPlates": 2, "l_intNumberOfMIDIPlates": 3, "l_intNumberOfHamiltonComfortLids": 1,
         "l_intNumberOf50uLTips": 96, "l_intNumberOf300uLTips": 480, "l_intNumberOf1000uLTips": 24}


@pytest.fixture(scope="module")
def avenio():
  return NGS / "assets" / "NGSStar" / "Roche" / "Avenio CGP"


@pytest.fixture(scope="module")
def lay(avenio):
  return layout.read_layout(avenio / "Methods" / "Avenio CGP.lay")


@pytest.fixture(scope="module")
def calls(avenio):
  """Avenio's loading calls as (function, arguments as HSL text), in its source's order."""
  text = (avenio / "Methods" / "Avenio CGP_v1.0.1.sub").read_text(encoding="latin-1")
  want = r"(Define_VolumePerWell_MastermixComponent|Define_VolumePerWell|" \
         r"Calculate_TotalVolumeAndSequenceToAspirate_FixedTubeNumber|Calculate_TotalVolumeAndSequenceToAspirate|" \
         r"Calculate_ReformatSequenceToMatchNumberOfSamples|Add_LabwareForCurrentProcess)"
  out = []
  for m in re.finditer(r"NGSSTARLOADING::" + want + r"\((.*)\);", text):
    args = [a.strip() for a in _split(m.group(2))]
    out.append((m.group(1), [re.sub(r'Translate\(("[^"]*")\)', r"\1", a) for a in args]))
  return out


def _split(s):
  depth, cur, parts = 0, "", []
  for ch in s:
    if ch == "," and depth == 0:
      parts.append(cur)
      cur = ""
      continue
    depth += ch == "("
    depth -= ch == ")"
    cur += ch
  return parts + [cur]


def _labware_type(a):
  return a.split("::")[-1].strip('"') if "LabwareType" in a else a.strip('"')


class _Deck:
  def __init__(self, lay):
    self.layout = lay
    self.sequences = {s.name: list(s.items) for s in lay.sequences}
    self.live = {}

  def seq(self, name):
    if name not in self.live:
      self.live[name] = sq.Sequence(name, list(self.sequences[name]))
    return self.live[name]




def _value(a, samples):
  a = a.strip()
  if a == "t_intNumberOfSamplesFromFile":
    return samples
  if a in MINIMUMS:
    return MINIMUMS[a]
  if a in UNITS:
    return UNITS[a]
  return a


def hsl_side(avenio, lay, calls, samples, after="", before="", answers=None, run_only=False, handover="", stps=(),
             allow_unresolved=()):
  """The calls in the HSL; then `after` (HSL text) in the same method, `before` declared ahead of it,
  `handover` in place of the default DATA_HandOverDataToSMT_NGSStarLoading call, `answers` added to
  the run's, `stps` the step records. `run_only`: the run, not what the comparison reads."""
  from venus_interop.plr.libraries.ngsstar_loading import NGSStarLoading

  L = "NGSSTARLOADING::"
  body, outs = [], []
  for i, (fn, a) in enumerate(calls):
    if fn.startswith("Define"):
      body.append(f"{L}{fn}({', '.join(a)});")
    elif fn.startswith("Calculate_TotalVolume"):
      ins = [str(_value(x, samples)) for x in a[1:10]]
      ins[2] = f"ARW_Global::LabwareType::{_labware_type(a[3])}" if "LabwareType" in a[3] else a[3]
      body.append(f"{L}{fn}(ML_STAR, {', '.join(ins)}, d{i}, s{i}, v{i});")
      outs.append(i)
    elif fn == "Add_LabwareForCurrentProcess":
      body.append(f"{L}{fn}(ML_STAR, {a[1]}, {a[2]}, {_value(a[3], samples)}, {a[4]}, {a[5]});")
    else:
      body.append(f"{L}{fn}(ML_STAR, {_value(a[1], samples)}, {a[2]}, {samples}, s{i});")
      outs.append(i)
  decl = "".join(f"sequence d{i}; sequence s{i}; variable v{i}[];\n" for i in outs)
  src = (
    'namespace _Method { #include "HSLSeqLib.hsl" }\n'
    'namespace _Method { #include "NGSStarLoading\\\\NGSStarLoading.hs_" }\n'
    'global device ML_STAR ("x.lay", "ML_STAR", hslTrue);\n'
    'sequence t50; sequence t300; sequence t1000;\n' + decl +
    'namespace _Method { #include "HSLMECCLib.hs_" }\n' + ARRAYTOOLS + before +
    "namespace _Method { method main() void {\n"
    + (handover or f'{L}DATA_HandOverDataToSMT_NGSStarLoading("C:\\\\r\\\\report.csv", 1, "Roche", "Avenio CGP", 0, 0, '
       '"tc50", "tc300", "tc1000", t50, t300, t1000, 0);\n') + "\n".join(body) + "\n" + after + "\n} }\n")
  port = NGSStarLoading(_Deck(lay))  # its layout lookup answers the deck-layout object in the HSL too

  def carrier_site(run, p):
    carrier, site = port._carrier_and_site(str(p["i_str_labid"].value))
    p["o_str_carrierid"].value, p["o_str_siteid"].value = carrier, site
    return 1

  answers = dict(answers or {})
  functions = {"ngsstarloading::_abstract": lambda r, p: 0,
               "ngsstarloading::_getcarrieridandsiteid_fromlabid": carrier_site,
               **ARRAYTOOLS_MODELS, **answers.pop("functions", {})}
  run = hsl_run(src, avenio / "Library" / "port_test.hsl", [avenio / "Library", avenio / "Methods", *LIBS], stps,
                {"x.lay": lay}, answers={"functions": functions, **answers}, allow_unresolved=allow_unresolved)
  if run_only:
    return run
  from venus_interop.methods.hsl_eval import Device

  g = {k.lower(): c.value for cells in run.globals.values() for k, c in cells.items()}
  lib = {k.lower(): c for ns, cells in run.globals.items() if ns.lower().split("::")[-1] == "ngsstarloading" for k, c in cells.items()}
  device = next(v for v in g.values() if isinstance(v, Device))
  conn = next(iter(run.workbooks.values()))
  sheets = {}
  for t in ("RunData", "Mastermix_Prep"):
    cur = conn.execute(f"SELECT * FROM [{t}]")
    cols = [d[0] for d in cur.description]
    sheets[t] = [dict(zip(cols, r)) for r in cur.fetchall()]
  results = {i: (g.get(f"d{i}"), g.get(f"s{i}"), g.get(f"v{i}")) for i in outs}
  rgt = (list(lib["t_arr_flt_rgt_totalvolume"].value.items), list(lib["t_arr_str_rgt_reagentname"].value.items),
         [s.items for s in lib["t_arr_seq_rgt_sequencestoaspirate"].value.items])
  templates = {name: (s.cur, s.end) for name, s in device.sequences.items()}
  return sheets, results, rgt, templates


def port_side(lay, calls, samples, port=None):
  """The calls through the port (`port`, on a _Deck, when given)."""
  from venus_interop.plr.libraries.ngsstar_loading import LabwareType, NGSStarLoading

  deck = port.v if port is not None else _Deck(lay)
  port = port if port is not None else NGSStarLoading(deck)
  results = {}
  for i, (fn, a) in enumerate(calls):
    if fn == "Define_VolumePerWell":
      port.Define_VolumePerWell(a[0].strip('"'), float(a[1]))
    elif fn == "Define_VolumePerWell_MastermixComponent":
      port.Define_VolumePerWell_MastermixComponent(a[0].strip('"'), a[1].strip('"'), float(a[2]))
    elif fn.startswith("Calculate_TotalVolume"):
      v = [_value(x, samples) for x in a[1:10]]
      results[i] = getattr(port, fn)(
        None, v[0].strip('"'), int(v[1]), getattr(LabwareType, _labware_type(v[2]), _labware_type(v[2])), float(v[3]), float(v[4]), float(v[5]),
        v[6].split(".")[-1], int(v[7]), int(v[8]))
    elif fn == "Add_LabwareForCurrentProcess":
      named = lambda x: getattr(LabwareType, x.split("::")[-1]) if "LabwareType" in x else x.strip('"')  # noqa: E731
      port.Add_LabwareForCurrentProcess(None, named(a[1]), named(a[2]), int(_value(a[3], samples)),
                                        a[4].split(".")[-1], int(a[5]))
    else:
      results[i] = (None, port.Calculate_ReformatSequenceToMatchNumberOfSamples(
        None, int(_value(a[1], samples)), a[2].split(".")[-1], samples), None)
  sheets = {"RunData": port.run_data.rows, "Mastermix_Prep": port.mastermix_prep.rows}
  rgt = (port.rgt_total_volume, port.rgt_reagent_name, [s.items for s in port.rgt_sequences])
  return sheets, results, rgt, {n: (s.cur, s.end) for n, s in deck.live.items()}


def _cells_equal(a, b):
  if isinstance(a, (int, float)) and isinstance(b, (int, float)):
    return a == pytest.approx(b, rel=1e-12, abs=1e-12)
  return (a if a not in (None,) else None) == (b if b not in (None,) else None)


def test_covers_what_it_calls():
  assert LIBRARY == "NGSSTARLOADING" and "Calculate_TotalVolumeAndSequenceToAspirate" in COVERS


@pytest.mark.parametrize("samples", [1, 8, 11, 24, 96])  # 11: a fixed tube count that does not divide them
def test_loading_calculations_match_the_hsl(avenio, lay, calls, samples):
  assert sum(fn.startswith("Calculate_Total") for fn, _ in calls) == 20
  h_sheets, h_results, h_rgt, h_templates = hsl_side(avenio, lay, calls, samples)
  p_sheets, p_results, p_rgt, p_templates = port_side(lay, calls, samples)
  for sheet in ("RunData", "Mastermix_Prep"):
    assert len(h_sheets[sheet]) == len(p_sheets[sheet]), sheet
    for k, (hr, pr) in enumerate(zip(h_sheets[sheet], p_sheets[sheet])):
      for col in hr:
        assert _cells_equal(hr[col], pr[col]), (sheet, k, col, hr[col], pr[col])
  assert h_results.keys() == p_results.keys()
  for i in h_results:
    (hd, hs, hv), (pd, ps, pv) = h_results[i], p_results[i]
    if pd is not None:
      assert hd.items == pd.items, (i, calls[i])
    assert hs.items == ps.items, (i, calls[i])
    if pv is not None:
      assert list(hv.items) == pytest.approx(pv), (i, calls[i])
  assert h_rgt[0] == pytest.approx(p_rgt[0]) and h_rgt[1:] == p_rgt[1:]
  if h_templates is not None:
    for name, state in p_templates.items():
      assert h_templates[name.lower()] == state, name
