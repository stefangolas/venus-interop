// The realistic look (`?look=real`): a scene lit as a room is rather than as a drawing.
//
// The technical look carries every light on the camera, so a surface shades by its own shape and
// reads the same from any side. That also means no light has a direction in the world, so nothing
// casts a shadow and nothing sits on anything: a plate on its carrier looks pasted on. Here a key
// light is fixed high over the deck, as a room's ceiling lights are, and casts
// soft shadows; the camera's lights stay on as a fill so nothing goes black; and tone mapping keeps
// the gradient in near-white plastic that the flat look lets clip to white.

import * as THREE from "three";
import { smaa } from "three/addons/tsl/display/SMAANode.js";
import { pass, renderOutput } from "three/tsl";
import { MOVING_PARTS } from "./constants.js";
import { travels } from "./drawn.js";
import { beforeDraw, drawWith, invalidate } from "./frame.js";
import { onChange } from "./live.js";
import { LIGHT, LOOK_REAL } from "./options.js";
import { controls, fillLight, keyLight, renderer, skyLight, view } from "./renderer.js";
import { modelOf } from "./world.js";

// The world's light, as a share of the technical key it replaces; the camera's lights, the sky and
// the reflections keep these shares. A shadow takes away the sun's light and no other, so the sun
// has to carry most of it or the shadows are a faint grey: with the technical sky and fill kept,
// they were.
const SUN = 2.8;
const CAMERA_FILL = 0.15;
const SKY = 0.45;
const REFLECTIONS = 0.7;
// Where the light comes from, as a unit direction: high, as a room's ceiling lights are, and a little
// behind and to the left of the deck. Not from the front: a view is nearly always from the front,
// and a light from behind the viewer throws every shadow straight back behind what casts it, where
// no one sees it.
const SUN_FROM = new THREE.Vector3(-0.3, 0.4, 1).normalize();
// Shadow map texels: a STAR deck is about 1.8 m across, so ~0.45 mm a texel.
const SHADOW_MAP = 4096;
// How far the shadow's edge is blurred, in shadow-map texels: soft, as under a broad ceiling light.
const SHADOW_SOFTNESS = 8;
// The shadow's frustum is fitted to what casts, and refitted only when that changes by more than
// this, in mm: refitted on every change of the tree, a tip picked up shifted every shadow a little.
const REFIT_BEYOND = 50;
// Liquid in this look: enough body to see the level, enough show-through to see the well behind it.
const LIQUID_OPACITY = 0.55;
const LIQUID_ROUGHNESS = 0.25;

// `?shadows=0` leaves the shadows out, so they can be timed on their own (`plrViewer.benchmark()`).
// SMAA - three full-screen passes over each frame - is off unless asked for with `?smaa=1`: the
// renderer's own multisampling smooths edges for much less. Ambient occlusion was tried and taken
// out: the dearest of the effects, for what it added.
const ASKED = new URLSearchParams(location.search);
const SHADOWS = ASKED.get("shadows") !== "0";
const SMAA = ASKED.get("smaa") === "1";
// The enclosure's glazing - in the machine's own model, every material its file makes see-through
// enough to be glass (models.js: `asModelled.glazed`) - is left out unless asked for with `?glass=1`.
// Only the machine's: labware and devices have see-through parts that are not an enclosure. Glass cannot be
// skipped where something stands behind it, so each pixel under a panel was shaded twice or more,
// and the STAR's enclosure covers most of the view. Its frame stays.
const GLASS = ASKED.get("glass") === "1";
const ENCLOSURE_MODEL = /^(STAR|STARLet|STARPlus|star|starlet|starplus)|extension_housing/;

