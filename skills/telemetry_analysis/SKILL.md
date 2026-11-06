---
name: telemetry_analysis
description: Analyzes karting telemetry data using MCP server tools and corner sub-agents, comparing reference benchmark vs target laps with Delta T inflection analysis and data-grounded causation chains, producing interactive chat commentary and synchronized controls for the Antigravity Telemetry Viewer companion side panel.
---

# Telemetry Analysis & Companion Skill

This skill provides an autonomous, turn-by-turn workflow for analyzing karting and racing telemetry data inside Google Antigravity. It pairs conversational chat commentary on the left with the interactive **Telemetry Viewer** in Antigravity's auxiliary side panel on the right.

```
+-----------------------------------------------------------------------------------+
| Antigravity                                                                       |
| +-----------------------------------------------+ +-----------------------------+ |
| | Left: Agent Chat & Interactive Commentary     | | Right: Telemetry Viewer     | |
| |                                               | | (Auxiliary Sidecar Panel)   | |
| | Driver: "Why was Turn 3 slower on Lap 5?"     | |                             | |
| |                                               | | [Map & GPS Trajectory]      | |
| | Coach: On Benchmark Lap 6, braking was at     | |  - Live kart position       | |
| |   [316.5m (Braking Point)]                    | |  - Trajectory comparisons   | |
| | but on Lap 5 you braked late at               | |                             | |
| |   [319.5m] and scrubbed speed at              | | [Synchronized Plots]        | |
| |   [338.0m (Apex)]                             | |  - Speed (km/h)             | |
| |                                               | |  - Delta T (s)              | |
| | (Clicking pills immediately synchronizes the  | |  - Throttle & Steering      | |
| |  Telemetry Viewer in the right side panel)    | |                             | |
| +-----------------------------------------------+ +-----------------------------+ |
+-----------------------------------------------------------------------------------+
```

---

## 1. Opening the Telemetry Viewer Sidecar

When an analysis session is initiated or referenced, emit a markdown pill to open and focus the sidecar view in the auxiliary side panel:

```markdown
[Open Telemetry Viewer](sidecar://brbrtelemetry/telemetry-viewer/)
```

The sidecar runs a local HTTP/WebSocket event bridge on port `38472` connecting the Antigravity chat to the Telemetry Viewer in real time without page reloads.

---

## 2. Interactive In-Text Pill Commentary

Always format key telemetry evidence (braking points, apex scrub marks, throttle pickups) as clickable inline pills within your conversational text.

### Generative UI Template

Embed the commentary inline using `<agent-embed>` or transparent HTML artifact:

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
      <button onclick="trigger(316.5, ['speed', 'pedals'], [290, 380])" 
        class="inline-flex items-center px-1.5 py-0.5 mx-0.5 rounded bg-sky-500/15 text-sky-400 font-mono text-xs font-medium border border-sky-500/30 hover:bg-sky-500/25 active:scale-95 transition-all cursor-pointer">
        316.5m
      </button>, settling the kart. On Lap 5, the driver braked late at 
      <button onclick="trigger(319.5, ['speed', 'pedals'], [290, 380])" 
        class="inline-flex items-center px-1.5 py-0.5 mx-0.5 rounded bg-rose-500/15 text-rose-400 font-mono text-xs font-medium border border-rose-500/30 hover:bg-rose-500/25 active:scale-95 transition-all cursor-pointer">
        319.5m
      </button> and had to scrub 70° of steering at 
      <button onclick="trigger(338.0, ['speed', 'steering'], [315, 365])" 
        class="inline-flex items-center px-1.5 py-0.5 mx-0.5 rounded bg-amber-500/15 text-amber-400 font-mono text-xs font-medium border border-amber-500/30 hover:bg-amber-500/25 active:scale-95 transition-all cursor-pointer">
        338.0m (Apex)
      </button>.
      <span id="pill-ack" class="text-xs font-mono text-emerald-400 ml-1.5"></span>
    </p>
  </div>

  <script>
    async function trigger(dist, plots, xlim) {
      const ack = document.getElementById('pill-ack');
      try {
        await fetch('http://127.0.0.1:38472/api/action', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            type: 'telemetry_jump',
            dist: dist,
            plots: plots,
            xlim: xlim
          })
        });
        ack.textContent = '✓ ' + dist + 'm';
        setTimeout(() => { ack.textContent = ''; }, 2000);
      } catch (e) {
        ack.textContent = '✗ Error';
      }
    }
  </script>
