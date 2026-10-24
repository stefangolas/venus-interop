"""Build cosmetic GROQ-seq consumable meshes; never change protocol definitions.

Requires the models extra (trimesh and manifold3d). The saved Venus definitions supply the
footprints and position grids; every reconstructed detail is recorded in a Delta ledger.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial
from venus_interop.files.definitions import load
from venus_interop.rules.deltas import Delta

# Separate lid assets preserve identities even when their approximate shell geometry agrees.
SOURCES = {
  'fourtitude_4ti_0255': ('Culture Processing/Fourtitude Growth Plate with Lid.rck', 'growth'),
  'agilent_201250_100': ('Agilent/Agilent single cavity 12 col pyr bottom 290 mL reservoir with lid.rck', 'single'),
  'agilent_204284_100': ('Agilent/Agilent 6 well reservoir.rck', 'six'),
  'fourtitude_growth_lid': ('Culture Processing/Fourtitude Growth Plate with Lid.lid', 'lid'),
  'agilent_201250_lid': ('Agilent/Agilent single cavity 12 col pyr bottom 290 mL reservoir with lid.lid', 'lid'),
  'agilent_6_column_lid': ('Agilent/Agilent 6 well reservoir.lid', 'lid'),
  'core2_support_ht': ('TipSupport CO-RE II/Core2_96_TipSupport_HT_Filter_L.rck', 'support'),
  'core2_support_st': ('TipSupport CO-RE II/Core2_96_TipSupport_ST_Filter_L.rck', 'support'),
  'core2_support_50': ('TipSupport CO-RE II/Core2_96_TipSupport_50ulTipFilter_L.rck', 'support'),
}


def box(lo, hi):
  lo, hi = np.array(lo), np.array(hi)
  m = trimesh.creation.box(hi - lo)
  m.apply_translation((hi + lo) / 2)
  return m


def taper(cx, cy, lower, upper, z0, z1):
  """Closed rectangular frustum, for a tapered cavity cut."""
  vertices = [(cx + x * w / 2, cy + y * h / 2, z)
              for (w, h), z in ((lower, z0), (upper, z1))
              for x, y in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
  faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7)]
  for i in range(4):
    j = (i + 1) % 4
    faces.extend(((i, j, j + 4), (i, j + 4, i + 4)))
  return trimesh.Trimesh(vertices, faces, process=True)


def build(d, kind):
  sx, sy, sz = d.dim
  cuts, choices = [], {}
  positions = [(d.num('BndryX') + c * d.num('Dx'), sy - d.num('BndryY') - r * d.num('Dy'))
               for c in range(d.int('Columns')) for r in range(d.int('Rows'))]
  body = box((0, 0, 0), (sx, sy, sz))
  if kind == 'growth':
    choices = dict(well_opening_mm=7.7, bottom_square_mm=4.5, taper_height_mm=3.0,
                   floor_z_mm=2.3, skirt_wall_mm=1.2, underside_recess_mm=1.3)
    for x, y in positions:
      cuts.append(taper(x, y, (4.5, 4.5), (7.7, 7.7), 2.3, 5.3))
      cuts.append(box((x-3.85, y-3.85, 5.3), (x+3.85, y+3.85, sz+1)))
    cuts.append(box((1.2, 1.2, -1), (sx-1.2, sy-1.2, 1.3)))
  elif kind in ('single', 'six'):
    # The Venus grid represents aspiration locations: 96 sites in one cavity or 48 in six.
    # Only six-column partitions rise to the rim. Pyramid ridges stay below the common volume.
    cols = 12 if kind == 'single' else 6
    pitch = d.num('Dx')
    x0, y0 = d.num('BndryX') - pitch/2, sy - d.num('BndryY') - 7*d.num('Dy') - 4.5
    floor = 5.0 if kind == 'single' else 2.0
    ridge = floor + 3.0
    choices = dict(cavities=1 if kind == 'single' else 6, floor_features=12 if kind == 'single' else 24,
                   floor_z_mm=floor, ridge_height_mm=3.0, wall_mm=1.0,
                   floor_flat_width_mm=2.0, floor_end_inset_mm=2.0, skirt_wall_mm=1.2, underside_recess_mm=1.0,
                   cavity_length_mm=72.0, outside_recess_z_mm=[3.0, sz-2.0])
    if kind == 'single':
      cuts.append(box((x0, y0, ridge), (x0+cols*pitch, y0+72, sz+1)))
    for c in range(cols):
      cx = x0 + (c+.5)*pitch
      width = pitch if kind == 'single' else pitch - 1
      if kind == 'six':
        cuts.append(box((cx-width/2, y0, ridge), (cx+width/2, y0+72, sz+1)))
      rows = 1 if kind == 'single' else 4
      for r in range(rows):
        length = 72/rows
        cy = y0 + (r+.5)*length
        cuts.append(taper(cx, cy, (2, length-4), (width, length), floor, ridge))
    cuts.append(box((1.2, 1.2, -1), (sx-1.2, sy-1.2, 1)))
    # Recess the outside above the bottom skirt, leaving a broad foot and top rim.
    inset = 1.2
    for lo, hi in [((0,0,3),(inset,sy,sz-2)), ((sx-inset,0,3),(sx,sy,sz-2)),
                   ((0,0,3),(sx,inset,sz-2)), ((0,sy-inset,3),(sx,sy,sz-2))]:
      cuts.append(box(lo, hi))
  elif kind == 'lid':
    choices = dict(side_wall_mm=1.0, roof_thickness_mm=1.0,
                   underside='open universal lid; no unverified condensation rings')
    cuts.append(box((1,1,-1),(sx-1,sy-1,sz-1)))
  else:
    choices = dict(hole_diameter_mm=6.8, plate_thickness_mm=3.0, skirt_wall_mm=1.5,
                   cylinder_sections=32,
                   body_height='definition height retained; same part number has different rack heights')
    cuts.append(box((1.5,1.5,-1),(sx-1.5,sy-1.5,sz-3)))
    for x,y in positions:
      hole = trimesh.creation.cylinder(radius=3.4, height=sz+2, sections=32)
      hole.apply_translation((x,y,sz/2))
      cuts.append(hole)
  # One physical mesh per consumable: no tips, liquids, or removable lids baked into a plate.
  cut = trimesh.boolean.union(cuts, engine='manifold')
  mesh = trimesh.boolean.difference([body, cut], engine='manifold')
  colour = [45,49,50,255] if kind == 'support' else [225,235,240,110] if kind == 'lid' else [218,229,235,235]
  choices['appearance'] = dict(rgba=colour, roughness=.3, metallic=0,
                                alpha_mode='BLEND' if kind == 'lid' else 'OPAQUE')
  mesh.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(
    name='black_support' if kind == 'support' else 'translucent_polymer',
    baseColorFactor=colour, metallicFactor=0.0, roughnessFactor=.3,
    alphaMode='BLEND' if kind == 'lid' else 'OPAQUE', doubleSided=True))
  mesh.apply_scale(.001)
  return mesh, choices, positions


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--references', type=Path, default=ROOT / '.local/session_state/nist/groq_model_references/LabWare')
  parser.add_argument('--output', type=Path, default=ROOT/'models')
  args = parser.parse_args()
  args.output.mkdir(parents=True, exist_ok=True)
  for name, (rel, kind) in SOURCES.items():
    source = args.references / rel
    d = load(source)
    mesh, choices, positions = build(d, kind)
    if not mesh.is_watertight or not mesh.is_volume:
      raise ValueError(f'{name}: mesh is not a closed, outward-oriented solid')
    scene = trimesh.Scene(mesh)
    scene.export(args.output / (name + '.glb'))
    deltas = [Delta(name, 'interpretation', 'visual reconstruction', venus=d.fields.get('Description'),
                    plr=choices, decision='Approximate exterior and cavity details; no protocol geometry changes',
                    detail='Square tapered growth wells from NIST photo; reservoir cavity topology from Agilent; '
                           'support shape from Hamilton image. Sharp corners and material appearance are approximations.').as_dict(),
              Delta(name, 'convention', 'mesh units', venus='mm', plr='m',
                    decision='Multiply coordinates by 0.001').as_dict()]
    if kind in ('single','six'):
      deltas.append(Delta(name, 'stock_disagrees', 'footprint', venus=list(d.dim[:2]),
                          plr=[127.76,85.47], decision='Keep Venus footprint for visual registration; do not resize resources',
                          detail='Manufacturer physical footprint differs from the Venus definition').as_dict())
    info = dict(model=name, kind=kind, definition=rel, definition_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                size_mm=d.dim, positions_mm=positions, choices=choices, deltas=deltas,
                triangles=len(mesh.faces), watertight=bool(mesh.is_watertight),
                references='models/GROQ_SEQ_REFERENCES.md', fidelity='approximate visualization, not mechanical CAD')
    (args.output / (name+'.geometry.json')).write_text(json.dumps(info, indent=2)+'\n', encoding='utf-8')
    print(name, len(mesh.faces), 'triangles')
  # The Hamilton trough already has an authored mesh: reuse it instead of approximating a shell.
  from build_groq_viewer_models import convert
  reagent = args.references / 'ML_STAR/Reagent'
  convert(reagent / 'rgt_cont_60ml_BC_A00.hxx', reagent / 'rgt_cont_60ml_BC_A00.rck',
          args.output / 'rgt_cont_60ml_BC_A00.glb')


if __name__ == '__main__':
  main()
