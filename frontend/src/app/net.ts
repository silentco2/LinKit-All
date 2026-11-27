/**
 * How the app reaches its API. This is the PC build: the local server, by fetch and WebSocket.
 * The phone build (angular.json "phone", served at linkit-all.github.io/app/) replaces this file
 * with net.phone.ts, which carries the same calls through the iroh tunnel (docs/phone.md).
 */

/** fetch() for `/api/...` paths. */
export function apiFetch(url: string, init?: RequestInit): Promise<Response> {
  return fetch(url, init);
}

/** A URL an <img> or <a> can use for an API file (a screenshot, a CV PDF). */
export async function apiSrc(url: string): Promise<string> {
  return url;
}

export interface EventsHandler {
  open(): void;
  message(event: unknown): void;
  closed(): void;
}

/** The live events (WebSocket /api/events): `closed` fires on every drop; the caller reconnects. */
export function openEvents(h: EventsHandler): void {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const socket = new WebSocket(`${proto}://${location.host}/api/events`);
  socket.onopen = () => h.open();
  socket.onclose = () => h.closed();
  socket.onmessage = (msg) => h.message(JSON.parse(msg.data));
}

/** The phone keeps its token after pairing; the PC has none. */
export function savePairing(_token: string): void {}

/** The one-time code from the pairing link (phone only). */
export function pendingCode(): string {
  return '';
}

/** True when this phone has a PC to talk to (phone only). */
export function hasPc(): boolean {
  return true;
}
