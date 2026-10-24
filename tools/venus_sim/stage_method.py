"""Stage one of NIST's methods (`methods.py`) for a headless Venus run in <work>/<name>:
- the method's files (.hsl, .sub, .stp, .res) and its layout under the name it expects;
- every file its #includes reach that lives in NIST's repository (Methods or Library), copied
  beside it at the same relative path (Venus finds includes from the method's folder);
- the one change to the method: GetParams reads its parameters CSV from ~/hsl_data instead of
  HAMILTON\\LMSF_FrontEnd (the .sub re-signed; nothing else touched);
- that parameters CSV, from the method's demo's Parameters (the same run the demo makes), with the
  text NIST's front end writes ("true"/"false");
- probes/reload_tips.hsl on the method's layout (run it before each run: the operator's tip reload).

  python stage_method.py NAME          (marionette, groq_plate_1, groq_plates_2-5)"""
import pathlib
import re
import shutil
import sys

from paths import CORPUS, LIBRARY, NIST, REPO

sys.path.insert(0, str(REPO))
from venus_interop.files import footer  # noqa: E402

import methods  # noqa: E402
import sign  # noqa: E402
from methods import DATA  # noqa: E402

SOURCES = [NIST / "Methods", NIST / "Library"]
INCLUDE = re.compile(r'#include\s+"([^"]+)"')
OLD_PARAMS = b'C:\\\\Program Files (x86)\\\\HAMILTON\\\\LMSF_FrontEnd\\\\parameters.csv'


def new_params() -> bytes:
  return str(DATA / "parameters.csv").replace("\\", "\\\\").encode("latin-1")


def params_csv(rows: dict) -> str:
  def fmt(v):
    if isinstance(v, bool):
      return "true" if v else "false"
    return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)

  return "".join(f"{k},{fmt(v)}\r\n" for k, v in rows.items())


def find(name: str, here: pathlib.Path, out: pathlib.Path):
  rel = name.replace("\\\\", "\\").replace("\\", "/")
  for root in (here, out, LIBRARY, *SOURCES):
    p = root / rel
    if p.exists():
      return root, p
  return None, None


def stage(m: methods.Method) -> None:
  out, stem = m.staged, m.stem
  out.mkdir(parents=True, exist_ok=True)
  DATA.mkdir(parents=True, exist_ok=True)
  for ext in (".hsl", ".sub", ".stp"):
    shutil.copy2(m.folder / (stem + ext), out / (stem + ext))
  for res in m.folder.glob("*.res"):
    shutil.copy2(res, out / res.name)
  shutil.copy2(CORPUS / "raw" / f"{m.layout}.lay", out / m.layout_name)
  sub = out / (stem + ".sub")
  data = sub.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")  # CRLF, as Venus wrote it
  assert footer.ok(data), "the original .sub does not verify even with CRLF"
  assert data.count(OLD_PARAMS) == 2, data.count(OLD_PARAMS)
  data = footer.rewrite(data.replace(OLD_PARAMS, new_params()))
  assert footer.ok(data)
  sub.write_bytes(data)
  (DATA / "parameters.csv").write_text(params_csv(m.params()), encoding="latin-1", newline="")
  # an include relative to the method's folder in NIST's tree ("..\\..\\GSF-IMS.shared_submethods.hs_",
  # GROQ-Seq plate 1) leaves the staging folder: name it from its Methods/Library root, as the other
  # methods do, and re-sign
  hsl = out / (stem + ".hsl")
  data = hsl.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")

  def from_root(match):
    p = (m.folder / match.group(1).decode("latin-1").replace("\\\\", "/")).resolve()
    root = next((r for r in SOURCES if p.is_file() and p.is_relative_to(r.resolve())), None)
    if root is None:
      return match.group(0)
    return b'#include "' + str(p.relative_to(root.resolve())).replace("\\", "\\\\").encode("latin-1") + b'"'

  rerooted = re.sub(rb'#include\s+"(\.\.\\\\[^"]+)"', from_root, data)
  if rerooted != data:
    assert footer.ok(data), "the original .hsl does not verify even with CRLF"
    hsl.write_bytes(footer.rewrite(rerooted))
  todo, seen, missing = [out / (stem + ".hsl"), sub], set(), set()
  while todo:
    f = todo.pop()
    if f in seen:
      continue
    seen.add(f)
    text = f.read_text(encoding="latin-1", errors="replace")
    text = re.sub(r'__filename__\s*"([^"]+)"', lambda m: '"' + f.stem + m.group(1) + '"', text)
    for name in INCLUDE.findall(text):
      root, p = find(name, f.parent, out)
      if p is None:
        missing.add(name)
        continue
      if root in SOURCES:
        dest = out / p.relative_to(root)
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
  for f in out.rglob("*"):
    if f.suffix.lower() in (".hsl", ".hs_", ".hsi", ".sub", ".res", ".smt") and f.is_file():
      d = f.read_bytes()
      crlf = d.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
      if crlf != d and (b"$$checksum=" not in d or footer.ok(crlf)):
        f.write_bytes(crlf)
        fixed += 1
  # an include written relative to a library's folder ("..\\HSLTrcLib.hsl") lands in the staging root
  for name in ("HSLTrcLib.hsl",):
    if not (out / name).exists():
      shutil.copy2(LIBRARY / name, out / name)
  reload_tips = out / "reload_tips.hsl"
  probe = (pathlib.Path(__file__).parent / "probes" / "reload_tips.hsl").read_text(encoding="latin-1")
  reload_tips.write_text(probe.replace('"LAYOUT"', f'"{m.layout_name}"'), encoding="latin-1", newline="")
  sign.sign(reload_tips)
  bad = [str(f.relative_to(out)) for f in out.rglob("*") if f.suffix.lower() in (".hsl", ".hs_", ".hsi", ".sub")
         and b"$$checksum=" in f.read_bytes() and not footer.ok(f.read_bytes())]
  print(f"staged {out}: {len(seen)} files followed; missing includes: {sorted(missing) or 'none'}; "
        f"{fixed} files back to CRLF; footers still bad: {bad or 'none'}")


if __name__ == "__main__":
  if len(sys.argv) != 2:
    raise SystemExit(__doc__)
  stage(methods.get(sys.argv[1]))
