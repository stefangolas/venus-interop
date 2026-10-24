// Presentation timing leaves the recorded request and drive speeds unchanged.
export function playbackRequest(request, pauseScale = 1) {
  const scale = Number.isFinite(pauseScale) && pauseScale >= 0 ? pauseScale : 1;
  const paired = new Set(["core_tool_pickup", "core_tool_return", "core_grip", "core_move", "core_release"]);
  return {
    ...request,
    fixed: (request.fixed ?? 0) * scale,
    dwell: (request.dwell ?? 0) * scale,
    drives: paired.has(request.kind)
      ? { ...request.drives, y: { ...request.drives?.y, stagger: 0 } }
      : request.drives,
  };
}
