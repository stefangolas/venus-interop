"""The NIST methods the firmware test runs, and what staging and the PLR run need of each. Standard
library only at import: `run_method.py` reads it from the 32-bit Python that drives Venus; the
parameters and the PLR run import their demo when called.

Each method is staged in <work>/<name>, its Venus commands go to <work>/phase3/<name>_venus.fw, PLR's
to <name>_plr.fw, and the ComTrace line its run starts at to <work>/<name>_comtrace_start.txt."""
import pathlib
from dataclasses import dataclass
from typing import Callable

from paths import NIST, WORK

FITNESS = NIST / "Methods" / "GSF-IMS Project" / "E. coli Methods" / "Fitness Selection 2.With DNA Extraction"
# a path without "\v" in it: Venus's schema.ini handling breaks on one
DATA = pathlib.Path.home() / "hsl_data"


@dataclass
class Method:
  name: str
  folder: pathlib.Path  # the method's folder in NIST's repository
  stem: str  # its .hsl/.sub/.stp name
  layout: str  # the corpus layout, raw/<hash>.lay
  layout_name: str  # the name the method's `device` line opens it under
  params: Callable[[], dict]  # its parameters CSV's keys and values, from the demo's Parameters
  plr: Callable[[], object]  # a coroutine running the demo as the Venus run is set up
  timeout: int = 1500  # seconds, for the Venus run

  @property
  def staged(self) -> pathlib.Path:
    return WORK / self.name

  @property
  def hsl(self) -> pathlib.Path:
    return self.staged / (self.stem + ".hsl")

  def fw(self, side: str) -> pathlib.Path:
    return WORK / "phase3" / f"{self.name}_{side}.fw"

  @property
  def comtrace_start(self) -> pathlib.Path:
    return WORK / f"{self.name}_comtrace_start.txt"


def _paths():
  import sys

  from paths import CORPUS, REPO

  sys.path.insert(0, str(REPO))
  sys.path.insert(0, str(REPO / "examples"))
  return CORPUS, REPO / ".local/session_state/analysis/traces", NIST.parent / "liquid_classes.json"


def _marionette_params() -> dict:
  _paths()
  from marionette_demo import Parameters

  p = Parameters()
  return {
    "worklistFile": str(DATA / "marionette_worklist.csv"), "isDebugging": False, "isPipetting": p.is_pipetting,
    "cultureVolume": p.culture_volume, "dilutionFactor": p.dilution_factor, "plateNum": p.plate_number,
    "van_stock_dilution": p.van_stock_dilution, "sal_tmp_stock_dilution": p.sal_tmp_stock_dilution,
    "dilutionSeriesFactor": p.dilution_series_factor,
    "inducer2_1_grad_max_conc": p.sal_grad_max_conc[0], "inducer2_2_grad_max_conc": p.sal_grad_max_conc[1],
    "strain1": p.strain_1_id, **{f"plasmid{i + 1}": v for i, v in enumerate(p.plasmid_ids)},
    "inducer1": p.inducer_1_id, "inducer1StockUnits": p.inducer_1_units, "inducer1StockConc": p.inducer_1_stock_conc,
    "inducer2": p.inducer_2_id, "inducer2StockUnits": p.inducer_2_units,
    **{f"inducer2_{i + 1}StockConc": v for i, v in enumerate(p.sal_stock_conc)},  # read as "inducer2_" + n + "StockConc"
    "selector1": p.additive_1_id, "selector1StockUnits": p.additive_1_units, "selector1StockConc": p.additive_1_stock_conc,
  }


def _marionette_plr():
  corpus, traces, liquid_classes = _paths()
  import marionette_demo as demo

  return demo.main(corpus, False, demo.Parameters(), traces / demo.TRACE, None, liquid_classes)


def _groq_params() -> dict:
  """Both GROQ-Seq methods' keys (each reads its own): plate 1 the clonal test and lineage, plates
  2-5 the inducers, selectors and gradient."""
  _paths()
  from groq_seq_demo import Parameters

  p = Parameters()
  return {
    "worklistFile": str(DATA / "groq_worklist.csv"), "isDebugging": False, "isPipetting": p.is_pipetting,
    "cultureVolume": p.culture_volume, "strain1": p.strain_1_id,
    **{f"plasmid_1_{i + 1}": v for i, v in enumerate(p.plasmid_1_ids)},
    **{f"plasmid_2_{i + 1}": v for i, v in enumerate(p.plasmid_2_ids)},
    "isClonalTest": p.is_clonal_test, "lineage": p.lineage,
    "dilutionFactor": p.dilution_factor, "gradPlateNum": p.grad_plate_num, "plateNum": p.grad_plate_num,
    "dilutionSeriesFactor": p.dilution_series_factor,
    **{k: v for i in range(2) for k, v in ((f"inducer{i + 1}", p.inducer_ids[i]),
                                          (f"inducer{i + 1}StockConc", p.inducer_stock_conc[i]),
                                          (f"inducer{i + 1}StockUnits", p.inducer_units[i]))},
    **{k: v for i in range(2) for k, v in ((f"selector{i + 1}", p.selector_ids[i]),
                                          (f"selector{i + 1}StockConc", p.selector_stock_conc[i]),
                                          (f"selector{i + 1}StockUnits", p.selector_units[i]))},
  }


def _groq_plr(which: str):
  def run():
    corpus, traces, liquid_classes = _paths()
    import groq_seq_demo as demo

    return demo.main(corpus, which, False, demo.Parameters(), traces / demo.METHODS[which].TRACE, False, None,
                     liquid_classes)

  return run


METHODS = {m.name: m for m in [
  Method("marionette", FITNESS, "Marionette protease.gradient plate prep.v5", "3ed5809e547e",
         "Fitness Selection.Marionette protease.v5.lay", _marionette_params, _marionette_plr),
  Method("groq_plate_1", FITNESS, "GROQ-Seq.2_TFs.plate_1", "5ae1a84b57e5", "GROQ-Seq.2_TFs.lay",
         _groq_params, _groq_plr("plate_1")),
  Method("groq_plates_2-5", FITNESS, "GROQ-Seq.2_TFs.plates_2-5", "5ae1a84b57e5", "GROQ-Seq.2_TFs.lay",
         _groq_params, _groq_plr("plates_2-5")),
]}


def get(name: str) -> Method:
  if name not in METHODS:
    raise SystemExit(f"unknown method {name!r}; one of {', '.join(METHODS)}")
  return METHODS[name]
