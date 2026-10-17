"""HxPars records: parsing, the named-key table and variable binding."""
from venus_interop.methods import stp_pars

# A trimmed Aspirate record, modeled on GSF-IMS.shared_submethods.stp
# 05a6e94c… (2024-12-15): two channel blocks, volume/mix bound to variables.
ITEMS = [
  "1CommandStepFileGuid", "05a6e94c_b11e_4718_9ec6578a7bf10f02",
  "1SequenceObject", "from_seq",
  "3TipType", "5",
  "1StepName", "Aspirate",
  "(-534183936",
    "(3",
      "5-534183918", "0",
      "3-534183919", "5",
      "1-534183924", "p_vol",
      "1-534183914", "mix_cycles",
      "1-534183915", "mix_volume",
      "1LiquidName", '"HighVolumeFilter_Water_FastMixing_DispenseSurface_Empty"',
    ")",
    "(4",
      "1-534183924", "p_vol",
    ")",
  ")",
  "(Variables",
    "(-534118398",
      "(mix_volume", "(3", "30", "-534183936", "31", "4", "32", "-534183915", ")", ")",
      "(mix_cycles", "(3", "30", "-534183936", "31", "4", "32", "-534183914", ")", ")",
      "(p_vol", "(3", "30", "-534183936", "31", "4", "32", "-534183924", ")", ")",
    ")",
    "(-534118399",
      "(from_seq", "(0", "10", "SequenceObject", ")", ")",
    ")",
  ")",
  "3from_seq", "2",
  "3DispenseMode", "5",
]


def rec() -> stp_pars.Record:
  return stp_pars.Record("05a6e94c_b11e_4718_9ec6578a7bf10f02", stp_pars.parse(ITEMS))


def test_parse_tree():
  tree = stp_pars.parse(ITEMS)
  names = [k for k, v in tree]
  assert names[:4] == ["1CommandStepFileGuid", "1SequenceObject", "3TipType", "1StepName"]
  channels = [v for k, v in tree if stp_pars.key_id(k) == "-534183936"][0]
  assert [stp_pars.key_id(k) for k, v in channels] == ["3", "4"]
  ch3 = channels[0][1]
  assert ("1LiquidName", '"HighVolumeFilter_Water_FastMixing_DispenseSurface_Empty"') in ch3


def test_typed_value_starting_with_paren():
  # an Allen Institute package manifest names a bookmark "(x86)-HAMILTON-Methods-…"
  items = ["(542", "1-347734010", "(x86)-HAMILTON-Methods-Scan", "3-347734011", "537",
           "(-347734008", ")", ")", "(531", "1-347734010", "", ")"]
  tree = stp_pars.parse(items)
  assert [k for k, v in tree] == ["542", "531"]
  assert tree[0][1][0] == ("1-347734010", "(x86)-HAMILTON-Methods-Scan")
  assert tree[0][1][2] == ("-347734008", [])


def test_key_names_and_prefixes():
  assert stp_pars.key_name("1-534183924") == "aspirate volume"
  assert stp_pars.key_name("5-534183918") == "max height difference"
  assert stp_pars.key_name("1LiquidName") == "LiquidName"
  assert stp_pars.key_name("-534183936") == "channels"
  assert stp_pars.key_name("1SomethingNew") == "SomethingNew"


def test_top_and_step_name():
  r = rec()
  assert r.step_name == "Aspirate"
  assert r.top["TipType"] == "5" and r.top["DispenseMode"] == "5"


def test_variable_bindings():
  r = rec()
  b = r.variable_bindings
  assert b["p_vol"] == [("-534183936", "4", "-534183924")]
  assert b["from_seq"] == [("", "", "SequenceObject")]


def test_resolve():
  r = rec()
  assert r.resolve("p_vol") == "p_vol"  # the channel block holds the variable name
  assert r.resolve("from_seq") == "from_seq"


def test_readable():
  lines = rec().readable()
  d = {(p, n): v for p, n, v in lines}
  assert d[("/channels", "aspirate volume")] == "<p_vol>"
  assert d[("/channels", "mix cycles")] == "<mix_cycles>"
  assert d[("/channels", "cLLD sensitivity")] == "5"
  assert d[("/channels", "LiquidName")] == '"HighVolumeFilter_Water_FastMixing_DispenseSurface_Empty"'
  assert not any(n in ("StepName", "CommandStepFileGuid", "from_seq") for _p, n, _v in lines)
