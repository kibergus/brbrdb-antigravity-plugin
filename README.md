# BRBR Telemetry Companion Plugin for Antigravity

This plugin connects Antigravity to the [BrBrDb](https://brbrdb.brbrkitten.com) Telemetry Viewer. It enables interactive racing telemetry analysis, live companion view control, custom GeoJSON track overlays, and custom derived telemetry channels (such as high-rate EEG band power or vehicle dynamics metrics) right inside Antigravity.

---

## 1. Setup & Installation

### Step 1: Install Antigravity

Download and install [Antigravity](https://antigravity.google) for your operating system. It does come with some amount of free LLM quota, but you may need to purchase a plan to increase it and have access to better models. NOTE: Antigravity is a Google product and neither it nor the subscription are directly related to the plugin. This is not subscription for the plugin.

### Step 2: Create a Dedicated Racing Workspace (Recommended)

Create a dedicated workspace folder on your computer for your driving telemetry studies, custom overlays, derived channels, and coaching conversations (e.g., `~/racing` or `~/telemetry`). The plugin automatically organizes generated artifacts under `<workspace>/studies/<YYYY-MM-DD>_<track>_<topic>/`.

### Step 3: Install the Plugin

The easiest way to install the plugin is to ask Antigravity to do that:

```text
Install the BRBR Telemetry companion plugin globally by following the installation instructions in its README.md: clone https://github.com/kibergus/brbrdb-antigravity-plugin.git into ~/.gemini/config/plugins/brbrtelemetry and configure the MCP tools in ~/.gemini/config/mcp_config.json (ask me for my BrBrDb authentication key).
```

Alternatively, to install it manually, clone the plugin repository into `~/.gemini/config/plugins/brbrtelemetry`:

```bash
mkdir -p ~/.gemini/config/plugins
git clone https://github.com/kibergus/brbrdb-antigravity-plugin.git ~/.gemini/config/plugins/brbrtelemetry
```

Antigravity will automatically detect the plugin in `~/.gemini/config/plugins/brbrtelemetry`, activate its bundled local **`companion` MCP server** (`mcp_config.json` -> `sidecars/telemetry-viewer/mcp.sh`, zero external dependencies, Node.js or Python stdlib), and register the Telemetry Viewer sidecar across your workspaces.

---

## 2. Configuring MCP Tools for BrBrDb (Required)

In addition to the bundled local `companion` MCP server (which starts automatically with the plugin), configure the `brbrdb` MCP server so the AI assistant can query sessions, lap stats, and raw telemetry (`list_sessions`, `get_track_info`, `get_stats`, `get_telemetry_data`, `get_telemetry_plot`, etc.). Create or edit `~/.gemini/config/mcp_config.json` (or `.gemini/mcp_config.json` in your workspace):

```json
{
  "mcpServers": {
    "brbrdb": {
      "url": "https://brbrdb.brbrkitten.com/api/mcp?key=YOUR_API_KEY"
    }
  }
}
```

---

## 3. Telemetry Viewer Authentication

The Telemetry Viewer sidecar runs in Antigravity's auxiliary side panel. When the sidecar panel opens, if you are not yet authenticated, simply enter your access key in the login form inside the side panel. Your session cookie is saved in the embedded webview.

---

## 4. Features & How to Use

1. **Open the Telemetry Viewer Panel:**
   Click the sidecar link in chat or ask the assistant:
   `Open Telemetry Viewer`
   The Telemetry Viewer opens in Antigravity's auxiliary side panel on the right and connects to the local companion bridge on `127.0.0.1:38472`.

2. **Live Agent View Control (`companion` MCP):**
   Ask any telemetry or driving technique question, for example:
   > *"Compare my laps 14 and 18 in Turn 3 at Buckmore Park and highlight the braking differences."*
   The assistant automatically selects the laps, zooms the map and plots to Turn 3, and provides clickable distance pills (`316.5m`, `Apex`) inside chat commentary.

3. **Workspace Studies, Map Overlays & Custom Channels:**
   - **GeoJSON Vector & Heatmap Overlays**: The assistant can write `.geojson` vector markers/lines/polygons or smooth `<canvas>` heatmaps into `<workspace>/studies/<study>/overlays/` and display them directly over the satellite track map (even when viewing remote `brbrdb.brbrkitten.com` sessions).
   - **Custom Telemetry Channels & Plot Tabs**: Using `get_telemetry_data` (including `raw_aux_stream` for high-rate ~500 Hz auxiliary streams like `spikerbit` EEG), the assistant can compute derived channels in `<workspace>/studies/<study>/channels/`, group them via `register_plot_group` (e.g. an `EEG` tab with `Alpha` and `Theta` traces), and synchronize them with track cursor scrubbing and hover tooltips.
