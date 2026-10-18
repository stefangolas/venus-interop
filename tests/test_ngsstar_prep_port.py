"""Hamilton's NGSStar framework, NGSStarPrep: the port against the HSL library itself.

Roche Avenio CGP's own calls to the library (heater shakers, CPAC, ODTC), in the method's order,
for both HHS configurations it supports: five on the heater shaker box, or one on the STAR's TCC.
The HSL runs in the interpreter with the device drivers answered by recording models (the HHS and
ODTC drivers' sources are not on this machine: they are declared here); the port runs on recording
PLR devices. Both logs, in one vocabulary, must match call for call. Needs VENUS_INTEROP_NGS and
VENUS_INTEROP_HAMILTON_LIBS (pyhamilton's library has the Inheco TEC driver).
"""
import asyncio
import os
import pathlib
import re

import pytest

from port_harness import hsl_run  # noqa: E402
from venus_interop.files import layout  # noqa: E402

NGS = pathlib.Path(os.environ["VENUS_INTEROP_NGS"]) if os.environ.get("VENUS_INTEROP_NGS") else None
LIBS = [pathlib.Path(p) for p in os.environ.get("VENUS_INTEROP_HAMILTON_LIBS", "").split(os.pathsep) if p]
pytestmark = pytest.mark.skipif(NGS is None or not LIBS,
                                reason="VENUS_INTEROP_NGS and VENUS_INTEROP_HAMILTON_LIBS not set")

# What this test checks against the HSL (read by tools/trace_method.py --status)
LIBRARY = "NGSSTARPREP"
COVERS = ["DATA_HandOverSimulationModeForAllLocalSMTs", "HHS_Init", "HHS_SetTemperature", "HHS_Shake",
          "HHS_Terminate", "CPAC_Init", "CPAC_SetTemperature", "CPAC_Terminate", "ODTC_Init",
          "ODTC_DownloadProtocol", "ODTC_ExecuteProtocol", "ODTC_WaitForStartedProtocolToFinish",
          "ODTC_OpenDoor", "ODTC_CloseDoor", "ODTC_Terminate"]

# the method's variables these calls read (illustrative: Venus sets them from its dialogs and files)
VALUES = {"t_strDeviceAddressODTC": "192.168.0.20", "t_strLocalIPAddressOfComputer": "192.168.0.10",
          "t_strODTCFolderXML": "C:\\odtc\\Roche_AVENIO_CGP.xml", "l_strODTCFolderXML": "C:\\odtc\\Init.xml",
          "t_blnShortenPreheat": 1, "t_blnSimulationMode": 0}

# the drivers the library calls whose sources are missing: declared, then answered by models
STUBS = """namespace _Method { namespace HSLHamHeaterShaker {
function SetSimulation(variable s) variable { variable stub; }
function CreateStarDevice(device & d, variable n, variable & o) variable { variable stub; }
function CreateUsbDevice(variable n, variable & o) variable { variable stub; }
function GetSerialNumber(variable h, variable & o) variable { variable stub; }
function SetPlateLock(variable h, variable v) variable { variable stub; }
function StartShaker(variable h, variable s) variable { variable stub; }
function StopShaker(variable h) variable { variable stub; }
function StopAllShaker() variable { variable stub; }
function StartTempCtrl(variable h, variable t, variable w) variable { variable stub; }
function StopTempCtrl(variable h) variable { variable stub; }
function Terminate() variable { variable stub; }
} }
namespace _Method { namespace Inheco_ODTC { namespace Standard {
function SetTraceLevel(variable l) variable { variable stub; }
function Connect(variable ip, variable a, variable x, variable s, variable & dev, variable & msg) variable { variable stub; }
function Reset(variable dev, variable s, variable t, variable a, variable b, variable c, variable & ret, variable & msg) variable { variable stub; }
function Initialize(variable dev, variable x, variable & ret, variable & msg) variable { variable stub; }
function GetStatus(variable dev, variable & id, variable & state, variable & locked, variable & pms, variable & t, variable & ret, variable & msg) variable { variable stub; }
function DownloadProtocol(variable dev, variable x, variable file, variable & ret, variable & msg) variable { variable stub; }
function ExecuteMethod(variable dev, variable x, variable name, variable prio, variable & t, variable & req, variable & ret, variable & msg) variable { variable stub; }
function WaitForEndOfExecuteMethod(variable dev, variable t, variable req, variable & ret, variable & msg) variable { variable stub; }
function OpenDoor(variable dev, variable x, variable & ret, variable & msg) variable { variable stub; }
function CloseDoor(variable dev, variable x, variable & ret, variable & msg) variable { variable stub; }
function StopMethod(variable dev, variable x, variable & ret, variable & msg) variable { variable stub; }
function Terminate(variable dev, variable & msg) variable { variable stub; }
} } }
"""

OUTPUTS = {"HHS_Init": range(5), "ODTC_Init": [1], "ODTC_ExecuteProtocol": [3, 4]}  # by-reference arguments


