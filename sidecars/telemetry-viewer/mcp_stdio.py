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

"""Zero-dependency newline-delimited JSON-RPC 2.0 stdio bridge to Companion Sidecar /mcp."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WS_PORT = int(os.environ.get('BRBR_COMPANION_WS_PORT') or '38472')
CALLER_CWD = os.getcwd()

_server_ready = False


def check_health() -> bool:
    url = f"http://127.0.0.1:{WS_PORT}/healthz"
    req = urllib.request.Request(url, method='GET')
    try:
        with urllib.request.urlopen(req, timeout=0.5) as resp:
            return int(resp.status) == 200
    except Exception:
        return False


def ensure_sidecar_running() -> bool:
    global _server_ready
    if _server_ready and check_health():
        return True
    if check_health():
        _server_ready = True
        return True

    start_script = os.path.join(SCRIPT_DIR, 'start.sh')
    child_env = dict(os.environ)
    child_env['BRBR_COMPANION_WS_PORT'] = str(WS_PORT)
    if not child_env.get('ANTIGRAVITY_SIDECAR_WEB_PORT'):
        child_env['ANTIGRAVITY_SIDECAR_WEB_PORT'] = str(WS_PORT)

    try:
        subprocess.Popen(
            ['bash', start_script],
            cwd=CALLER_CWD,
            env=child_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        sys.stderr.write(f"Failed to spawn sidecar start.sh: {exc}\n")
        return False

    for _ in range(40):
        time.sleep(0.1)
        if check_health():
            _server_ready = True
            return True
    return False


def post_mcp_payload(raw_json_line: str) -> tuple[int, str]:
    url = f"http://127.0.0.1:{WS_PORT}/mcp"
    data = raw_json_line.encode('utf-8')
    req = urllib.request.Request(
        url,
        data=data,
        method='POST',
        headers={
            'Content-Type': 'application/json; charset=utf-8',
            'X-Workspace-Cwd': CALLER_CWD,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            body = resp.read().decode('utf-8')
            return int(resp.status), body
    except urllib.error.HTTPError as http_err:
        body = http_err.read().decode('utf-8', errors='replace')
        return int(http_err.code), body


def write_json_line(obj: Any) -> None:
    sys.stdout.write(json.dumps(obj, separators=(',', ':')) + '\n')
    sys.stdout.flush()


def handle_line(line: str) -> None:
    global _server_ready
    trimmed = line.strip()
    if not trimmed:
        return

    try:
        parsed_req = json.loads(trimmed)
    except json.JSONDecodeError as err:
        write_json_line({
            'jsonrpc': '2.0',
            'id': None,
            'error': {'code': -32700, 'message': f"Parse error: {err}"},
        })
        return

    req_id = parsed_req.get('id') if isinstance(parsed_req, dict) else None
    has_id = isinstance(parsed_req, dict) and 'id' in parsed_req

    if not ensure_sidecar_running():
        if has_id:
            write_json_line({
                'jsonrpc': '2.0',
                'id': req_id,
                'error': {
                    'code': -32000,
                    'message': f"Telemetry Companion sidecar unreachable on port {WS_PORT}",
                },
            })
        return

    try:
        status, body = post_mcp_payload(trimmed)
        if status == 202 or not body.strip():
            return
        resp_obj = json.loads(body)
        write_json_line(resp_obj)
    except Exception as err:
        _server_ready = False
        if has_id:
            write_json_line({
                'jsonrpc': '2.0',
                'id': req_id,
                'error': {'code': -32000, 'message': f"Bridge forwarding error: {err}"},
            })


def main() -> None:
    for line in sys.stdin:
        handle_line(line)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
