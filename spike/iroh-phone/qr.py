"""Spike: keep a fresh pairing QR code on screen for the phone test (codes last 5 minutes).

    python spike/iroh-phone/qr.py --port 8772 --pc <pc id> --relay <relay url>

Writes public/qr.html + public/qr.png every 4 minutes; open http://localhost:8773/qr.html.
"""

import argparse
import time
from pathlib import Path
from urllib.parse import quote

import httpx
import segno

OUT = Path(__file__).parent / "public"
PAGE = "https://linkit-all.github.io/"

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True)
ap.add_argument("--pc", required=True)
ap.add_argument("--relay", required=True)
args = ap.parse_args()
app = f"http://127.0.0.1:{args.port}"

while True:
    code = httpx.post(f"{app}/api/phone/pair", headers={"origin": app}).json()["code"]
    link = f"{PAGE}#pc={args.pc}&code={code}&relay={quote(args.relay, safe='')}"
    segno.make(link, error="m").save(OUT / "qr.png", scale=8, border=3)
    (OUT / "qr.html").write_text(
        '<!doctype html><meta http-equiv="refresh" content="20"><title>Pair your phone</title>'
        '<body style="font:18px system-ui;text-align:center;background:#e5e2db">'
        "<h1>Scan with your phone's camera</h1>"
        f'<img src="qr.png?{code}" alt="Pairing QR code">'
        f"<p>Code {code}, renewed every 4 minutes</p>",
        "utf-8",
    )
    print("new code", code, flush=True)
    time.sleep(240)
