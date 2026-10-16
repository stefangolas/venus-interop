"""Corpus fixtures. Set VENUS_INTEROP_CORPUS to a folder with:

  raw/*.lay            layouts as found (binary or text form)
  text/<same name>     Hamilton converter's text form of each binary layout (optional)
  defs_raw/*           definition files, named as in defs_index.tsv
  defs_index.tsv       <file name> TAB <relative Labware path> TAB <source>

Corpus tests are skipped when it is unset.
"""
import csv
import os
import pathlib

import pytest

from venus_interop.files.definitions import DEFAULT_VENUS_LABWARE, DefinitionStore

CORPUS = pathlib.Path(os.environ["VENUS_INTEROP_CORPUS"]) if os.environ.get("VENUS_INTEROP_CORPUS") else None
LAYOUTS = sorted((CORPUS / "raw").glob("*.lay")) if CORPUS else []
DEFINITIONS = sorted((CORPUS / "defs_raw").iterdir()) if CORPUS else []


def corpus_params(paths):
  if not paths:
    return [pytest.param(None, marks=pytest.mark.skip(reason="VENUS_INTEROP_CORPUS not set"))]
  return [pytest.param(p, id=p.name) for p in paths]


@pytest.fixture(scope="session")
def store():
  if CORPUS is None:
    pytest.skip("VENUS_INTEROP_CORPUS not set")
  index = {}
  with open(CORPUS / "defs_index.tsv", encoding="utf-8") as f:
    for name, rel, src in csv.reader(f, delimiter="\t"):
      if (CORPUS / "defs_raw" / name).exists():
        index[rel] = CORPUS / "defs_raw" / name
  # Corpus definitions first: the layouts were saved against those, not the local Venus install.
  return DefinitionStore([DEFAULT_VENUS_LABWARE] if DEFAULT_VENUS_LABWARE.is_dir() else [], index)
