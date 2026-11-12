---
name: telemetry_analysis
description: Analyzes karting telemetry data using MCP server tools and corner sub-agents, comparing reference benchmark vs target laps with Delta T inflection analysis and data-grounded causation chains, producing interactive chat commentary and synchronized controls for the Antigravity Telemetry Viewer companion side panel.
---

# Telemetry Analysis & Companion Skill

This skill provides an autonomous, turn-by-turn workflow for analyzing karting and racing telemetry data inside Google Antigravity. It pairs conversational chat commentary on the left with the interactive **Telemetry Viewer** in Antigravity's auxiliary side panel on the right, backed by two MCP servers:
- **`telemetry` / `brbrdb` MCP server**: Session discovery, track geometry, lap statistics, inspection plots, and raw numeric telemetry (`get_telemetry_data`, including high-rate `raw_aux_stream` auxiliary streams).
- **`companion` MCP server** (bundled locally with the plugin on `127.0.0.1:38472`): Live Telemetry Viewer control (`set_telemetry_view`), workspace study discovery (`list_workspace_studies`), dynamic plot group registration (`register_plot_group`), live reload (`sync_workspace_data`), and connection status (`get_telemetry_view_status`).

```
+-----------------------------------------------------------------------------------+
| Antigravity                                                                       |
| +-----------------------------------------------+ +-----------------------------+ |
| | Left: Agent Chat & Interactive Commentary     | | Right: Telemetry Viewer     | |
| |                                               | | (Auxiliary Sidecar Panel)   | |
| | Driver: "Why was Turn 3 slower on Lap 5?"     | |                             | |
| |                                               | | [Map & GPS Overlays]        | |
| | Coach: On Benchmark Lap 6, braking was at     | |  - Live kart position       | |
| |   [316.5m (Braking Point)]                    | |  - Vector & heatmap layers  | |
| | but on Lap 5 you braked late at               | |                             | |
| |   [319.5m] and scrubbed speed at              | | [Synchronized Plots]        | |
| |   [338.0m (Apex)]                             | |  - Speed, Delta T, Pedals   | |
| |                                               | |  - Custom tabs (e.g. EEG)   | |
| +-----------------------------------------------+ +-----------------------------+ |
+-----------------------------------------------------------------------------------+
```

---

## 1. Opening the Telemetry Viewer Sidecar & Selecting Laps

When an analysis session is initiated or referenced:
1. Emit a markdown pill so the user can open or focus the sidecar view in the auxiliary side panel:
   ```markdown
   [Open Telemetry Viewer](sidecar://brbrtelemetry/telemetry-viewer/)
   ```
2. Drive the viewer directly using the **`companion` MCP tool `set_telemetry_view(...)`** whenever introducing a session, comparing laps, focusing a corner, or toggling custom plots and overlays:
   - `session_url`: Navigate to a session URL when changing sessions (zero-reload when already on the target session).
   - `laps_a` / `laps_b`: Set active comparison laps (e.g. `laps_a=["18_43_practice_kartsim_coach_rs-25", "18_43_practice_katia_guseinova-36"]` or `["14", "18"]`).
   - `turn`: 1-indexed turn number to focus (`turn=3` focuses Turn 3), or `xlim=[290, 380]` / `map_range=[290, 380]` / `dist=316.5`.
   - `plots`: Visible bottom plots, including built-in (`"speed"`, `"delta"`, `"pedals"`, `"steering"`, `"gforce"`) and custom study groups (`"eeg"`).
   - `study`: Active study subfolder under `<workspace>/studies/` (e.g. `"2026-04-12_buckmore_eeg"`).
   - `overlays`: Explicit list of GeoJSON overlay IDs to display on the map (e.g. `["braking_zones", "apex_theta_heatmap"]`), or `[]` to clear all overlays.

### Fast-Path: Opening a Session & Selecting Laps (2 Steps)
When the user asks to open a session URL or show/compare specific laps (e.g. fastest lap by two drivers) without requesting a deep corner-by-corner coaching breakdown, follow this **2-step fast path** and **STOP** (do NOT run per-turn `get_stats`, `get_telemetry_plot`, or inspect local/remote HTML/JS files):

