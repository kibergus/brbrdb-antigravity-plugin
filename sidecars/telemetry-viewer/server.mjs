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
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const DEFAULT_PORT = 38472;
const UI_PORT = parseInt(
  process.env.ANTIGRAVITY_SIDECAR_WEB_PORT ||
    process.env.PORT ||
    process.env.BRBR_COMPANION_WS_PORT ||
    String(DEFAULT_PORT),
  10
);
const WS_PORT = parseInt(
  process.env.BRBR_COMPANION_WS_PORT || process.env.PORT || String(DEFAULT_PORT),
  10
);
const API_KEY = (process.env.BRBRDB_API_KEY || '').trim();
const TARGET_HOST = (process.env.BRBRDB_HOST || 'brbrdb.brbrkitten.com').trim();
const LOG_FILE =
  process.env.BRBR_COMPANION_LOG_FILE || path.join(os.tmpdir(), 'telemetry_companion.log');
const STATE_FILE =
  process.env.BRBR_COMPANION_STATE_FILE ||
  path.join(os.tmpdir(), 'brbr_telemetry_companion_state.json');

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With, Mcp-Session-Id, X-Workspace-Cwd',
  'Access-Control-Allow-Private-Network': 'true',
};

const MIME_TYPES = {
  '.geojson': 'application/geo+json; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.md': 'text/plain; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8',
  '.csv': 'text/csv; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
};

function log(msg) {
  const line = `[${new Date().toISOString()}] ${msg}\n`;
  try { fs.appendFileSync(LOG_FILE, line); } catch {}
  console.log(msg);
}

function isGlobalPluginDir(dirPath) {
  if (!dirPath) return true;
  const norm = dirPath.replace(/\\/g, '/');
  return norm.includes('/.gemini/config/plugins') || norm.includes('/.gemini/antigravity/builtin');
}

function inferDefaultWorkspaceDir() {
  // Check if running inside <workspace>/.agents/plugins/brbrtelemetry/...
  const normScript = __dirname.replace(/\\/g, '/');
  const marker = '/.agents/plugins/';
  const idx = normScript.indexOf(marker);
  if (idx > 0) {
    const candidate = __dirname.slice(0, idx);
    if (fs.existsSync(candidate)) {
      return path.resolve(candidate);
    }
  }
  const cwd = process.cwd();
  if (!isGlobalPluginDir(cwd)) {
    return path.resolve(cwd);
  }
  return path.resolve(cwd);
}

function loadPersistedState() {
  try {
    if (fs.existsSync(STATE_FILE)) {
      return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
    }
  } catch {}
  return {};
}

const persisted = loadPersistedState();
let explicitWorkspaceBound = Boolean(
  process.env.BRBR_STUDIES_DIR || process.env.BRBR_WORKSPACE_DIR || persisted.workspaceDir
);

let workspaceDir = (() => {
  if (process.env.BRBR_WORKSPACE_DIR) return path.resolve(process.env.BRBR_WORKSPACE_DIR);
  if (process.env.BRBR_STUDIES_DIR) return path.dirname(path.resolve(process.env.BRBR_STUDIES_DIR));
  if (persisted.workspaceDir && fs.existsSync(persisted.workspaceDir)) {
    return path.resolve(persisted.workspaceDir);
  }
  return inferDefaultWorkspaceDir();
})();

let customStudiesDirOverride = process.env.BRBR_STUDIES_DIR
  ? path.resolve(process.env.BRBR_STUDIES_DIR)
  : '';

let activeStudy = normalizeStudyId(persisted.activeStudy || '');
let activeOverlays = Array.isArray(persisted.activeOverlays) ? [...persisted.activeOverlays] : [];

function getStudiesDir() {
  if (customStudiesDirOverride) return customStudiesDirOverride;
  return path.join(workspaceDir, 'studies');
}

function savePersistedState() {
  try {
    fs.writeFileSync(
      STATE_FILE,
      JSON.stringify(
        {
          workspaceDir,
          activeStudy,
          activeOverlays,
          updatedAt: new Date().toISOString(),
        },
        null,
        2
      ),
      'utf8'
    );
  } catch {}
}

function normalizeStudyId(raw) {
  if (raw === undefined || raw === null) return '';
  const cleaned = String(raw)
    .trim()
    .replace(/\\/g, '/')
    .replace(/^\/+|\/+$/g, '');
  if (!cleaned) return '';
  const parts = cleaned.split('/');
  if (parts.some((p) => !p || p === '.' || p === '..' || p.includes('\0'))) {
    throw new Error(`Invalid study path: ${raw}`);
  }
  return parts.join('/');
}

function maybeAdoptCallerCwd(callerCwd) {
  if (explicitWorkspaceBound || !callerCwd) return;
  if (isGlobalPluginDir(callerCwd)) return;
  try {
    if (fs.existsSync(callerCwd) && fs.statSync(callerCwd).isDirectory()) {
      workspaceDir = path.resolve(callerCwd);
      explicitWorkspaceBound = true;
      savePersistedState();
    }
  } catch {}
}

function getHttpBase() {
  return `http://127.0.0.1:${WS_PORT}`;
}

function encodePathSegments(relPath) {
  return relPath
    .split('/')
    .filter(Boolean)
    .map((seg) => encodeURIComponent(seg))
    .join('/');
}

/**
 * Resolve a relative subpath strictly inside studiesDir, blocking .. and symlink escapes.
 */
function resolveSafeStudyPath(relSubpath, { mustExist = true, allowRoot = false } = {}) {
  if (typeof relSubpath !== 'string' || relSubpath.includes('\0')) {
    return { ok: false, status: 403, error: 'Forbidden path' };
  }
  const studiesDir = getStudiesDir();
  const rootReal = fs.existsSync(studiesDir) ? fs.realpathSync(studiesDir) : path.resolve(studiesDir);

  let decoded = relSubpath;
  try {
    decoded = decodeURIComponent(relSubpath);
  } catch {
    return { ok: false, status: 400, error: 'Malformed URL path encoding' };
  }
  if (decoded.includes('\0')) {
    return { ok: false, status: 403, error: 'Forbidden path' };
  }

  const stripped = decoded.replace(/\\/g, '/').replace(/^\/+/, '');
  if (!stripped) {
    if (allowRoot) {
      return { ok: true, fullPath: rootReal, rootReal, relPath: '' };
    }
    return { ok: false, status: 403, error: 'Forbidden root path' };
  }

  const rawSegments = stripped.split('/');
  if (rawSegments.some((seg) => seg === '..')) {
    return { ok: false, status: 403, error: 'Path traversal is not allowed' };
  }

  const candidate = path.resolve(rootReal, stripped);
  if (candidate !== rootReal && !candidate.startsWith(rootReal + path.sep)) {
    return { ok: false, status: 403, error: 'Path escapes studies root' };
  }

  if (mustExist) {
    if (!fs.existsSync(candidate)) {
      return { ok: false, status: 404, error: 'File not found' };
    }
    let realCandidate;
    try {
      realCandidate = fs.realpathSync(candidate);
    } catch {
      return { ok: false, status: 404, error: 'File not found' };
    }
    if (realCandidate !== rootReal && !realCandidate.startsWith(rootReal + path.sep)) {
      return { ok: false, status: 403, error: 'Symlink escapes studies root' };
    }
    const relNorm = path.relative(rootReal, realCandidate).replace(/\\/g, '/');
    return { ok: true, fullPath: realCandidate, rootReal, relPath: relNorm };
  }

  // When creating files (e.g. register_plot_group), check nearest existing ancestor for symlink escape
  let ancestor = path.dirname(candidate);
  while (ancestor && !fs.existsSync(ancestor)) {
    const parent = path.dirname(ancestor);
    if (parent === ancestor) break;
    ancestor = parent;
  }
  if (ancestor && fs.existsSync(ancestor) && fs.existsSync(studiesDir)) {
    const realAncestor = fs.realpathSync(ancestor);
    if (realAncestor !== rootReal && !realAncestor.startsWith(rootReal + path.sep)) {
      return { ok: false, status: 403, error: 'Ancestor symlink escapes studies root' };
    }
  }
  const relNorm = path.relative(rootReal, candidate).replace(/\\/g, '/');
  return { ok: true, fullPath: candidate, rootReal, relPath: relNorm };
}

