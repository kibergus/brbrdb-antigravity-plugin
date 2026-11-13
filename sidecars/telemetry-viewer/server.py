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

Serves the auxiliary web panel, jailed <workspace>/studies/ static files, workspace discovery
& manifest APIs, Streamable HTTP JSON-RPC 2.0 MCP server, and WebSocket event bridge.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import struct
import tempfile
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_PORT = 38472
UI_PORT = int(
    os.environ.get('ANTIGRAVITY_SIDECAR_WEB_PORT')
    or os.environ.get('PORT')
    or os.environ.get('BRBR_COMPANION_WS_PORT')
    or DEFAULT_PORT
)
WS_PORT = int(
    os.environ.get('BRBR_COMPANION_WS_PORT') or os.environ.get('PORT') or DEFAULT_PORT
)
API_KEY = os.environ.get('BRBRDB_API_KEY', '').strip()
TARGET_HOST = os.environ.get('BRBRDB_HOST', 'brbrdb.brbrkitten.com').strip()
LOG_FILE = os.environ.get('BRBR_COMPANION_LOG_FILE') or os.path.join(
    tempfile.gettempdir(), 'telemetry_companion.log'
)
STATE_FILE = os.environ.get('BRBR_COMPANION_STATE_FILE') or os.path.join(
    tempfile.gettempdir(), 'brbr_telemetry_companion_state.json'
)

CORS_HEADERS: dict[str, str] = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': (
        'Content-Type, Authorization, X-Requested-With, Mcp-Session-Id, X-Workspace-Cwd'
    ),
    'Access-Control-Allow-Private-Network': 'true',
}

MIME_TYPES: dict[str, str] = {
    '.geojson': 'application/geo+json; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.md': 'text/plain; charset=utf-8',
    '.txt': 'text/plain; charset=utf-8',
    '.csv': 'text/csv; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
}

GROUP_SLUG_RE = re.compile(r'^[a-z0-9_-]+$')


def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}\n"
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line)
    except OSError:
        pass
    print(msg, flush=True)


def is_global_plugin_dir(dir_path: str) -> bool:
    if not dir_path:
        return True
    candidates = [dir_path]
    try:
        candidates.append(os.path.realpath(dir_path))
    except OSError:
        pass
    for p in candidates:
        norm = p.replace('\\', '/')
        if (
            '/.gemini/config/plugins' in norm
            or '/.gemini/antigravity/builtin' in norm
            or '/.agents/plugins' in norm
        ):
            return True
    return False


def infer_default_workspace_dir() -> str:
    script_dirs = [SCRIPT_DIR]
    try:
        real_dir = os.path.realpath(SCRIPT_DIR)
        if real_dir != SCRIPT_DIR:
            script_dirs.append(real_dir)
    except OSError:
        pass
    for d in script_dirs:
        norm_script = d.replace('\\', '/')
        marker = '/.agents/plugins/'
        idx = norm_script.find(marker)
        if idx > 0:
            candidate = d[:idx]
            if os.path.exists(candidate):
                return os.path.abspath(candidate)
    return os.path.abspath(os.getcwd())


def load_persisted_state() -> dict[str, Any]:
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def normalize_study_id(raw: Any) -> str:
    if raw is None:
        return ''
    cleaned = str(raw).strip().replace('\\', '/').strip('/')
    if not cleaned:
        return ''
    parts = cleaned.split('/')
    if any((not p or p == '.' or p == '..' or '\0' in p) for p in parts):
        raise ValueError(f"Invalid study path: {raw}")
    return '/'.join(parts)


_persisted = load_persisted_state()
_persisted_ws_raw = _persisted.get('workspaceDir')
_valid_persisted_ws: str = (
    os.path.abspath(_persisted_ws_raw)
    if isinstance(_persisted_ws_raw, str)
    and _persisted_ws_raw
    and not is_global_plugin_dir(_persisted_ws_raw)
    and os.path.exists(_persisted_ws_raw)
    else ''
)

explicit_workspace_bound: bool = bool(
    os.environ.get('BRBR_STUDIES_DIR')
    or os.environ.get('BRBR_WORKSPACE_DIR')
    or _valid_persisted_ws
)


def _init_workspace_dir() -> str:
    env_ws = os.environ.get('BRBR_WORKSPACE_DIR')
    if env_ws:
        return os.path.abspath(env_ws)
    env_studies = os.environ.get('BRBR_STUDIES_DIR')
    if env_studies:
        return os.path.dirname(os.path.abspath(env_studies))
    if _valid_persisted_ws:
        return _valid_persisted_ws
    return infer_default_workspace_dir()


workspace_dir: str = _init_workspace_dir()
custom_studies_dir_override: str = (
    os.path.abspath(os.environ['BRBR_STUDIES_DIR']) if os.environ.get('BRBR_STUDIES_DIR') else ''
)
active_study: str = normalize_study_id(_persisted.get('activeStudy') or '')
active_overlays: list[str] = (
    [str(x) for x in _persisted['activeOverlays']]
    if isinstance(_persisted.get('activeOverlays'), list)
    else []
)


def get_studies_dir() -> str:
    if custom_studies_dir_override:
        return custom_studies_dir_override
    return os.path.join(workspace_dir, 'studies')


def save_persisted_state() -> None:
    try:
        payload = {
            'workspaceDir': workspace_dir,
            'activeStudy': active_study,
            'activeOverlays': active_overlays,
            'updatedAt': datetime.now(timezone.utc).isoformat(),
        }
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2)
    except OSError:
        pass


def maybe_adopt_caller_cwd(caller_cwd: str) -> None:
    global workspace_dir, explicit_workspace_bound
    if explicit_workspace_bound or not caller_cwd:
        return
    if is_global_plugin_dir(caller_cwd):
        return
    try:
        if os.path.isdir(caller_cwd):
            workspace_dir = os.path.abspath(caller_cwd)
            explicit_workspace_bound = True
            save_persisted_state()
    except OSError:
        pass


def get_http_base() -> str:
    return f"http://127.0.0.1:{WS_PORT}"


def encode_path_segments(rel_path: str) -> str:
    return '/'.join(quote(seg, safe='') for seg in rel_path.split('/') if seg)


