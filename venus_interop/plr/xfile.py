"""Hamilton 3D models: DirectX text `.x` and Hamilton `.hxx` (a `Hamilton3dData` header, then a
gzip stream holding a text `.x`).

The `.x` reader is copied from plr-viz3d-scratch/hamilton_library/x_to_glb.py: it applies the frame
hierarchy (row-vector matrices, D3D style), keeps one material per MeshMaterialList entry, and swaps
the file's Y-up to Z-up with the winding reversed. Units stay as authored (Hamilton models are in mm).
"""

import zlib
import pathlib
import re

import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

TOKEN = re.compile(r'"[^"]*"|[{}]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|[A-Za-z_][\w\-\.]*|[;,]')


class Block:
  def __init__(self, kind, name):
    self.kind, self.name, self.values, self.children = kind, name, [], []


def parse(text):
  """Data objects as a tree of Blocks; numbers and strings in order, separators dropped."""
  text = text[text.index("\n") + 1:]  # after the `xof 0302txt 0032` header line
  text = re.sub(r"(//|#)[^\n]*", "", text)  # comments
  tokens = TOKEN.findall(text)
  root = Block("root", None)
  stack = [root]
  i = 0
  while i < len(tokens):
    t = tokens[i]
    if t == "}":
      stack.pop(); i += 1; continue
    if t in ";,":
      i += 1; continue
    if re.match(r"[A-Za-z_]", t):
      # `Kind name {`, `Kind {`, or a reference `{ Name }` handled below
      if i + 1 < len(tokens) and tokens[i + 1] == "{":
        b = Block(t, None); stack[-1].children.append(b); stack.append(b); i += 2; continue
      if i + 2 < len(tokens) and tokens[i + 2] == "{":
        b = Block(t, tokens[i + 1]); stack[-1].children.append(b); stack.append(b); i += 3; continue
      stack[-1].values.append(t); i += 1; continue
    if t == "{":
      # a reference: `{ Name }`
      b = Block("ref", tokens[i + 1] if tokens[i + 1] != "}" else None)
      stack[-1].children.append(b)
      i += 3 if tokens[i + 1] != "}" else 2
      continue
    stack[-1].values.append(t[1:-1] if t.startswith('"') else float(t)); i += 1
  return root


def material_of(block):
  v = [x for x in block.values if isinstance(x, float)]
  rgba, power = v[0:4], v[4]
  tex = [c for c in block.children if c.kind == "TextureFilename"]
  return {"rgba": rgba, "power": power, "texture": tex[0].values[0] if tex else None}


def meshes(block, parent, materials, out):
  """Walk frames, collect (vertices, faces, face_materials) in the root frame."""
  m = parent
  ftm = [c for c in block.children if c.kind == "FrameTransformMatrix"]
  if ftm:
    m = np.array(ftm[0].values, dtype=float).reshape(4, 4) @ parent
  for c in block.children:
    if c.kind == "Frame":
      meshes(c, m, materials, out)
    elif c.kind == "Mesh":
      v = c.values
      n = int(v[0]); verts = np.array(v[1:1 + 3 * n], dtype=float).reshape(n, 3)
      k = 1 + 3 * n; nf = int(v[k]); k += 1
      faces = []
      for _ in range(nf):
        s = int(v[k]); idx = [int(x) for x in v[k + 1:k + 1 + s]]; k += 1 + s
        faces += [[idx[0], idx[j], idx[j + 1]] for j in range(1, s - 1)]  # fan polygons
      mats, face_mat = [], [0] * len(faces)
      mml = [x for x in c.children if x.kind == "MeshMaterialList"]
      if mml:
        mv = [int(x) for x in mml[0].values if isinstance(x, float)]
        nm, nfi = mv[0], mv[1]
        per_face = mv[2:2 + nfi]
        for x in mml[0].children:
          mats.append(material_of(x) if x.kind == "Material" else materials.get(x.name, {"rgba": [0.7, 0.7, 0.7, 1], "power": 20, "texture": None}))
        # expand per-polygon material to per-triangle
        tri_mat, fi = [], 0
        k2 = 1 + 3 * n + 1
        for p in range(nf):
          s = int(v[k2]); k2 += 1 + s
          tri_mat += [per_face[p] if p < len(per_face) else per_face[-1]] * (s - 2)
        face_mat = tri_mat
      world = np.c_[verts, np.ones(len(verts))] @ m
      out.append((world[:, :3], np.array(faces), np.array(face_mat), mats or [{"rgba": [0.7, 0.7, 0.7, 1], "power": 20, "texture": None}]))
    elif c.kind == "Material":
      materials[c.name] = material_of(c)


class UnsupportedModel(ValueError):
  pass


def x_text(path) -> str:
  """The `.x` text inside a `.x` or `.hxx` file."""
  data = pathlib.Path(path).read_bytes()
  if data.startswith(b"Hamilton3dData"):
    start = data.find(bytes([0x1F, 0x8B, 0x08]))  # gzip magic
    if start < 0:
      raise UnsupportedModel(f"{path}: no gzip stream in .hxx")
    data = zlib.decompressobj(wbits=31).decompress(data[start:])  # the first gzip member: the model
  if not data.startswith(b"xof "):
    raise UnsupportedModel(f"{path}: not a DirectX file")
  if data[8:12] != b"txt ":
    raise UnsupportedModel(f"{path}: DirectX format {data[8:12]!r} (only text is read)")
  return data.decode("latin-1")


def load(path) -> trimesh.Scene:
  """The model as a Z-up scene in the file's own units and frame, one geometry per material."""
  root = parse(x_text(path))
  materials = {c.name: material_of(c) for c in root.children if c.kind == "Material"}
  parts = []
  meshes(root, np.eye(4), materials, parts)
  groups = {}
  for verts, faces, face_mat, mats in parts:
    for mi, mat in enumerate(mats):
      sel = faces[face_mat == mi] if len(face_mat) == len(faces) else faces
      if not len(sel):
        continue
      key = tuple(round(x, 3) for x in mat["rgba"]) + (round(mat["power"], 1),)
      groups.setdefault(key, []).append(trimesh.Trimesh(vertices=verts, faces=sel, process=False))
  scene = trimesh.Scene()
  for i, (key, ms) in enumerate(groups.items()):
    mesh = trimesh.util.concatenate(ms)
    mesh.vertices = mesh.vertices[:, [0, 2, 1]]  # Y-up to Z-up
    mesh.faces = mesh.faces[:, ::-1]  # the swap mirrors, so reverse the winding
    mesh.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(
      name=f"m{i}", baseColorFactor=list(key[:4]), metallicFactor=0.0,
      roughnessFactor=float(np.sqrt(2 / (key[4] + 2))), doubleSided=True))
    scene.add_geometry(mesh, geom_name=f"m{i}", node_name=f"m{i}")
  return scene
