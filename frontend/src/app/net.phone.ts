/**
 * The phone build's net.ts (angular.json "phone" fileReplacements; docs/phone.md): every API call
 * goes through the iroh tunnel to the user's PC (src/linkit_all/api/tunnel.py), end-to-end
 * encrypted. Kept on this phone: the PC's iroh id and relay (from the pairing link), this
 * phone's own iroh key (the PC ties the token to its id) and the token.
 */
import init, { newKey, Phone, Tunnel } from '../../tunnel/pkg/linkit_tunnel.js';

export interface EventsHandler {
  open(): void;
  message(event: unknown): void;
  closed(): void;
}

const PC = 'linkit-pc';
const TOKEN = 'linkit-token';
const KEY = 'linkit-key';
const CODE = 'linkit-code'; // sessionStorage: the one-time code until it is traded
const USED = 'linkit-code-used'; // the iPhone Home Screen copy reopens its pairing link each launch
const enc = new TextEncoder();
const dec = new TextDecoder();

interface Pc { pc: string; relay: string }

// The pairing link: https://linkit-all.github.io/app/#pc=<id>&code=<code>&relay=<url>. The PC
// part is kept; the one-time code stays in memory and the link leaves the address bar.
const link = new URLSearchParams(location.hash.slice(1));
const fresh = !!link.get('code') && link.get('code') !== localStorage.getItem(USED);
if (link.get('pc') && fresh) {
  localStorage.setItem(PC, JSON.stringify({ pc: link.get('pc'), relay: link.get('relay') ?? '' }));
  localStorage.removeItem(TOKEN); // a new pairing replaces the old one
  sessionStorage.setItem(CODE, link.get('code') ?? ''); // survives a reload of this tab
}
const code = sessionStorage.getItem(CODE) ?? '';
// a pending code: start on the pairing page (before any other page asks the PC for data).
// iPhone keeps the link in the address: its Home Screen copy opens with the address it was added from
const iphoneTab = /iPhone|iPad/.test(navigator.userAgent) && !(navigator as { standalone?: boolean }).standalone;
if (code && !localStorage.getItem(TOKEN)) {
  history.replaceState(null, '', new URL(`pair${iphoneTab ? location.hash : ''}`, document.baseURI));
} else if (location.hash) {
  history.replaceState(null, '', location.pathname);
}
if (!/iPhone|iPad/.test(navigator.userAgent)) {
  const manifest = document.createElement('link'); // Android: install prompt and push
  manifest.rel = 'manifest';
  manifest.href = 'manifest.webmanifest';
  document.head.append(manifest);
}

function savedPc(): Pc | null {
  try {
    return JSON.parse(localStorage.getItem(PC) ?? 'null') as Pc | null;
  } catch {
    return null;
  }
}

function phoneKey(): Uint8Array {
  const saved = localStorage.getItem(KEY);
  if (saved) return Uint8Array.from(atob(saved), (c) => c.charCodeAt(0));
  const key = newKey();
  localStorage.setItem(KEY, btoa(String.fromCharCode(...key)));
  return key;
}

const RETRY_MS = 5000; // after a failed dial, callers fail fast until then (no dial storm)
let phone: Promise<Phone> | null = null;
let tunnel: Promise<Tunnel> | null = null;
let failedAt = 0;

/** This page's one endpoint: made once, kept for the page's life (its relay link reconnects itself). */
function endpoint(): Promise<Phone> {
  phone ??= init({ module_or_path: new URL('tunnel/linkit_tunnel_bg.wasm', document.baseURI) })
    .then(() => Phone.bind(phoneKey()))
    .catch((e: unknown) => {
      phone = null;
      throw e;
    });
  return phone;
}

/** The open connection to the PC: one dial at a time, again only when it dropped. */
async function open(): Promise<Tunnel> {
  const pc = savedPc();
  if (!pc) throw new TypeError('This phone is not paired yet');
  if (tunnel) {
    const t = await tunnel.catch(() => null);
    if (t && !t.closed()) return t;
    if (tunnel && t?.closed()) tunnel = null;
  }
  if (!tunnel && Date.now() - failedAt < RETRY_MS) throw new TypeError('PC not reachable');
  tunnel ??= endpoint()
    .then((p) => p.dial(pc.pc, pc.relay || undefined) as Promise<Tunnel>)
    .catch((e: unknown) => {
      tunnel = null;
      failedAt = Date.now();
      throw new TypeError(`PC not reachable (${(e as Error)?.message ?? e})`); // like fetch's network error
    });
  return tunnel;
}

function frame(head: object, body: Uint8Array = new Uint8Array()): Uint8Array {
  const h = enc.encode(JSON.stringify(head));
  const out = new Uint8Array(4 + h.length + body.length);
  new DataView(out.buffer).setUint32(0, h.length);
  out.set(h, 4);
  out.set(body, 4 + h.length);
  return out;
}

function headers(init?: HeadersInit): [string, string][] {
  const out = [...new Headers(init).entries()];
  const token = localStorage.getItem(TOKEN);
  if (token) out.push(['authorization', `Bearer ${token}`]);
  return out;
}

export async function apiFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const path = new URL(url, location.origin).pathname + new URL(url, location.origin).search;
  const body = init.body == null ? new Uint8Array() : new Uint8Array(await new Response(init.body).arrayBuffer());
  const t = await open();
  const raw: Uint8Array = await t.send(frame({ method: init.method ?? 'GET', path, headers: headers(init.headers) }, body));
  const n = new DataView(raw.buffer, raw.byteOffset).getUint32(0);
  const head = JSON.parse(dec.decode(raw.subarray(4, 4 + n))) as { status: number; headers: [string, string][] };
  const content = [204, 304].includes(head.status) ? null : raw.slice(4 + n);
  return new Response(content, { status: head.status, headers: head.headers });
}

const blobs = new Map<string, Promise<string>>();

/** API files come through the tunnel too: as blob: URLs, made once per file. */
export function apiSrc(url: string): Promise<string> {
  let src = blobs.get(url);
  if (!src) {
    src = apiFetch(url).then(async (res) => (res.ok ? URL.createObjectURL(await res.blob()) : ''));
    blobs.set(url, src);
  }
  return src;
}

/** The live events as a stream through the tunnel; `closed` fires on every drop. */
export function openEvents(h: EventsHandler): void {
  if (!localStorage.getItem(TOKEN)) { // not paired (yet): nothing to watch; look again later
    setTimeout(() => h.closed(), 0);
    return;
  }
  void (async () => {
    try {
      const t = await open();
      const messages = await t.stream(frame({ method: 'GET', path: '/api/events', stream: true, headers: headers() }));
      const first = await messages.next();
      const head = first ? (JSON.parse(dec.decode(first)) as { status: number }) : { status: 0 };
      if (head.status !== 200) {
        messages.close();
        if (head.status === 401 && !location.pathname.endsWith('/pair')) {
          localStorage.removeItem(TOKEN); // unpaired on the PC
          location.assign(new URL('pair', document.baseURI));
        }
        return h.closed();
      }
      h.open();
      for (let m = await messages.next(); m; m = await messages.next()) h.message(JSON.parse(dec.decode(m)));
    } catch {
      // the PC went away: closed() below, the caller dials again
    }
    h.closed();
  })();
}

export function savePairing(token: string): void {
  localStorage.setItem(TOKEN, token);
  localStorage.setItem(USED, code);
  sessionStorage.removeItem(CODE);
}

export function pendingCode(): string {
  return localStorage.getItem(TOKEN) ? '' : code;
}

export function hasPc(): boolean {
  return savedPc() !== null;
}