def resolve_safe_study_path(
    rel_subpath: str,
    must_exist: bool = True,
    allow_root: bool = False,
) -> dict[str, Any]:
    """Resolve a relative subpath strictly inside studies_dir, blocking .. and symlink escapes."""
    if not isinstance(rel_subpath, str) or '\0' in rel_subpath:
        return {'ok': False, 'status': 403, 'error': 'Forbidden path'}

    studies_dir = get_studies_dir()
    root_real = os.path.realpath(studies_dir) if os.path.exists(studies_dir) else os.path.abspath(studies_dir)

    if '%' in rel_subpath:
        # Reject malformed percent-encoding explicitly
        idx = 0
        while idx < len(rel_subpath):
            p = rel_subpath.find('%', idx)
            if p == -1:
                break
            hex_part = rel_subpath[p + 1:p + 3]
            if len(hex_part) < 2 or not all(c in '0123456789abcdefABCDEF' for c in hex_part):
                return {'ok': False, 'status': 400, 'error': 'Malformed URL path encoding'}
            idx = p + 3

    decoded = unquote(rel_subpath)
    if '\0' in decoded:
        return {'ok': False, 'status': 403, 'error': 'Forbidden path'}

    stripped = decoded.replace('\\', '/').lstrip('/')
    if not stripped:
        if allow_root:
            return {'ok': True, 'fullPath': root_real, 'rootReal': root_real, 'relPath': ''}
        return {'ok': False, 'status': 403, 'error': 'Forbidden root path'}

    raw_segments = stripped.split('/')
    if any(seg == '..' for seg in raw_segments):
        return {'ok': False, 'status': 403, 'error': 'Path traversal is not allowed'}

    candidate = os.path.abspath(os.path.join(root_real, stripped))
    if candidate != root_real and not candidate.startswith(root_real + os.sep):
        return {'ok': False, 'status': 403, 'error': 'Path escapes studies root'}

    if must_exist:
        if not os.path.lexists(candidate):
            return {'ok': False, 'status': 404, 'error': 'File not found'}
        try:
            real_candidate = os.path.realpath(candidate)
        except OSError:
            return {'ok': False, 'status': 404, 'error': 'File not found'}
        if real_candidate != root_real and not real_candidate.startswith(root_real + os.sep):
            return {'ok': False, 'status': 403, 'error': 'Symlink escapes studies root'}
        if not os.path.exists(real_candidate):
            return {'ok': False, 'status': 404, 'error': 'File not found'}
        rel_norm = os.path.relpath(real_candidate, root_real).replace('\\', '/')
        return {'ok': True, 'fullPath': real_candidate, 'rootReal': root_real, 'relPath': rel_norm}

    ancestor = os.path.dirname(candidate)
    while ancestor and not os.path.exists(ancestor):
        parent = os.path.dirname(ancestor)
        if parent == ancestor:
            break
        ancestor = parent
    if ancestor and os.path.exists(ancestor) and os.path.exists(studies_dir):
        real_ancestor = os.path.realpath(ancestor)
        if real_ancestor != root_real and not real_ancestor.startswith(root_real + os.sep):
            return {'ok': False, 'status': 403, 'error': 'Ancestor symlink escapes studies root'}

    rel_norm = os.path.relpath(candidate, root_real).replace('\\', '/')
    return {'ok': True, 'fullPath': candidate, 'rootReal': root_real, 'relPath': rel_norm}