</body>
</html>
```

### Supported Action Properties dispatched to `/api/action`:
- `dist` (number): Distance in meters along track to position cursor and kart marker.
- `xlim` / `plotRange` (array `[min, max]`): Visible X-axis meter range on bottom charts.
- `mapRange` (array `[min, max]`): Centers satellite map over track segment.
- `plots` (array of strings): Visible bottom channel plots, e.g. `['speed', 'pedals']` or `['speed', 'steering']`.
- `laps` / `lapsA` (array of lap IDs): Active comparison laps.

---

## 3. Telemetry Analysis Methodology

### Step 1: Session & Data Discovery (Orchestrator)
1. **MCP Data Loading**:
   - All session lists, track metadata, pace summaries, lap statistics, and telemetry plots are loaded via MCP server tools (`list_sessions`, `get_track_info`, `get_pace_summary`, `get_stats`, `get_telemetry_plot`, `get_trajectory_plot`).
   - Do NOT search the local workspace or filesystem for telemetry logs, CSVs, or databases.
2. **Channel Audit**:
   - Identify physically recorded channels (`Speed`, `accel`, `Latitude`/`Longitude` vs full sensor suites with `Steering Angle`, `Throttle`, `Brake`).
   - Ground conclusions in available data. If a channel is absent, never present inferences as measured facts.
3. **Corner Benchmark Rule**:
   - When analyzing a corner (e.g. Turn 3), the benchmark reference lap **MUST be selected based on the fastest segment time for THAT SPECIFIC CORNER** (`turn_time_s` from `get_stats(..., turn_index=N)`), **NOT overall full lap time**.
4. **Readability Constraints**:
   - **Keep compared laps under 3** (typically 2 laps: 1 Benchmark Reference Lap vs 1 Target Comparison Lap).
   - **Keep simultaneously opened bottom plots under 3** (e.g. Speed + Pedals, or Speed + Steering). Opening 3+ bottom plots pushes the track map off-screen.
   - **All compared laps belong in Group A (`lapsA`)**. Group B is not used.

### Step 2: Corner-by-Corner Investigation via Sub-Agents
When analyzing a specific corner:
1. Delegate to a sub-agent targeting the turn distance range (`start_m` to `end_m`).
2. Compare turn metrics: entry speed ($km/h$), minimum apex speed ($km/h$), exit speed ($km/h$), straight exit speed ($km/h$), and steering lock ($deg$, *if recorded*).
3. **Delta T Inflection Analysis**:
   - Pinpoint where the time delta starts to climb on the `Delta Time` trace (entry, apex, or exit).
4. **Data-Grounded Causation Chains with Calibrated Confidence**:
   - **Direct Evidence (High Confidence)**: Directly measured channels (Speed, Delta T, GPS line width).
   - **Inferred (Medium Confidence)**: Surrogate channels (e.g., assessing drive out of corner via longitudinal `accel` when throttle sensor is absent).
   - **Hypothesis (Low-to-Medium Confidence)**: Unmeasured driver actions (e.g., guessing steering snap when steering sensor is absent). Must be explicitly stated as a hypothesis.
5. **Junior Driver Coaching Tone**:
   - Positive, actionable coaching takeaways formulated for junior drivers (~11 years old) using `km/h` exclusively.

---

## 4. Report Saving Policy & Graceful Permission Handling

### Default Behavior: Interactive Chat Delivery
By default, the agent delivers all insights, turn comparisons, and interactive pill triggers directly in the Antigravity chat.
- **Do NOT automatically call `save_report` at the end of an analysis.**

### Explicit User Request Only
Only invoke `save_report` (or `edit_report`) when the user **explicitly asks to save, publish, or store the report on the website**.

### Graceful Permission Handling
Not all users or API tokens have permission to publish reports on the server (`manage_reports` permission).
- If `save_report` fails with a `PermissionError` (e.g. *"Permission denied: current user does not have permission to manage reports..."*):
  1. Do **NOT** fail or halt the analysis.
  2. Inform the user clearly that remote report publishing requires higher credentials/permissions on the server.
  3. Reassure the user that all findings, analysis commentary, and interactive telemetry controls remain **100% available and functional right here within the Antigravity workspace and companion side panel**.