function listFilesRecursive(baseDir, extFilter, maxDepth = 5) {
  const results = [];
  if (!fs.existsSync(baseDir)) return results;
  function walk(curr, depth) {
    if (depth > maxDepth) return;
    let entries;
    try {
      entries = fs.readdirSync(curr, { withFileTypes: true });
    } catch {
      return;
    }
    entries.sort((a, b) => a.name.localeCompare(b.name));
    for (const ent of entries) {
      if (ent.name.startsWith('.') || ent.name === '__pycache__') continue;
      const full = path.join(curr, ent.name);
      if (ent.isDirectory()) {
        walk(full, depth + 1);
      } else if (ent.isFile() || ent.isSymbolicLink()) {
        if (!extFilter || ent.name.toLowerCase().endsWith(extFilter)) {
          results.push(full);
        }
      }
    }
  }
  walk(baseDir, 0);
  return results;
}

function inspectStudyDir(studyDir, relStudyId) {
  const overlaysDir = path.join(studyDir, 'overlays');
  const channelsDir = path.join(studyDir, 'channels');
  const plotGroupsFile = path.join(studyDir, 'plot_groups.json');
  const readmeFile = path.join(studyDir, 'README.md');

  const overlayFiles = listFilesRecursive(overlaysDir, '.geojson', 4);
  const channelFiles = listFilesRecursive(channelsDir, '.json', 4);
  const hasPlotGroups = fs.existsSync(plotGroupsFile);
  const hasReadme = fs.existsSync(readmeFile);

  // Also check top-level .geojson files inside a named study folder
  let topGeojson = [];
  if (relStudyId) {
    try {
      for (const ent of fs.readdirSync(studyDir, { withFileTypes: true })) {
        if (ent.isFile() && ent.name.toLowerCase().endsWith('.geojson')) {
          topGeojson.push(path.join(studyDir, ent.name));
        }
      }
    } catch {}
  }

  const isStudy =
    overlayFiles.length > 0 ||
    topGeojson.length > 0 ||
    channelFiles.length > 0 ||
    hasPlotGroups ||
    hasReadme ||
    fs.existsSync(overlaysDir) ||
    fs.existsSync(channelsDir);

  if (!isStudy) return null;

  let latestMtime = 0;
  try {
    latestMtime = fs.statSync(studyDir).mtimeMs / 1000;
  } catch {}

  const overlayIds = [];
  for (const fp of overlayFiles) {
    const rel = path.relative(overlaysDir, fp).replace(/\\/g, '/').replace(/\.geojson$/i, '');
    overlayIds.push(rel);
    try {
      const mt = fs.statSync(fp).mtimeMs / 1000;
      if (mt > latestMtime) latestMtime = mt;
    } catch {}
  }
  for (const fp of topGeojson) {
    const rel = path.basename(fp).replace(/\.geojson$/i, '');
    if (!overlayIds.includes(rel)) overlayIds.push(rel);
    try {
      const mt = fs.statSync(fp).mtimeMs / 1000;
      if (mt > latestMtime) latestMtime = mt;
    } catch {}
  }

  const channelIds = [];
  const inferredGroups = new Set();
  for (const fp of channelFiles) {
    try {
      const st = fs.statSync(fp);
      const mt = st.mtimeMs / 1000;
      if (mt > latestMtime) latestMtime = mt;
      const parsed = JSON.parse(fs.readFileSync(fp, 'utf8'));
      const list = Array.isArray(parsed.channels) ? parsed.channels : [parsed];
      for (const ch of list) {
        if (ch && ch.channel_id) {
          channelIds.push(String(ch.channel_id));
          if (ch.group) inferredGroups.add(String(ch.group));
        }
      }
    } catch {}
  }

  const plotGroupIds = new Set(inferredGroups);
  if (hasPlotGroups) {
    try {
      const st = fs.statSync(plotGroupsFile);
      const mt = st.mtimeMs / 1000;
      if (mt > latestMtime) latestMtime = mt;
      const pg = JSON.parse(fs.readFileSync(plotGroupsFile, 'utf8'));
      for (const g of pg.groups || []) {
        if (g && g.id) plotGroupIds.add(String(g.id));
      }
    } catch {}
  }

  return {
    id: relStudyId,
    label: relStudyId || 'Root',
    mtime: Number(latestMtime.toFixed(3)),
    has_readme: hasReadme,
    overlays: overlayIds.sort(),
    channels: channelIds.sort(),
    plot_groups: Array.from(plotGroupIds).sort(),
  };
}

function discoverStudies() {
  const studiesDir = getStudiesDir();
  if (!fs.existsSync(studiesDir)) return [];
  let rootReal;
  try {
    rootReal = fs.realpathSync(studiesDir);
  } catch {
    return [];
  }

  const studies = [];
  const rootInfo = inspectStudyDir(rootReal, '');
  if (rootInfo && (rootInfo.overlays.length > 0 || rootInfo.channels.length > 0 || rootInfo.plot_groups.length > 0)) {
    studies.push(rootInfo);
  }

  function scanDirs(currDir, depth) {
    if (depth > 5) return;
    let entries;
    try {
      entries = fs.readdirSync(currDir, { withFileTypes: true });
    } catch {
      return;
    }
    entries.sort((a, b) => a.name.localeCompare(b.name));
    for (const ent of entries) {
      if (!ent.isDirectory()) continue;
      if (ent.name.startsWith('.') || ent.name === '__pycache__' || ent.name === 'overlays' || ent.name === 'channels') {
        continue;
      }
      const subFull = path.join(currDir, ent.name);
      let realSub;
      try {
        realSub = fs.realpathSync(subFull);
      } catch {
        continue;
      }
      if (!realSub.startsWith(rootReal + path.sep)) continue;
      const relId = path.relative(rootReal, realSub).replace(/\\/g, '/');
      const info = inspectStudyDir(realSub, relId);
      if (info) {
        studies.push(info);
      }
      scanDirs(realSub, depth + 1);
    }
  }

  scanDirs(rootReal, 0);
  return studies;
}