1. **Find the lap numbers and session IDs**: Call `get_pace_summary(track, date, session_id)` (or `get_stats(track, date, session_id)`).
2. **Construct Lap IDs (`laps_a`) and dispatch via `set_telemetry_view` (or `/api/action` fallback)**:
   - **Lap ID Format**: Strip `.csv` from the lap's `session_id` (or `actual_best_session`) and append `-{lap_number}`.
     - Single-driver session example: `20_06_practice-28`
     - Multi-driver session example: `18_43_practice_kartsim_coach_rs-25` and `18_43_practice_katia_guseinova-36`
   - **Update the sidecar session URL & active laps** in one `set_telemetry_view` call:
     ```python
     set_telemetry_view(
         session_url="/telemetry/kartsim/iame_waterswift_restricted_cadet_uk/2026-11-05/Whilton%20Mill?session_id=18_43_practice&lapsA=18_43_practice_kartsim_coach_rs-25%2C18_43_practice_katia_guseinova-36&tab=map",
         laps_a=["18_43_practice_kartsim_coach_rs-25", "18_43_practice_katia_guseinova-36"],
         tab="map",
     )
     ```
     *(If `companion` MCP is not yet loaded in the current turn, POST `{"type": "telemetry_jump", "lapsA": [...], "url": "..."}` to `http://127.0.0.1:38472/api/action`.)*
   - Reply immediately with `[Open Telemetry Viewer](sidecar://brbrtelemetry/telemetry-viewer/)` and a concise summary table.

---

## 2. Workspace Studies Organization (`<workspace>/studies/`)

When generating local overlays, custom telemetry channels, or analysis scripts in the user's workspace, keep the workspace organized so data from past sessions can be revisited and compared cleanly:

```text
<workspace>/
└── studies/
    ├── 2026-04-12_buckmore_turn3_braking/
    │   ├── README.md
    │   ├── overlays/
    │   │   └── braking_zones.geojson
    │   ├── channels/
    │   │   └── trail_brake_efficiency.json
    │   ├── plot_groups.json
    │   └── scripts/
    │       └── compute_braking.py
    └── 2026-04-12_buckmore_eeg_focus/
        ├── overlays/
        │   └── theta_heatmap.geojson
        ├── channels/
        │   └── eeg_alpha_theta.json
        └── plot_groups.json
```

### Multi-Study Rules
1. **Check Existing Studies First**: Call `list_workspace_studies()` before creating new folders so you can reuse or cross-compare prior studies on the same track or driver instead of duplicating files.
2. **Naming Convention**: Name each study folder `<YYYY-MM-DD>_<track>_<topic>/` under `<workspace>/studies/`.
3. **Scoped Loading & Explicit Overlay Selection**:
   - Activating `study="<study_id>"` scopes custom channels and plot tabs to that study, unmounting tabs from unrelated studies.
   - **Never auto-dump every GeoJSON file onto the map**: explicitly pass `overlays=[...]` in `set_telemetry_view` (or interactive pills) for the specific layers relevant to the current insight, and pass `overlays=[]` to clear them. Cross-study overlays can be referenced as `"<other_study>/overlays/<file>"`.

---

## 3. Recipes for Map Overlays & Custom Channels (EEG, Signal Processing)

### Recipe A: GeoJSON Vector & Heatmap Map Overlays
Write standard WGS84 (`[longitude, latitude]`) GeoJSON `FeatureCollection` files into `<workspace>/studies/<study_id>/overlays/<name>.geojson`:
- **Vector overlay (`metadata.render = "vector"`)**: Supports `Point`, `LineString`, `Polygon`, per-feature style overrides (`strokeColor`, `strokeWeight`, `fillColor`, `fillOpacity`, `radius`, `label`, `tooltip`), or scalar colormaps (`value_property`, `colormap` in `"turbo" | "inferno" | "viridis" | "rdylgn" | "coolwarm"`, `domain`, `unit`).
- **Heatmap overlay (`metadata.render = "heatmap"`)**: Renders smooth Gaussian spatial heatmaps (`radius_m`, `opacity`, `value_property`, `colormap`, `domain`, `unit`) for continuous spatial metrics such as tyre scrub intensity or EEG cognitive load around the circuit.