def list_files_recursive(base_dir: str, ext_filter: str, max_depth: int = 5) -> list[str]:
    results: list[str] = []
    if not os.path.exists(base_dir):
        return results

    def walk(curr: str, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(os.scandir(curr), key=lambda e: e.name)
        except OSError:
            return
        for ent in entries:
            if ent.name.startswith('.') or ent.name == '__pycache__':
                continue
            full = os.path.join(curr, ent.name)
            try:
                if ent.is_dir(follow_symlinks=False):
                    walk(full, depth + 1)
                elif ent.is_file(follow_symlinks=False) or ent.is_symlink():
                    if not ext_filter or ent.name.lower().endswith(ext_filter):
                        results.append(full)
            except OSError:
                continue

    walk(base_dir, 0)
    return results


def inspect_study_dir(study_dir: str, rel_study_id: str) -> dict[str, Any] | None:
    overlays_dir = os.path.join(study_dir, 'overlays')
    channels_dir = os.path.join(study_dir, 'channels')
    plot_groups_file = os.path.join(study_dir, 'plot_groups.json')
    readme_file = os.path.join(study_dir, 'README.md')

    overlay_files = list_files_recursive(overlays_dir, '.geojson', 4)
    channel_files = list_files_recursive(channels_dir, '.json', 4)
    has_plot_groups = os.path.exists(plot_groups_file)
    has_readme = os.path.exists(readme_file)

    top_geojson: list[str] = []
    if rel_study_id:
        try:
            for ent in sorted(os.scandir(study_dir), key=lambda e: e.name):
                if ent.is_file(follow_symlinks=False) and ent.name.lower().endswith('.geojson'):
                    top_geojson.append(os.path.join(study_dir, ent.name))
        except OSError:
            pass

    is_study = (
        len(overlay_files) > 0
        or len(top_geojson) > 0
        or len(channel_files) > 0
        or has_plot_groups
        or has_readme
        or os.path.exists(overlays_dir)
        or os.path.exists(channels_dir)
    )
    if not is_study:
        return None

    latest_mtime = 0.0
    try:
        latest_mtime = os.stat(study_dir).st_mtime
    except OSError:
        pass

    overlay_ids: list[str] = []
    for fp in overlay_files:
        rel = os.path.relpath(fp, overlays_dir).replace('\\', '/')
        if rel.lower().endswith('.geojson'):
            rel = rel[:-8]
        overlay_ids.append(rel)
        try:
            mt = os.stat(fp).st_mtime
            if mt > latest_mtime:
                latest_mtime = mt
        except OSError:
            pass

    for fp in top_geojson:
        rel = os.path.basename(fp)
        if rel.lower().endswith('.geojson'):
            rel = rel[:-8]
        if rel not in overlay_ids:
            overlay_ids.append(rel)
        try:
            mt = os.stat(fp).st_mtime
            if mt > latest_mtime:
                latest_mtime = mt
        except OSError:
            pass

    channel_ids: list[str] = []
    inferred_groups: set[str] = set()
    for fp in channel_files:
        try:
            mt = os.stat(fp).st_mtime
            if mt > latest_mtime:
                latest_mtime = mt
            with open(fp, 'r', encoding='utf-8') as f:
                parsed = json.load(f)
            if isinstance(parsed, dict):
                ch_list = parsed.get('channels') if isinstance(parsed.get('channels'), list) else [parsed]
                for ch in ch_list:
                    if isinstance(ch, dict) and ch.get('channel_id'):
                        channel_ids.append(str(ch['channel_id']))
                        if ch.get('group'):
                            inferred_groups.add(str(ch['group']))
        except (OSError, json.JSONDecodeError):
            pass

    plot_group_ids: set[str] = set(inferred_groups)
    if has_plot_groups:
        try:
            mt = os.stat(plot_groups_file).st_mtime
            if mt > latest_mtime:
                latest_mtime = mt
            with open(plot_groups_file, 'r', encoding='utf-8') as f:
                pg = json.load(f)
            if isinstance(pg, dict) and isinstance(pg.get('groups'), list):
                for g in pg['groups']:
                    if isinstance(g, dict) and g.get('id'):
                        plot_group_ids.add(str(g['id']))
        except (OSError, json.JSONDecodeError):
            pass

    return {
        'id': rel_study_id,
        'label': rel_study_id or 'Root',
        'mtime': round(latest_mtime, 3),
        'has_readme': has_readme,
        'overlays': sorted(overlay_ids),
        'channels': sorted(channel_ids),
        'plot_groups': sorted(plot_group_ids),
    }


def discover_studies() -> list[dict[str, Any]]:
    studies_dir = get_studies_dir()
    if not os.path.exists(studies_dir):
        return []
    try:
        root_real = os.path.realpath(studies_dir)
    except OSError:
        return []

    studies: list[dict[str, Any]] = []
    root_info = inspect_study_dir(root_real, '')
    if root_info and (root_info['overlays'] or root_info['channels'] or root_info['plot_groups']):
        studies.append(root_info)

    def scan_dirs(curr_dir: str, depth: int) -> None:
        if depth > 5:
            return
        try:
            entries = sorted(os.scandir(curr_dir), key=lambda e: e.name)
        except OSError:
            return
        for ent in entries:
            try:
                if not ent.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            if ent.name.startswith('.') or ent.name in ('__pycache__', 'overlays', 'channels'):
                continue
            sub_full = os.path.join(curr_dir, ent.name)
            try:
                real_sub = os.path.realpath(sub_full)
            except OSError:
                continue
            if not real_sub.startswith(root_real + os.sep):
                continue
            rel_id = os.path.relpath(real_sub, root_real).replace('\\', '/')
            info = inspect_study_dir(real_sub, rel_id)
            if info is not None:
                studies.append(info)
            scan_dirs(real_sub, depth + 1)

    scan_dirs(root_real, 0)
    return studies


def matches_session_filter(match_obj: Any, filters: dict[str, Any]) -> bool:
    if not isinstance(match_obj, dict):
        return True
    f_date = filters.get('date')
    if f_date and match_obj.get('date') and str(match_obj['date']).lower() != str(f_date).lower():
        return False
    f_track = filters.get('track')
    if f_track and match_obj.get('track') and str(match_obj['track']).lower() != str(f_track).lower():
        return False
    f_sid = filters.get('session_id')
    if f_sid and match_obj.get('session_id') and str(match_obj['session_id']).lower() != str(f_sid).lower():
        return False
    return True


def build_overlay_descriptor(
    full_file_path: str,
    root_real: str,
    id_override: str = '',
    study_id: str = '',
) -> dict[str, Any]:
    rel_file = os.path.relpath(full_file_path, root_real).replace('\\', '/')
    mtime = 0.0
    try:
        mtime = round(os.stat(full_file_path).st_mtime, 3)
    except OSError:
        pass

    meta: dict[str, Any] = {}
    try:
        with open(full_file_path, 'r', encoding='utf-8') as f:
            parsed = json.load(f)
        if isinstance(parsed, dict) and isinstance(parsed.get('metadata'), dict):
            meta = parsed['metadata']
    except (OSError, json.JSONDecodeError):
        pass

    base_stem = os.path.basename(full_file_path)
    if base_stem.lower().endswith('.geojson'):
        base_stem = base_stem[:-8]
    ov_id = id_override or (str(meta['id']) if meta.get('id') else base_stem)
    return {
        'id': ov_id,
        'meta_id': str(meta['id']) if meta.get('id') else ov_id,
        'study': study_id,
        'label': str(meta['label']) if meta.get('label') else ov_id,
        'render': 'heatmap' if meta.get('render') == 'heatmap' else 'vector',
        'path': rel_file,
        'url': f"{get_http_base()}/files/{encode_path_segments(rel_file)}",
        'mtime': mtime,
        'metadata': meta,
    }


def resolve_cross_study_overlay(ref_str: str, root_real: str) -> dict[str, Any] | None:
    cleaned = str(ref_str).strip().replace('\\', '/').lstrip('/')
    if not cleaned or '..' in cleaned or '\0' in cleaned:
        return None

    candidates = [cleaned]
    if not cleaned.lower().endswith('.geojson'):
        candidates.append(f"{cleaned}.geojson")
        slash_idx = cleaned.find('/')
        if slash_idx > 0:
            study_part = cleaned[:slash_idx]
            rest_part = cleaned[slash_idx + 1:]
            candidates.append(f"{study_part}/overlays/{rest_part}.geojson")

    for cand in candidates:
        res = resolve_safe_study_path(cand, must_exist=True)
        if res.get('ok') and os.path.isfile(res['fullPath']):
            return build_overlay_descriptor(res['fullPath'], root_real, cleaned, '')
    return None


def build_manifest(query: dict[str, Any] | None = None) -> dict[str, Any]:
    q = query or {}
    studies = discover_studies()
    requested_study = (
        normalize_study_id(q['study']) if 'study' in q and q['study'] is not None else active_study
    )

    http_base = get_http_base()
    studies_dir = get_studies_dir()
    overlays: list[dict[str, Any]] = []
    seen_overlay_ids: set[str] = set()
    channels: list[dict[str, Any]] = []
    channel_map: dict[str, dict[str, Any]] = {}
    plot_groups: list[dict[str, Any]] = []
    diagnostics: list[str] = []

    root_real = os.path.abspath(studies_dir)
    if os.path.exists(studies_dir):
        try:
            root_real = os.path.realpath(studies_dir)
        except OSError:
            pass

    study_res = resolve_safe_study_path(requested_study, must_exist=True, allow_root=True)
    if study_res.get('ok') and os.path.isdir(study_res['fullPath']):
        study_dir = study_res['fullPath']
        overlays_dir = os.path.join(study_dir, 'overlays')

        overlay_files = list_files_recursive(overlays_dir, '.geojson', 4)
        for fp in overlay_files:
            try:
                real_fp = os.path.realpath(fp)
            except OSError:
                continue
            if not real_fp.startswith(root_real + os.sep) or not os.path.isfile(real_fp):
                continue
            rel_id = os.path.relpath(fp, overlays_dir).replace('\\', '/')
            if rel_id.lower().endswith('.geojson'):
                rel_id = rel_id[:-8]
            desc = build_overlay_descriptor(real_fp, root_real, rel_id, requested_study)
            overlays.append(desc)
            seen_overlay_ids.add(desc['id'])
            if desc.get('meta_id'):
                seen_overlay_ids.add(desc['meta_id'])
            seen_overlay_ids.add(desc['path'])

        if requested_study:
            try:
                for ent in sorted(os.scandir(study_dir), key=lambda e: e.name):
                    if ent.is_file(follow_symlinks=False) and ent.name.lower().endswith('.geojson'):
                        real_fp = os.path.realpath(os.path.join(study_dir, ent.name))
                        if not real_fp.startswith(root_real + os.sep) or not os.path.isfile(real_fp):
                            continue
                        rel_id = ent.name[:-8]
                        if rel_id not in seen_overlay_ids:
                            desc = build_overlay_descriptor(real_fp, root_real, rel_id, requested_study)
                            overlays.append(desc)
                            seen_overlay_ids.add(desc['id'])
                            seen_overlay_ids.add(desc['path'])
            except OSError:
                pass

        channels_dir = os.path.join(study_dir, 'channels')
        channel_files = list_files_recursive(channels_dir, '.json', 4)
        for fp in channel_files:
            try:
                real_fp = os.path.realpath(fp)
            except OSError:
                continue
            if not real_fp.startswith(root_real + os.sep) or not os.path.isfile(real_fp):
                continue
            rel_file = os.path.relpath(real_fp, root_real).replace('\\', '/')
            mtime = 0.0
            try:
                mtime = round(os.stat(real_fp).st_mtime, 3)
            except OSError:
                pass
            try:
                with open(real_fp, 'r', encoding='utf-8') as f:
                    parsed = json.load(f)
                ch_list = (
                    parsed.get('channels')
                    if isinstance(parsed, dict) and isinstance(parsed.get('channels'), list)
                    else [parsed]
                )
                for ch in ch_list:
                    if not isinstance(ch, dict) or not ch.get('channel_id'):
                        continue
                    if not matches_session_filter(ch.get('match'), q):
                        continue
                    ch_id = str(ch['channel_id'])
                    ch_desc: dict[str, Any] = {
                        'channel_id': ch_id,
                        'label': str(ch['label']) if ch.get('label') else ch_id,
                        'unit': str(ch['unit']) if ch.get('unit') else '',
                        'color': str(ch['color']) if ch.get('color') else '#38bdf8',
                        'group': str(ch['group']).lower() if ch.get('group') else '',
                        'group_label': str(ch['group_label']) if ch.get('group_label') else '',
                        'match': ch.get('match') or None,
                        'study': requested_study,
                        'path': rel_file,
                        'url': f"{http_base}/files/{encode_path_segments(rel_file)}",
                        'mtime': mtime,
                    }
                    channels.append(ch_desc)
                    channel_map[ch_id] = ch_desc
            except (OSError, json.JSONDecodeError) as err:
                diagnostics.append(f"Invalid channel JSON {rel_file}: {err}")

        plot_groups_path = os.path.join(study_dir, 'plot_groups.json')
        registered_group_ids: set[str] = set()
        if os.path.exists(plot_groups_path):
            try:
                with open(plot_groups_path, 'r', encoding='utf-8') as f:
                    pg_data = json.load(f)
                raw_groups = pg_data.get('groups', []) if isinstance(pg_data, dict) else []
                for raw_group in raw_groups:
                    if not isinstance(raw_group, dict) or not raw_group.get('id'):
                        continue
                    g_id = str(raw_group['id']).lower()
                    registered_group_ids.add(g_id)
                    norm_channels: list[dict[str, Any]] = []
                    for item in raw_group.get('channels') or []:
                        ch_obj = {'channel_id': item} if isinstance(item, str) else item
                        if not isinstance(ch_obj, dict):
                            continue
                        c_id = str(ch_obj.get('channel_id') or '')
                        base_desc = channel_map.get(c_id)
                        norm_channels.append({
                            'channel_id': c_id,
                            'label': ch_obj.get('label') or (base_desc['label'] if base_desc else c_id),
                            'unit': ch_obj.get('unit') or (base_desc['unit'] if base_desc else ''),
                            'color': ch_obj.get('color') or (base_desc['color'] if base_desc else '#38bdf8'),
                            'yaxis': 'y2' if ch_obj.get('yaxis') == 'y2' else 'y',
                        })
                    raw_yr = raw_group.get('y_range')
                    y_range = raw_yr if isinstance(raw_yr, list) and len(raw_yr) == 2 else None
                    plot_groups.append({
                        'id': g_id,
                        'label': str(raw_group['label']) if raw_group.get('label') else g_id.upper(),
                        'y_label': str(raw_group['y_label']) if raw_group.get('y_label') else '',
                        'y2_label': str(raw_group['y2_label']) if raw_group.get('y2_label') else '',
                        'y_range': y_range,
                        'color_mode': 'lap' if raw_group.get('color_mode') == 'lap' else 'channel',
                        'channels': norm_channels,
                    })
            except (OSError, json.JSONDecodeError) as err:
                diagnostics.append(f"Invalid plot_groups.json: {err}")

        auto_groups: dict[str, dict[str, Any]] = {}
        for ch in channels:
            grp = ch['group']
            if not grp or grp in registered_group_ids:
                continue
            if grp not in auto_groups:
                auto_groups[grp] = {
                    'id': grp,
                    'label': ch['group_label'] or grp.upper(),
                    'y_label': ch['unit'] or '',
                    'y2_label': '',
                    'y_range': None,
                    'color_mode': 'channel',
                    'channels': [],
                }
            auto_groups[grp]['channels'].append({
                'channel_id': ch['channel_id'],
                'label': ch['label'],
                'unit': ch['unit'],
                'color': ch['color'],
                'yaxis': 'y',
            })
        for g in auto_groups.values():
            plot_groups.append(g)

    extra_refs: set[str] = set(active_overlays)
    if q.get('overlays'):
        for item in str(q['overlays']).split(','):
            trimmed = item.strip()
            if trimmed:
                extra_refs.add(trimmed)
    for ref in sorted(extra_refs):
        if ref not in seen_overlay_ids and os.path.exists(studies_dir):
            resolved = resolve_cross_study_overlay(ref, root_real)
            if resolved is not None:
                overlays.append(resolved)
                seen_overlay_ids.add(resolved['id'])
                seen_overlay_ids.add(resolved['path'])

    etag_payload = json.dumps(
        {
            'study': requested_study,
            'studies': [[s['id'], s['mtime'], s['overlays'], s['channels'], s['plot_groups']] for s in studies],
            'overlays': [[o['id'], o['path'], o['mtime']] for o in overlays],
            'channels': [[c['channel_id'], c['path'], c['mtime']] for c in channels],
            'plotGroups': [[g['id'], g['label'], g['channels']] for g in plot_groups],
        },
        separators=(',', ':'),
    )
    etag = hashlib.sha1(etag_payload.encode('utf-8')).hexdigest()[:16]

    return {
        'ok': True,
        'http_base': http_base,
        'workspace_dir': workspace_dir,
        'studies_dir': studies_dir,
        'study': requested_study,
        'active_overlays': active_overlays,
        'etag': etag,
        'studies': studies,
        'overlays': overlays,
        'channels': channels,
        'plot_groups': plot_groups,
        'diagnostics': diagnostics,
    }


ws_clients: set[asyncio.StreamWriter] = set()
latest_action: dict[str, Any] = {
    'type': 'telemetry_jump',
    'dist': 0,
    'timestamp': datetime.now(timezone.utc).isoformat(),
}
current_telemetry_path: str = (
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


async def broadcast(message_dict: dict[str, Any]) -> int:
    """Broadcast JSON payload to all active WebSocket clients."""
    frame = encode_text_frame(json.dumps(message_dict))
    dead_clients: set[asyncio.StreamWriter] = set()
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


def compute_watch_snapshot_etag() -> str:
    try:
        return str(build_manifest({'study': active_study})['etag'])
    except Exception:
        return ''


last_watched_etag: str = compute_watch_snapshot_etag()


async def watch_studies_loop() -> None:
    global last_watched_etag
    while True:
        await asyncio.sleep(1.0)
        next_etag = compute_watch_snapshot_etag()
        if next_etag and next_etag != last_watched_etag:
            last_watched_etag = next_etag
            if ws_clients:
                await broadcast({
                    'type': 'workspace_sync',
                    'study': active_study,
                    'etag': next_etag,
                    'httpBase': get_http_base(),
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                })


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

    ready_frame = encode_text_frame(json.dumps({
        'type': 'COMPANION_READY',
        'port': WS_PORT,
        'httpBase': get_http_base(),
        'study': active_study,
        'activeOverlays': active_overlays,
        'etag': last_watched_etag or compute_watch_snapshot_etag(),
    }))
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


# ---------------------------------------------------------------------------
# MCP Server Tool Definitions & Handlers
# ---------------------------------------------------------------------------

MCP_TOOLS: list[dict[str, Any]] = [
    {
        'name': 'set_telemetry_view',
        'description': (
            'Controls the Antigravity Telemetry Viewer side panel identically to clicking interactive '
            'report pills, plus switching active workspace study subfolders, selecting/clearing GeoJSON '
            'map overlays and heatmaps, opening custom plot groups, and navigating sessions.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'study': {
                    'type': 'string',
                    'description': 'Active study subfolder relative to <workspace>/studies/.',
                },
                'overlays': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': (
                        'Overlay IDs (within active study) or relative paths (across studies) to display '
                        'on the map right now. Pass [] to hide all overlays while keeping files saved on disk.'
                    ),
                },
                'toggle_overlay': {
                    'type': 'string',
                    'description': 'Toggle a single GeoJSON overlay ID on or off.',
                },
                'plots': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': 'Visible bottom-bar plots, e.g. ["speed", "delta", "pedals", "eeg"].',
                },
                'toggle_plot': {
                    'type': 'string',
                    'description': 'Toggle a single bottom plot channel/group on or off.',
                },
                'session_url': {
                    'type': 'string',
                    'description': 'Navigate viewer to a specific telemetry meeting/session URL or path.',
                },
                'tab': {
                    'type': 'string',
                    'enum': ['map', 'stats'],
                    'description': 'Main view tab ("map" or "stats").',
                },
                'right_tab': {
                    'type': 'string',
                    'enum': ['cornering', 'acceleration', 'slip_angle', 'report'],
                    'description': 'Right side-panel tab.',
                },
                'side_panel': {
                    'type': 'string',
                    'enum': ['collapsed', 'expanded'],
                    'description': 'Collapse or expand the right side panel.',
                },
                'laps_a': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': 'Active Group A reference laps (e.g. ["20_06_practice-28"]).',
                },
                'laps_b': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': 'Active Group B target laps. Pass [] to clear.',
                },
                'dist': {
                    'type': 'number',
                    'description': 'Seek distance cursor and kart marker to distance in meters.',
                },
                'focus_range': {
                    'type': 'array',
                    'items': {'type': 'number'},
                    'minItems': 2,
                    'maxItems': 2,
                    'description': 'Zoom both map bounds and bottom plot X-axis to [start_m, end_m].',
                },
                'xlim': {
                    'type': 'array',
                    'items': {'type': 'number'},
                    'minItems': 2,
                    'maxItems': 2,
                    'description': 'Zoom bottom plot X-axis only to [start_m, end_m].',
                },
                'map_range': {
                    'type': 'array',
                    'items': {'type': 'number'},
                    'minItems': 2,
                    'maxItems': 2,
                    'description': 'Zoom map bounds only to track segment [start_m, end_m].',
                },
                'lat': {'type': 'number', 'description': 'Center map on GPS latitude.'},
                'lng': {'type': 'number', 'description': 'Center map on GPS longitude.'},
                'zoom': {'type': 'number', 'description': 'Google Maps zoom level.'},
                'turn': {
                    'type': 'integer',
                    'description': '1-indexed turn number to select and focus (e.g. 1 for Turn 1).',
                },
                'trajectory_color': {
                    'type': 'string',
                    'description': 'Trajectory color mode ("pedals", "speed", "accel", "delta_t", "lap").',
                },
                'map_type': {
                    'type': 'string',
                    'enum': ['satellite', 'kartsim', 'hybrid'],
                    'description': 'Map background mode.',
                },
                'workspace_dir': {
                    'type': 'string',
                    'description': 'Optional workspace root path override.',
                },
            },
        },
    },
    {
        'name': 'list_workspace_studies',
        'description': (
            'Lists all saved study subfolders under <workspace>/studies/ along with their overlays, '
            'custom derived channels, plot groups, and README status so past analyses can be reused.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'workspace_dir': {
                    'type': 'string',
                    'description': 'Optional workspace root path override.',
                },
            },
        },
    },
    {
        'name': 'register_plot_group',
        'description': (
            'Creates or updates a custom bottom-bar plot group (e.g. "eeg_bands" / "EEG Bands") in '
            '<workspace>/studies/<study>/plot_groups.json and immediately syncs the Telemetry Viewer UI. '
            'All channels in a group overlay on one chart (y/y2 axes)—register separate groups for '
            'distinct scales, and avoid id="eeg"/"ecg"/"emg" unless intentionally overriding built-in sensor tabs.'
        ),
        'inputSchema': {
            'type': 'object',
            'required': ['id', 'label', 'channels'],
            'properties': {
                'id': {
                    'type': 'string',
                    'description': 'Plot group identifier (lowercase slug, e.g. "eeg_bands").',
                },
                'label': {
                    'type': 'string',
                    'description': 'Display label on the bottom plot tab button (e.g. "EEG Bands").',
                },
                'study': {
                    'type': 'string',
                    'description': 'Target study subfolder relative to <workspace>/studies/.',
                },
                'y_label': {
                    'type': 'string',
                    'description': 'Primary Y-axis label (e.g. "Band Power (Z-score)").',
                },
                'y2_label': {
                    'type': 'string',
                    'description': 'Optional secondary right-hand Y-axis label.',
                },
                'y_range': {
                    'type': 'array',
                    'items': {'type': 'number'},
                    'minItems': 2,
                    'maxItems': 2,
                    'description': 'Optional fixed Y-axis [min, max]; omit for dynamic auto-scaling.',
                },
                'color_mode': {
                    'type': 'string',
                    'enum': ['channel', 'lap'],
                    'description': '"channel" colors by channel with solid/dashed per lap; "lap" colors by lap.',
                },
                'channels': {
                    'type': 'array',
                    'description': 'Channels rendered in this plot group.',
                    'items': {
                        'type': 'object',
                        'required': ['channel_id'],
                        'properties': {
                            'channel_id': {'type': 'string'},
                            'label': {'type': 'string'},
                            'unit': {'type': 'string'},
                            'color': {'type': 'string'},
                            'yaxis': {'type': 'string', 'enum': ['y', 'y2']},
                        },
                    },
                },
                'open_plot': {
                    'type': 'boolean',
                    'description': 'If true, immediately opens this plot group in the bottom bar.',
                },
                'workspace_dir': {
                    'type': 'string',
                    'description': 'Optional workspace root path override.',
                },
            },
        },
    },
    {
        'name': 'sync_workspace_data',
        'description': (
            'Validates study overlays/channels/plot_groups in <workspace>/studies/, updates '
            'workspace/study binding if provided, and broadcasts workspace_sync to reload files in the UI.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'study': {
                    'type': 'string',
                    'description': 'Optional study subfolder relative to <workspace>/studies/.',
                },
                'workspace_dir': {
                    'type': 'string',
                    'description': 'Optional workspace root path override.',
                },
            },
        },
    },
    {
        'name': 'get_telemetry_view_status',
        'description': (
            'Returns Companion sidecar connection status, connected WebSocket viewer count, '
            'current session URL, active workspace & study, active overlays, and available plot groups.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {},
        },
    },
]