function matchesSessionFilter(matchObj, filters) {
  if (!matchObj || typeof matchObj !== 'object') return true;
  if (filters.date && matchObj.date && String(matchObj.date).toLowerCase() !== String(filters.date).toLowerCase()) {
    return false;
  }
  if (filters.track && matchObj.track && String(matchObj.track).toLowerCase() !== String(filters.track).toLowerCase()) {
    return false;
  }
  if (
    filters.session_id &&
    matchObj.session_id &&
    String(matchObj.session_id).toLowerCase() !== String(filters.session_id).toLowerCase()
  ) {
    return false;
  }
  return true;
}

function buildOverlayDescriptor(fullFilePath, rootReal, idOverride = '', studyId = '') {
  const relFile = path.relative(rootReal, fullFilePath).replace(/\\/g, '/');
  let mtime = 0;
  try {
    mtime = Number((fs.statSync(fullFilePath).mtimeMs / 1000).toFixed(3));
  } catch {}

  let meta = {};
  try {
    const parsed = JSON.parse(fs.readFileSync(fullFilePath, 'utf8'));
    if (parsed && typeof parsed.metadata === 'object' && parsed.metadata !== null) {
      meta = parsed.metadata;
    }
  } catch {}

  const id = idOverride || (meta.id ? String(meta.id) : path.basename(fullFilePath).replace(/\.geojson$/i, ''));
  return {
    id,
    meta_id: meta.id ? String(meta.id) : id,
    study: studyId,
    label: meta.label ? String(meta.label) : id,
    render: meta.render === 'heatmap' ? 'heatmap' : 'vector',
    path: relFile,
    url: `${getHttpBase()}/files/${encodePathSegments(relFile)}`,
    mtime,
    metadata: meta,
  };
}

function resolveCrossStudyOverlay(refStr, rootReal) {
  const cleaned = String(refStr).trim().replace(/\\/g, '/').replace(/^\/+/, '');
  if (!cleaned || cleaned.includes('..') || cleaned.includes('\0')) return null;

  const candidates = [cleaned];
  if (!cleaned.toLowerCase().endsWith('.geojson')) {
    candidates.push(`${cleaned}.geojson`);
    const slashIdx = cleaned.indexOf('/');
    if (slashIdx > 0) {
      const studyPart = cleaned.slice(0, slashIdx);
      const restPart = cleaned.slice(slashIdx + 1);
      candidates.push(`${studyPart}/overlays/${restPart}.geojson`);
    }
  }

  for (const cand of candidates) {
    const res = resolveSafeStudyPath(cand, { mustExist: true });
    if (res.ok && fs.statSync(res.fullPath).isFile()) {
      return buildOverlayDescriptor(res.fullPath, rootReal, cleaned, '');
    }
  }
  return null;
}

