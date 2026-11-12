# Telemetry & Companion MCP Tools Reference

This reference outlines the tools exposed by both MCP servers used during telemetry analysis:
1. **`brbrdb` MCP Server** — Remote or local telemetry database, statistics, plots, and raw numeric sample extraction.
2. **`companion` MCP Server** — Bundled local sidecar (`127.0.0.1:38472`) controlling the live Telemetry Viewer panel, workspace studies, GeoJSON map overlays, and custom channel plot groups.

---

## Part 1: `brbrdb` MCP Server Tools

### 1. `list_sessions(track=None, date=None, driver_name=None, league=None, class_name=None)`
- Lists recorded sessions with metadata (`session_id`, `date`, `track`, `driver_names`, `telemetry_channels`, `aux_streams`).

### 2. `get_track_info(track, include_geometry=False)`
- Returns track length (`lap_length`), sector boundaries (`sector_end`), and named turn definitions (`turns`). Track geometry (`center_line` coordinates and boundary `geojson`) is omitted by default and can be included by passing `include_geometry=True`.
- Each turn object contains: `name` (e.g. `"1"`), `start` (meters), `apex` (list of meters), `end` (meters).

### 3. `get_pace_summary(track, date, session_id=None, driver_name=None)`
- Returns actual best lap time, theoretical best lap time, total time delta, and per-turn breakdown of best times and priority rankings.

### 4. `get_aggregates(track, date=None, session_id=None, driver_name=None, exclude_outlier_pct=0.0)`
- Returns mean, min, max, and standard deviation for overall lap time and per-turn metrics (`turn_time`, `min_speed`, `max_steering`).

### 5. `get_stats(track, date=None, session_id=None, driver_name=None, turn_index=None, percentile_center=None, percentile_half_width=5.0)`
- Lap or per-turn statistics across matching laps.
- When `turn_index` is omitted: whole lap stats (`time_s`, `entry_speed_kmh`, `exit_speed_kmh`).
- When `turn_index` is provided: specific turn stats (`time_s`, `entry_speed_kmh`, `exit_speed_kmh`, `straight_exit_speed_kmh`, `apexes` array with `min_speed_kmh`, `max_steering_deg`).
- Use `percentile_center=0` for fastest laps, `percentile_center=50` for median laps, `percentile_center=75` for 75th percentile laps.

### 6. `get_telemetry_data(session_id, track, date, channels=None, driver_name=None, laps=None, start_m=None, end_m=None, raw_aux_stream=None)`
- Returns raw numeric telemetry columns as JSON arrays for mathematical signal processing, custom channel synthesis, or GeoJSON overlay generation.
- **Primary stream (`raw_aux_stream=None`, default)**: Reads the ~20–100 Hz primary `.brtc` telemetry file (`Lap`, `Lap Distance`, `Speed`, `Latitude`, `Longitude`, `Throttle`, `Brake`, etc., with high-rate auxiliary channels downsampled via per-bin sample averaging), optionally filtered to `laps` and `[start_m, end_m]`.
- **High-rate auxiliary stream (`raw_aux_stream="<stream_name>"`, e.g. `"spikerbit"`)**:
  - Reads the native high-frequency (~500 Hz) auxiliary `.brtc` file (`<stem>.aux.<stream>.brtc`) **without** collapsing it onto the primary GPS grid, preserving full Nyquist bandwidth for spectral analysis (e.g. EEG Theta `4–8 Hz` and Alpha `8–13 Hz` band power).
  - Automatically interpolates `Lap` and `Lap Distance` from the primary stream's `Time` / `timestamp` column onto every auxiliary sample (accounting for midnight rollover), filters by `laps` and `start_m` / `end_m`, and returns `aux_stream` and `sample_rate_hz` metadata.