// What things are made of, by resource model: nearly every file came with the same middling
// roughness and little metalness, so aluminium, anodised metal and polypropylene all read alike.
// Names inside the files are no guide - the standard tip rack's plastic is called "Steel - Satin".
// First match wins; a model none match keeps what its file says.
const FINISHES = [
  // Anodised housings: metal under a coloured, slightly rough coat.
  { match: /^inheco_/, finish: "anodised" },
  // Labware: polypropylene, polystyrene - matte.
  {
    match:
      /wellplate|troughplate|trough_\d|tiprack|tip_support|_tip_|^hamilton_tip|comfort_lid|_lid$|tube_/i,
    finish: "plastic",
  },
  // Carriers, MultiFlex modules, plate adapters, the arm and gripper hardware: machined aluminium.
  {
    match:
      /_CAR_|^MFX_CAR|plateadapter|mfx_plateholder|mfx_tiprackholder|odtc_lid_park|cpac_bracket|hhs_nest|heater_shaker|core_gripper|dual_rail_arm|iswap/i,
    finish: "aluminium",
  },
];
const FINISH = {
  aluminium: { metalness: 0.85, roughness: 0.32, reflections: 2.2 },
  anodised: { metalness: 0.55, roughness: 0.42, reflections: 1.6 },
  plastic: { metalness: 0.0, roughness: 0.55, reflections: 0.6 },
  // Near-black parts - a carrier's base, a black plastic - stay matte whatever they are.
  dark: { metalness: 0.1, roughness: 0.75, reflections: 0.4 },
};
// Within the STAR's own model, where each material is one part, its names do say.
const STAR_METAL = /alumin|steel|metal|chrom/i;

function finishOf(model, material) {
  const name = model?.model ?? "";
  if (/^(STAR|STARLet|STARPlus|star|starlet|starplus)/.test(name)) {
    return STAR_METAL.test(material.name) ? "aluminium" : null;
  }
  const found = FINISHES.find((f) => f.match.test(name));
  if (!found) return null;
  const c = material.color;
  const dark = c && !material.vertexColors && c.r + c.g + c.b < 0.25;
  return dark && found.finish !== "anodised" ? "dark" : found.finish;
}

// A resource with no model file is drawn as a see-through box; in this look they are fainter still
// - over the channels' tip waste they read as a haze. The bench and the arm keep theirs.
const STAND_IN_OPACITY = 0.3; // of what the box had
const STAND_IN_KEPT = new Set(["bench", "x_arm", "arm", "facility"]);
// With SMAA asked for: while the view is orbited or zoomed, frames skip it, and the finished frame is
// drawn once the view has settled this long.
const SETTLE_MS = 250;

// Parts the shadow pass leaves alone: anything see-through (a glass panel would shade the whole
// deck), and overlays drawn over the scene rather than in it.
function castsAndReceives(o) {
  const m = o.material;
  if (!m || Array.isArray(m)) return false;
  if (m.transparent && m.opacity < 0.95) return false;
  if (o.renderOrder > 0 || o.isLine || o.isSprite || o.isPoints) return false;
  return true;
}

// The resource a mesh draws, where the page has said.
const resourceOf = (o) => (o.isInstancedMesh ? o.userData.instances?.[0] : o.userData.declaredBy);

// Only what stands still casts: the arm, the channels, the heads, the iSWAP and whatever they carry
// do not. The shadows are then those of the deck and what stands on it, and the shadow map - the
// whole scene drawn once more - is drawn again only when something is put down or taken away, not
// on every frame of a motion. What moves still receives shadows.
// Tips do not cast either: a tip's shadow falls inside its rack, where it is not seen, and 1,824
// of them on a KAPA deck are a third of what the shadow map would draw.
function casts(o) {
  if (!castsAndReceives(o)) return false;
  const index = resourceOf(o);
  // A mesh the page has not tied to one resource - a well's rim or liquid, a tip spot's cavity, one
  // instanced mesh for all of them - casts nothing: some ride the heads, and their shadows moved
  // across the deck. What they sit in casts, through its own model.
  if (index === undefined) return false;
  return !travels(index) && modelOf(index).category !== "tip";
}

