# iroh phone tunnel spike: findings (2026-11-27)

Browser page (Rust -> WASM, iroh 1.5) <-> iroh relay <-> PC (Python iroh 1.2 wheel, `bridge.py`)
<-> LinKit on 127.0.0.1. Tested in the desktop app's browser pane against a scratch data folder.

## Works
- Pairing through the tunnel: `POST /api/phone/claim` -> 200, device token kept in localStorage,
  survives reloads. LocalOnly treats bridged calls as remote (Host `linkit.iroh` + x-forwarded-for),
  so the device check and the phone limits apply with no change.
- The PC keeps one iroh id across restarts (secret key file), so a pairing link stays valid.

## Numbers (PC on home internet, n0 relay euc1-1 Frankfurt)
| Step | Time |
|---|---|
| WASM load (2.0 MB raw, 0.86 MB gzip, no wasm-opt yet) | ~40 ms from cache |
| Tunnel open, dialing at once (first try) | ~22 s |
| Tunnel open, after `endpoint.online()` | ~2.5 s (own relay 2.2 s, dial 0.3 s) |
| Tunnel open, relay URL in the link too | ~1.1 s (own relay 0.9 s, dial 0.14 s) |
| One API call through the relay | 150-350 ms (server time 5-80 ms of that) |

Fixes to keep: wait for `online()` before `connect()`; put the PC's relay URL in the pairing link
(falls back to lookup if the PC's home relay changes).

## Build notes
- `ring` needs clang for wasm32: CC/AR_wasm32_unknown_unknown -> LLVM (D:\LLVM here; CI: ubuntu clang).
- wasm-opt fails with default flags; needs --enable-bulk-memory --enable-nontrapping-float-to-int.
- Rust crate pulls iroh 1.5, the PC wheel is 1.2: interoperate fine.

## Not yet tested
1. A real iPhone (Safari + Home Screen copy keeping the token) and Android Chrome: needs the page on
   HTTPS (GitHub Pages).
2. `/api/events` WebSocket as one long stream; the live screenshot view through the relay.
3. Web push from the github.io origin.

## Risks found
- GitHub Pages: every project site of one account shares the origin `<user>.github.io`, so any other
  Pages site of that account could read the device token. The phone app needs its own origin
  (custom domain or a dedicated account/org site).
- All phone traffic rides n0's free relays (browsers can't hole-punch); self-hosted relay is the fallback.