function buildManifest(query = {}) {
  const studies = discoverStudies();
  const requestedStudy =
    query.study !== undefined ? normalizeStudyId(query.study) : activeStudy;

  const httpBase = getHttpBase();
  const studiesDir = getStudiesDir();
  const overlays = [];
  const seenOverlayIds = new Set();
  const channels = [];
  const channelMap = new Map();
  const plotGroups = [];
  const diagnostics = [];

  let rootReal = path.resolve(studiesDir);
  if (fs.existsSync(studiesDir)) {
    try {
      rootReal = fs.realpathSync(studiesDir);
    } catch {}
  }

  const studyRes = resolveSafeStudyPath(requestedStudy, { mustExist: true, allowRoot: true });
  if (studyRes.ok && fs.existsSync(studyRes.fullPath) && fs.statSync(studyRes.fullPath).isDirectory()) {
    const studyDir = studyRes.fullPath;
    const overlaysDir = path.join(studyDir, 'overlays');

    const overlayFiles = listFilesRecursive(overlaysDir, '.geojson', 4);
    for (const fp of overlayFiles) {
      let realFp;
      try {
        realFp = fs.realpathSync(fp);
      } catch {
        continue;
      }
      if (!realFp.startsWith(rootReal + path.sep)) continue;
      const relId = path.relative(overlaysDir, fp).replace(/\\/g, '/').replace(/\.geojson$/i, '');
      const desc = buildOverlayDescriptor(realFp, rootReal, relId, requestedStudy);
      overlays.push(desc);
      seenOverlayIds.add(desc.id);
      if (desc.meta_id) seenOverlayIds.add(desc.meta_id);
      seenOverlayIds.add(desc.path);
    }

    if (requestedStudy) {
      try {
        for (const ent of fs.readdirSync(studyDir, { withFileTypes: true })) {
          if (ent.isFile() && ent.name.toLowerCase().endsWith('.geojson')) {
            const realFp = fs.realpathSync(path.join(studyDir, ent.name));
            if (!realFp.startsWith(rootReal + path.sep)) continue;
            const relId = ent.name.replace(/\.geojson$/i, '');
            if (!seenOverlayIds.has(relId)) {
              const desc = buildOverlayDescriptor(realFp, rootReal, relId, requestedStudy);
              overlays.push(desc);
              seenOverlayIds.add(desc.id);
              seenOverlayIds.add(desc.path);
            }
          }
        }
      } catch {}
    }

    const channelsDir = path.join(studyDir, 'channels');
    const channelFiles = listFilesRecursive(channelsDir, '.json', 4);
    for (const fp of channelFiles) {
      let realFp;
      try {
        realFp = fs.realpathSync(fp);
      } catch {
        continue;
      }
      if (!realFp.startsWith(rootReal + path.sep)) continue;
      const relFile = path.relative(rootReal, realFp).replace(/\\/g, '/');
      let mtime = 0;
      try {
        mtime = Number((fs.statSync(realFp).mtimeMs / 1000).toFixed(3));
      } catch {}
      try {
        const parsed = JSON.parse(fs.readFileSync(realFp, 'utf8'));
        const list = Array.isArray(parsed.channels) ? parsed.channels : [parsed];
        for (const ch of list) {
          if (!ch || !ch.channel_id) continue;
          if (!matchesSessionFilter(ch.match, query)) continue;
          const chId = String(ch.channel_id);
          const desc = {
            channel_id: chId,
            label: ch.label ? String(ch.label) : chId,
            unit: ch.unit ? String(ch.unit) : '',
            color: ch.color ? String(ch.color) : '#38bdf8',
            group: ch.group ? String(ch.group).toLowerCase() : '',
            group_label: ch.group_label ? String(ch.group_label) : '',
            match: ch.match || null,
            study: requestedStudy,
            path: relFile,
            url: `${httpBase}/files/${encodePathSegments(relFile)}`,
            mtime,
          };
          channels.push(desc);
          channelMap.set(chId, desc);
        }
      } catch (err) {
        diagnostics.push(`Invalid channel JSON ${relFile}: ${err.message}`);
      }
    }

    const plotGroupsPath = path.join(studyDir, 'plot_groups.json');
    const registeredGroupIds = new Set();
    if (fs.existsSync(plotGroupsPath)) {
      try {
        const pgData = JSON.parse(fs.readFileSync(plotGroupsPath, 'utf8'));
        for (const rawGroup of pgData.groups || []) {
          if (!rawGroup || !rawGroup.id) continue;
          const gId = String(rawGroup.id).toLowerCase();
          registeredGroupIds.add(gId);
          const normChannels = (rawGroup.channels || []).map((item) => {
            const chObj = typeof item === 'string' ? { channel_id: item } : item;
            const cId = String(chObj.channel_id || '');
            const baseDesc = channelMap.get(cId);
            return {
              channel_id: cId,
              label: chObj.label || (baseDesc ? baseDesc.label : cId),
              unit: chObj.unit || (baseDesc ? baseDesc.unit : ''),
              color: chObj.color || (baseDesc ? baseDesc.color : '#38bdf8'),
              yaxis: chObj.yaxis === 'y2' ? 'y2' : 'y',
            };
          });
          plotGroups.push({
            id: gId,
            label: rawGroup.label ? String(rawGroup.label) : gId.toUpperCase(),
            y_label: rawGroup.y_label ? String(rawGroup.y_label) : '',
            y2_label: rawGroup.y2_label ? String(rawGroup.y2_label) : '',
            y_range: Array.isArray(rawGroup.y_range) && rawGroup.y_range.length === 2 ? rawGroup.y_range : null,
            color_mode: rawGroup.color_mode === 'lap' ? 'lap' : 'channel',
            channels: normChannels,
          });
        }
      } catch (err) {
        diagnostics.push(`Invalid plot_groups.json: ${err.message}`);
      }
    }

    // Synthesize plot groups for channels whose group is not explicitly listed in plot_groups.json
    const autoGroups = new Map();
    for (const ch of channels) {
      if (!ch.group || registeredGroupIds.has(ch.group)) continue;
      if (!autoGroups.has(ch.group)) {
        autoGroups.set(ch.group, {
          id: ch.group,
          label: ch.group_label || ch.group.toUpperCase(),
          y_label: ch.unit || '',
          y2_label: '',
          y_range: null,
          color_mode: 'channel',
          channels: [],
        });
      }
      autoGroups.get(ch.group).channels.push({
        channel_id: ch.channel_id,
        label: ch.label,
        unit: ch.unit,
        color: ch.color,
        yaxis: 'y',
      });
    }
    for (const g of autoGroups.values()) {
      plotGroups.push(g);
    }
  }

  // Resolve any cross-study overlays requested in query.overlays or activeOverlays
  const extraRefs = new Set(activeOverlays);
  if (query.overlays) {
    for (const item of String(query.overlays).split(',')) {
      const trimmed = item.trim();
      if (trimmed) extraRefs.add(trimmed);
    }
  }
  for (const ref of extraRefs) {
    if (!seenOverlayIds.has(ref) && fs.existsSync(studiesDir)) {
      const resolved = resolveCrossStudyOverlay(ref, rootReal);
      if (resolved) {
        overlays.push(resolved);
        seenOverlayIds.add(resolved.id);
        seenOverlayIds.add(resolved.path);
      }
    }
  }

  const etagPayload = JSON.stringify({
    study: requestedStudy,
    studies: studies.map((s) => [s.id, s.mtime, s.overlays, s.channels, s.plot_groups]),
    overlays: overlays.map((o) => [o.id, o.path, o.mtime]),
    channels: channels.map((c) => [c.channel_id, c.path, c.mtime]),
    plotGroups: plotGroups.map((g) => [g.id, g.label, g.channels]),
  });
  const etag = crypto.createHash('sha1').update(etagPayload).digest('hex').slice(0, 16);

  return {
    ok: true,
    http_base: httpBase,
    workspace_dir: workspaceDir,
    studies_dir: studiesDir,
    study: requestedStudy,
    active_overlays: activeOverlays,
    etag,
    studies,
    overlays,
    channels,
    plot_groups: plotGroups,
    diagnostics,
  };
}

log(`Telemetry Companion (Pure Node Zero-Dep) starting... UI_PORT=${UI_PORT}, WS_PORT=${WS_PORT}, WORKSPACE=${workspaceDir}`);

const wsClients = new Set();
let latestAction = { type: 'telemetry_jump', dist: 0, timestamp: new Date().toISOString() };
let currentTelemetryPath = `/telemetry/kartsim/iame_waterswift_restricted_cadet_uk/2026-11-04/Whilton%20Mill%20Zulu?tab=map&lapsA=20_06_practice-28%2C20_06_practice-20&visA=1&turn=4&dist=654.4&delta=1&speed=1&rtab=report&companion=1&ws_port=${WS_PORT}`;

