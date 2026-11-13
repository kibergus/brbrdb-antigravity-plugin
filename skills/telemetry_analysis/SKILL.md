---
name: telemetry_analysis
description: Analyzes karting and racing telemetry data, session URLs (/telemetry/<league>/<class>/<date>/<track>), and logged channels using the telemetry and brbrtelemetry_companion MCP servers—without using external browser automation—producing data-grounded insights and synchronized controls for the Antigravity Telemetry Viewer side panel.
---

# Telemetry Analysis & Companion Skill

Pairs conversational telemetry analysis on the left with the interactive **BrBrDb Telemetry** viewer in Antigravity's auxiliary side panel on the right, backed by two MCP servers:
- **`telemetry` MCP server**: Session discovery (`list_sessions`), track geometry (`get_track_info`), lap statistics (`get_pace_summary`, `get_stats`, `get_aggregates`), static inspection plots, and numeric sample arrays (`get_telemetry_data`, including high-rate `raw_aux_stream` auxiliary streams).
- **`brbrtelemetry_companion` MCP server** (local sidecar on `127.0.0.1:38472`): Live viewer control (`set_telemetry_view`), study discovery (`list_workspace_studies`), custom plot-group registration (`register_plot_group`), live reload (`sync_workspace_data`), and connection status (`get_telemetry_view_status`).

> [!IMPORTANT]
> **Do NOT use the `browser` subagent, `curl`, or web scraping for telemetry URLs.**
> Treat any URL like `https://<host>/telemetry/<league>/<class_name>/<date>/<track>?session_id=<session_id>` as a structured session identifier, NOT a web page to browse:
> 1. Parse `league`, `class_name`, `date`, URL-decoded `track`, and `session_id` directly from the URL.
> 2. Query the **`telemetry` MCP server** (`list_sessions`, `get_telemetry_data`, `get_pace_summary`, `get_stats`) to answer questions about sessions, logged channels, or laps.
> 3. Drive the integrated **Telemetry Viewer sidecar** via `brbrtelemetry_companion` (`set_telemetry_view`) whenever visual UI navigation is needed.

---

## 1. Opening the Sidecar & Selecting Laps

When introducing or switching a session:
1. Emit the sidecar pill (matching `sidecar.json`'s view `title` per `ui-plugin-navigation`) so the user can open or focus the panel:
   ```markdown
   [BrBrDb Telemetry](sidecar://brbrtelemetry/telemetry-viewer/)
   ```
2. **Lap ID Format**: Strip `.csv` from the driver's `session_id` (or `actual_best_session` from `get_pace_summary`) and append `-{lap_number}`:
   - Single-driver session: `"20_06_practice-28"`
   - Multi-driver session: `"18_43_practice_kartsim_coach_rs-25"`, `"18_43_practice_katia_guseinova-36"`
3. **Fast-Path (Open / Compare Laps Only)**: If the user asks to open a session or display specific laps without requesting a corner-by-corner breakdown, run **only** these 2 steps and stop:
   - Call `get_pace_summary(track, date, session_id)` (or `get_stats`) to get lap numbers and driver `session_id` stems.
   - Call `set_telemetry_view(session_url="/telemetry/...", laps_a=[...], tab="map")` and reply with `[BrBrDb Telemetry](sidecar://brbrtelemetry/telemetry-viewer/)` plus a concise summary table.

---

## 2. Workspace Studies, Map Overlays & Custom Channels (`<workspace>/studies/`)

Store generated GeoJSON overlays, derived channels, and analysis scripts under `<workspace>/studies/<YYYY-MM-DD>_<track>_<topic>/`:

```text
<workspace>/studies/<study_id>/
├── README.md
├── overlays/<name>.geojson      # Vector or Gaussian heatmap layers
├── channels/<name>.json         # brbr.custom_channel.v1 series
├── plot_groups.json             # Managed via register_plot_group
└── scripts/<script>.py
```

- **Check Existing Studies First**: Call `list_workspace_studies()` before creating new folders so prior work can be reused or compared.
- **Explicit Overlay Selection**: Activating `study="<study_id>"` scopes custom channels/tabs to that study. Never auto-dump all GeoJSON files onto the map—pass `overlays=[...]` explicitly in `set_telemetry_view` (or `overlays=[]` to clear).
- **Creating Overlays, Derived Channels, or Plot Groups**: Read [overlays_and_channels.md](references/overlays_and_channels.md) first for exact GeoJSON `metadata`, `brbr.custom_channel.v1` (`session_id` stem matching & dynamic `sample_rate_hz` handling), and `register_plot_group` rules (1–2 compatible traces per chart; distinct IDs from built-in `eeg`/`ecg`/`emg`).

---

## 3. Interactive In-Text Pill Commentary (`<agent-embed>`)

Format key spatial evidence (braking points, apexes, sensor events, overlay toggles) as clickable inline pills using Antigravity's **Generative UI (`<agent-embed>`)** workflow.

> [!IMPORTANT]
> **NEVER output ` ```html ... ``` ` blocks directly in chat** (they render as literal code, not buttons). Always:
> 1. `write_file` a self-contained `.html` file to `<appDataDir>/brain/<conversation-id>/<widget>.html` with `Overwrite: true` and `ArtifactMetadata: { "Summary": "Interactive telemetry pills", "UserFacing": true, "RequestFeedback": false }`.
> 2. Place `<agent-embed src="file:///absolute/path/to/brain/<conversation-id>/<widget>.html"></agent-embed>` on its own line in chat (outside backticks/fences).

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
</head>
<body class="bg-transparent text-[var(--foreground)] antialiased m-0 p-0 font-sans">
  <p class="text-sm leading-relaxed text-[var(--foreground)] m-0">
    Benchmark Lap 6 brakes at
    <button onclick="trigger({ dist: 316.5, plots: ['speed', 'pedals'], focusRange: [290, 380], overlays: ['braking_zones'] })"
      class="inline-flex items-center px-1.5 py-0.5 mx-0.5 rounded bg-sky-500/15 text-sky-400 font-mono text-xs font-medium border border-sky-500/30 hover:bg-sky-500/25 active:scale-95 transition-all cursor-pointer">
      316.5m
    </button>, whereas Lap 5 brakes late at
    <button onclick="trigger({ dist: 319.5, turn: 3, plots: ['speed', 'eeg_bands'], overlays: ['theta_heatmap'] })"
      class="inline-flex items-center px-1.5 py-0.5 mx-0.5 rounded bg-rose-500/15 text-rose-400 font-mono text-xs font-medium border border-rose-500/30 hover:bg-rose-500/25 active:scale-95 transition-all cursor-pointer">
      319.5m (Turn 3)
    </button>.
    <span id="pill-ack" class="text-xs font-mono text-emerald-400 ml-1.5"></span>
  </p>
  <script>
    async function trigger(opts) {
      const ack = document.getElementById('pill-ack');
      try {
        await fetch('http://127.0.0.1:38472/api/action', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(Object.assign({ type: 'telemetry_jump', tab: 'map' }, opts))
        });
        ack.textContent = '✓ ' + (opts.dist !== undefined ? opts.dist + 'm' : 'Synced');
        setTimeout(() => { ack.textContent = ''; }, 2000);
      } catch (e) { ack.textContent = '✗ Error'; }
    }
  </script>