After writing or updating an overlay file, call:
```python
set_telemetry_view(
    study="2026-04-12_buckmore_eeg_focus",
    overlays=["theta_heatmap"],
    map_range=[280, 410],
)
```

### Recipe B: Custom Channels & Multi-Channel Plot Groups (e.g. Raw 500 Hz EEG -> Alpha & Theta)
1. **Fetch High-Rate Auxiliary Samples**:
   When a session lists an auxiliary stream (e.g. `spikerbit` at ~500 Hz), call `get_telemetry_data(..., raw_aux_stream="spikerbit")`. Each sample includes native `Time` alongside `Lap` and `Lap Distance` interpolated from the primary GPS stream.
2. **Compute Band Power / Custom Metrics in Python**:
   Run a script in `<workspace>/studies/<study_id>/scripts/` (e.g. Welch PSD / bandpass + Hilbert envelope over sliding windows for **EEG Alpha (`8–13 Hz`)** and **EEG Theta (`4–8 Hz`)**) and write `<workspace>/studies/<study_id>/channels/eeg_alpha_theta.json`:
   ```json
   {
     "channels": [
       {
         "schema": "brbr.custom_channel.v1",
         "channel_id": "eeg_alpha",
         "label": "Alpha (8-13 Hz)",
         "unit": "uV^2",
         "color": "#a855f7",
         "group": "eeg",
         "group_label": "EEG",
         "series": [
           {
             "session_id": "20260412_104512_kibergus",
             "lap_num": 14,
             "align": "distance",
             "x": [0.0, 2.0, 4.0],
             "y": [14.2, 13.8, 12.1]
           }
         ]
       },
       {
         "schema": "brbr.custom_channel.v1",
         "channel_id": "eeg_theta",
         "label": "Theta (4-8 Hz)",
         "unit": "uV^2",
         "color": "#06b6d4",
         "group": "eeg",
         "group_label": "EEG",
         "series": [
           {
             "session_id": "20260412_104512_kibergus",
             "lap_num": 14,
             "align": "distance",
             "x": [0.0, 2.0, 4.0],
             "y": [9.4, 11.2, 15.6]
           }
         ]
       }
     ]
   }
   ```
   *(Series support `"align": "distance"` where `x` is track meters per lap, or `"align": "time"` where `x` is session elapsed seconds.)*
3. **Register & Open the Plot Tab**:
   Call `register_plot_group` on the `companion` MCP server to mount the `EEG` tab next to `Pedals` / `Steering` and open it immediately:
   ```python
   register_plot_group(
       study="2026-04-12_buckmore_eeg_focus",
       id="eeg",
       label="EEG",
       channels=[
           {"channel_id": "eeg_alpha", "label": "Alpha (8-13 Hz)", "color": "#a855f7"},
           {"channel_id": "eeg_theta", "label": "Theta (4-8 Hz)", "color": "#06b6d4"},
       ],
       y_label="Band Power (uV^2)",
       color_mode="channel",
       open_plot=True,
   )
   ```

---

## 4. Interactive In-Text Pill Commentary

Always format key telemetry evidence (braking points, apex scrub marks, throttle pickups, overlay highlights) as clickable inline pills within your conversational text using Antigravity's **Generative UI (`<agent-embed>`)** system.

> [!IMPORTANT]
> **NEVER output ` ```html ... ``` ` code blocks directly in your chat message!** Fenced HTML blocks in chat are rendered as literal syntax-highlighted source code, NOT interactive buttons.
>
> You **MUST** follow this exact two-step workflow every time you render interactive telemetry pills:
> 1. **Write the HTML file to the Artifact Directory**: Use `write_file` to save a self-contained `.html` file at `<appDataDir>/brain/<conversation-id>/<widget-name>.html` with `Overwrite: true` and `ArtifactMetadata: { "Summary": "Interactive telemetry pills", "UserFacing": true, "RequestFeedback": false }`.
> 2. **Embed Inline with `<agent-embed>`**: In your chat response, place the `<agent-embed>` tag on its own line (outside any code fences or backticks):
>
> `<agent-embed src="file:///absolute/path/to/brain/<conversation-id>/<widget-name>.html"></agent-embed>`

