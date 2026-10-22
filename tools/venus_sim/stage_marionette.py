"""Stage NIST's Marionette method for a headless Venus run in <work>/marionette:
- the method's files (.hsl, .sub, .stp, .res) and its layout under the name it expects;
- every file its #includes reach that lives in NIST's repository (Methods or Library), copied
  beside it at the same relative path (Venus finds includes from the method's folder);
- the one change to the method: GetParams reads its parameters CSV from <work>/hsl_data instead of
  HAMILTON\\LMSF_FrontEnd (the .sub re-signed; nothing else touched);
- that parameters CSV, from examples/marionette_demo.py's Parameters (the same run the demo makes),
  with the text NIST's front end writes ("true"/"false");
- probes/marionette_reload_tips.hsl (run it before each run: the operator's tip reload).

  python stage_marionette.py"""
import pathlib
import re
import shutil
import sys

from paths import CORPUS, LIBRARY, NIST, REPO, WORK

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "examples"))
from venus_interop.files import footer  # noqa: E402

import sign  # noqa: E402

METHOD_DIR = NIST / "Methods" / "GSF-IMS Project" / "E. coli Methods" / "Fitness Selection 2.With DNA Extraction"
STEM = "Marionette protease.gradient plate prep.v5"
LAYOUT = CORPUS / "raw" / "3ed5809e547e.lay"
OUT = WORK / "marionette"
# a path without "\v" in it: Venus's schema.ini handling breaks on one
DATA = pathlib.Path.home() / "hsl_data"
SOURCES = [NIST / "Methods", NIST / "Library"]
INCLUDE = re.compile(r'#include\s+"([^"]+)"')
OLD_PARAMS = b'C:\\\\Program Files (x86)\\\\HAMILTON\\\\LMSF_FrontEnd\\\\parameters.csv'


def new_params() -> bytes:
  return str(DATA / "parameters.csv").replace("\\", "\\\\").encode("latin-1")


def params_csv() -> str:
  from marionette_demo import Parameters

  p = Parameters()
  rows = {
    "worklistFile": str(DATA / "marionette_worklist.csv"), "isDebugging": "false", "isPipetting": "true" if p.is_pipetting else "false",
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
  fmt = lambda v: (str(int(v)) if isinstance(v, float) and v.is_integer() else str(v))  # noqa: E731
  return "".join(f"{k},{fmt(v)}\r\n" for k, v in rows.items())


def find(name: str, here: pathlib.Path):
  rel = name.replace("\\\\", "\\").replace("\\", "/")
  for root in (here, OUT, LIBRARY, *SOURCES):
    p = root / rel
    if p.exists():
      return root, p
  return None, None


def stage() -> None:
  OUT.mkdir(parents=True, exist_ok=True)
  DATA.mkdir(parents=True, exist_ok=True)
  for ext in (".hsl", ".sub", ".stp"):
    shutil.copy2(METHOD_DIR / (STEM + ext), OUT / (STEM + ext))
  for res in METHOD_DIR.glob("*.res"):
    shutil.copy2(res, OUT / res.name)
  shutil.copy2(LAYOUT, OUT / "Fitness Selection.Marionette protease.v5.lay")
  sub = OUT / (STEM + ".sub")
  data = sub.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")  # CRLF, as Venus wrote it
  assert footer.ok(data), "the original .sub does not verify even with CRLF"
  assert data.count(OLD_PARAMS) == 2, data.count(OLD_PARAMS)
  data = footer.rewrite(data.replace(OLD_PARAMS, new_params()))
  assert footer.ok(data)
  sub.write_bytes(data)
  (DATA / "parameters.csv").write_text(params_csv(), encoding="latin-1", newline="")
  todo, seen, missing = [OUT / (STEM + ".hsl"), sub], set(), set()
  while todo:
    f = todo.pop()
    if f in seen:
      continue
    seen.add(f)
    text = f.read_text(encoding="latin-1", errors="replace")
    text = re.sub(r'__filename__\s*"([^"]+)"', lambda m: '"' + f.stem + m.group(1) + '"', text)
    for name in INCLUDE.findall(text):
      root, p = find(name, f.parent)
      if p is None:
        missing.add(name)
        continue
      if root in SOURCES:
        dest = OUT / p.relative_to(root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        for comp in [p, *(p.with_suffix(s) for s in (".stp", ".res", ".smt", ".hsi", ".hs_", ".sub"))]:
          if comp.exists() and not (dest.parent / comp.name).exists():
            shutil.copy2(comp, dest.parent / comp.name)
        p = dest
      todo.append(p)
      if p.suffix == ".hs_" and p.with_suffix(".hsi").exists():
        todo.append(p.with_suffix(".hsi"))
  # the repository's checkout has LF line endings; Venus's checksums are over the CRLF files
  fixed = 0
  for f in OUT.rglob("*"):
    if f.suffix.lower() in (".hsl", ".hs_", ".hsi", ".sub", ".res", ".smt") and f.is_file():
      d = f.read_bytes()
      crlf = d.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
      if crlf != d and (b"$$checksum=" not in d or footer.ok(crlf)):
        f.write_bytes(crlf)
        fixed += 1
  # an include written relative to a library's folder ("..\\HSLTrcLib.hsl") lands in the staging root
  for name in ("HSLTrcLib.hsl",):
    if not (OUT / name).exists():
      shutil.copy2(LIBRARY / name, OUT / name)
  reload_tips = OUT / "reload_tips.hsl"
  shutil.copy2(pathlib.Path(__file__).parent / "probes" / "marionette_reload_tips.hsl", reload_tips)
  sign.sign(reload_tips)
  bad = [str(f.relative_to(OUT)) for f in OUT.rglob("*") if f.suffix.lower() in (".hsl", ".hs_", ".hsi", ".sub")
         and b"$$checksum=" in f.read_bytes() and not footer.ok(f.read_bytes())]
  print(f"staged {OUT}: {len(seen)} files followed; missing includes: {sorted(missing) or 'none'}; "
        f"{fixed} files back to CRLF; footers still bad: {bad or 'none'}")


if __name__ == "__main__":
  stage()
