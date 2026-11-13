# GeoJSON Map Overlays & Custom Derived Channels Reference

Read this reference when creating or updating files inside `<workspace>/studies/<study_id>/`.

---

## 1. GeoJSON Vector & Heatmap Overlays (`overlays/<id>.geojson`)

Write standard WGS84 (`[longitude, latitude]`) GeoJSON `FeatureCollection` files with top-level `"metadata"`:

```json
{
  "type": "FeatureCollection",
  "metadata": {
    "id": "blink_heatmap",
    "label": "EEG Blink Density",
    "render": "heatmap",
    "radius_m": 22.0,
    "opacity": 0.8,
    "value_property": "intensity",
    "colormap": "inferno",
    "domain": [0.0, 1.0],
    "unit": "rel. density"
  },
  "features": [
    {
      "type": "Feature",
      "geometry": { "type": "Point", "coordinates": [-0.51234, 51.34567] },
      "properties": { "intensity": 0.72, "dist_m": 318.0 }
    }
  ]
}
```

- **`metadata.render = "vector"`**: Supports `Point`, `LineString`, `Polygon`, per-feature style overrides (`strokeColor`, `strokeWeight`, `fillColor`, `fillOpacity`, `radius`, `label`, `tooltip`), or scalar colormaps (`value_property`, `colormap`, `domain`, `unit`).
- **`metadata.render = "heatmap"`**: Smooth `<canvas>` Gaussian spatial heatmap (`radius_m`, `opacity`, `value_property`, `colormap`, `domain`, `unit`).
- **Supported `colormap` names**: `"turbo"`, `"inferno"`, `"viridis"`, `"plasma"`, `"magma"`, `"hot"`, `"ylorrd"`, `"rdylgn"`, `"coolwarm"`, plus `*_r` reversed variants (e.g. `"rdylgn_r"`).
- Activate explicitly via `set_telemetry_view(study="<study_id>", overlays=["blink_heatmap"])` (or `overlays=[]` to clear). Cross-study overlays can be referenced as `"<other_study>/overlays/<name>"`.

---

## 2. Custom Derived Channels (`channels/<name>.json`)

1. **Fetch Recorded Samples**:
   Call `get_telemetry_data(session_id=..., track=..., date=..., channels=["Time", "Lap", "Lap Distance", "Speed", "EEG", ...])` on the `telemetry` MCP server (there is no `raw_aux_stream` argument—request channel names directly via `channels`).
   - Always inspect the returned `sample_rate_hz` (or `Time` step) dynamically instead of assuming a fixed sample rate, and keep any digital filter cutoff strictly below `sample_rate_hz / 2` (Nyquist).
2. **Write `brbr.custom_channel.v1` JSON** to `<workspace>/studies/<study_id>/channels/<name>.json`:

```json
{
  "channels": [
    {
      "schema": "brbr.custom_channel.v1",
      "channel_id": "eeg_alpha",
      "label": "Alpha (8-13 Hz)",
      "unit": "uV^2",
      "color": "#a855f7",
      "group": "eeg_bands",
      "group_label": "EEG Bands",
      "series": [
        {
          "session_id": "23_47_practice",
          "lap_num": 14,
          "align": "distance",
          "x": [0.0, 2.0, 4.0],
          "y": [14.2, 13.8, 12.1]
        }
      ]
    }
  ]
}
```

- **`series[].session_id` (Critical)**: Must match the exact lap-ID stem—strip `.csv` from the driver's `session_id` in `get_pace_summary` / `list_sessions` (e.g. `"23_47_practice"` or `"18_43_practice_katia_guseinova"`, identical to the prefix before `-{lap_num}` in `laps_a`). Mismatched strings load silently with zero visible traces.
- **`series[].align`**: `"distance"` (`x` in track meters per lap) or `"time"` (`x` in session elapsed seconds).

---

## 3. Custom Plot Groups (`register_plot_group`)

Call `register_plot_group` on `brbrtelemetry_companion` to write `<workspace>/studies/<study_id>/plot_groups.json` and hot-reload the bottom bar:

```python
register_plot_group(
    study="2026-04-12_buckmore_eeg_focus",
    id="eeg_bands",
    label="EEG Bands",
    folder="neuro",
    folder_label="EEG & Load",
    channels=[
        {"channel_id": "eeg_alpha", "label": "Alpha (8-13 Hz)", "color": "#a855f7", "yaxis": "y"},
        {"channel_id": "eeg_theta", "label": "Theta (4-8 Hz)", "color": "#06b6d4", "yaxis": "y"},
    ],
    y_label="Band Power (uV^2)",
    color_mode="channel",
    open_plot=True,
)
```

- **One chart per plot group**: All `channels` in a group overlay onto **one shared plot** (`yaxis: "y"` and optional right-hand `"y2"`). Keep **1–2 compatible-scale traces per group**; register **separate** plot groups for channels with distinct units, scales, or meanings instead of crowding many traces onto one unreadable chart.
- **Toolbar folders & layout (`folder`, `folder_label`, `layout`)**:
  - Pass `folder="<slug>"` and `folder_label="<Label>"` on related custom plot groups to bundle 2+ groups into a single dropdown menu (single-item folders unwrap automatically unless `unwrap_single: false`).
  - Pass `layout=[...]` (or write `"layout"` in `<study>/plot_groups.json` or `<workspace>/studies/plot_layout.json`) to control top-level tab order, mix built-in and custom groups in folders (`{"folder": "neuro", "label": "EEG & Load", "items": [...]}`), or demote secondary tabs into `{"folder": "more", "label": "•••", "overflow": true, "items": ["gforce", "rps", "eeg", "*"]}`.
- **Built-in vs. custom IDs**: Sessions with Spiker:bit channels automatically mount built-in `eeg`, `ecg`, and `emg` tabs. Register derived groups under distinct IDs (`eeg_bands`, `eog_blinks`, `cognition`) unless you intentionally want to override the built-in tab while the study is active.
- After editing existing channel or GeoJSON files on disk without calling `register_plot_group`, call `sync_workspace_data(study="<study_id>")` to push live updates to the viewer.
