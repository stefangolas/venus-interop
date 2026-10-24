// What a link asks of the page, beyond the angle it opens at (`?view=`, read in renderer.js).
// `Viewer3D(overlays=False, hover=False)` puts these in the link it prints and opens.

const asked = new URLSearchParams(globalThis.location?.search ?? "");

// `?bare=1`: all three below off at once - the models on a plain background and nothing else.
const BARE = asked.get("bare") === "1";

// `?overlays=0`: the resources and nothing else. No floor grid, origin triad, rail numbers,
// reference or grip marks, box outlines, channel halos, axis gizmo, scale bar or statistics, and a device's
// panels are not opened when it arrives (its navbar buttons still open them).
export const OVERLAYS = !BARE && asked.get("overlays") !== "0";

// `?ui=0`: the canvas and nothing around it. No navbar, tool rails, tree, zoom or home buttons,
// panels or readouts; the view fills the window and is driven by mouse alone. A page that cannot
// draw still says why.
export const UI = !BARE && asked.get("ui") !== "0";

// `?hover=0`: pointing at a resource, in the viewport or the tree, neither outlines it nor shows
// its readout; the scene is not raycast on every pointer move either. Clicking still selects.
// `?camera=fx,fy,fz,ax,ay,az`: where the view opens, and where Home goes back to - the camera at
// (fx, fy, fz) looking at (ax, ay, az), in the facility's millimetres, under perspective. Without
// it the view frames the whole scene from the front left.
const cameraAsked = (asked.get("camera") ?? "").split(",").map(Number);
export const START_CAMERA =
  cameraAsked.length === 6 && cameraAsked.every(Number.isFinite)
    ? { from: cameraAsked.slice(0, 3), at: cameraAsked.slice(3) }
    : null;

// `?light=0.8`: every light and the reflections scaled by this, from 1 as the page is lit by
// default. Metal and near-white surfaces are the first to reach pure white; below 1 they keep
// their shading.
const lightAsked = Number(asked.get("light"));
export const LIGHT = Number.isFinite(lightAsked) && lightAsked > 0 ? lightAsked : 1;

export const HOVER_HIGHLIGHT = !BARE && asked.get("hover") !== "0";

// `?look=real`: lit as a room is rather than as a drawing - a light fixed in the world that casts
// soft shadows, the camera's own lights kept as a fill, and tone mapping (look.js). The default,
// technical look lights every surface from the camera, so a face reads the same from any side.
export const LOOK_REAL = asked.get("look") === "real";
