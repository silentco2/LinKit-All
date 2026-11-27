//! Spike: the phone web app's side of the iroh tunnel to the user's PC (see ../bridge.py).
//! Browsers can't send UDP, so this always goes through an iroh relay, end-to-end encrypted.

use iroh::{Endpoint, EndpointAddr, EndpointId, RelayUrl, endpoint::Connection};
use wasm_bindgen::prelude::*;

const ALPN: &[u8] = b"linkit/http/1";
const MAX_BODY: usize = 16 * 1024 * 1024;

#[wasm_bindgen(start)]
fn start() {
    console_error_panic_hook::set_once();
}

#[wasm_bindgen]
pub struct Tunnel {
    _endpoint: Endpoint,
    conn: Connection,
    timings: String,
}

#[wasm_bindgen]
impl Tunnel {
    /// Dial the PC by its iroh id; `relay` (from the pairing link) skips the address lookup.
    pub async fn connect(pc: String, relay: Option<String>) -> Result<Tunnel, JsError> {
        let id: EndpointId = pc.parse().map_err(js)?;
        let mut addr = EndpointAddr::new(id);
        if let Some(url) = relay.filter(|u| !u.is_empty()) {
            addr = addr.with_relay_url(url.parse::<RelayUrl>().map_err(js)?);
        }
        let t0 = js_sys::Date::now();
        let endpoint = Endpoint::builder(iroh::endpoint::presets::N0)
            .bind()
            .await
            .map_err(js)?;
        let t1 = js_sys::Date::now();
        endpoint.online().await;
        let t2 = js_sys::Date::now();
        let conn = endpoint.connect(addr, ALPN).await.map_err(js)?;
        let t3 = js_sys::Date::now();
        let timings = format!("bind {:.0} ms, own relay {:.0} ms, dial PC {:.0} ms", t1 - t0, t2 - t1, t3 - t2);
        Ok(Tunnel { _endpoint: endpoint, conn, timings })
    }

    pub fn timings(&self) -> String {
        self.timings.clone()
    }

    /// One request frame in (u32 length + JSON head + body), one response frame out.
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
}

fn js(err: impl std::fmt::Display) -> JsError {
    JsError::new(&err.to_string())
}
