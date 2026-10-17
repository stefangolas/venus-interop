"""The animated MPE² model (`plr-models`) as a PLR resource whose pose follows the MPE² simulation.

The model is `plr-models/models/hamilton_mpe2_animated.glb`: a shell, the shuttle, the upper and
lower lifters, and the filter and waste carriers as named nodes, in the original Hamilton frame
(X -354..70 mm, the plate seat near X -5). Two changes are made to a copy at run time, the source
is left as it is:

  - each carrier gets a parent node, so its X (with the shuttle) and its Z (with a lifter) are two
    joints: the viewer drives one axis per node;
  - the whole model is moved so its frame starts at its bounding box's corner, where PLR puts a
    resource's origin, so the resource's box is the model's.

`MPE2Model` declares the joints, carries the filter and collection carriers as child resources
(a plate on the MPE² is assigned to one, and moves with it), and takes its pose from the MPE²
simulation's states. The poses are the model's own review clips' (`waste_cycle`,
`collection_cycle`, `clamp_and_present`): shuttle travel 203 mm and the lifts are the modeller's
estimates, see plr-models/REVIEW.md.
"""

import json
import pathlib
import struct
import tempfile
from typing import Any, Dict

from pylabrobot.hamilton.mpe2 import SPEControlState
from pylabrobot.resources import Coordinate, Resource, ResourceStack

S = SPEControlState
MIN_CORNER = (-354.0, -79.03, 1.5)  # mm: the model's bounding box, from its JSON
# The resource's box is the closed body only, X -354 to -75 in the original frame: the integration
# area in front of it (to X 70) is open to the STAR, and PLR will not set a plate down at a point
# inside another resource's box. The mesh draws the whole unit whatever the box.
SIZE = (279.0, 158.06, 195.5)
SEAT = Coordinate(-5.0, 0.0, 49.6)  # the filter carrier's seat at rest, in the original frame
COLLECTION_SEAT_Z = 26.4

# Joint values per pose, in mm from the file's rest pose (the clips' plateaus).
REST = dict(shuttle=0.0, upper_lift=0.0, lower_lift=0.0, filter_x=0.0, filter_z=0.0, waste_x=0.0, waste_z=0.0)
CLAMPED = dict(REST, upper_lift=62.0, filter_x=-203.0, filter_z=60.0)
TO_WASTE = dict(CLAMPED, shuttle=-203.0, lower_lift=73.2, waste_x=-203.0, waste_z=65.3)
TO_COLLECTION = dict(CLAMPED, shuttle=-203.0, lower_lift=71.8, waste_x=-203.0, waste_z=63.8)
POSE = {
  S.CLAMPING_FILTER_PLATE_1: CLAMPED, S.CLAMPING_FILTER_PLATE_2: CLAMPED, S.FILTER_PLATE_CLAMPED: CLAMPED,
  S.PROCESS_FILTER_PLATE_TO_WASTE: TO_WASTE, S.PROCESS_FILTER_PLATE_TO_COLLECTION: TO_COLLECTION,
}


def derived_glb(source: pathlib.Path, out_dir: pathlib.Path) -> pathlib.Path:
  """The source GLB with each carrier nested under an X node, and the model moved to its corner."""
  data = source.read_bytes()
  json_len = struct.unpack_from("<I", data, 12)[0]
  gltf = json.loads(data[20:20 + json_len])
  rest = data[20 + json_len:]
  nodes = gltf["nodes"]
  index = {n.get("name"): i for i, n in enumerate(nodes)}
  world = nodes[index["world"]]
  for name in ("filter_carrier", "waste_carrier"):
    nodes.append({"name": f"{name}_x", "children": [index[name]]})
    world["children"] = [len(nodes) - 1 if c == index[name] else c for c in world["children"]]
  t = world.get("translation", [0.0, 0.0, 0.0])
  world["translation"] = [t[0] - MIN_CORNER[0] / 1000, t[1] - MIN_CORNER[1] / 1000, t[2] - MIN_CORNER[2] / 1000]
  text = json.dumps(gltf, separators=(",", ":")).encode()
  text += b" " * (-len(text) % 4)
  body = struct.pack("<II", len(text), 0x4E4F534A) + text + rest
  out = out_dir / "hamilton_mpe2_nested.glb"
  out.write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)
  return out


class MPE2Model(Resource):
  """The MPE², drawn from the animated model; its pose is the simulation's state."""

  def __init__(self, name: str, glb: pathlib.Path):
    super().__init__(name, size_x=SIZE[0], size_y=SIZE[1], size_z=SIZE[2], category="mpe2",
                     model="hamilton_mpe2_animated")
    path = derived_glb(glb, pathlib.Path(tempfile.mkdtemp(prefix="mpe2_")))
    speed = 100.0  # mm/s: the clips move the shuttle 203 mm in 2 s
    joint = lambda node, axis: {"node": node, "type": "prismatic", "axis": axis, "speed": speed}  # noqa: E731
    self.mesh = {
      "path": str(path), "units": "m", "up": "Z",
      "joints": {
        "shuttle": joint("shuttle", "x"), "upper_lift": joint("upper_lifter", "z"),
        "lower_lift": joint("lower_lifter", "z"),
        "filter_x": joint("filter_carrier_x", "x"), "filter_z": joint("filter_carrier", "z"),
        "waste_x": joint("waste_carrier_x", "x"), "waste_z": joint("waste_carrier", "z"),
      },
    }
    self.joints: Dict[str, float] = dict(REST)
    # The carriers as stacks, at rest under the plate seat: a plate put on one moves with it, and a
    # filter plate set on a receiving plate (the lysate clearing) stacks on top of it.
    seat = self.from_original(SEAT)
    self.filter_carrier = ResourceStack(f"{name}_filter_carrier", "z")
    self.collection_carrier = ResourceStack(f"{name}_collection_carrier", "z")
    # by name: a stack's equality, and so its hash, follows what it holds
    self._rest = {
      self.filter_carrier.name: Coordinate(seat.x - 63.88, seat.y - 42.74, seat.z),
      self.collection_carrier.name: Coordinate(seat.x - 63.88, seat.y - 42.74, seat.z - (SEAT.z - COLLECTION_SEAT_Z)),
    }
    for carrier in (self.filter_carrier, self.collection_carrier):
      self.assign_child_resource(carrier, location=self._rest[carrier.name])

  @staticmethod
  def from_original(c: Coordinate) -> Coordinate:
    """A point in the original Hamilton model frame, in this resource's frame."""
    return Coordinate(c.x - MIN_CORNER[0], c.y - MIN_CORNER[1], c.z - MIN_CORNER[2])

  @classmethod
  def location_for_seat(cls, seat_on_deck: Coordinate) -> Coordinate:
    """Where to put the resource so its filter seat is at `seat_on_deck` (a plate's centre-bottom)."""
    return seat_on_deck - cls.from_original(SEAT)

  def on_state(self, state: SPEControlState) -> None:
    pose = POSE.get(state, REST)
    if pose == self.joints:
      return
    self.joints = dict(pose)
    for carrier, axis_x, axis_z in ((self.filter_carrier, "filter_x", "filter_z"),
                                    (self.collection_carrier, "waste_x", "waste_z")):
      carrier.location = self._rest[carrier.name] + Coordinate(pose[axis_x], 0, pose[axis_z])
    self._state_updated()

  def serialize_state(self) -> Dict[str, Any]:
    return {**super().serialize_state(), "joints": dict(self.joints)}
