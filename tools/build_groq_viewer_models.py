"""Prepare GROQ-seq viewer assets from downloaded NIST files and the existing plr-models MPE2.

Run with the models extra installed. Inputs are read only; output defaults to this repo's models/.
Registration is cosmetic and recorded in Delta ledgers beside each converted model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from venus_interop.files.definitions import load  # noqa: E402
from venus_interop.plr import xfile  # noqa: E402
from venus_interop.rules.deltas import Delta  # noqa: E402

CARRIERS = (
  "MFX_CAR_2Empty_2HHSF30DWP", "MFX_CAR_2Low_2HHC", "MFX_CAR_HHC_Empty_2Base HPTab",
  "MFX_CAR_5DWP NestRB", "MFX_CAR_5DWP", "MFX_CAR_5TipBC",
)
ACCESSORIES = (
  ('ML_STAR/CORE/WasteBlock.hxx', 'ML_STAR/CORE/WasteBlock.tml', 'WasteBlock'),
  ('ML_STAR/CORE/Verification.hxx', 'ML_STAR/CORE/Verification.rck', 'Verification'),
  ('ML_STAR/CORE/TeachingNeedle5ml.hxx', 'ML_STAR/CORE/TeachingNeedle5ml.rck', 'TeachingNeedle5ml'),
  ('ML_STAR/CORE/TeachingNeedleBlock.hxx', 'ML_STAR/CORE/TeachingNeedleBlock.rck', 'TeachingNeedleBlock'),
  ('ML_STAR/96COREHEAD/core96SlideWasteRack.hxx', 'ML_STAR/96COREHEAD/core96SlideWaste.rck',
   'core96SlideWasteRack'),
)


def convert(source: pathlib.Path, definition: pathlib.Path, output: pathlib.Path) -> dict:
  """Keep authored dimensions; place the mesh minimum at the definition's 3D offsets.

  This is an explicit viewer interpretation, not a verified general Venus placement rule.
  In particular, do not centre the carrier's protruding handle in its nominal footprint.
  """
  scene = xfile.load(source)
  d = load(definition)
  before = scene.bounds.copy()
  offset = [d.num(f"3D{axis}Offset") for axis in "xyz"]
  translation = [float(offset[i] - before[0, i]) for i in range(3)]
  scene.apply_translation(translation)
  scene.apply_scale(0.001)
  ledger = [
    Delta(source.stem, "interpretation", "mesh origin", venus=before[0].tolist(), plr=offset,
          decision="Place mesh minimum at definition 3D offsets; preserve overhangs and dimensions",
          detail="Cosmetic registration; not verified against Venus rendering").as_dict(),
    Delta(source.stem, "convention", "mesh units", venus="mm", plr="m",
          decision="Multiply all coordinates by 0.001").as_dict(),
  ]
  info = dict(source=source.name, source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
              definition=definition.name, definition_sha256=hashlib.sha256(definition.read_bytes()).hexdigest(),
              source_bounds_mm=before.tolist(), translation_mm=translation, scale=0.001,
              output_bounds_m=scene.bounds.tolist(), deltas=ledger)
  output.parent.mkdir(parents=True, exist_ok=True)
  scene.export(output)
  output.with_suffix('.geometry.json').write_text(json.dumps(info, indent=2) + '\n', encoding='utf-8')
  return info


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--references', type=pathlib.Path,
                      default=ROOT / '.local/session_state/nist/groq_model_references/LabWare')
  parser.add_argument('--mpe2', type=pathlib.Path,
                      default=ROOT.parent / 'plr-models/models/hamilton_mpe2_animated.glb')
  parser.add_argument('--output', type=pathlib.Path, default=ROOT / 'models')
  args = parser.parse_args()
  for mesh, definition, name in ACCESSORIES:
    convert(args.references / mesh, args.references / definition, args.output / f'{name}.glb')
  mfx = args.references / 'ML_STAR/MultiFlexCarrier'
  for stem in CARRIERS:
    convert(mfx / f'{stem}.x', mfx / f'{stem}.tml', args.output / f'{stem}.glb')
  mpe = args.references / 'ML_STAR/MPE2'
  convert(mpe / '[MPE]2 Base.x', mpe / 'Culture_Processing_STAR_MPE2_Base_Back.tml',
          args.output / 'Culture_Processing_STAR_MPE2_Base_Back.glb')
  shutil.copyfile(args.mpe2, args.output / args.mpe2.name)
  info = dict(source='plr-models/models/hamilton_mpe2_animated.glb',
              sha256=hashlib.sha256(args.mpe2.read_bytes()).hexdigest(),
              registration='Unmodified original; examples/mpe2_model.py registers the filter seat at runtime')
  (args.output / 'hamilton_mpe2_animated.geometry.json').write_text(
    json.dumps(info, indent=2) + '\n', encoding='utf-8')
  print(f'Prepared {len(CARRIERS) + len(ACCESSORIES) + 2} GLBs in {args.output}')


if __name__ == '__main__':
  main()
