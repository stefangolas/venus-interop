"""Register PLR's STAR chassis mesh in the imported deck's unchanged coordinate frame."""
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pylabrobot.hamilton.star import device
from venus_interop.rules.deltas import Delta


def build():
  source = Path(device.__file__).parent / 'resource_model/star_base.glb'
  data = source.read_bytes()
  size = struct.unpack_from('<I', data, 12)[0]
  gltf = json.loads(data[20:20 + size])
  # The source includes the hood and waste hardware as well as the platform. Keep only
  # the lower chassis; GROQ already has an authored waste block and a moving arm.
  selected = [3, 4, 5, 7, 11]
  expected = ['XMat.008', 'XMat.009', 'XMat.003', 'XMat.004', 'Aluminum_-_Anodized_Glossy_(Grey)']
  primitives = gltf['meshes'][0]['primitives']
  assert [gltf['materials'][primitives[i]['material']]['name'] for i in selected] == expected, 'STAR asset changed; review chassis selection'
  gltf['meshes'][0]['primitives'] = [primitives[i] for i in selected]
  origin = device.STAR_DECK_LOCATION
  shift = [-origin.x / 1000, -origin.y / 1000, -origin.z / 1000]
  for scene in gltf['scenes']:
    node = len(gltf['nodes'])
    gltf['nodes'].append(dict(name='imported_deck_frame', translation=shift, children=scene['nodes']))
    scene['nodes'] = [node]
  encoded = json.dumps(gltf, separators=(',', ':')).encode()
  encoded += b' ' * (-len(encoded) % 4)
  body = struct.pack('<II', len(encoded), 0x4E4F534A) + encoded + data[20 + size:]
  target = ROOT / 'models/star_base_deck_frame.glb'
  target.write_bytes(struct.pack('<III', 0x46546C67, 2, len(body) + 12) + body)
  ledger = Delta(resource='STAR chassis', kind='convention', quantity='visual origin in metres',
                 venus=[0, 0, 0], plr=shift,
                 detail='PLR STAR factory places its deck at STAR_DECK_LOCATION in the chassis frame.',
                 decision='Translate the mesh by minus that origin; retain every imported resource coordinate.')
  target.with_suffix('.geometry.json').write_text(json.dumps(dict(
    source='pylabrobot/hamilton/star/resource_model/star_base.glb',
    source_sha256=hashlib.sha256(data).hexdigest(), translation_m=shift,
    retained_primitives=selected,
    deltas=[ledger.as_dict(), Delta(resource='STAR chassis', kind='interpretation',
      quantity='visible source components', venus=list(range(len(primitives))), plr=selected,
      detail='The source combines lower chassis, waste hardware, door and upper enclosure.',
      decision='Show lower platform and chassis only; retain imported waste hardware and an unobstructed deck view.').as_dict()]), indent=2), encoding='utf-8')
  print(target)


if __name__ == '__main__':
  build()