function ensureCompanionParams(urlOrPath) {
  if (!urlOrPath) return urlOrPath;
  let res = urlOrPath;
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

function broadcastJson(payloadObj) {
  const frame = encodeTextFrame(JSON.stringify(payloadObj));
  let sentCount = 0;
  for (const client of wsClients) {
    try {
      if (!client.destroyed && client.writable) {
        client.write(frame);
        sentCount++;
      }
    } catch {}
  }
  return sentCount;
}

let lastWatchedEtag = '';
function computeWatchSnapshotEtag() {
  try {
    return buildManifest({ study: activeStudy }).etag;
  } catch {
    return '';
  }
}
lastWatchedEtag = computeWatchSnapshotEtag();

const watchTimer = setInterval(() => {
  const nextEtag = computeWatchSnapshotEtag();
  if (nextEtag && nextEtag !== lastWatchedEtag) {
    lastWatchedEtag = nextEtag;
    if (wsClients.size > 0) {
      broadcastJson({
        type: 'workspace_sync',
        study: activeStudy,
        etag: nextEtag,
        httpBase: getHttpBase(),
        timestamp: new Date().toISOString(),
      });
    }
  }
}, 1000);
if (typeof watchTimer.unref === 'function') watchTimer.unref();

function handleWebSocketUpgrade(req, socket) {
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

  const readyFrame = encodeTextFrame(
    JSON.stringify({
      type: 'COMPANION_READY',
      port: WS_PORT,
      httpBase: getHttpBase(),
      study: activeStudy,
      activeOverlays,
      etag: lastWatchedEtag || computeWatchSnapshotEtag(),
    })
  );
  socket.write(readyFrame);

  socket.on('data', (chunk) => {
    if (chunk.length < 2) return;
    const opcode = chunk[0] & 0x0f;
    if (opcode === 0x8) {
      try { socket.write(Buffer.from([0x88, 0x00])); } catch {}
      socket.end();
      return;
    }
    if (opcode === 0x9) {
      const isMasked = (chunk[1] & 0x80) !== 0;
      const payloadLen = chunk[1] & 0x7f;
      const payloadOffset = isMasked ? 6 : 2;
      const payload = chunk.subarray(payloadOffset, payloadOffset + payloadLen);
      try { socket.write(Buffer.concat([Buffer.from([0x8a, payload.length]), payload])); } catch {}
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

// ---------------------------------------------------------------------------
// MCP Server Tool Definitions & Handlers
// ---------------------------------------------------------------------------

const MCP_TOOLS = [
  {
    name: 'set_telemetry_view',
    description:
      'Controls the Antigravity Telemetry Viewer side panel identically to clicking interactive report pills, plus switching active workspace study subfolders, selecting/clearing GeoJSON map overlays and heatmaps, opening custom plot groups, and navigating sessions.',
    inputSchema: {
      type: 'object',
      properties: {
        study: {
          type: 'string',
          description: 'Active study subfolder relative to <workspace>/studies/ (e.g. "2026-11-11_spa_eeg").',
        },
        overlays: {
          type: 'array',
          items: { type: 'string' },
          description:
            'Overlay IDs (within active study) or relative paths (across studies) to display on the map right now. Pass [] to hide all overlays while keeping files saved on disk.',
        },
        toggle_overlay: {
          type: 'string',
          description: 'Toggle a single GeoJSON overlay ID on or off.',
        },
        plots: {
          type: 'array',
          items: { type: 'string' },
          description:
            'Visible bottom-bar plots, e.g. ["speed", "delta", "pedals", "eeg"].',
        },
        toggle_plot: {
          type: 'string',
          description: 'Toggle a single bottom plot channel/group on or off.',
        },
        session_url: {
          type: 'string',
          description: 'Navigate viewer to a specific telemetry meeting/session URL or path.',
        },
        tab: {
          type: 'string',
          enum: ['map', 'stats'],
          description: 'Main view tab ("map" or "stats").',
        },
        right_tab: {
          type: 'string',
          enum: ['cornering', 'acceleration', 'slip_angle', 'report'],
          description: 'Right side-panel tab.',
        },
        side_panel: {
          type: 'string',
          enum: ['collapsed', 'expanded'],
          description: 'Collapse or expand the right side panel.',
        },
        laps_a: {
          type: 'array',
          items: { type: 'string' },
          description: 'Active Group A reference laps (e.g. ["20_06_practice-28"]).',
        },
        laps_b: {
          type: 'array',
          items: { type: 'string' },
          description: 'Active Group B target laps (e.g. ["20_06_practice-20"]). Pass [] to clear.',
        },
        dist: {
          type: 'number',
          description: 'Seek distance cursor and kart marker to distance in meters.',
        },
        focus_range: {
          type: 'array',
          items: { type: 'number' },
          minItems: 2,
          maxItems: 2,
          description: 'Zoom both map bounds and bottom plot X-axis to [start_m, end_m].',
        },
        xlim: {
          type: 'array',
          items: { type: 'number' },
          minItems: 2,
          maxItems: 2,
          description: 'Zoom bottom plot X-axis only to [start_m, end_m].',
        },
        map_range: {
          type: 'array',
          items: { type: 'number' },
          minItems: 2,
          maxItems: 2,
          description: 'Zoom map bounds only to track segment [start_m, end_m].',
        },
        lat: { type: 'number', description: 'Center map on GPS latitude.' },
        lng: { type: 'number', description: 'Center map on GPS longitude.' },
        zoom: { type: 'number', description: 'Google Maps zoom level.' },
        turn: {
          type: 'integer',
          description: '1-indexed turn number to select and focus (e.g. 1 for Turn 1).',
        },
        trajectory_color: {
          type: 'string',
          description: 'Trajectory color mode ("pedals", "speed", "group", "sector", "none").',
        },
        map_type: {
          type: 'string',
          enum: ['satellite', 'kartsim', 'hybrid'],
          description: 'Map background mode.',
        },
        workspace_dir: {
          type: 'string',
          description: 'Optional workspace root path override.',
        },
      },
    },
  },
  {
    name: 'list_workspace_studies',
    description:
      'Lists all saved study subfolders under <workspace>/studies/ along with their overlays, custom derived channels, plot groups, and README status so past analyses can be discovered and reused.',
    inputSchema: {
      type: 'object',
      properties: {
        workspace_dir: {
          type: 'string',
          description: 'Optional workspace root path override.',
        },
      },
    },
  },
  {
    name: 'register_plot_group',
    description:
      'Creates or updates a custom bottom-bar plot group (e.g. "eeg" / "EEG") in <workspace>/studies/<study>/plot_groups.json and immediately syncs the Telemetry Viewer UI.',
    inputSchema: {
      type: 'object',
      required: ['id', 'label', 'channels'],
      properties: {
        id: {
          type: 'string',
          description: 'Plot group identifier (lowercase slug, e.g. "eeg").',
        },
        label: {
          type: 'string',
          description: 'Display label on the bottom plot tab button (e.g. "EEG").',
        },
        study: {
          type: 'string',
          description: 'Target study subfolder relative to <workspace>/studies/ (defaults to active study).',
        },
        y_label: {
          type: 'string',
          description: 'Primary Y-axis label (e.g. "Band Power (Z-score)").',
        },
        y2_label: {
          type: 'string',
          description: 'Optional secondary right-hand Y-axis label.',
        },
        y_range: {
          type: 'array',
          items: { type: 'number' },
          minItems: 2,
          maxItems: 2,
          description: 'Optional fixed Y-axis [min, max]; omit for dynamic auto-scaling.',
        },
        color_mode: {
          type: 'string',
          enum: ['channel', 'lap'],
          description: '"channel" colors by channel with solid/dashed per lap; "lap" colors by lap.',
        },
        channels: {
          type: 'array',
          description: 'Channels rendered in this plot group.',
          items: {
            type: 'object',
            required: ['channel_id'],
            properties: {
              channel_id: { type: 'string' },
              label: { type: 'string' },
              unit: { type: 'string' },
              color: { type: 'string' },
              yaxis: { type: 'string', enum: ['y', 'y2'] },
            },
          },
        },
        open_plot: {
          type: 'boolean',
          description: 'If true, immediately opens this plot group in the Telemetry Viewer bottom bar.',
        },
        workspace_dir: {
          type: 'string',
          description: 'Optional workspace root path override.',
        },
      },
    },
  },
  {
    name: 'sync_workspace_data',
    description:
      'Validates study overlays/channels/plot_groups in <workspace>/studies/, updates workspace/study binding if provided, and broadcasts workspace_sync to reload modified files in the UI.',
    inputSchema: {
      type: 'object',
      properties: {
        study: {
          type: 'string',
          description: 'Optional study subfolder relative to <workspace>/studies/.',
        },
        workspace_dir: {
          type: 'string',
          description: 'Optional workspace root path override.',
        },
      },
    },
  },
  {
    name: 'get_telemetry_view_status',
    description:
      'Returns Companion sidecar connection status, connected WebSocket viewer count, current session URL, active workspace & study, active overlays, and available plot groups.',
    inputSchema: {
      type: 'object',
      properties: {},
    },
  },
];

function applyWorkspaceOverride(dirArg) {
  if (!dirArg) return;
  const resolved = path.resolve(String(dirArg));
  workspaceDir = resolved;
  customStudiesDirOverride = '';
  explicitWorkspaceBound = true;
}

function dispatchActionPayload(rawArgs) {
  const payload = { type: 'telemetry_jump', timestamp: new Date().toISOString() };

  if (rawArgs.workspace_dir) {
    applyWorkspaceOverride(rawArgs.workspace_dir);
  }
  if (rawArgs.study !== undefined) {
    activeStudy = normalizeStudyId(rawArgs.study);
    payload.study = activeStudy;
  }
  if (rawArgs.overlays !== undefined) {
    activeOverlays = Array.isArray(rawArgs.overlays) ? rawArgs.overlays.map(String) : [];
    payload.overlays = activeOverlays;
  }
  if (rawArgs.toggle_overlay !== undefined) {
    const tId = String(rawArgs.toggle_overlay);
    const idx = activeOverlays.indexOf(tId);
    if (idx >= 0) activeOverlays.splice(idx, 1);
    else activeOverlays.push(tId);
    payload.toggleOverlay = tId;
  }

  savePersistedState();

  if (rawArgs.session_url) {
    currentTelemetryPath = ensureCompanionParams(String(rawArgs.session_url));
    payload.sessionUrl = currentTelemetryPath;
  }
  if (rawArgs.tab !== undefined) payload.tab = rawArgs.tab;
  if (rawArgs.right_tab !== undefined) payload.rtab = rawArgs.right_tab;
  if (rawArgs.side_panel !== undefined) payload.sidePanel = rawArgs.side_panel;
  if (rawArgs.laps_a !== undefined) payload.lapsA = rawArgs.laps_a;
  if (rawArgs.laps_b !== undefined) payload.lapsB = rawArgs.laps_b;
  if (rawArgs.dist !== undefined) payload.dist = rawArgs.dist;
  if (rawArgs.focus_range !== undefined) payload.focusRange = rawArgs.focus_range;
  if (rawArgs.xlim !== undefined) payload.xlim = rawArgs.xlim;
  if (rawArgs.map_range !== undefined) payload.mapRange = rawArgs.map_range;
  if (rawArgs.lat !== undefined) payload.lat = rawArgs.lat;
  if (rawArgs.lng !== undefined) payload.lng = rawArgs.lng;
  if (rawArgs.zoom !== undefined) payload.zoom = rawArgs.zoom;
  if (rawArgs.turn !== undefined && rawArgs.turn !== null) {
    payload.turnNumber = Number(rawArgs.turn);
  }
  if (rawArgs.plots !== undefined) payload.plots = rawArgs.plots;
  if (rawArgs.toggle_plot !== undefined) payload.togglePlot = rawArgs.toggle_plot;
  if (rawArgs.trajectory_color !== undefined) payload.tcol = rawArgs.trajectory_color;
  if (rawArgs.map_type !== undefined) payload.mapType = rawArgs.map_type;

  latestAction = payload;
  lastWatchedEtag = computeWatchSnapshotEtag();

  let syncSent = 0;
  if (rawArgs.workspace_dir !== undefined || rawArgs.study !== undefined || rawArgs.overlays !== undefined) {
    syncSent = broadcastJson({
      type: 'workspace_sync',
      study: activeStudy,
      etag: lastWatchedEtag,
      httpBase: getHttpBase(),
      timestamp: payload.timestamp,
    });
  }
  const sentCount = broadcastJson(payload);
  return {
    ok: true,
    clients_notified: Math.max(sentCount, syncSent),
    active_study: activeStudy,
    active_overlays: activeOverlays,
    action: payload,
  };
}

function executeMcpTool(name, args = {}) {
  if (name === 'set_telemetry_view') {
    return dispatchActionPayload(args);
  }

  if (name === 'list_workspace_studies') {
    if (args.workspace_dir) {
      applyWorkspaceOverride(args.workspace_dir);
      savePersistedState();
    }
    const studies = discoverStudies();
    return {
      ok: true,
      workspace_dir: workspaceDir,
      studies_dir: getStudiesDir(),
      active_study: activeStudy,
      active_overlays: activeOverlays,
      studies,
    };
  }

  if (name === 'register_plot_group') {
    if (args.workspace_dir) {
      applyWorkspaceOverride(args.workspace_dir);
    }
    const targetStudy = args.study !== undefined ? normalizeStudyId(args.study) : activeStudy;
    if (args.study !== undefined) {
      activeStudy = targetStudy;
    }
    savePersistedState();

    const groupSlug = String(args.id || '').trim().toLowerCase();
    if (!groupSlug || !/^[a-z0-9_-]+$/.test(groupSlug)) {
      throw new Error(`Invalid plot group id: ${args.id}`);
    }

    const pgRel = targetStudy ? `${targetStudy}/plot_groups.json` : 'plot_groups.json';
    const studiesDir = getStudiesDir();
    fs.mkdirSync(studiesDir, { recursive: true });

    const safeTarget = resolveSafeStudyPath(pgRel, { mustExist: false });
    if (!safeTarget.ok) {
      throw new Error(safeTarget.error);
    }

    fs.mkdirSync(path.dirname(safeTarget.fullPath), { recursive: true });
    let existing = { groups: [] };
    if (fs.existsSync(safeTarget.fullPath)) {
      try {
        const parsed = JSON.parse(fs.readFileSync(safeTarget.fullPath, 'utf8'));
        if (parsed && Array.isArray(parsed.groups)) existing = parsed;
      } catch {}
    }

    const groupEntry = {
      id: groupSlug,
      label: String(args.label || groupSlug.toUpperCase()),
      y_label: args.y_label ? String(args.y_label) : '',
      y2_label: args.y2_label ? String(args.y2_label) : '',
      y_range: Array.isArray(args.y_range) && args.y_range.length === 2 ? args.y_range : null,
      color_mode: args.color_mode === 'lap' ? 'lap' : 'channel',
      channels: Array.isArray(args.channels) ? args.channels : [],
    };

    const idx = existing.groups.findIndex((g) => g && String(g.id).toLowerCase() === groupSlug);
    if (idx >= 0) existing.groups[idx] = groupEntry;
    else existing.groups.push(groupEntry);

    fs.writeFileSync(safeTarget.fullPath, JSON.stringify(existing, null, 2) + '\n', 'utf8');

    lastWatchedEtag = computeWatchSnapshotEtag();
    const notified = broadcastJson({
      type: 'workspace_sync',
      study: activeStudy,
      etag: lastWatchedEtag,
      httpBase: getHttpBase(),
      timestamp: new Date().toISOString(),
    });

    if (args.open_plot) {
      broadcastJson({
        type: 'telemetry_jump',
        study: activeStudy,
        togglePlot: groupSlug,
        openPlot: groupSlug,
        timestamp: new Date().toISOString(),
      });
    }

    return {
      ok: true,
      study: targetStudy,
      file: safeTarget.fullPath,
      group: groupEntry,
      clients_notified: notified,
    };
  }

  if (name === 'sync_workspace_data') {
    if (args.workspace_dir) {
      applyWorkspaceOverride(args.workspace_dir);
    }
    if (args.study !== undefined) {
      activeStudy = normalizeStudyId(args.study);
    }
    savePersistedState();
    const manifest = buildManifest({ study: activeStudy });
    lastWatchedEtag = manifest.etag;
    const notified = broadcastJson({
      type: 'workspace_sync',
      study: activeStudy,
      etag: manifest.etag,
      httpBase: getHttpBase(),
      timestamp: new Date().toISOString(),
    });
    return {
      ok: true,
      clients_notified: notified,
      study: manifest.study,
      workspace_dir: manifest.workspace_dir,
      studies_dir: manifest.studies_dir,
      overlays_count: manifest.overlays.length,
      channels_count: manifest.channels.length,
      plot_groups: manifest.plot_groups.map((g) => g.id),
      diagnostics: manifest.diagnostics,
    };
  }

  if (name === 'get_telemetry_view_status') {
    const manifest = buildManifest({ study: activeStudy });
    return {
      ok: true,
      clients_connected: wsClients.size,
      ui_port: UI_PORT,
      ws_port: WS_PORT,
      http_base: getHttpBase(),
      session_url: currentTelemetryPath,
      workspace_dir: workspaceDir,
      studies_dir: getStudiesDir(),
      active_study: activeStudy,
      active_overlays: activeOverlays,
      available_studies: manifest.studies.map((s) => s.id),
      study_overlays: manifest.overlays.map((o) => o.id),
      study_channels: manifest.channels.map((c) => c.channel_id),
      study_plot_groups: manifest.plot_groups.map((g) => g.id),
      latest_action: latestAction,
    };
  }

  throw new Error(`Unknown tool: ${name}`);
}

function handleMcpRpcObject(rpcReq) {
  if (!rpcReq || typeof rpcReq !== 'object') {
    return { jsonrpc: '2.0', id: null, error: { code: -32600, message: 'Invalid Request' } };
  }
  const { id, method, params } = rpcReq;
  const isNotification = id === undefined;

  if (method === 'notifications/initialized' || (typeof method === 'string' && method.startsWith('notifications/'))) {
    return null;
  }

  if (method === 'initialize') {
    const clientProto = params && params.protocolVersion ? String(params.protocolVersion) : '2024-11-05';
    return {
      jsonrpc: '2.0',
      id: isNotification ? null : id,
      result: {
        protocolVersion: clientProto,
        capabilities: {
          tools: { listChanged: false },
        },
        serverInfo: {
          name: 'brbrtelemetry-companion',
          version: '1.1.0',
        },
      },
    };
  }

  if (method === 'ping') {
    return { jsonrpc: '2.0', id: isNotification ? null : id, result: {} };
  }

  if (method === 'tools/list') {
    return {
      jsonrpc: '2.0',
      id: isNotification ? null : id,
      result: { tools: MCP_TOOLS },
    };
  }

  if (method === 'tools/call') {
    const toolName = params && params.name ? String(params.name) : '';
    const toolArgs = (params && params.arguments) || {};
    try {
      const resultObj = executeMcpTool(toolName, toolArgs);
      return {
        jsonrpc: '2.0',
        id: isNotification ? null : id,
        result: {
          content: [{ type: 'text', text: JSON.stringify(resultObj, null, 2) }],
          isError: false,
        },
      };
    } catch (err) {
      return {
        jsonrpc: '2.0',
        id: isNotification ? null : id,
        result: {
          content: [{ type: 'text', text: JSON.stringify({ ok: false, error: err.message }) }],
          isError: true,
        },
      };
    }
  }

  if (isNotification) return null;
  return {
    jsonrpc: '2.0',
    id,
    error: { code: -32601, message: `Method not found: ${method}` },
  };
}

function sendJson(res, status, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(status, {
    ...CORS_HEADERS,
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-cache',
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
}

function readRequestBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

function createHttpHandler() {
  return async (clientReq, clientRes) => {
    const reqUrl = clientReq.url || '/';
    const rawPathPart = reqUrl.split('?')[0] || '/';
    const parsedUrl = new URL(reqUrl, `http://127.0.0.1:${UI_PORT}`);

    if (clientReq.method === 'OPTIONS') {
      clientRes.writeHead(204, CORS_HEADERS);
      clientRes.end();
      return;
    }

    const callerCwd = clientReq.headers['x-workspace-cwd'];
    if (typeof callerCwd === 'string' && callerCwd) {
      maybeAdoptCallerCwd(callerCwd);
    }

    // 1. Static study files: GET /files/<subpath>
    if (rawPathPart.startsWith('/files/')) {
      if (clientReq.method !== 'GET' && clientReq.method !== 'HEAD') {
        sendJson(clientRes, 405, { error: 'Method not allowed' });
        return;
      }
      const subpath = rawPathPart.slice('/files/'.length);
      const resolved = resolveSafeStudyPath(subpath, { mustExist: true });
      if (!resolved.ok) {
        sendJson(clientRes, resolved.status, { error: resolved.error });
        return;
      }
      let stat;
      try {
        stat = fs.statSync(resolved.fullPath);
      } catch {
        sendJson(clientRes, 404, { error: 'File not found' });
        return;
      }
      if (!stat.isFile()) {
        sendJson(clientRes, 404, { error: 'Not a file' });
        return;
      }
      const ext = path.extname(resolved.fullPath).toLowerCase();
      const contentType = MIME_TYPES[ext] || 'application/octet-stream';
      const data = fs.readFileSync(resolved.fullPath);
      clientRes.writeHead(200, {
        ...CORS_HEADERS,
        'Content-Type': contentType,
        'Cache-Control': 'no-cache',
        'Content-Length': data.length,
      });
      if (clientReq.method === 'HEAD') clientRes.end();
      else clientRes.end(data);
      return;
    }

    // 2. Workspace studies discovery: GET /api/workspace/studies
    if (parsedUrl.pathname === '/api/workspace/studies' && clientReq.method === 'GET') {
      sendJson(clientRes, 200, {
        ok: true,
        workspace_dir: workspaceDir,
        studies_dir: getStudiesDir(),
        active_study: activeStudy,
        studies: discoverStudies(),
      });
      return;
    }

    // 3. Scoped workspace manifest: GET /api/workspace/manifest
    if (parsedUrl.pathname === '/api/workspace/manifest' && clientReq.method === 'GET') {
      try {
        const query = {
          study: parsedUrl.searchParams.has('study') ? parsedUrl.searchParams.get('study') : undefined,
          overlays: parsedUrl.searchParams.get('overlays') || '',
          date: parsedUrl.searchParams.get('date') || '',
          track: parsedUrl.searchParams.get('track') || '',
          session_id: parsedUrl.searchParams.get('session_id') || '',
        };
        sendJson(clientRes, 200, buildManifest(query));
      } catch (err) {
        sendJson(clientRes, 400, { ok: false, error: err.message });
      }
      return;
    }

    // 4. Workspace configuration update: POST /api/workspace
    if (parsedUrl.pathname === '/api/workspace') {
      if (clientReq.method === 'POST') {
        try {
          const body = await readRequestBody(clientReq);
          const payload = JSON.parse(body || '{}');
          if (payload.workspace_dir) applyWorkspaceOverride(payload.workspace_dir);
          if (payload.study !== undefined) activeStudy = normalizeStudyId(payload.study);
          if (payload.overlays !== undefined && Array.isArray(payload.overlays)) {
            activeOverlays = payload.overlays.map(String);
          }
          savePersistedState();
          const manifest = buildManifest({ study: activeStudy });
          lastWatchedEtag = manifest.etag;
          const notified = broadcastJson({
            type: 'workspace_sync',
            study: activeStudy,
            etag: manifest.etag,
            httpBase: getHttpBase(),
            timestamp: new Date().toISOString(),
          });
          sendJson(clientRes, 200, {
            ok: true,
            clients_notified: notified,
            workspace_dir: workspaceDir,
            studies_dir: getStudiesDir(),
            active_study: activeStudy,
            active_overlays: activeOverlays,
            etag: manifest.etag,
          });
        } catch (err) {
          sendJson(clientRes, 400, { ok: false, error: err.message });
        }
        return;
      }
      sendJson(clientRes, 200, {
        ok: true,
        workspace_dir: workspaceDir,
        studies_dir: getStudiesDir(),
        active_study: activeStudy,
        active_overlays: activeOverlays,
      });
      return;
    }

    // 5. MCP Streamable HTTP endpoint: POST /mcp
    if (parsedUrl.pathname === '/mcp') {
      if (clientReq.method !== 'POST') {
        sendJson(clientRes, 200, { name: 'brbrtelemetry-companion', status: 'ok' });
        return;
      }
      try {
        const body = await readRequestBody(clientReq);
        const rpcPayload = JSON.parse(body || '{}');
        if (Array.isArray(rpcPayload)) {
          const responses = rpcPayload.map(handleMcpRpcObject).filter(Boolean);
          if (responses.length === 0) {
            clientRes.writeHead(202, CORS_HEADERS);
            clientRes.end();
          } else {
            sendJson(clientRes, 200, responses);
          }
          return;
        }
        const rpcResp = handleMcpRpcObject(rpcPayload);
        if (!rpcResp) {
          clientRes.writeHead(202, CORS_HEADERS);
          clientRes.end();
        } else {
          sendJson(clientRes, 200, rpcResp);
        }
      } catch (err) {
        sendJson(clientRes, 400, {
          jsonrpc: '2.0',
          id: null,
          error: { code: -32700, message: `Parse error: ${err.message}` },
        });
      }
      return;
    }

    // 6. Companion action dispatch API: /api/action
    if (parsedUrl.pathname === '/api/action') {
      if (clientReq.method === 'POST') {
        try {
          const body = await readRequestBody(clientReq);
          const payload = JSON.parse(body || '{}');
          if (payload.url) {
            currentTelemetryPath = ensureCompanionParams(payload.url);
            payload.sessionUrl = currentTelemetryPath;
          }
          if (payload.sessionUrl) {
            currentTelemetryPath = ensureCompanionParams(payload.sessionUrl);
            payload.sessionUrl = currentTelemetryPath;
          }
          if (payload.study !== undefined) {
            activeStudy = normalizeStudyId(payload.study);
            payload.study = activeStudy;
          }
          if (Array.isArray(payload.overlays)) {
            activeOverlays = payload.overlays.map(String);
          }
          savePersistedState();
          if (!payload.type) payload.type = 'telemetry_jump';
          payload.timestamp = new Date().toISOString();
          latestAction = payload;

          log(`Dispatched action: ${JSON.stringify(payload)} to ${wsClients.size} viewer client(s)`);
          const sentCount = broadcastJson(payload);
          sendJson(clientRes, 200, { ok: true, sentTo: sentCount, action: payload });
        } catch (err) {
          sendJson(clientRes, 400, { error: err.message });
        }
        return;
      }
      sendJson(clientRes, 200, {
        latestAction,
        clientsConnected: wsClients.size,
        activeStudy,
        activeOverlays,
      });
      return;
    }

    // 7. Health status
    if (
      parsedUrl.pathname === '/health' ||
      parsedUrl.pathname === '/healthz' ||
      parsedUrl.pathname === '/api/status'
    ) {
      sendJson(clientRes, 200, {
        ok: true,
        status: 'ok',
        clientsConnected: wsClients.size,
        uiPort: UI_PORT,
        wsPort: WS_PORT,
        workspaceDir,
        studiesDir: getStudiesDir(),
        activeStudy,
      });
      return;
    }

    // 8. Default route serves a seamless wrapper pointing directly to the HTTPS host via /auth,
    // establishing the partitioned cookie and preserving the production referrer for Google Maps.
    const rawPath =
      parsedUrl.searchParams.get('url') || parsedUrl.searchParams.get('next') || currentTelemetryPath;
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
      ...CORS_HEADERS,
      'Content-Type': 'text/html; charset=utf-8',
      'Cache-Control': 'no-cache',
    });
    clientRes.end(wrapperHtml);
  };
}

const uiServer = http.createServer(createHttpHandler());
uiServer.on('upgrade', handleWebSocketUpgrade);
uiServer.on('error', (err) => log(`UI Server error on port ${UI_PORT}: ${err.message}`));
uiServer.listen(UI_PORT, '127.0.0.1', () => {
  log(`UI Server listening on http://127.0.0.1:${UI_PORT}`);
});

if (UI_PORT !== WS_PORT) {
  const wsServer = http.createServer(createHttpHandler());
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