export function initLook() {
  if (!LOOK_REAL) return;

  renderer.toneMapping = THREE.NeutralToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.shadowMap.enabled = SHADOWS;
  // Variance shadow maps: the shadow is blurred into a real penumbra, as under a broad ceiling light,
  // where PCF's few samples left edges stepped and shimmering as the arm moved.
  renderer.shadowMap.type = THREE.VSMShadowMap;
  // The light is fixed in the world, so orbiting changes no shadow: the map is drawn again only when
  // something in the scene moves or changes, not every frame - it is the whole scene drawn once more.
  // (In three's WebGPU renderer that is the light's own `shadow.autoUpdate`, set below: the
  // renderer's `shadowMap.autoUpdate` is the WebGL renderer's, and does nothing here - the map was
  // drawn and blurred afresh every frame, 11 ms of a 26 ms frame.)
  renderer.shadowMap.autoUpdate = false;
  let shadowsStale = true;
  // Drawn again at discrete points only: something put down or taken away ("moves"), switched on or
  // off ("visibility"), or the scene gaining or losing resources. A motion's steps ("glide") move
  // only what does not cast, and a command's new state - volumes, tip states - moves nothing.
  // A move redraws only if what moved casts, or did where it was: the moves a run sends are nearly
  // all of arms, channels and tips, which cast nothing, and each redraw of a 4096 map stalls a
  // frame for ~300 ms - the motion then jumped by that much.
  const castsAt = (index, holder) =>
    modelOf(index).category !== "tip" &&
    !MOVING_PARTS.has(modelOf(index).category) &&
    !(holder >= 0 && (travels(holder) || MOVING_PARTS.has(modelOf(holder).category)));
  const castsHere = (index) => modelOf(index).category !== "tip" && !travels(index);
  onChange((change) => {
    if (change.kind === "visibility") shadowsStale = true;
    if (change.kind !== "moves") return;
    if (!change.moved || change.moved.some(({ index, was }) => castsHere(index) || castsAt(index, was))) {
      shadowsStale = true;
    }
  });

  keyLight.intensity *= CAMERA_FILL;
  fillLight.intensity *= CAMERA_FILL;
  skyLight.intensity *= SKY;
  // Kept when the page steps its quality down (frame.js): it used to put the full sky back, and the
  // page brightened mid-load and washed the shadows out.
  skyLight.userData.lookShare = SKY;
  // Metal reads as metal by what it reflects; the page's lowest quality level would take the
  // reflections away (and recompile every lit pipeline doing it).
  view.userData.keepEnvironment = true;
  view.environmentIntensity *= REFLECTIONS;

  const sun = new THREE.DirectionalLight(0xffffff, SUN * 0.9 * LIGHT);
  sun.castShadow = true;
  sun.shadow.mapSize.set(SHADOW_MAP, SHADOW_MAP);
  sun.shadow.bias = -0.0002;
  sun.shadow.normalBias = 0.6; // mm: keeps curved plastic from shadowing itself in stripes
  sun.shadow.radius = SHADOW_SOFTNESS;
  sun.shadow.blurSamples = 16;
  sun.shadow.autoUpdate = false;
  view.add(sun);
  view.add(sun.target);

  // With `?smaa=1`, drawn through a pipeline under perspective: the scene, the output transform (tone
  // mapping), and SMAA over the finished picture, where the edges are. Otherwise the renderer draws
  // the frame itself, tone mapped, with no pipeline at all. A plan view is drawn as it is - an axis view
  // needs its edges crisp rather than smoothed. One pipeline per camera, as a pass is bound to the
  // camera it was built with.
  const pipelines = new Map();
  const pipelineFor = (camera) => {
    let post = pipelines.get(camera);
    if (post) return post;
    post = new THREE.PostProcessing(renderer);
    post.outputColorTransform = false;
    post.outputNode = smaa(renderOutput(pass(view, camera)));
    pipelines.set(camera, post);
    return post;
  };
  let interacting = false;
  let settle = null;
  controls.addEventListener("start", () => {
    interacting = true;
    clearTimeout(settle);
  });
  controls.addEventListener("end", () => {
    clearTimeout(settle);
    settle = setTimeout(() => {
      interacting = false;
      invalidate();
    }, SETTLE_MS);
  });
  drawWith((camera) => {
    if (!SMAA || !camera.isPerspectiveCamera || interacting) return false;
    pipelineFor(camera).render();
    return true;
  });

  // Fitted to the scene each time it changes shape: the shadow camera covers what is drawn, and no
  // more, so its texels stay small.
  const box = new THREE.Box3();
  const fitted = new THREE.Box3();
  const size = new THREE.Vector3();
  const centre = new THREE.Vector3();
  let fittedFor = -1;

  // Marked as they join the scene, before they are first drawn: whether a mesh takes shadows is
  // built into what draws it, and a mesh marked after it has drawn once goes on drawing without them
  // (material.needsUpdate does not bring them back). Casting is decided afresh each frame, so a
  // part that turns see-through - carried, say - stops casting.
  const mark = (added) =>
    added.traverse((o) => {
      if (!o.isMesh) return;
      const on = castsAndReceives(o);
      o.castShadow = on;
      o.receiveShadow = on;
    });
  mark(view);
  view.addEventListener("childadded", (event) => mark(event.child));

  // Each material is dressed once, the first time the resource it draws is known: an instanced
  // model's meshes learn which resources they stand for only after they join the scene.
  const dress = (o) => {
    const m = o.material;
    if (m.userData.lookDressed || !("metalness" in m)) return;
    const index = o.isInstancedMesh ? o.userData.instances?.[0] : o.userData.declaredBy;
    if (index === undefined) return;
    m.userData.lookDressed = true;
    const model = modelOf(index);
    // The bench is drawn see-through for the technical look's sake; a room's bench is solid. Left
    // see-through it cast nothing, so the shadow map was fitted to what stands on it and the bench
    // lay outside it: it came out black and streaked.
    // The X-arm is drawn see-through in the technical look so the heads under it show; the real one is
    // solid, the heads hang below it where a view from the front sees them, and see-through its
    // strip across the deck was shaded twice over.
    if (model.category === "x_arm" && m.transparent) {
      m.transparent = false;
      m.opacity = 1;
      m.depthWrite = true;
      m.needsUpdate = true;
    }
    if (model.category === "bench") {
      m.transparent = false;
      m.opacity = 1;
      m.depthWrite = true;
      m.metalness = 0;
      m.roughness = 0.8;
      m.needsUpdate = true;
      shadowsStale = true;
      return;
    }
    if (!model.mesh && m.transparent && m.opacity < 0.95 && !STAND_IN_KEPT.has(model.category)) {
      m.opacity *= STAND_IN_OPACITY;
      m.needsUpdate = true;
      shadowsStale = true;
      return;
    }
    const finish = FINISH[finishOf(model, m)];
    if (!finish) return;
    m.metalness = finish.metalness;
    m.roughness = finish.roughness;
    m.envMapIntensity = finish.reflections;
    m.needsUpdate = true;
  };

  beforeDraw(() => {
    let count = 0;
    view.traverse((o) => {
      if (!o.isMesh) return;
      count++;
      if (o.receiveShadow) o.castShadow = SHADOWS && casts(o);
      if (o.material && !Array.isArray(o.material)) {
        dress(o);
        // Liquid reads as liquid here, not as a solid fill: see-through, and wetter than plastic.
        // The technical look keeps it solid, where its colour is the volume read at a glance.
        if (o.userData.liquid && !o.material.userData.lookDressed) {
          o.material.userData.lookDressed = true;
          o.material.opacity = LIQUID_OPACITY;
          o.material.roughness = LIQUID_ROUGHNESS;
          o.material.needsUpdate = true;
        }
        if (!GLASS && o.userData.asModelled?.glazed && o.material.visible) {
          const index = resourceOf(o);
          if (index !== undefined && ENCLOSURE_MODEL.test(modelOf(index).model ?? "")) {
            o.material.visible = false;
          }
        }
      }
    });
    if (count !== fittedFor) shadowsStale = true;
    if (shadowsStale) {
      renderer.shadowMap.needsUpdate = true;
      sun.shadow.needsUpdate = true;
      shadowsStale = false;
    }
    if (count === fittedFor) return;
    fittedFor = count;
    box.makeEmpty();
    view.traverse((o) => {
      if (o.isMesh && o.castShadow && o.visible) box.expandByObject(o);
    });
    if (box.isEmpty()) return;
    // Only a real change of what casts moves the frustum: each move shifts every shadow's texels.
    if (
      !fitted.isEmpty() &&
      Math.abs(box.min.x - fitted.min.x) < REFIT_BEYOND &&
      Math.abs(box.min.y - fitted.min.y) < REFIT_BEYOND &&
      Math.abs(box.min.z - fitted.min.z) < REFIT_BEYOND &&
      Math.abs(box.max.x - fitted.max.x) < REFIT_BEYOND &&
      Math.abs(box.max.y - fitted.max.y) < REFIT_BEYOND &&
      Math.abs(box.max.z - fitted.max.z) < REFIT_BEYOND
    ) {
      return;
    }
    fitted.copy(box);
    box.getSize(size);
    box.getCenter(centre);
    const reach = size.length() / 2;
    sun.target.position.copy(centre);
    sun.position.copy(centre).addScaledVector(SUN_FROM, reach * 2);
    const cam = sun.shadow.camera;
    cam.left = -reach;
    cam.right = reach;
    cam.top = reach;
    cam.bottom = -reach;
    cam.near = reach * 0.5;
    cam.far = reach * 3.5;
    cam.updateProjectionMatrix();
    invalidate();
  });
}
