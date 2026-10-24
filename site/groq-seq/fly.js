// WASD flying: the camera and the point it orbits move together, so the view is carried rather than
// turned. W/S forward and back along the view (a zoom in an orthographic one, where moving forward
// changes nothing on screen), A/D sideways, E/Q up and down in Z, Shift for four times the speed.

import * as THREE from "three";

import { invalidate } from "./frame.js";
import { camera, controls, dolly, mmPerPixel, projection, viewportEl } from "./renderer.js";

// Of what the viewport shows top to bottom, how much a second of holding a key crosses. Measured
// against the view, so it is as quick to cross a deck up close as a facility from afar.
const VIEWS_PER_SECOND = 0.6;

const SHIFT_FACTOR = 4;

// An orthographic view zooms by this factor a second while W or S is held.
const ZOOM_PER_SECOND = 2.5;

const KEYS = new Set(["KeyW", "KeyA", "KeyS", "KeyD", "KeyQ", "KeyE"]);

const held = new Set();

let fast = false;

/** Whether a key press is meant for a field rather than the view. */
function typing(event) {
  const target = /** @type {HTMLElement} */ (event.target);
  return target?.isContentEditable || ["INPUT", "SELECT", "TEXTAREA"].includes(target?.tagName);
}

document.addEventListener("keydown", (event) => {
  fast = event.shiftKey;
  if (!KEYS.has(event.code) || event.ctrlKey || event.metaKey || event.altKey || typing(event)) {
    return;
  }
  event.preventDefault();
  held.add(event.code);
  invalidate();
});

document.addEventListener("keyup", (event) => {
  fast = event.shiftKey;
  held.delete(event.code);
});

// A key let go while the page is not looking would be held for good.
window.addEventListener("blur", () => held.clear());

const _forward = new THREE.Vector3();

const _right = new THREE.Vector3();

const _step = new THREE.Vector3();

const UP = new THREE.Vector3(0, 0, 1); // PLR is Z-up

/** Move the view for the keys held, over `delta` seconds; whether any still are. */
export function stepFly(delta) {
  if (held.size === 0) return false;
  const perPixel = mmPerPixel();
  if (!Number.isFinite(perPixel) || perPixel <= 0) return true;
  const speed = fast ? SHIFT_FACTOR : 1;
  const distance = perPixel * viewportEl.clientHeight * VIEWS_PER_SECOND * speed * delta;
  const along = (plus, minus) => (held.has(plus) ? 1 : 0) - (held.has(minus) ? 1 : 0);

  camera.getWorldDirection(_forward);
  // The camera's own right, which is there even looking straight down, where forward x up is not.
  _right.setFromMatrixColumn(camera.matrixWorld, 0);
  _step.set(0, 0, 0);
  const forward = along("KeyW", "KeyS");
  if (projection === "orthographic") {
    if (forward !== 0) dolly(ZOOM_PER_SECOND ** (-forward * speed * delta));
  } else {
    _step.addScaledVector(_forward, forward * distance);
  }
  _step.addScaledVector(_right, along("KeyD", "KeyA") * distance);
  _step.addScaledVector(UP, along("KeyE", "KeyQ") * distance);
  camera.position.add(_step);
  controls.target.add(_step);
  return true;
}
