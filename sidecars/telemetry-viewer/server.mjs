/*
 * Copyright 2026 Alexey Guseynov (kibergus). All Rights Reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 * ==============================================================================
 */

import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';

const DEFAULT_PORT = 38472;
const UI_PORT = parseInt(process.env.ANTIGRAVITY_SIDECAR_WEB_PORT || DEFAULT_PORT, 10);
const WS_PORT = DEFAULT_PORT;
const API_KEY = process.env.BRBRDB_API_KEY || '';
const TARGET_HOST = process.env.BRBRDB_HOST || 'brbrdb.brbrkitten.com';
const LOG_FILE = path.join(os.tmpdir(), 'telemetry_companion.log');

function log(msg) {
  const line = `[${new Date().toISOString()}] ${msg}\n`;
  try { fs.appendFileSync(LOG_FILE, line); } catch {}
  console.log(msg);
}

log(`Telemetry Companion (Pure Node Zero-Dep) starting... UI_PORT=${UI_PORT}, WS_PORT=${WS_PORT}`);

const wsClients = new Set();
let latestAction = { type: 'telemetry_jump', dist: 0, timestamp: new Date().toISOString() };
let currentTelemetryPath = `/telemetry/kartsim/iame_waterswift_restricted_cadet_uk/2026-11-04/Whilton%20Mill%20Zulu?tab=map&lapsA=20_06_practice-28%2C20_06_practice-20&visA=1&turn=4&dist=654.4&delta=1&speed=1&rtab=report&companion=1&ws_port=${WS_PORT}`;

function ensureCompanionParams(path) {
  if (!path) return path;
  let res = path;
  if (!res.includes('companion=')) {
    const sep = res.includes('?') ? '&' : '?';
    res = `${res}${sep}companion=1`;
  }
  if (!res.includes('ws_port=')) {
    const sep = res.includes('?') ? '&' : '?';
    res = `${res}${sep}ws_port=${WS_PORT}`;
  }
  return res;
}

// Zero-dependency RFC 6455 text frame encoder (Server -> Client is unmasked)
function encodeTextFrame(str) {
  const payload = Buffer.from(str, 'utf8');
  const len = payload.length;
  let header;
  if (len < 126) {
    header = Buffer.from([0x81, len]);
  } else if (len <= 65535) {
    header = Buffer.alloc(4);
    header[0] = 0x81;
    header[1] = 126;
    header.writeUInt16BE(len, 2);
  } else {
    header = Buffer.alloc(10);
    header[0] = 0x81;
    header[1] = 127;
    header.writeBigUInt64BE(BigInt(len), 2);
  }
  return Buffer.concat([header, payload]);
}

// Zero-dependency RFC 6455 WebSocket upgrade handler
function handleWebSocketUpgrade(req, socket, head) {
  const upgradeHeader = req.headers['upgrade'];
  if (!upgradeHeader || upgradeHeader.toLowerCase() !== 'websocket') {
    socket.destroy();
    return;
  }
  const key = req.headers['sec-websocket-key'];
  if (!key) {
    socket.destroy();
    return;
  }

  const GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';
  const accept = crypto.createHash('sha1').update(key + GUID).digest('base64');
  socket.write(
    'HTTP/1.1 101 Switching Protocols\r\n' +
    'Upgrade: websocket\r\n' +
    'Connection: Upgrade\r\n' +
    `Sec-WebSocket-Accept: ${accept}\r\n\r\n`
  );

  wsClients.add(socket);
  log(`Viewer connected to companion WebSocket (active clients: ${wsClients.size})`);

  // Send COMPANION_READY frame
  const readyFrame = encodeTextFrame(JSON.stringify({ type: 'COMPANION_READY', port: WS_PORT }));
  socket.write(readyFrame);

  socket.on('data', (chunk) => {
    if (chunk.length < 2) return;
    const opcode = chunk[0] & 0x0f;
    if (opcode === 0x8) {
      // Close frame
      try { socket.write(Buffer.from([0x88, 0x00])); } catch {}
      socket.end();
      return;
    }
    if (opcode === 0x9) {
      // Ping frame -> Pong (0x8A)
      const isMasked = (chunk[1] & 0x80) !== 0;
      const payloadLen = chunk[1] & 0x7f;
      const payloadOffset = isMasked ? 6 : 2;
      const payload = chunk.subarray(payloadOffset, payloadOffset + payloadLen);
      try { socket.write(Buffer.concat([Buffer.from([0x8a, payload.length]), payload])); } catch {}
      return;
    }
  });

  const cleanup = () => {
    if (wsClients.has(socket)) {
      wsClients.delete(socket);
      log(`Viewer disconnected from companion WebSocket (remaining: ${wsClients.size})`);
    }
  };
  socket.on('close', cleanup);
  socket.on('end', cleanup);
  socket.on('error', cleanup);
}