@pytest.fixture(scope="module")
def avenio():
  return NGS / "assets" / "NGSStar" / "Roche" / "Avenio CGP"


@pytest.fixture(scope="module")
def calls(avenio):
  """Avenio's NGSStarPrep calls: the main method's, then its submethods', in source order; the
  terminating calls last; neither HHS_Init (each configuration is a case)."""
  out = []
  for name in ("Avenio CGP_v1.0.1.hsl", "Avenio CGP_v1.0.1.sub"):
    text = (avenio / "Methods" / name).read_text(encoding="latin-1")
    for m in re.finditer(r"NGSSTARPREP::(\w+)\((.*)\);", text):
      args = [re.sub(r'Translate\(("[^"]*")\)', r"\1", a.strip()) for a in m.group(2).split(",")] if m.group(2) else []
      out.append((m.group(1), args))
  skip = ("_InitLibrary", "_ExitLibrary", "LiquidWasteSensor_Init", "HHS_Init")
  body = [c for c in out if c[0] not in skip and not c[0].endswith("_Terminate")]
  ends = list(dict((c[0], c) for c in out if c[0].endswith("_Terminate")).values())
  return body, ends


CONFIGS = {"box": ["HHSB"] * 5, "tcc": ["TCC", "0", "0", "0", "0"]}
HANDLES = ["t_intHHS1_HSP1", "t_intHHS2_HSP2", "t_intHHS3_HSP3_MIDI3", "t_intHHS4_MIDI1", "t_intHHS5_MIDI2"]


def _hhs_init(config):
  # the method's two calls name the handles in different orders: the TCC one fills HHS3's first
  order = HANDLES if config == "box" else [HANDLES[2], HANDLES[1], HANDLES[0], HANDLES[3], HANDLES[4]]
  return ("HHS_Init", order + [f'"{k}"' for k in CONFIGS[config]] + ["ML_STAR"])


def hsl_side(avenio, lay, sequence):
  log, created = [], []
  hhs, odtc, tec = {}, {}, {}

  def rec(*event):
    log.append(event)
    return 1

  def create(run, p, n="n"):
    p["o"].value = int(p[n].value)
    created.append(int(p[n].value))
    return 0

  hhs.update({
    "setsimulation": lambda r, p: 0, "getserialnumber": lambda r, p: 0, "terminate": lambda r, p: 0,
    "createstardevice": create, "createusbdevice": create,
    "setplatelock": lambda r, p: rec("hhs", p["h"].value, "lock_plate" if p["v"].value else "unlock_plate") and 0,
    "startshaker": lambda r, p: rec("hhs", p["h"].value, "shake", p["s"].value) and 0,
    "stopshaker": lambda r, p: rec("hhs", p["h"].value, "stop_shaking") and 0,
    "stopallshaker": lambda r, p: [rec("hhs", n, "stop_shaking") for n in created] and 0,
    "starttempctrl": lambda r, p: rec("hhs", p["h"].value, "set_temperature", p["t"].value) and 0,
    "stoptempctrl": lambda r, p: rec("hhs", p["h"].value, "deactivate") and 0,
  })
  target = {}

  def tec_ok(run, p):
    p["o_strerrorcode"].value = "000"
    return 1

  tec.update({
    "settargettemperature": lambda r, p: target.update(t=p["i_flttargettemperature"].value) or tec_ok(r, p),
    "starttemperaturecontrol": lambda r, p: rec("cpac", "set_temperature", target["t"]) and tec_ok(r, p),
    "stoptemperaturecontrol": lambda r, p: rec("cpac", "stop_temperature_control") and tec_ok(r, p),
    "initialize": tec_ok, "getactualdevicetemperature": tec_ok, "getfirmwareversion": tec_ok,
    "settracelevel": lambda r, p: 1, "terminate": lambda r, p: 1,
  })
  requests = []

  def connect(run, p):
    p["dev"].value = 1
    return 1

  def execute(run, p):
    requests.append(len(requests) + 1)
    p["t"].value, p["req"].value = 0, requests[-1]
    return rec("odtc", p["dev"].value, "execute", p["name"].value, p["prio"].value)

  def status(run, p):
    p["state"].value = "idle"
    return 1

  odtc.update({
    "settracelevel": lambda r, p: 1, "connect": connect, "reset": lambda r, p: 1, "initialize": lambda r, p: 1,
    "getstatus": status, "terminate": lambda r, p: 1,
    "downloadprotocol": lambda r, p: rec("odtc", p["dev"].value, "upload", p["file"].value),
    "executemethod": execute,
    "waitforendofexecutemethod": lambda r, p: rec("odtc", p["dev"].value, "wait", p["req"].value),
    "opendoor": lambda r, p: rec("odtc", p["dev"].value, "open"),
    "closedoor": lambda r, p: rec("odtc", p["dev"].value, "close"),
    "stopmethod": lambda r, p: rec("odtc", p["dev"].value, "stop_method"),
  })
  functions = {f"hslhamheatershaker::{k}": v for k, v in hhs.items()}
  functions.update({f"inheco_odtc::standard::{k}": v for k, v in odtc.items()})
  functions.update({f"hslinhecoteclib::{k}": v for k, v in tec.items()})
  names = sorted({a for _, args in sequence for a in args if re.fullmatch(r"[tl]_\w+", a)})
  literal = lambda v: '"' + v.replace("\\", "\\\\") + '"' if isinstance(v, str) else str(v)  # noqa: E731
  values = "".join(f"{n} = {literal(VALUES[n])};\n" for n in names if n in VALUES)
  body = "\n".join(f"NGSSTARPREP::{fn}({', '.join(args)});" for fn, args in sequence)
  src = (STUBS +
         'namespace _Method { #include "NGSStarPrep.hs_" }\n'
         'global device ML_STAR ("x.lay", "ML_STAR", hslTrue);\n'
         + "".join(f"variable {n};\n" for n in names) +
         'namespace _Method { #include "HSLMECCLib.hs_" }\n'
         "namespace _Method { method main() void {\n" + values + body + "\n} }\n")
  hsl_run(src, avenio / "Library" / "port_test.hsl", [avenio / "Library", avenio / "Methods", *LIBS], [],
          {"x.lay": lay}, answers={"functions": functions})
  return log


