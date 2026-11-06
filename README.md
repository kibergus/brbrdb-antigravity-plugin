# BRBR Telemetry Companion Plugin for Antigravity

This plugin connects Antigravity to the [brbrdb.brbrkitten.com](https://brbrdb.brbrkitten.com) Telemetry Viewer. It enables interactive racing telemetry analysis where the AI assistant highlights key driving moments (braking points, apex scrubbing, throttle application) with in-text clickable buttons that jump and zoom the Telemetry Viewer in the side panel in real time without reloading the page.

---

## 1. Setup & Installation

### Step 1: Install Antigravity

Download and install [Antigravity](https://antigravity.google) for your operating system. It does come with some amount of free LLM quota, but you may need to purchase a plan to increase it and have access to better models. NOTE: Antigravity is a Google product and neither it nor the subscription are directly related to the plugin. This is not subscription for the plugin.

### Step 2: Create a Dedicated Racing Workspace (Recommended)

You will likely want a dedicated workspace on your computer for your driving telemetry, session notes, and coaching conversations (e.g., `racing` or `telemetry`). Workspaces are basically directories.

### Step 3: Install the Plugin

You can point the agent to this page and ask it to do all the technical installation steps.

Inside your racing workspace, clone the plugin repository into `.agents/plugins/brbrtelemetry`:

```bash
mkdir -p .agents/plugins
git clone https://github.com/kibergus/brbrdb-antigravity-plugin.git .agents/plugins/brbrtelemetry
```

Antigravity will automatically detect the plugin in `.agents/plugins/brbrtelemetry` and activate it for your workspace.

---

## 2. Configuring MCP Tools for BrBrDb (Required)

The AI assistant needs the BrBrDb MCP tools (`list_sessions`, `get_track_info`, `get_stats`, `get_telemetry_plot`, etc.) to query and inspect telemetry data. Create or edit `.gemini/mcp_config.json` in your workspace (or globally at `~/.gemini/config/mcp_config.json`):

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

## 4. How to Use

1. **Open the Telemetry Viewer Panel:**
   Click the sidecar link in chat or ask the assistant:
   `Open Telemetry Viewer`
   The Telemetry Viewer opens in Antigravity's auxiliary side panel on the right.

2. **Ask Questions:**
   Ask any telemetry or driving technique question, for example:
   > *"Compare my laps 2 and 3 in Turn 3 at Whilton Mill and highlight the braking differences."*

3. **Interact with the Telemetry:**
   Click any of the highlighted distance pills (e.g. `316.5m`, `Apex`, `Throttle`) inside the AI's commentary. The side panel viewer will instantly zoom and align to that exact track position and telemetry trace.
