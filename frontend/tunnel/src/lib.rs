//! The phone web app's end of the iroh tunnel to the user's PC (src/linkit_all/api/tunnel.py).
//!
//! Browsers can't send UDP, so this always goes through an iroh relay; the connection is still
//! end-to-end encrypted between the phone and the PC. The phone keeps one iroh key (the app
//! stores it), because the PC ties each paired phone's token to that key's id.
//!
//! Wire format, ALPN `linkit/http/1`, one bidirectional stream per request:
//!   request  = u32 length + JSON head + body, then finish
//!   response = u32 length + JSON head + body
//! A streamed request (/api/events) answers with u32-length-prefixed JSON messages instead.

use std::cell::RefCell;
use std::rc::Rc;

use iroh::endpoint::{Connection, RecvStream};
use iroh::{Endpoint, EndpointAddr, EndpointId, RelayUrl, SecretKey};
use wasm_bindgen::prelude::*;

const ALPN: &[u8] = b"linkit/http/1";
const MAX_BODY: usize = 16 * 1024 * 1024;
const MAX_MESSAGE: usize = 4 * 1024 * 1024;

#[wasm_bindgen(start)]
fn start() {
    console_error_panic_hook::set_once();
}

/// A new phone key (32 bytes) for the app to keep.
#[wasm_bindgen(js_name = newKey)]
pub fn new_key() -> Vec<u8> {
    SecretKey::generate().to_bytes().to_vec()
}

#[wasm_bindgen]
pub struct Tunnel {
    endpoint: Endpoint,
    conn: Connection,
}

#[wasm_bindgen]
impl Tunnel {
    /// Dial the PC by its iroh id with the phone's own key; `relay` (from the pairing link)
    /// skips the address lookup. Waits for this phone's relay first: dialing before it is up
    /// stalled ~20 s in the spike.
    pub async fn connect(pc: String, relay: Option<String>, key: Vec<u8>) -> Result<Tunnel, JsError> {
        let id: EndpointId = pc.parse().map_err(js)?;
        let key: [u8; 32] = key.try_into().map_err(|_| JsError::new("bad phone key"))?;
        let mut addr = EndpointAddr::new(id);
        if let Some(url) = relay.filter(|u| !u.is_empty()) {
            addr = addr.with_relay_url(url.parse::<RelayUrl>().map_err(js)?);
        }
        let endpoint = Endpoint::builder(iroh::endpoint::presets::N0)
            .secret_key(SecretKey::from_bytes(&key))
            .bind()
            .await
            .map_err(js)?;
        endpoint.online().await;
        let conn = endpoint.connect(addr, ALPN).await.map_err(js)?;
        Ok(Tunnel { endpoint, conn })
    }

    /// This phone's iroh id (what the PC ties the token to).
    pub fn id(&self) -> String {
        self.endpoint.id().to_string()
    }

    /// One request frame in, one response frame out.
    pub fn send(&self, frame: Vec<u8>) -> js_sys::Promise {
        let conn = self.conn.clone();
        wasm_bindgen_futures::future_to_promise(async move {
            let (mut tx, mut rx) = conn.open_bi().await.map_err(js)?;
            tx.write_all(&frame).await.map_err(js)?;
            tx.finish().map_err(js)?;
            let out = rx.read_to_end(MAX_BODY).await.map_err(js)?;
            Ok(js_sys::Uint8Array::from(out.as_slice()).into())
        })
    }

    /// Open a streamed request (the live events); read it with `Messages.next()`.
    pub async fn stream(&self, frame: Vec<u8>) -> Result<Messages, JsError> {
        let (mut tx, rx) = self.conn.open_bi().await.map_err(js)?;
        tx.write_all(&frame).await.map_err(js)?;
        tx.finish().map_err(js)?;
        Ok(Messages(Rc::new(RefCell::new(Some(rx)))))
    }

    /// True once the PC went away (asleep, closed, network change): the app dials again.
    pub fn closed(&self) -> bool {
        self.conn.close_reason().is_some()
    }

    pub fn close(&self) {
        self.conn.close(0u8.into(), b"bye");
    }
}

#[wasm_bindgen]
pub struct Messages(Rc<RefCell<Option<RecvStream>>>);

#[wasm_bindgen]
impl Messages {
    /// The next JSON message as bytes, or undefined when the stream ended.
    /// Call it again only after the previous call settled.
    pub fn next(&self) -> js_sys::Promise {
        let slot = self.0.clone();
        wasm_bindgen_futures::future_to_promise(async move {
            let Some(mut rx) = slot.borrow_mut().take() else {
                return Ok(JsValue::UNDEFINED);
            };
            let mut len = [0u8; 4];
            if rx.read_exact(&mut len).await.is_err() {
                return Ok(JsValue::UNDEFINED); // finished or reset: the stream is over
            }
            let n = u32::from_be_bytes(len) as usize;
            if n > MAX_MESSAGE {
                return Err(JsError::new("message too large").into());
            }
            let mut buf = vec![0u8; n];
            rx.read_exact(&mut buf).await.map_err(js)?;
            *slot.borrow_mut() = Some(rx);
            Ok(js_sys::Uint8Array::from(buf.as_slice()).into())
        })
    }

    pub fn close(&self) {
        if let Some(mut rx) = self.0.borrow_mut().take() {
            rx.stop(0u8.into()).ok();
        }
    }
}

fn js(err: impl std::fmt::Display) -> JsError {
    JsError::new(&err.to_string())
}
