#!/bin/bash
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

exec >> /tmp/sidecar_debug.log 2>&1
echo "=== Sidecar started at $(date) ==="
echo "Working directory: $(pwd)"
echo "Arguments: $@"
echo "ANTIGRAVITY_SIDECAR_WEB_PORT=$ANTIGRAVITY_SIDECAR_WEB_PORT"

SCRIPT_DIR="${BASH_SOURCE[0]%/*}"
[ -z "$SCRIPT_DIR" ] && SCRIPT_DIR="."
SCRIPT_DIR="$(cd "$SCRIPT_DIR" && pwd)"

# Ensure default port 38472 is free so EADDRINUSE never causes startup failures
fuser -k 38472/tcp 2>/dev/null || true
sleep 0.2

# 1. Prefer Node.js (pure built-in standard library, zero external dependencies)
NODE_BIN="$(command -v node || true)"
if [ -n "$NODE_BIN" ] && [ -x "$NODE_BIN" ]; then
    echo "Starting sidecar via Node.js ($NODE_BIN)..."
    exec "$NODE_BIN" "$SCRIPT_DIR/server.mjs" "$@"
fi

# 2. Fall back to Python 3 (pure built-in standard library, zero external dependencies)
PYTHON_BIN="$(command -v python3 || command -v python || true)"
if [ -n "$PYTHON_BIN" ] && [ -x "$PYTHON_BIN" ]; then
    echo "Node.js not detected; starting sidecar via Python 3 fallback ($PYTHON_BIN)..."
    exec "$PYTHON_BIN" "$SCRIPT_DIR/server.py" "$@"
fi

echo "ERROR: Neither Node.js (node) nor Python 3 (python3) was found in PATH." >&2
exit 1
