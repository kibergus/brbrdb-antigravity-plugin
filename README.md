# BRBR Telemetry Companion Plugin for Antigravity

This plugin connects Antigravity to the [BrBrDb](https://brbrdb.brbrkitten.com) Telemetry Viewer. It enables interactive racing telemetry analysis within the AI assistant.

---

## 1. Setup & Installation

### Step 1: Install Antigravity

Download and install [Antigravity](https://antigravity.google) for your operating system. It does come with some amount of free LLM quota, but you may need to purchase a plan to increase it and have access to better models. NOTE: Antigravity is a Google product and neither it nor the subscription are directly related to the plugin. This is not subscription for the plugin.

### Step 2: Create a Dedicated Racing Workspace (Recommended)

You will likely want a dedicated workspace on your computer for your driving telemetry, session notes, and coaching conversations (e.g., `racing` or `telemetry`). Workspaces are basically directories.


## Quick Installation (Copy-Paste Prompt for Vanilla Antigravity)

The easiest way to install the plugin is to ask Antigravity to do that:

```text
Install the BRBR Telemetry plugin globally by following the installation instructions in its README.md: clone https://github.com/kibergus/brbrdb-antigravity-plugin.git into ~/.gemini/config/plugins/brbrtelemetry and configure the MCP tools in ~/.gemini/config/mcp_config.json (ask me for my BrBrDb authentication key).
```

---

## Extended installation runbook (for agents or very curious minds)

### Step 1: Clone the Plugin into `~/.gemini/config/plugins/brbrtelemetry`
Antigravity discovers both skills and UI sidecars globally from `~/.gemini/config/plugins/` (on Windows: `%USERPROFILE%\.gemini\config\plugins\`). The sidecar (`sidecars/telemetry-viewer/server.mjs`) is completely zero-dependency, using only Node.js built-in standard library modules.

Clone the repository directly there:

```bash
git clone https://github.com/kibergus/brbrdb-antigravity-plugin.git ~/.gemini/config/plugins/brbrtelemetry
```

*(If the directory already exists, run `git -C ~/.gemini/config/plugins/brbrtelemetry pull --ff-only` to update it.)*

### Step 2: Configure the `telemetry` MCP Server
Add the `telemetry` server to `~/.gemini/config/mcp_config.json` using your BrBrDb authentication key (if you are an AI agent running this setup, ask the user for their key first):

```json
{
  "mcpServers": {
    "telemetry": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://brbrdb.brbrkitten.com/api/mcp?key=<API_KEY>"
      ]
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

## 3. How to Use

1. **Open the Telemetry Viewer Panel:**
   Click the **[Open Telemetry Viewer](sidecar://brbrtelemetry/telemetry-viewer/)** pill in chat, or select **Telemetry Viewer** from the Auxiliary Side Pane on the right.

2. **Ask Questions:**
   Ask any telemetry or driving technique question, for example:
   > *"Compare the fastest lap by Katia and by the Coach in the Whilton Mill 18:43 practice session."*

3. **Interact with the Telemetry:**
   Click any of the highlighted distance pills (e.g. `668.7m`, `Apex`, `Braking`) inside the AI's commentary. The side panel viewer will immediately jump and zoom to that exact track section and telemetry channel trace.

4. **Saving Reports (Optional):**
   Conversational analysis and interactive triggers work entirely within Antigravity. If you want to publish a report to the website, ask:
   > *"Save this report to the site."*
   *(Requires server `manage_reports` permission)*.