</body>
</html>
```

### `/api/action` Payload Keys (camelCase equivalents of `set_telemetry_view`)
- **Session & Laps**: `url` / `sessionUrl` (relative or full `/telemetry/...` URL), `lapsA` / `lapsB` (array of `<session_stem>-<lap>`), `tab` (`"map" | "stats"`), `rtab` (`"cornering" | "acceleration" | "slip_angle" | "report"`).
- **Cursor & Framing**: `dist` (meters), `turn` / `turnNumber` (**both 1-indexed**, e.g. `1` = Turn 1), `focusRange` (`[min, max]` sets both map & X-axis), `xlim` (`[min, max]` plot only), `mapRange` (`[min, max]` map only).
- **Plots & Study Layers**: `plots` (array of visible plot IDs, e.g. `["speed", "delta", "eeg_bands"]`), `openPlot` / `togglePlot` (string), `study` (string), `overlays` (array, `[]` clears all), `toggleOverlay` (string).
- **Map Styling**: `tcol` (`"pedals" | "speed" | "group" | "sector" | "none"`), `mapType` (`"satellite" | "kartsim" | "hybrid"`).

---

## 4. Telemetry Analysis Methodology

1. **Channel Audit & Grounded Evidence**:
   - Inspect recorded channels via `list_sessions` / `get_telemetry_data` (`Speed`, `accel`, GPS `Latitude`/`Longitude`, `Steering Angle`, `Throttle`, `Brake`, `EEG`/`ECG`/`EMG`, etc.). Do not search outside `<workspace>/studies/` for server logs/DBs.
   - Calibrate confidence strictly to logged sensors:
     - **Direct Evidence (High)**: Measured traces (`Speed`, `Delta T`, GPS line, logged sensors).
     - **Inferred (Medium)**: Surrogates (e.g. longitudinal `accel` when pedals are unlogged).
     - **Hypothesis (Low–Medium)**: Unmeasured driver inputs (state explicitly as a hypothesis).
2. **Corner Benchmark Rule**:
   - For any specific corner `N`, select the benchmark reference lap by the fastest **corner segment time** (`turn_time_s` from `get_stats(..., turn_index=N)`), **never** full-lap time.
3. **Viewer Readability Limits**:
   - Compare **at most 2 laps** at once (1 Benchmark vs. 1 Target).
   - Show **at most 2–3 bottom plots** simultaneously so the track map stays visible (even if a study registers more tabs in the bottom bar).
4. **Corner Investigation (Sub-Agents for Multi-Turn Reports)**:
   - Delegate per-corner deep dives (`start_m` to `end_m`) using [subagent_prompt.md](references/subagent_prompt.md), comparing entry, min-apex, corner-exit, and straight-exit speeds (`km/h` exclusively) plus **Delta T inflection** (where time loss begins: entry, apex, or exit).
   - Keep coaching takeaways positive, specific, and accessible for junior drivers (~11 years old).

---

## 5. Report Publishing Policy (`save_report` / `edit_report`)

- **Local by Default**: Deliver commentary, `<agent-embed>` pills, and `<workspace>/studies/` files locally—**never** call `save_report` or `edit_report` unless the user explicitly asks to publish/save to the website (when requested, format using [report_template.html](references/report_template.html)).
- **Graceful `PermissionError` Handling**: If `save_report` fails with `PermissionError` (`manage_reports` permission required), do not treat it as a failure; inform the user that server publishing requires elevated permissions and confirm all local studies and viewer controls remain active.
