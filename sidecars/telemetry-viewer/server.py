#!/usr/bin/env python3
# Copyright 2026 Alexey Guseynov (kibergus). All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

"""Zero-dependency Antigravity Telemetry Viewer Companion Server in pure Python standard library.

Serves the auxiliary web panel and provides a local WebSocket event bridge on port 38472.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import struct
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote, urlparse

DEFAULT_PORT = 38472
UI_PORT = int(os.environ.get('ANTIGRAVITY_SIDECAR_WEB_PORT', DEFAULT_PORT))
WS_PORT = DEFAULT_PORT
API_KEY = os.environ.get('BRBRDB_API_KEY', '').strip()
TARGET_HOST = os.environ.get('BRBRDB_HOST', 'brbrdb.brbrkitten.com').strip()
LOG_FILE = '/tmp/telemetry_companion.log'

ws_clients: set[asyncio.StreamWriter] = set()
latest_action: dict = {'type': 'telemetry_jump', 'dist': 0, 'timestamp': datetime.now(timezone.utc).isoformat()}
current_telemetry_path = (
    f"/telemetry/kartsim/iame_waterswift_restricted_cadet_uk/2026-11-04/Whilton%20Mill%20Zulu"
    f"?tab=map&lapsA=20_06_practice-28%2C20_06_practice-20&visA=1&turn=4&dist=654.4&delta=1&speed=1"
    f"&rtab=report&companion=1&ws_port={WS_PORT}"
)


def ensure_companion_params(path: str) -> str:
    if not path:
        return path
    res = path
    if 'companion=' not in res:
        sep = '&' if '?' in res else '?'
        res = f"{res}{sep}companion=1"
    if 'ws_port=' not in res:
        sep = '&' if '?' in res else '?'
        res = f"{res}{sep}ws_port={WS_PORT}"
    return res


def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}\n"
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line)
    except OSError:
        pass
    print(msg, flush=True)


def encode_text_frame(message: str) -> bytes:
    """Encode an RFC 6455 unmasked text frame (Server -> Client)."""
    payload = message.encode('utf-8')
    length = len(payload)
    if length < 126:
        header = bytes([0x81, length])
    elif length <= 65535:
        header = struct.pack('!BBH', 0x81, 126, length)
    else:
        header = struct.pack('!BBQ', 0x81, 127, length)
    return header + payload


async def broadcast(message_dict: dict) -> int:
    """Broadcast JSON payload to all active WebSocket clients."""
    frame = encode_text_frame(json.dumps(message_dict))
    dead_clients = set()
    sent_count = 0
    for writer in list(ws_clients):
        try:
            if not writer.is_closing():
                writer.write(frame)
                await writer.drain()
                sent_count += 1
            else:
                dead_clients.add(writer)
        except (OSError, ConnectionResetError):
            dead_clients.add(writer)

    for dead in dead_clients:
        ws_clients.discard(dead)
    return sent_count


async def handle_websocket(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, key: str) -> None:
    """Handle RFC 6455 WebSocket connection."""
    guid = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
    accept_val = base64.b64encode(hashlib.sha1((key + guid).encode('utf-8')).digest()).decode('ascii')

    handshake_resp = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept_val}\r\n\r\n"
    )
    writer.write(handshake_resp.encode('utf-8'))
    await writer.drain()

    ws_clients.add(writer)
    log(f"Viewer connected to companion WebSocket (active clients: {len(ws_clients)})")

    # Send COMPANION_READY
    ready_frame = encode_text_frame(json.dumps({'type': 'COMPANION_READY', 'port': WS_PORT}))
    writer.write(ready_frame)
    await writer.drain()

    try:
        while True:
            header = await reader.readexactly(2)
            b0, b1 = header[0], header[1]
            opcode = b0 & 0x0F
            is_masked = bool(b1 & 0x80)
            payload_len = b1 & 0x7F

            if payload_len == 126:
                ext_len = await reader.readexactly(2)
                payload_len = struct.unpack('!H', ext_len)[0]
            elif payload_len == 127:
                ext_len = await reader.readexactly(8)
                payload_len = struct.unpack('!Q', ext_len)[0]

            mask_key = await reader.readexactly(4) if is_masked else b''
            payload = await reader.readexactly(payload_len) if payload_len > 0 else b''

            if is_masked and payload:
                unmasked = bytearray(payload_len)
                for i in range(payload_len):
                    unmasked[i] = payload[i] ^ mask_key[i % 4]
                payload = bytes(unmasked)

            if opcode == 0x8:  # Close
                writer.write(bytes([0x88, 0x00]))
                await writer.drain()
                break
            elif opcode == 0x9:  # Ping -> Pong (0x8A)
                pong = bytes([0x8A, len(payload)]) + payload
                writer.write(pong)
                await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
        pass
    finally:
        ws_clients.discard(writer)
        log(f"Viewer disconnected from companion WebSocket (remaining: {len(ws_clients)})")
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def handle_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Handle incoming HTTP or WebSocket connection."""
    global current_telemetry_path, latest_action
    try:
        header_data = bytearray()
        while b'\r\n\r\n' not in header_data:
            chunk = await reader.read(4096)
            if not chunk:
                break
            header_data.extend(chunk)
            if len(header_data) > 65536:
                break

        if not header_data:
            writer.close()
            await writer.wait_closed()
            return

        split_pos = header_data.find(b'\r\n\r\n')
        raw_headers = bytes(header_data[:split_pos]).decode('utf-8', errors='replace')
        initial_body = bytes(header_data[split_pos + 4:])

        lines = raw_headers.split('\r\n')
        if not lines:
            writer.close()
            await writer.wait_closed()
            return

        req_line = lines[0].split()
        if len(req_line) < 2:
            writer.close()
            await writer.wait_closed()
            return

        method, raw_path = req_line[0].upper(), req_line[1]
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ':' in line:
                k, v = line.split(':', 1)
                headers[k.strip().lower()] = v.strip()

        # Check for WebSocket Upgrade
        if headers.get('upgrade', '').lower() == 'websocket':
            ws_key = headers.get('sec-websocket-key')
            if ws_key:
                await handle_websocket(reader, writer, ws_key)
                return

        parsed = urlparse(raw_path)
        path = parsed.path

        # CORS preflight
        if method == 'OPTIONS':
            resp = (
                "HTTP/1.1 204 No Content\r\n"
                "Access-Control-Allow-Origin: *\r\n"
                "Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
                "Access-Control-Allow-Headers: Content-Type, Authorization, X-Requested-With\r\n"
                "Content-Length: 0\r\n\r\n"
            )
            writer.write(resp.encode('utf-8'))
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return

        # Companion action dispatch API
        if path == '/api/action':
            if method == 'POST':
                content_length = int(headers.get('content-length', 0))
                body_bytes = bytearray(initial_body)
                while len(body_bytes) < content_length:
                    more = await reader.read(content_length - len(body_bytes))
                    if not more:
                        break
                    body_bytes.extend(more)

                try:
                    payload = json.loads(bytes(body_bytes).decode('utf-8') or '{}')
                    if payload.get('url'):
                        current_telemetry_path = ensure_companion_params(payload['url'])
                    if 'type' not in payload:
                        payload['type'] = 'telemetry_jump'
                    payload['timestamp'] = datetime.now(timezone.utc).isoformat()
                    latest_action = payload

                    log(f"Dispatched action: {json.dumps(payload)} to {len(ws_clients)} viewer client(s)")
                    sent = await broadcast(payload)

                    resp_body = json.dumps({'ok': True, 'sentTo': sent, 'action': payload}).encode('utf-8')
                    resp = (
                        "HTTP/1.1 200 OK\r\n"
                        "Content-Type: application/json\r\n"
                        "Access-Control-Allow-Origin: *\r\n"
                        f"Content-Length: {len(resp_body)}\r\n\r\n"
                    ).encode('utf-8') + resp_body
                except Exception as err:
                    err_body = json.dumps({'error': str(err)}).encode('utf-8')
                    resp = (
                        "HTTP/1.1 400 Bad Request\r\n"
                        "Content-Type: application/json\r\n"
                        "Access-Control-Allow-Origin: *\r\n"
                        f"Content-Length: {len(err_body)}\r\n\r\n"
                    ).encode('utf-8') + err_body

                writer.write(resp)
                await writer.drain()
                writer.close()
                await writer.wait_closed()
                return
            else:
                resp_dict = {'latestAction': latest_action, 'clientsConnected': len(ws_clients)}
                resp_body = json.dumps(resp_dict).encode('utf-8')
                resp = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    "Access-Control-Allow-Origin: *\r\n"
                    f"Content-Length: {len(resp_body)}\r\n\r\n"
                ).encode('utf-8') + resp_body
                writer.write(resp)
                await writer.drain()
                writer.close()
                await writer.wait_closed()
                return

        # Health status
        if path in ('/healthz', '/api/status'):
            resp_body = json.dumps({
                'status': 'ok',
                'clientsConnected': len(ws_clients),
                'uiPort': UI_PORT,
                'wsPort': WS_PORT
            }).encode('utf-8')
            resp = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json\r\n"
                "Access-Control-Allow-Origin: *\r\n"
                f"Content-Length: {len(resp_body)}\r\n\r\n"
            ).encode('utf-8') + resp_body
            writer.write(resp)
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return

        # Default route serves HTML wrapper with iframe
        query_params = parse_qs(parsed.query)
        raw_path = (
            query_params.get('url', [None])[0]
            or query_params.get('next', [None])[0]
            or current_telemetry_path
        )
        telemetry_path = ensure_companion_params(raw_path)
        if API_KEY:
            auth_target = f"https://{TARGET_HOST}/auth?key={quote(API_KEY)}&next={quote(telemetry_path)}"
        else:
            auth_target = f"https://{TARGET_HOST}/auth?next={quote(telemetry_path)}"

        wrapper_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Telemetry Viewer</title>
  <style>
    html, body {{ margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: #0b0f19; }}
    iframe {{ width: 100%; height: 100%; border: none; display: block; }}
  </style>
</head>
<body>
  <iframe id="viewer" src="{auth_target}" allow="clipboard-read; clipboard-write; microphone; fullscreen"></iframe>
  <script>
    window.addEventListener('message', (e) => {{
      const f = document.getElementById('viewer');
      if (f && f.contentWindow) {{
        try {{ f.contentWindow.postMessage(e.data, '*'); }} catch (_) {{}}
      }}
    }});
  </script>
</body>
</html>"""
        html_bytes = wrapper_html.encode('utf-8')
        resp = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            "Access-Control-Allow-Origin: *\r\n"
            "Cache-Control: no-cache\r\n"
            f"Content-Length: {len(html_bytes)}\r\n\r\n"
        ).encode('utf-8') + html_bytes
        writer.write(resp)
        await writer.drain()
        writer.close()
        await writer.wait_closed()
    except Exception as exc:
        log(f"Connection error: {exc}")
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def main() -> None:
    log(f"Telemetry Companion (Pure Python Zero-Dep) starting... UI_PORT={UI_PORT}, WS_PORT={WS_PORT}")

    server_ui = await asyncio.start_server(handle_connection, '127.0.0.1', UI_PORT)
    log(f"UI Server listening on http://127.0.0.1:{UI_PORT}")

    if UI_PORT != WS_PORT:
        server_ws = await asyncio.start_server(handle_connection, '127.0.0.1', WS_PORT)
        log(f"WS HTTP Server listening on http://127.0.0.1:{WS_PORT}")
        async with server_ui, server_ws:
            await asyncio.gather(server_ui.serve_forever(), server_ws.serve_forever())
    else:
        async with server_ui:
            await server_ui.serve_forever()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