### Step-by-Step Generative UI Template

**Step A — Save to `<appDataDir>/brain/<conversation-id>/turn_commentary.html` via `write_file`:**

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
</head>
<body class="bg-transparent text-[var(--foreground)] antialiased m-0 p-0 font-sans">
  <div class="space-y-2">
    <p class="text-sm leading-relaxed text-[var(--foreground)] m-0">
      On Benchmark Lap 6, braking begins smoothly at
      <button onclick="trigger({ dist: 316.5, plots: ['speed', 'pedals'], xlim: [290, 380], overlays: ['braking_zones'] })"
        class="inline-flex items-center px-1.5 py-0.5 mx-0.5 rounded bg-sky-500/15 text-sky-400 font-mono text-xs font-medium border border-sky-500/30 hover:bg-sky-500/25 active:scale-95 transition-all cursor-pointer">
        316.5m
      </button>, settling the kart. On Lap 5, the driver braked late at
      <button onclick="trigger({ dist: 319.5, plots: ['speed', 'eeg'], xlim: [290, 380], overlays: ['theta_heatmap'] })"
        class="inline-flex items-center px-1.5 py-0.5 mx-0.5 rounded bg-rose-500/15 text-rose-400 font-mono text-xs font-medium border border-rose-500/30 hover:bg-rose-500/25 active:scale-95 transition-all cursor-pointer">
        319.5m
      </button> as frontal Theta power spiked before apex at
      <button onclick="trigger({ dist: 338.0, plots: ['speed', 'steering'], xlim: [315, 365] })"
        class="inline-flex items-center px-1.5 py-0.5 mx-0.5 rounded bg-amber-500/15 text-amber-400 font-mono text-xs font-medium border border-amber-500/30 hover:bg-amber-500/25 active:scale-95 transition-all cursor-pointer">
        338.0m (Apex)
      </button>.
      <span id="pill-ack" class="text-xs font-mono text-emerald-400 ml-1.5"></span>
    </p>
  </div>

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
      } catch (e) {
        ack.textContent = '✗ Error';
      }
    }
  </script>
