// Static replay transport. This module never opens a WebSocket.
import { startReplay } from './replay.js';
let handlers;
export function initTransport(deps) { handlers = deps.handlers; }
export function send() {}
let started = false;
export function connect() {
  if (started) return;
  started = true;
  startReplay(handlers).catch(error => {
    document.getElementById('status-label').textContent = `Replay error: ${error.message}`;
    console.error(error);
  });
}
