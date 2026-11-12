#!/usr/bin/env node
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
import path from 'node:path';
import readline from 'node:readline';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const WS_PORT = parseInt(process.env.BRBR_COMPANION_WS_PORT || '38472', 10);
const CALLER_CWD = process.cwd();

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function checkHealth() {
  return new Promise((resolve) => {
    const req = http.request(
      {
        hostname: '127.0.0.1',
        port: WS_PORT,
        path: '/healthz',
        method: 'GET',
        timeout: 500,
      },
      (res) => {
        res.resume();
        resolve(res.statusCode === 200);
      }
    );
    req.on('error', () => resolve(false));
    req.on('timeout', () => {
      req.destroy();
      resolve(false);
    });
    req.end();
  });
}

let serverReady = false;

async function ensureSidecarRunning() {
  if (serverReady && (await checkHealth())) {
    return true;
  }
  if (await checkHealth()) {
    serverReady = true;
    return true;
  }

  const startScript = path.join(__dirname, 'start.sh');
  const childEnv = {
    ...process.env,
    BRBR_COMPANION_WS_PORT: String(WS_PORT),
    ANTIGRAVITY_SIDECAR_WEB_PORT: process.env.ANTIGRAVITY_SIDECAR_WEB_PORT || String(WS_PORT),
  };
  try {
    const child = spawn('bash', [startScript], {
      cwd: CALLER_CWD,
      env: childEnv,
      detached: true,
      stdio: 'ignore',
    });
    child.unref();
  } catch (err) {
    process.stderr.write(`Failed to spawn sidecar start.sh: ${err.message}\n`);
    return false;
  }

  for (let i = 0; i < 40; i++) {
    await sleep(100);
    if (await checkHealth()) {
      serverReady = true;
      return true;
    }
  }
  return false;
}

function postMcpPayload(rawJsonLine) {
  return new Promise((resolve, reject) => {
    const bodyBuf = Buffer.from(rawJsonLine, 'utf8');
    const req = http.request(
      {
        hostname: '127.0.0.1',
        port: WS_PORT,
        path: '/mcp',
        method: 'POST',
        headers: {
          'Content-Type': 'application/json; charset=utf-8',
          'Content-Length': bodyBuf.length,
          'X-Workspace-Cwd': CALLER_CWD,
        },
        timeout: 15000,
      },
      (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => {
          resolve({
            status: res.statusCode || 500,
            body: Buffer.concat(chunks).toString('utf8'),
          });
        });
      }
    );
    req.on('error', reject);
    req.on('timeout', () => {
      req.destroy(new Error('MCP HTTP request timed out'));
    });
    req.write(bodyBuf);
    req.end();
  });
}

async function handleLine(line) {
  const trimmed = line.trim();
  if (!trimmed) return;

  let parsedReq = null;
  try {
    parsedReq = JSON.parse(trimmed);
  } catch (err) {
    const errResp = {
      jsonrpc: '2.0',
      id: null,
      error: { code: -32700, message: `Parse error: ${err.message}` },
    };
    process.stdout.write(JSON.stringify(errResp) + '\n');
    return;
  }

  const ok = await ensureSidecarRunning();
  if (!ok) {
    if (parsedReq && parsedReq.id !== undefined) {
      const errResp = {
        jsonrpc: '2.0',
        id: parsedReq.id,
        error: { code: -32000, message: `Telemetry Companion sidecar unreachable on port ${WS_PORT}` },
      };
      process.stdout.write(JSON.stringify(errResp) + '\n');
    }
    return;
  }

  try {
    const { status, body } = await postMcpPayload(trimmed);
    if (status === 202 || !body.trim()) {
      return;
    }
    const respObj = JSON.parse(body);
    process.stdout.write(JSON.stringify(respObj) + '\n');
  } catch (err) {
    serverReady = false;
    if (parsedReq && parsedReq.id !== undefined) {
      const errResp = {
        jsonrpc: '2.0',
        id: parsedReq.id,
        error: { code: -32000, message: `Bridge forwarding error: ${err.message}` },
      };
      process.stdout.write(JSON.stringify(errResp) + '\n');
    }
  }
}

const rl = readline.createInterface({
  input: process.stdin,
  crlfDelay: Infinity,
});

let queue = Promise.resolve();
rl.on('line', (line) => {
  queue = queue.then(() => handleLine(line)).catch((err) => {
    process.stderr.write(`Unhandled stdio bridge error: ${err.message}\n`);
  });
});

rl.on('close', () => {
  queue.finally(() => process.exit(0));
});