def apply_workspace_override(dir_arg: Any) -> None:
    global workspace_dir, custom_studies_dir_override, explicit_workspace_bound
    if not dir_arg:
        return
    workspace_dir = os.path.abspath(str(dir_arg))
    custom_studies_dir_override = ''
    explicit_workspace_bound = True


async def dispatch_action_payload(raw_args: dict[str, Any]) -> dict[str, Any]:
    global active_study, active_overlays, current_telemetry_path, latest_action, last_watched_etag

    payload: dict[str, Any] = {
        'type': 'telemetry_jump',
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }

    if raw_args.get('workspace_dir'):
        apply_workspace_override(raw_args['workspace_dir'])
    if 'study' in raw_args and raw_args['study'] is not None:
        active_study = normalize_study_id(raw_args['study'])
        payload['study'] = active_study
    if 'overlays' in raw_args and raw_args['overlays'] is not None:
        ov_arg = raw_args['overlays']
        active_overlays = [str(x) for x in ov_arg] if isinstance(ov_arg, list) else []
        payload['overlays'] = active_overlays
    if 'toggle_overlay' in raw_args and raw_args['toggle_overlay'] is not None:
        t_id = str(raw_args['toggle_overlay'])
        if t_id in active_overlays:
            active_overlays.remove(t_id)
        else:
            active_overlays.append(t_id)
        payload['toggleOverlay'] = t_id

    save_persisted_state()

    if raw_args.get('session_url'):
        current_telemetry_path = ensure_companion_params(str(raw_args['session_url']))
        payload['sessionUrl'] = current_telemetry_path
    if 'tab' in raw_args and raw_args['tab'] is not None:
        payload['tab'] = raw_args['tab']
    if 'right_tab' in raw_args and raw_args['right_tab'] is not None:
        payload['rtab'] = raw_args['right_tab']
    if 'side_panel' in raw_args and raw_args['side_panel'] is not None:
        payload['sidePanel'] = raw_args['side_panel']
    if 'laps_a' in raw_args and raw_args['laps_a'] is not None:
        payload['lapsA'] = raw_args['laps_a']
    if 'laps_b' in raw_args and raw_args['laps_b'] is not None:
        payload['lapsB'] = raw_args['laps_b']
    if 'dist' in raw_args and raw_args['dist'] is not None:
        payload['dist'] = raw_args['dist']
    if 'focus_range' in raw_args and raw_args['focus_range'] is not None:
        payload['focusRange'] = raw_args['focus_range']
    if 'xlim' in raw_args and raw_args['xlim'] is not None:
        payload['xlim'] = raw_args['xlim']
    if 'map_range' in raw_args and raw_args['map_range'] is not None:
        payload['mapRange'] = raw_args['map_range']
    if 'lat' in raw_args and raw_args['lat'] is not None:
        payload['lat'] = raw_args['lat']
    if 'lng' in raw_args and raw_args['lng'] is not None:
        payload['lng'] = raw_args['lng']
    if 'zoom' in raw_args and raw_args['zoom'] is not None:
        payload['zoom'] = raw_args['zoom']
    if 'turn' in raw_args and raw_args['turn'] is not None:
        payload['turnNumber'] = int(raw_args['turn'])
        payload['turn'] = int(raw_args['turn'])
    if 'plots' in raw_args and raw_args['plots'] is not None:
        payload['plots'] = raw_args['plots']
    if 'toggle_plot' in raw_args and raw_args['toggle_plot'] is not None:
        payload['togglePlot'] = raw_args['toggle_plot']
    if 'trajectory_color' in raw_args and raw_args['trajectory_color'] is not None:
        payload['tcol'] = raw_args['trajectory_color']
    if 'map_type' in raw_args and raw_args['map_type'] is not None:
        payload['mapType'] = raw_args['map_type']

    latest_action = payload
    last_watched_etag = compute_watch_snapshot_etag()

    sync_sent = 0
    if any(
        k in raw_args and raw_args[k] is not None
        for k in ('workspace_dir', 'study', 'overlays', 'toggle_overlay')
    ):
        sync_sent = await broadcast({
            'type': 'workspace_sync',
            'study': active_study,
            'activeOverlays': active_overlays,
            'etag': last_watched_etag,
            'httpBase': get_http_base(),
            'timestamp': payload['timestamp'],
        })
    log(f"Dispatched MCP action: {json.dumps(payload)} to {len(ws_clients)} viewer client(s)")
    sent_count = await broadcast(payload)
    return {
        'ok': True,
        'clients_notified': max(sent_count, sync_sent),
        'active_study': active_study,
        'active_overlays': active_overlays,
        'action': payload,
    }


