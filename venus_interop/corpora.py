"""Where test layouts and labware definitions come from, and how to turn them into a corpus folder.

A corpus folder (VENUS_INTEROP_CORPUS) holds:
  raw/<sha1[:12]>.lay   layouts, named by content, copied byte for byte
  index.tsv            <hash> TAB <source> TAB <original path> TAB <size in bytes>
  defs_raw/<name>       definition files (.rck .tml .lid .ctr), named by a hash of their source path
  defs_index.tsv        <file in defs_raw> TAB <path relative to a Labware folder> TAB <source>

Sources are listed here; `tools/build_corpus.py` copies from the local ones. Nothing is downloaded
unless a source's `fetch` is run explicitly.
"""
from __future__ import annotations

import csv
import dataclasses
import hashlib
import os
import pathlib
import shutil
from typing import Iterable, Optional

VENUS = pathlib.Path(r"C:\Program Files (x86)\HAMILTON")


@dataclasses.dataclass(frozen=True)
class Source:
  name: str
  description: str
  local: Optional[pathlib.Path]  # where it is on this machine, if anywhere
  url: Optional[str] = None
  labware_roots: tuple[str, ...] = ("Labware",)  # folders under `local` that are Labware roots

  def layouts(self) -> list[pathlib.Path]:
    if self.local is None or not self.local.exists():
      return []
    return sorted(self.local.rglob("*.lay"))

  def labware_dirs(self) -> list[pathlib.Path]:
    if self.local is None or not self.local.exists():
      return []
    out = []
    for dirpath, dirs, _ in os.walk(self.local):
      for d in dirs:
        if d.lower() in {r.lower() for r in self.labware_roots}:
          out.append(pathlib.Path(dirpath, d))
    return out


def _env_path(name: str) -> Optional[pathlib.Path]:
  value = os.environ.get(name)
  return pathlib.Path(value) if value else None


SOURCES = [
  Source("venus", "The local Venus install: its layouts, Labware folder and NGS STAR kits",
         _env_path("HAMILTON_DIR") or VENUS),
  Source("ngs_protocols", "NGS STAR protocols (KAPA, 10x, PacBio, QIAseq, ONT, Avenio) and their kit labware",
         _env_path("VENUS_INTEROP_NGS")),
  Source("lmsf_hamilton", "djross22/lmsf_hamilton, branch S-Cell_STAR-2: 141 layouts and the lab's labware",
         _env_path("VENUS_INTEROP_NIST"), "https://github.com/djross22/lmsf_hamilton/tree/S-Cell_STAR-2",
         labware_roots=("LabWare",)),
  Source("pyhamilton", "PyHamilton's sample layouts", None, "https://github.com/dgretton/pyhamilton"),
  Source("hamilton_library", "Hamilton's shared library (labautomation.io), downloaded and unpacked",
         _env_path("VENUS_INTEROP_HAMILTON_LIBRARY"),
         "https://download.hamiltonsupport.com/wl/?id=VQY0XAzTfcT7KY29A1YJtZVFwZ7GMOO2"),
]


def _key(path: pathlib.Path) -> str:
  return hashlib.sha1(str(path).lower().encode()).hexdigest()[:12] + path.suffix.lower()


def layout_key(path: pathlib.Path) -> str:
  """A layout's name in a corpus: its content's sha1, so the same file has the same name on every
  machine (the demos and tests name layouts this way, e.g. GROQ-Seq.2_TFs.lay is 5ae1a84b57e5.lay)."""
  return hashlib.sha1(pathlib.Path(path).read_bytes()).hexdigest()[:12] + ".lay"


def build(out: pathlib.Path, layouts: Iterable[pathlib.Path], labware_dirs: Iterable[pathlib.Path],
          source: str = "local", root: Optional[pathlib.Path] = None) -> dict[str, int]:
  """Copy layouts and every definition under the Labware folders into a corpus folder.

  Layouts go to `raw/<content hash>.lay`, listed in `index.tsv` (hash, source, path under `root`,
  size); definitions to `defs_raw/`, listed in `defs_index.tsv`."""
  out = pathlib.Path(out)
  (out / "raw").mkdir(parents=True, exist_ok=True)
  (out / "defs_raw").mkdir(parents=True, exist_ok=True)
  n_lay = n_def = 0
  listed_path = out / "index.tsv"
  listed = {}
  if listed_path.exists():
    with open(listed_path, encoding="utf-8") as f:
      listed = {row[0]: row for row in csv.reader(f, delimiter="\t")}
  for lay in layouts:
    lay = pathlib.Path(lay)
    key = layout_key(lay)
    shutil.copyfile(lay, out / "raw" / key)
    where = lay.relative_to(root).as_posix() if root is not None and lay.is_relative_to(root) else lay.name
    listed[key[:-4]] = [key[:-4], source, where, str(lay.stat().st_size)]
    n_lay += 1
  with open(listed_path, "w", encoding="utf-8", newline="") as f:
    csv.writer(f, delimiter="\t").writerows(listed.values())
  index_path = out / "defs_index.tsv"
  index = {}
  if index_path.exists():
    with open(index_path, encoding="utf-8") as f:
      index = {row[0]: row for row in csv.reader(f, delimiter="\t")}
  for root in labware_dirs:
    for dirpath, _, files in os.walk(root):
      for name in files:
        p = pathlib.Path(dirpath, name)
        if p.suffix.lower() not in (".rck", ".tml", ".lid", ".ctr"):
          continue
        k = _key(p)
        shutil.copyfile(p, out / "defs_raw" / k)
        index[k] = [k, p.relative_to(root).as_posix().lower(), source]
        n_def += 1
  with open(index_path, "w", encoding="utf-8", newline="") as f:
    csv.writer(f, delimiter="\t").writerows(index.values())
  return {"layouts": n_lay, "definitions": n_def}