function createHttpHandler() {
  return (clientReq, clientRes) => {
    let reqUrl = clientReq.url;
    const parsedUrl = new URL(reqUrl, `http://localhost:${UI_PORT}`);

    // CORS preflight
    if (clientReq.method === 'OPTIONS') {
      clientRes.writeHead(204, {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With',
      });
      clientRes.end();
      return;
    }

    // Companion action dispatch API
    if (parsedUrl.pathname === '/api/action') {
      if (clientReq.method === 'POST') {
        let body = '';
        clientReq.on('data', chunk => body += chunk);
        clientReq.on('end', () => {
          try {
            const payload = JSON.parse(body || '{}');
            if (payload.url) {
              currentTelemetryPath = ensureCompanionParams(payload.url);
            }
            if (!payload.type) payload.type = 'telemetry_jump';
            payload.timestamp = new Date().toISOString();
            latestAction = payload;

            log(`Dispatched action: ${JSON.stringify(payload)} to ${wsClients.size} viewer client(s)`);

            const frame = encodeTextFrame(JSON.stringify(payload));
            let sentCount = 0;
            for (const client of wsClients) {
              try {
                if (!client.destroyed && client.writable) {
                  client.write(frame);
                  sentCount++;
                }
              } catch {}
            }

            clientRes.writeHead(200, {
              'Content-Type': 'application/json',
              'Access-Control-Allow-Origin': '*',
            });
            clientRes.end(JSON.stringify({ ok: true, sentTo: sentCount, action: payload }));
          } catch (err) {
            clientRes.writeHead(400, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
            clientRes.end(JSON.stringify({ error: err.message }));
          }
        });
        return;
      } else {
        clientRes.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
        clientRes.end(JSON.stringify({ latestAction, clientsConnected: wsClients.size }));
        return;
      }
    }

    // Health status
    if (parsedUrl.pathname === '/healthz' || parsedUrl.pathname === '/api/status') {
      clientRes.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
      clientRes.end(JSON.stringify({ status: 'ok', clientsConnected: wsClients.size, uiPort: UI_PORT, wsPort: WS_PORT }));
      return;
    }

    // Default route serves a seamless wrapper pointing directly to the HTTPS host via /auth,
    // establishing the partitioned cookie and preserving the production referrer for Google Maps.
    const rawPath = parsedUrl.searchParams.get('url') || parsedUrl.searchParams.get('next') || currentTelemetryPath;
    const telemetryPath = ensureCompanionParams(rawPath);
    const authTarget = API_KEY
      ? `https://${TARGET_HOST}/auth?key=${encodeURIComponent(API_KEY)}&next=${encodeURIComponent(telemetryPath)}`
      : `https://${TARGET_HOST}/auth?next=${encodeURIComponent(telemetryPath)}`;
    const wrapperHtml = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Telemetry Viewer</title>
  <style>
    html, body { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: #0b0f19; }
    iframe { width: 100%; height: 100%; border: none; display: block; }
  </style>
</head>
<body>
  <iframe id="viewer" src="${authTarget}" allow="clipboard-read; clipboard-write; microphone; fullscreen"></iframe>
  <script>
    window.addEventListener('message', (e) => {
      const f = document.getElementById('viewer');
      if (f && f.contentWindow) {
        try { f.contentWindow.postMessage(e.data, '*'); } catch (_) {}
      }
    });
  </script>
</body>
</html>`;
    clientRes.writeHead(200, {
      'Content-Type': 'text/html; charset=utf-8',
      'Access-Control-Allow-Origin': '*',
      'Cache-Control': 'no-cache',
    });
    clientRes.end(wrapperHtml);
  };
}

// 1. Start the UI server on UI_PORT
const uiServer = http.createServer(createHttpHandler());
uiServer.on('upgrade', handleWebSocketUpgrade);
uiServer.on('error', (err) => log(`UI Server error on port ${UI_PORT}: ${err.message}`));
uiServer.listen(UI_PORT, '127.0.0.1', () => {
  log(`UI Server listening on http://127.0.0.1:${UI_PORT}`);
});

// 2. Start WebSocket server on WS_PORT (38472) if distinct from UI_PORT
let wsServer = uiServer;
if (UI_PORT !== WS_PORT) {
  wsServer = http.createServer(createHttpHandler());
  wsServer.on('upgrade', handleWebSocketUpgrade);
  wsServer.on('error', (err) => {
    if (err.code === 'EADDRINUSE') {
      log(`WS Port ${WS_PORT} already in use; attaching to existing daemon`);
    } else {
      log(`WS Server error on port ${WS_PORT}: ${err.message}`);
    }
  });
  wsServer.listen(WS_PORT, '127.0.0.1', () => {
    log(`WS HTTP Server listening on http://127.0.0.1:${WS_PORT}`);
  });
}

process.on('uncaughtException', (err) => {
  log(`Uncaught exception caught safely: ${err.message}`);
});