</body>
</html>
```

**Step B — Output the raw `<agent-embed>` tag in your chat response (no backticks):**

```markdown
<agent-embed src="file:///home/user/.gemini/antigravity/brain/<conversation-id>/turn_commentary.html"></agent-embed>
```

### Supported Action Properties dispatched to `/api/action`:
- `url` (string): Relative path + query string (e.g. `"/telemetry/kartsim/.../Whilton%20Mill?session_id=18_43_practice&lapsA=...&tab=map"`) to load or switch the active session in the sidecar viewer.
- `laps` / `lapsA` / `lapsB` (array of lap IDs): Active comparison laps formatted as `<session_id_without_csv>-<lap_number>` (e.g. `["18_43_practice_kartsim_coach_rs-25", "18_43_practice_katia_guseinova-36"]`).
- `dist` (number): Distance in meters along track to position cursor and kart marker.
- `xlim` / `plotRange` (array `[min, max]`): Visible X-axis meter range on bottom charts.
- `mapRange` / `focusRange` (array `[min, max]`): Centers satellite map over track segment (`focusRange` sets both `xlim` and `mapRange`).
- `turnNumber` (1-indexed integer) or `turn` (0-indexed integer): Focuses a numbered corner.
- `plots` (array of strings): Visible bottom channel plots, including custom group IDs (e.g. `['speed', 'eeg']`).
- `openPlot` / `togglePlot` (string): Idempotently open or toggle a single plot tab.
- `study` (string): Active workspace study ID.
- `overlays` (array of strings) / `toggleOverlay` (string): Active GeoJSON map overlays (`[]` clears all).
- `tcol` (`"pedals" | "delta_t" | "speed" | "accel" | "lap"`) & `mapType` (`"satellite" | "solid_dark"`).

---

## 5. Telemetry Analysis Methodology

### Step 1: Session & Data Discovery (Orchestrator)
1. **MCP Data Loading**:
   - Load session lists, track metadata, pace summaries, lap statistics, inspection plots, and raw numeric arrays via `telemetry` / `brbrdb` MCP tools (`list_sessions`, `get_track_info`, `get_pace_summary`, `get_stats`, `get_telemetry_plot`, `get_trajectory_plot`, `get_telemetry_data`).
   - Check `list_workspace_studies()` on `companion` MCP to discover existing workspace studies, overlays, and custom channels. Do NOT search outside `<workspace>/studies/` for raw server logs or databases, and do NOT grep HTML files or curl frontend JS to inspect URL/lap formats.
2. **Channel Audit**:
   - Identify physically recorded primary channels (`Speed`, `accel`, `Latitude`/`Longitude` vs `Steering Angle`, `Throttle`, `Brake`) as well as any recorded auxiliary streams (`aux_streams` such as `spikerbit`).
   - Ground conclusions in available data. If a channel is absent, never present inferences as measured facts.
3. **Corner Benchmark Rule**:
   - When analyzing a corner (e.g. Turn 3), the benchmark reference lap **MUST be selected based on the fastest segment time for THAT SPECIFIC CORNER** (`turn_time_s` from `get_stats(..., turn_index=N)`), **NOT overall full lap time**.
4. **Readability Constraints**:
   - **Keep compared laps under 3** (typically 2 laps: 1 Benchmark Reference Lap vs 1 Target Comparison Lap).
   - **Keep simultaneously opened bottom plots under 3** (e.g. `Speed` + `Pedals`, or `Speed` + `EEG`). Opening 3+ bottom plots pushes the track map off-screen.

### Step 2: Corner-by-Corner Investigation via Sub-Agents
When analyzing a specific corner:
1. Delegate to a sub-agent targeting the turn distance range (`start_m` to `end_m`).
2. Compare turn metrics: entry speed ($km/h$), minimum apex speed ($km/h$), exit speed ($km/h$), straight exit speed ($km/h$), and steering lock ($deg$, *if recorded*).
3. **Delta T Inflection Analysis**:
   - Pinpoint where the time delta starts to climb on the `Delta Time` trace (entry, apex, or exit).
4. **Data-Grounded Causation Chains with Calibrated Confidence**:
   - **Direct Evidence (High Confidence)**: Directly measured channels (Speed, Delta T, GPS line width, measured EEG/sensor traces).
   - **Inferred (Medium Confidence)**: Surrogate channels (e.g., assessing drive out of corner via longitudinal `accel` when throttle sensor is absent).
   - **Hypothesis (Low-to-Medium Confidence)**: Unmeasured driver actions (e.g., guessing steering snap when steering sensor is absent). Must be explicitly stated as a hypothesis.
5. **Junior Driver Coaching Tone**:
   - Positive, actionable coaching takeaways formulated for junior drivers (~11 years old) using `km/h` exclusively.

---

## 6. Report Saving Policy & Graceful Permission Handling

### Default Behavior: Interactive Chat Delivery
By default, the agent delivers all insights, turn comparisons, workspace overlays/channels, and interactive pill triggers directly in the Antigravity chat and local `<workspace>/studies/` folder.
- **Do NOT automatically call `save_report` at the end of an analysis.**

### Explicit User Request Only
Only invoke `save_report` (or `edit_report`) when the user **explicitly asks to save, publish, or store the report on the website**.

### Graceful Permission Handling
Not all users or API tokens have permission to publish reports on the server (`manage_reports` permission).
- If `save_report` fails with a `PermissionError` (e.g. *"Permission denied: current user does not have permission to manage reports..."*):
  1. Do **NOT** fail or halt the analysis.
  2. Inform the user clearly that remote report publishing requires higher credentials/permissions on the server.
  3. Reassure the user that all findings, local study artifacts, and interactive telemetry controls remain **100% available and functional right here within the Antigravity workspace and companion side panel**.