class _Recorder:
  def __init__(self, log, *prefix):
    self.log, self.prefix = log, prefix

  def __getattr__(self, op):
    async def call(*args, **kwargs):
      self.log.append((*self.prefix, op, *args, *kwargs.values()))
    return call


class _HeaterShaker(_Recorder):
  async def shake(self, speed):
    self.log.append((*self.prefix, "shake", speed))


class _ODTC:
  def __init__(self, log):
    self.log = log

  async def upload_method_set(self, xml):
    self.log.append(("odtc", 1, "upload", xml))

  async def execute_method(self, name, priority=None):
    self.log.append(("odtc", 1, "execute", name, priority))
    await asyncio.sleep(0)

  def __getattr__(self, op):
    names = {"open_lid": "open", "close_lid": "close", "stop_method": "stop_method"}
    if op not in names:
      raise AttributeError(op)

    async def call():
      self.log.append(("odtc", 1, names[op]))
    return call


def port_side(sequence):
  from venus_interop.plr.libraries.ngsstar_prep import NGSStarPrep

  log, slept = [], []

  async def sleep(s):
    slept.append(s)

  prep = NGSStarPrep({n: _HeaterShaker(log, "hhs", n) for n in range(1, 6)}, _Recorder(log, "cpac"),
                     {VALUES["t_strDeviceAddressODTC"]: _ODTC(log)}, sleep=sleep, read_file=lambda path: path)
  env = dict(VALUES)
  value = lambda a: (a.strip('"') if a.startswith('"') else 1 if a.endswith("::TRUE") else 0 if a.endswith("::FALSE")  # noqa: E731
                     else int(a) if a.lstrip("-").isdigit() else env.get(a))

  async def run():
    for fn, args in sequence:
      outs = OUTPUTS.get(fn, ())
      ins = [value(a) for i, a in enumerate(args) if i not in outs and a != "ML_STAR"]
      if fn == "ODTC_WaitForStartedProtocolToFinish":
        log.append(("odtc", ins[0], "wait", ins[2]))
      got = getattr(prep, fn)(*ins)
      got = await got if asyncio.iscoroutine(got) else got
      for i, v in zip(outs, got if isinstance(got, tuple) else (got,)):
        env[args[i]] = v
  asyncio.run(run())
  return log, slept


@pytest.mark.parametrize("config", ["box", "tcc"])
def test_device_calls_match_the_hsl(avenio, calls, config):
  body, ends = calls
  sequence = [("DATA_HandOverSimulationModeForAllLocalSMTs", ["t_blnSimulationMode", "0"]), _hhs_init(config)]
  sequence += [c for c in body if c[0] != "DATA_HandOverSimulationModeForAllLocalSMTs"] + ends
  if config == "tcc":  # one HHS: only the calls to it (HHS3's handle) and the rest of the devices
    sequence = [c for c in sequence if not c[0].startswith("HHS_") or c[0] in ("HHS_Init", "HHS_Terminate")
                or c[1][0] == HANDLES[2]]
  lay = layout.read_layout(avenio / "Methods" / "Avenio CGP.lay")
  h_log = hsl_side(avenio, lay, sequence)
  p_log, slept = port_side(sequence)
  assert len([e for e in h_log if e[0] == "odtc" and e[2] == "execute"]) == 13
  assert h_log == p_log
  shakes = [c for c in sequence if c[0] == "HHS_Shake"]
  assert slept == [float(c[1][2]) for c in shakes]  # each shake's duration waited (Venus's timer)


def test_simulation_leaves_the_devices_alone(calls):
  body, ends = calls
  sequence = [("DATA_HandOverSimulationModeForAllLocalSMTs", ["1", "0"]), _hhs_init("box")] + body[1:] + ends
  log, slept = port_side(sequence)
  assert log == [e for e in log if e[2] == "wait"] and slept == []