### 7. `get_telemetry_plot(laps, start_m, end_m, channels)`
- **Agent inspection tool**: Renders stacked multi-channel telemetry plot and returns base64 PNG.
- **Plot Readability Guideline**: Keep `laps` under 3 (default: 2 laps — Benchmark Reference Lap vs Target Comparison Lap).
- **`laps` format**: List of 4-element tuples `(date, track, session_id, lap_number)`.
- Channels: `["Speed", "Throttle", "Brake", "Steering Angle", "Delta Time"]` (or `"accel"` when pedals are absent).

### 8. `get_trajectory_plot(laps, start_m, end_m, color_mode="lap")`
- **Agent inspection tool**: Renders X/Z GPS line trajectories for comparison over distance crop.
- **`color_mode`**: `"lap"`, `"pedals"`, `"accel"`, `"speed"`, or `"delta_t"`.

### 9. `get_session_consistency_image(session_id, track, date, driver_name=None)`
- Renders lap time evolution scatter plot over the session.

---

## Part 2: `companion` MCP Server Tools (Local Telemetry Viewer Bridge)

### 1. `set_telemetry_view(...)`
Synchronizes the live Telemetry Viewer side panel in one call without reloading when already on the target session:
- `session_url` (string, optional): Full URL or path to navigate to when switching sessions.
- `tab` (`"map" | "stats"`, optional): Active main view tab.
- `rtab` (`"cornering" | "acceleration" | "slip_angle" | "report"`, optional): Active right-panel tab.
- `laps_a` / `laps_b` (list of strings, optional): Selected laps for Group A / Group B.
- `dist` (number, optional): Track cursor position in meters.
- `xlim` (`[min_m, max_m]`, optional): Bottom plot X-axis distance range.
- `map_range` / `focus_range` (`[min_m, max_m]`, optional): Map segment zoom bounds (`focus_range` sets both `xlim` and `map_range`).
- `lat`, `lng`, `zoom` (numbers, optional): Direct GPS map center and zoom.
- `turn` (integer, optional): **1-indexed** turn number to focus (e.g. `turn=1` focuses Turn 1).
- `plots` (list of strings, optional): Exact set of open bottom plots, e.g. `["speed", "delta", "eeg"]`.
- `toggle_plot` (string, optional): Toggle a single bottom plot.
- `trajectory_color` (`"pedals" | "delta_t" | "speed" | "accel" | "gforce_lon" | "gforce_lat" | "lap"`, optional): Map trajectory coloring mode.
- `map_type` (`"satellite" | "solid_dark"`, optional): Map background mode.
- `study` (string, optional): Active workspace study folder relative to `<workspace>/studies/`.
- `overlays` (list of strings, optional): Explicit list of GeoJSON overlay IDs to show on the map (`[]` clears all overlays).
- `toggle_overlay` (string, optional): Toggle a single GeoJSON map overlay on/off.
- `side_panel` (`"collapsed" | "expanded"`, optional): Collapse or expand the right side panel.

### 2. `list_workspace_studies()`
- Scans `<workspace>/studies/` (up to 3 directory levels) and returns all discovered studies with their `id`, `label`, `overlays`, `channels`, `plot_groups`, and `updated_at` timestamps so agents can reuse or compare historical study artifacts.

### 3. `register_plot_group(id, label, channels, study=None, y_label="", y2_label="", y_range=None, color_mode="channel", open_plot=True)`
- Creates or updates `<workspace>/studies/<study>/plot_groups.json` to group one or more custom channels under a single bottom plot tab (e.g. `id="eeg"`, `label="EEG"` combining `eeg_alpha` and `eeg_theta`), broadcasts `workspace_sync`, and optionally opens the plot tab immediately (`open_plot=True`).

### 4. `sync_workspace_data(study=None, overlays=None)`
- Forces an immediate manifest rescan of `<workspace>/studies/` and broadcasts `workspace_sync` to all connected Telemetry Viewer tabs so newly written or edited `.geojson` overlays and `.json` custom channels hot-reload immediately.

### 5. `get_telemetry_view_status()`
- Returns the companion sidecar's current health, connected WebSocket client count (`clients_connected`), active `workspace_dir` / `studies_dir`, `active_study`, `active_overlays`, and `latest_action`.
