# BRBR Telemetry Companion Plugin for Antigravity

This plugin connects Antigravity to the [BrBrDb](https://brbrdb.brbrkitten.com) Telemetry Viewer. It enables interactive racing telemetry analysis, live companion view control, custom GeoJSON track overlays, and custom derived telemetry channels (such as high-rate EEG band power or vehicle dynamics metrics) right inside the AI assistant.

---

## 1. Setup & Installation

### Step 1: Install Antigravity

Download and install [Antigravity](https://antigravity.google) for your operating system. It does come with some amount of free LLM quota, but you may need to purchase a plan to increase it and have access to better models. NOTE: Antigravity is a Google product and neither it nor the subscription are directly related to the plugin. This is not subscription for the plugin.

### Step 2: Create a Dedicated Racing Workspace (Recommended)

You will likely want a dedicated workspace directory on your computer for your driving telemetry studies, session notes, custom overlays, derived channels, and coaching conversations (e.g., `racing` or `telemetry`). Generated study artifacts are organized automatically under `<workspace>/studies/<YYYY-MM-DD>_<track>_<topic>/`.

---

## Quick Installation (Copy-Paste Prompt for Vanilla Antigravity)

The easiest way to install the plugin is to ask Antigravity to do that:

```text
Install the BRBR Telemetry plugin globally by following the installation instructions in its README.md: clone https://github.com/kibergus/brbrdb-antigravity-plugin.git into ~/.gemini/config/plugins/brbrtelemetry and configure the MCP tools in ~/.gemini/config/mcp_config.json (ask me for my BrBrDb authentication key).
```

---

## Extended installation runbook (for agents or very curious minds)

### Step 1: Clone the Plugin into `~/.gemini/config/plugins/brbrtelemetry`
Antigravity discovers skills, bundled MCP servers (`mcp_config.json`), and UI sidecars globally from `~/.gemini/config/plugins/` (on Windows: `%USERPROFILE%\.gemini\config\plugins\`). Both the sidecar (`sidecars/telemetry-viewer/server.mjs`) and its local `companion` stdio MCP bridge (`sidecars/telemetry-viewer/mcp_stdio.mjs`, with pure-Python `server.py` / `mcp_stdio.py` parity) are completely zero-dependency, using only built-in standard library modules.

Clone the repository directly there:

```bash
git clone https://github.com/kibergus/brbrdb-antigravity-plugin.git ~/.gemini/config/plugins/brbrtelemetry
```

*(If the directory already exists, run `git -C ~/.gemini/config/plugins/brbrtelemetry pull --ff-only` to update it.)*

### Step 2: Configure the `telemetry` MCP Server (Streamable HTTP)
In addition to the bundled local `companion` MCP server (which activates automatically with the plugin), add the remote `telemetry` server to `~/.gemini/config/mcp_config.json` over native Streamable HTTP using your BrBrDb authentication key (if you are an AI agent running this setup, ask the user for their key first, and merge `"telemetry"` into any existing `"mcpServers"` object rather than overwriting other servers):

```json
{
  "mcpServers": {
    "telemetry": {
      "url": "https://brbrdb.brbrkitten.com/api/mcp?key=<API_KEY>"
    }
  }
}
```

### Step 3: Open the Telemetry Viewer Panel
Antigravity automatically detects and starts the sidecar within a few seconds of installation (or after restarting Antigravity). If an AI agent is performing the installation, it can read `~/.gemini/config/plugins/brbrtelemetry/skills/telemetry_analysis/SKILL.md` and output the panel shortcut in chat:

```markdown
[Open Telemetry Viewer](sidecar://brbrtelemetry/telemetry-viewer/)
```

---

## 2. Telemetry Viewer Authentication

The Telemetry Viewer sidecar runs in Antigravity's auxiliary side panel. When the sidecar panel opens, if you are not yet authenticated, simply enter your access key in the login form inside the side panel. Your session cookie is saved in the embedded webview.

---

## 3. How to Use

1. **Open the Telemetry Viewer Panel:**
   Click the **[Open Telemetry Viewer](sidecar://brbrtelemetry/telemetry-viewer/)** pill in chat, or select **Telemetry Viewer** from the Auxiliary Side Pane on the right.

2. **Ask Questions & Live View Control (`companion` MCP):**
   Ask any telemetry or driving technique question, for example:
   > *"Compare the fastest lap by Katia and by the Coach in the Whilton Mill 18:43 practice session."*

3. **Interact with the Telemetry:**
   Click any of the highlighted distance pills (e.g. `668.7m`, `Apex`, `Braking`) inside the AI's commentary. The side panel viewer will immediately jump and zoom to that exact track section and telemetry channel trace.

4. **Workspace Studies, Map Overlays & Custom Channels:**
   - **GeoJSON Vector & Heatmap Overlays**: The assistant can write `.geojson` vector markers/lines/polygons or smooth `<canvas>` heatmaps into `<workspace>/studies/<study>/overlays/` and display them directly over the satellite track map (even when viewing remote `brbrdb.brbrkitten.com` sessions).
   - **Custom Telemetry Channels & Plot Tabs**: Using `get_telemetry_data` (including `raw_aux_stream` for high-rate ~500 Hz auxiliary streams like `spikerbit` EEG), the assistant can compute derived channels in `<workspace>/studies/<study>/channels/`, group them via `register_plot_group` (e.g. an `EEG` tab with `Alpha` and `Theta` traces), and synchronize them with track cursor scrubbing and hover tooltips.

5. **Saving Reports (Optional):**
   Conversational analysis, local study artifacts, and interactive triggers work entirely within Antigravity. If you want to publish a report to the website, ask:
   > *"Save this report to the site."*
   *(Requires server `manage_reports` permission)*.