async def execute_mcp_tool(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    global active_study, last_watched_etag
    tool_args = args or {}

    if name == 'set_telemetry_view':
        return await dispatch_action_payload(tool_args)

    if name == 'list_workspace_studies':
        if tool_args.get('workspace_dir'):
            apply_workspace_override(tool_args['workspace_dir'])
            save_persisted_state()
        studies = discover_studies()
        return {
            'ok': True,
            'workspace_dir': workspace_dir,
            'studies_dir': get_studies_dir(),
            'active_study': active_study,
            'active_overlays': active_overlays,
            'studies': studies,
        }

    if name == 'register_plot_group':
        if tool_args.get('workspace_dir'):
            apply_workspace_override(tool_args['workspace_dir'])
        target_study = (
            normalize_study_id(tool_args['study'])
            if 'study' in tool_args and tool_args['study'] is not None
            else active_study
        )
        if 'study' in tool_args and tool_args['study'] is not None:
            active_study = target_study
        save_persisted_state()

        group_slug = str(tool_args.get('id') or '').strip().lower()
        if not group_slug or not GROUP_SLUG_RE.fullmatch(group_slug):
            raise ValueError(f"Invalid plot group id: {tool_args.get('id')}")

        pg_rel = f"{target_study}/plot_groups.json" if target_study else 'plot_groups.json'
        studies_dir = get_studies_dir()
        os.makedirs(studies_dir, exist_ok=True)

        safe_target = resolve_safe_study_path(pg_rel, must_exist=False)
        if not safe_target.get('ok'):
            raise ValueError(str(safe_target.get('error') or 'Forbidden path'))

        target_fp = str(safe_target['fullPath'])
        os.makedirs(os.path.dirname(target_fp), exist_ok=True)

        existing: dict[str, Any] = {'groups': []}
        if os.path.exists(target_fp):
            try:
                with open(target_fp, 'r', encoding='utf-8') as f:
                    parsed = json.load(f)
                if isinstance(parsed, dict) and isinstance(parsed.get('groups'), list):
                    existing = parsed
            except (OSError, json.JSONDecodeError):
                pass

        raw_yr = tool_args.get('y_range')
        group_entry: dict[str, Any] = {
            'id': group_slug,
            'label': str(tool_args.get('label') or group_slug.upper()),
            'y_label': str(tool_args['y_label']) if tool_args.get('y_label') else '',
            'y2_label': str(tool_args['y2_label']) if tool_args.get('y2_label') else '',
            'y_range': raw_yr if isinstance(raw_yr, list) and len(raw_yr) == 2 else None,
            'color_mode': 'lap' if tool_args.get('color_mode') == 'lap' else 'channel',
            'channels': tool_args['channels'] if isinstance(tool_args.get('channels'), list) else [],
        }

        groups_list: list[dict[str, Any]] = existing['groups']
        replaced = False
        for i, g in enumerate(groups_list):
            if isinstance(g, dict) and str(g.get('id') or '').lower() == group_slug:
                groups_list[i] = group_entry
                replaced = True
                break
        if not replaced:
            groups_list.append(group_entry)

        with open(target_fp, 'w', encoding='utf-8') as f:
            f.write(json.dumps(existing, indent=2) + '\n')

        last_watched_etag = compute_watch_snapshot_etag()
        notified = await broadcast({
            'type': 'workspace_sync',
            'study': active_study,
            'etag': last_watched_etag,
            'httpBase': get_http_base(),
            'timestamp': datetime.now(timezone.utc).isoformat(),
        })

        if tool_args.get('open_plot'):
            await broadcast({
                'type': 'telemetry_jump',
                'study': active_study,
                'togglePlot': group_slug,
                'openPlot': group_slug,
                'timestamp': datetime.now(timezone.utc).isoformat(),
            })

        return {
            'ok': True,
            'study': target_study,
            'file': target_fp,
            'group': group_entry,
            'clients_notified': notified,
        }

    if name == 'sync_workspace_data':
        if tool_args.get('workspace_dir'):
            apply_workspace_override(tool_args['workspace_dir'])
        if 'study' in tool_args and tool_args['study'] is not None:
            active_study = normalize_study_id(tool_args['study'])
        save_persisted_state()
        manifest = build_manifest({'study': active_study})
        last_watched_etag = str(manifest['etag'])
        notified = await broadcast({
            'type': 'workspace_sync',
            'study': active_study,
            'etag': manifest['etag'],
            'httpBase': get_http_base(),
            'timestamp': datetime.now(timezone.utc).isoformat(),
        })
        return {
            'ok': True,
            'clients_notified': notified,
            'study': manifest['study'],
            'workspace_dir': manifest['workspace_dir'],
            'studies_dir': manifest['studies_dir'],
            'overlays_count': len(manifest['overlays']),
            'channels_count': len(manifest['channels']),
            'plot_groups': [g['id'] for g in manifest['plot_groups']],
            'diagnostics': manifest['diagnostics'],
        }

    if name == 'get_telemetry_view_status':
        manifest = build_manifest({'study': active_study})
        return {
            'ok': True,
            'clients_connected': len(ws_clients),
            'ui_port': UI_PORT,
            'ws_port': WS_PORT,
            'http_base': get_http_base(),
            'session_url': current_telemetry_path,
            'workspace_dir': workspace_dir,
            'studies_dir': get_studies_dir(),
            'active_study': active_study,
            'active_overlays': active_overlays,
            'available_studies': [s['id'] for s in manifest['studies']],
            'study_overlays': [o['id'] for o in manifest['overlays']],
            'study_channels': [c['channel_id'] for c in manifest['channels']],
            'study_plot_groups': [g['id'] for g in manifest['plot_groups']],
            'latest_action': latest_action,
        }

    raise ValueError(f"Unknown tool: {name}")


async def handle_mcp_rpc_object(rpc_req: Any) -> dict[str, Any] | None:
    if not isinstance(rpc_req, dict):
        return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid Request'}}

    is_notification = 'id' not in rpc_req
    req_id = rpc_req.get('id')
    method = rpc_req.get('method')
    params = rpc_req.get('params') if isinstance(rpc_req.get('params'), dict) else {}

    if method == 'notifications/initialized' or (isinstance(method, str) and method.startswith('notifications/')):
        return None

    if method == 'initialize':
        client_proto = str(params['protocolVersion']) if params.get('protocolVersion') else '2024-11-05'
        return {
            'jsonrpc': '2.0',
            'id': None if is_notification else req_id,
            'result': {
                'protocolVersion': client_proto,
                'capabilities': {'tools': {'listChanged': False}},
                'serverInfo': {'name': 'brbrtelemetry-companion', 'version': '1.1.0'},
            },
        }

    if method == 'ping':
        return {'jsonrpc': '2.0', 'id': None if is_notification else req_id, 'result': {}}

    if method == 'tools/list':
        return {
            'jsonrpc': '2.0',
            'id': None if is_notification else req_id,
            'result': {'tools': MCP_TOOLS},
        }

    if method == 'tools/call':
        tool_name = str(params.get('name') or '')
        raw_tool_args = params.get('arguments')
        tool_args = raw_tool_args if isinstance(raw_tool_args, dict) else {}
        try:
            result_obj = await execute_mcp_tool(tool_name, tool_args)
            return {
                'jsonrpc': '2.0',
                'id': None if is_notification else req_id,
                'result': {
                    'content': [{'type': 'text', 'text': json.dumps(result_obj, indent=2)}],
                    'isError': False,
                },
            }
        except Exception as err:
            return {
                'jsonrpc': '2.0',
                'id': None if is_notification else req_id,
                'result': {
                    'content': [{'type': 'text', 'text': json.dumps({'ok': False, 'error': str(err)})}],
                    'isError': True,
                },
            }

    if is_notification:
        return None
    return {
        'jsonrpc': '2.0',
        'id': req_id,
        'error': {'code': -32601, 'message': f"Method not found: {method}"},
    }


def _status_text(status: int) -> str:
    return {
        200: 'OK',
        202: 'Accepted',
        204: 'No Content',
        400: 'Bad Request',
        403: 'Forbidden',
        404: 'Not Found',
        405: 'Method Not Allowed',
        500: 'Internal Server Error',
    }.get(status, 'OK')


async def send_response(
    writer: asyncio.StreamWriter,
    status: int,
    body: bytes = b'',
    extra_headers: dict[str, str] | None = None,
    send_body: bool = True,
) -> None:
    hdrs: dict[str, str] = dict(CORS_HEADERS)
    if extra_headers:
        hdrs.update(extra_headers)
    hdrs['Content-Length'] = str(len(body))
    hdrs['Connection'] = 'close'
    lines = [f"HTTP/1.1 {status} {_status_text(status)}"]
    for k, v in hdrs.items():
        lines.append(f"{k}: {v}")
    raw_head = ('\r\n'.join(lines) + '\r\n\r\n').encode('utf-8')
    writer.write(raw_head + (body if send_body else b''))
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def send_json(writer: asyncio.StreamWriter, status: int, obj: Any) -> None:
    body = json.dumps(obj).encode('utf-8')
    await send_response(
        writer,
        status,
        body,
        extra_headers={
            'Content-Type': 'application/json; charset=utf-8',
            'Cache-Control': 'no-cache',
        },
    )


async def read_body_bytes(
    reader: asyncio.StreamReader,
    headers: dict[str, str],
    initial_body: bytes,
) -> bytes:
    content_length = int(headers.get('content-length') or 0)
    body_bytes = bytearray(initial_body)
    while len(body_bytes) < content_length:
        more = await reader.read(min(65536, content_length - len(body_bytes)))
        if not more:
            break
        body_bytes.extend(more)
    return bytes(body_bytes[:content_length]) if content_length > 0 else bytes(body_bytes)


async def handle_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Handle incoming HTTP or WebSocket connection."""
    global current_telemetry_path, latest_action, active_study, active_overlays, last_watched_etag
    try:
        header_data = bytearray()
        while b'\r\n\r\n' not in header_data:
            chunk = await reader.read(4096)
            if not chunk:
                break
            header_data.extend(chunk)
            if len(header_data) > 65536:
                break

        if not header_data or b'\r\n\r\n' not in header_data:
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

        method, raw_target = req_line[0].upper(), req_line[1]
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ':' in line:
                k, v = line.split(':', 1)
                headers[k.strip().lower()] = v.strip()

        if headers.get('upgrade', '').lower() == 'websocket':
            ws_key = headers.get('sec-websocket-key')
            if ws_key:
                await handle_websocket(reader, writer, ws_key)
                return

        if method == 'OPTIONS':
            await send_response(writer, 204, b'')
            return

        caller_cwd = headers.get('x-workspace-cwd', '')
        if caller_cwd:
            maybe_adopt_caller_cwd(caller_cwd)

        parsed = urlparse(raw_target)
        req_path = parsed.path
        query_params = parse_qs(parsed.query, keep_blank_values=True)

        # 1. Static study files: GET/HEAD /files/<subpath>
        if req_path.startswith('/files/'):
            if method not in ('GET', 'HEAD'):
                await send_json(writer, 405, {'error': 'Method not allowed'})
                return
            subpath = req_path[len('/files/'):]
            resolved = resolve_safe_study_path(subpath, must_exist=True)
            if not resolved.get('ok'):
                await send_json(writer, int(resolved.get('status', 403)), {'error': resolved.get('error')})
                return
            full_fp = str(resolved['fullPath'])
            if not os.path.isfile(full_fp):
                await send_json(writer, 404, {'error': 'Not a file'})
                return
            ext = os.path.splitext(full_fp)[1].lower()
            content_type = MIME_TYPES.get(ext, 'application/octet-stream')
            try:
                with open(full_fp, 'rb') as f:
                    data = f.read()
            except OSError:
                await send_json(writer, 404, {'error': 'File not found'})
                return
            await send_response(
                writer,
                200,
                data,
                extra_headers={
                    'Content-Type': content_type,
                    'Cache-Control': 'no-cache',
                },
                send_body=(method != 'HEAD'),
            )
            return

        # 2. Workspace studies discovery: GET /api/workspace/studies
        if req_path == '/api/workspace/studies' and method == 'GET':
            await send_json(writer, 200, {
                'ok': True,
                'workspace_dir': workspace_dir,
                'studies_dir': get_studies_dir(),
                'active_study': active_study,
                'studies': discover_studies(),
            })
            return

        # 3. Scoped workspace manifest: GET /api/workspace/manifest
        if req_path == '/api/workspace/manifest' and method == 'GET':
            try:
                q_dict: dict[str, Any] = {
                    'study': query_params['study'][0] if 'study' in query_params else None,
                    'overlays': query_params.get('overlays', [''])[0],
                    'date': query_params.get('date', [''])[0],
                    'track': query_params.get('track', [''])[0],
                    'session_id': query_params.get('session_id', [''])[0],
                }
                await send_json(writer, 200, build_manifest(q_dict))
            except Exception as err:
                await send_json(writer, 400, {'ok': False, 'error': str(err)})
            return

        # 4. Workspace configuration update: /api/workspace
        if req_path == '/api/workspace':
            if method == 'POST':
                try:
                    raw_body = await read_body_bytes(reader, headers, initial_body)
                    payload = json.loads(raw_body.decode('utf-8') or '{}')
                    if payload.get('workspace_dir'):
                        apply_workspace_override(payload['workspace_dir'])
                    if 'study' in payload and payload['study'] is not None:
                        active_study = normalize_study_id(payload['study'])
                    ov_list = (
                        payload.get('overlays')
                        if isinstance(payload.get('overlays'), list)
                        else payload.get('activeOverlays')
                        if isinstance(payload.get('activeOverlays'), list)
                        else None
                    )
                    if ov_list is not None:
                        active_overlays = [str(x) for x in ov_list]
                    save_persisted_state()
                    manifest = build_manifest({'study': active_study})
                    last_watched_etag = str(manifest['etag'])
                    notified = await broadcast({
                        'type': 'workspace_sync',
                        'study': active_study,
                        'activeOverlays': active_overlays,
                        'etag': manifest['etag'],
                        'httpBase': get_http_base(),
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                    })
                    await send_json(writer, 200, {
                        'ok': True,
                        'clients_notified': notified,
                        'workspace_dir': workspace_dir,
                        'studies_dir': get_studies_dir(),
                        'active_study': active_study,
                        'active_overlays': active_overlays,
                        'etag': manifest['etag'],
                    })
                except Exception as err:
                    await send_json(writer, 400, {'ok': False, 'error': str(err)})
                return
            await send_json(writer, 200, {
                'ok': True,
                'workspace_dir': workspace_dir,
                'studies_dir': get_studies_dir(),
                'active_study': active_study,
                'active_overlays': active_overlays,
            })
            return

        # 5. MCP Streamable HTTP endpoint: /mcp
        if req_path == '/mcp':
            if method != 'POST':
                await send_json(writer, 200, {'name': 'brbrtelemetry-companion', 'status': 'ok'})
                return
            try:
                raw_body = await read_body_bytes(reader, headers, initial_body)
                rpc_payload = json.loads(raw_body.decode('utf-8') or '{}')
                if isinstance(rpc_payload, list):
                    responses: list[dict[str, Any]] = []
                    for item in rpc_payload:
                        r = await handle_mcp_rpc_object(item)
                        if r is not None:
                            responses.append(r)
                    if not responses:
                        await send_response(writer, 202, b'')
                    else:
                        await send_json(writer, 200, responses)
                    return
                rpc_resp = await handle_mcp_rpc_object(rpc_payload)
                if rpc_resp is None:
                    await send_response(writer, 202, b'')
                else:
                    await send_json(writer, 200, rpc_resp)
            except Exception as err:
                await send_json(writer, 400, {
                    'jsonrpc': '2.0',
                    'id': None,
                    'error': {'code': -32700, 'message': f"Parse error: {err}"},
                })
            return

        # 6. Companion action dispatch API: /api/action
        if req_path == '/api/action':
            if method == 'POST':
                try:
                    raw_body = await read_body_bytes(reader, headers, initial_body)
                    payload = json.loads(raw_body.decode('utf-8') or '{}')
                    if payload.get('workspace_dir'):
                        apply_workspace_override(payload['workspace_dir'])
                    if payload.get('url'):
                        current_telemetry_path = ensure_companion_params(str(payload['url']))
                        payload['sessionUrl'] = current_telemetry_path
                    if payload.get('sessionUrl'):
                        current_telemetry_path = ensure_companion_params(str(payload['sessionUrl']))
                        payload['sessionUrl'] = current_telemetry_path
                    if 'study' in payload and payload['study'] is not None:
                        active_study = normalize_study_id(payload['study'])
                        payload['study'] = active_study
                    if isinstance(payload.get('overlays'), list):
                        active_overlays = [str(x) for x in payload['overlays']]
                        payload['overlays'] = active_overlays
                    toggle_ov = (
                        payload.get('toggleOverlay')
                        if payload.get('toggleOverlay') is not None
                        else payload.get('toggle_overlay')
                    )
                    if toggle_ov is not None:
                        t_id = str(toggle_ov)
                        if t_id in active_overlays:
                            active_overlays.remove(t_id)
                        else:
                            active_overlays.append(t_id)
                        payload['toggleOverlay'] = t_id
                    if payload.get('turn') is not None and payload.get('turnNumber') is None:
                        payload['turnNumber'] = int(payload['turn'])
                    elif payload.get('turnNumber') is not None and payload.get('turn') is None:
                        payload['turn'] = int(payload['turnNumber'])
                    save_persisted_state()
                    if not payload.get('type'):
                        payload['type'] = 'telemetry_jump'
                    payload['timestamp'] = datetime.now(timezone.utc).isoformat()
                    latest_action = payload
                    last_watched_etag = compute_watch_snapshot_etag()

                    sync_sent = 0
                    if (
                        payload.get('workspace_dir') is not None
                        or 'study' in payload
                        or 'overlays' in payload
                        or toggle_ov is not None
                    ):
                        sync_sent = await broadcast({
                            'type': 'workspace_sync',
                            'study': active_study,
                            'activeOverlays': active_overlays,
                            'etag': last_watched_etag,
                            'httpBase': get_http_base(),
                            'timestamp': payload['timestamp'],
                        })

                    log(f"Dispatched action: {json.dumps(payload)} to {len(ws_clients)} viewer client(s)")
                    sent = await broadcast(payload)
                    await send_json(writer, 200, {'ok': True, 'sentTo': max(sent, sync_sent), 'action': payload})
                except Exception as err:
                    await send_json(writer, 400, {'error': str(err)})
                return
            await send_json(writer, 200, {
                'latestAction': latest_action,
                'clientsConnected': len(ws_clients),
                'activeStudy': active_study,
                'activeOverlays': active_overlays,
            })
            return

        # 7. Health status
        if req_path in ('/health', '/healthz', '/api/status'):
            await send_json(writer, 200, {
                'ok': True,
                'status': 'ok',
                'clientsConnected': len(ws_clients),
                'uiPort': UI_PORT,
                'wsPort': WS_PORT,
                'workspaceDir': workspace_dir,
                'studiesDir': get_studies_dir(),
                'activeStudy': active_study,
            })
            return

        # 8. Default route serves seamless wrapper iframe
        raw_next = (
            query_params.get('url', [''])[0]
            or query_params.get('next', [''])[0]
            or current_telemetry_path
        )
        telemetry_path = ensure_companion_params(raw_next)
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
        await send_response(
            writer,
            200,
            wrapper_html.encode('utf-8'),
            extra_headers={
                'Content-Type': 'text/html; charset=utf-8',
                'Cache-Control': 'no-cache',
            },
        )
    except Exception as exc:
        log(f"Connection error: {exc}")
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def main() -> None:
    log(
        f"Telemetry Companion (Pure Python Zero-Dep) starting... "
        f"UI_PORT={UI_PORT}, WS_PORT={WS_PORT}, WORKSPACE={workspace_dir}"
    )

    watch_task = asyncio.create_task(watch_studies_loop())
    try:
        server_ui = await asyncio.start_server(handle_connection, '127.0.0.1', UI_PORT)
        log(f"UI Server listening on http://127.0.0.1:{UI_PORT}")

        if UI_PORT != WS_PORT:
            try:
                server_ws = await asyncio.start_server(handle_connection, '127.0.0.1', WS_PORT)
                log(f"WS HTTP Server listening on http://127.0.0.1:{WS_PORT}")
                async with server_ui, server_ws:
                    await asyncio.gather(server_ui.serve_forever(), server_ws.serve_forever())
            except OSError as err:
                log(f"WS Port {WS_PORT} already in use ({err}); serving UI only")
                async with server_ui:
                    await server_ui.serve_forever()
        else:
            async with server_ui:
                await server_ui.serve_forever()
    finally:
        watch_task.cancel()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
