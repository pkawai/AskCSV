// AskCSV frontend. PR #3 wires upload -> profile -> charts. NLQ chat lands in PR #6.

const $ = (sel) => document.querySelector(sel);
const fileInput = $("#csv-file");
const uploadStatus = $("#upload-status");

let currentSessionId = null;

// Clean SVG icon for close/delete buttons. Font-glyph × renders as Cyrillic Ч
// or empty box in some macOS Chrome configurations — inline SVG is bulletproof.
const CLOSE_ICON_SVG = `
  <svg viewBox="0 0 14 14" width="12" height="12" fill="none" aria-hidden="true">
    <path d="M3 3 L11 11 M11 3 L3 11" stroke="currentColor"
          stroke-width="2" stroke-linecap="round"/>
  </svg>`;

// Poll /usage after any LLM-touching action so the chip stays fresh.
async function refreshUsageChip() {
  try {
    const res = await fetch("/usage");
    const data = await res.json();
    const chip = $("#usage-chip");
    chip.hidden = false;
    if (!data.calls) {
      chip.textContent = data.provider ? `${data.provider} · idle` : "no LLM configured";
      chip.classList.remove("usage-chip-active");
      return;
    }
    chip.classList.add("usage-chip-active");
    const total = (data.total_input_tokens + data.total_output_tokens).toLocaleString();
    const fb = data.fallback_calls
      ? ` · ${data.fallback_calls} fallback`
      : "";
    chip.textContent = `${data.provider} · ${data.calls} calls · ${total} tokens${fb}`;
  } catch (_) {
    // silent: usage chip is non-critical
  }
}

function toast(message, kind = "info") {
  const c = $("#toast-container");
  const t = document.createElement("div");
  t.className = `toast toast-${kind}`;
  t.textContent = message;
  c.appendChild(t);
  setTimeout(() => t.classList.add("toast-fade"), 3500);
  setTimeout(() => t.remove(), 4500);
}

// Provider switcher in the header — populated on load, swaps via POST /llm.
async function loadProviderSwitcher() {
  const select = $("#provider-select");
  try {
    const res = await fetch("/llm");
    const data = await res.json();
    select.innerHTML = data.providers
      .map(
        (p) =>
          `<option value="${p.name}" ${p.configured ? "" : "disabled"}
                   ${p.name === data.current ? "selected" : ""}>
             ${p.name} ${p.configured ? "" : "(no key)"}
           </option>`
      )
      .join("");
  } catch (_) {
    select.innerHTML = '<option>—</option>';
  }
}

$("#provider-select").addEventListener("change", async (e) => {
  const provider = e.target.value;
  try {
    const res = await fetch("/llm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Switch failed");
    toast(`Switched to ${data.current} (${data.primary_model})`);
    refreshUsageChip();
  } catch (err) {
    toast(`Could not switch: ${err.message}`, "error");
  }
});

loadProviderSwitcher();
refreshUsageChip();

const PLOTLY_LAYOUT = {
  paper_bgcolor: "#1e293b",
  plot_bgcolor: "#1e293b",
  font: { color: "#e2e8f0" },
  margin: { l: 50, r: 30, t: 40, b: 60 },
};

// Shared Plotly config: enable the modebar with ONLY the PNG download button.
// Everything else (lasso, pan, zoom, reset) is removed for a clean look.
const PLOTLY_CONFIG = {
  displayModeBar: true,
  displaylogo: false,
  responsive: true,
  modeBarButtonsToRemove: [
    "zoom2d", "pan2d", "select2d", "lasso2d", "zoomIn2d", "zoomOut2d",
    "autoScale2d", "resetScale2d", "hoverClosestCartesian",
    "hoverCompareCartesian", "toggleSpikelines",
  ],
  toImageButtonOptions: {
    format: "png",
    filename: "askcsv_chart",
    height: 600,
    width: 1000,
    scale: 2,
  },
};

fileInput.addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  await uploadAndRender(file);
});

// Drag-and-drop on the upload zone.
const zone = $("#upload-zone");
["dragover", "dragenter"].forEach((evt) =>
  zone.addEventListener(evt, (e) => {
    e.preventDefault();
    zone.classList.add("dragging");
  })
);
["dragleave", "drop"].forEach((evt) =>
  zone.addEventListener(evt, (e) => {
    e.preventDefault();
    zone.classList.remove("dragging");
  })
);
zone.addEventListener("drop", async (e) => {
  const file = e.dataTransfer.files[0];
  if (file) await uploadAndRender(file);
});

async function uploadAndRender(file) {
  showStatus(`Uploading ${file.name}…`);
  const fd = new FormData();
  fd.append("file", file);
  try {
    const res = await fetch("/upload", { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Upload failed");
    currentSessionId = data.session.session_id;
    showStatus(`Uploaded ${file.name} → session ${currentSessionId}`);
    const profRes = await fetch(`/profile/${currentSessionId}`);
    const profData = await profRes.json();
    if (!profRes.ok) throw new Error(profData.error || "Profile failed");
    renderAll(data, profData);
    $("#chat-section").hidden = false;
    $("#ideas-section").hidden = false;
    $("#ideas-grid").innerHTML = "";
    $("#export-link").href = `/report/${currentSessionId}`;
    initBuilder(profData.profile);
    loadAiSuggestions(currentSessionId);
  } catch (err) {
    showStatus(`Error: ${err.message}`, true);
  }
}

async function loadAiSuggestions(sessionId) {
  const container = $("#ai-suggestions");
  container.innerHTML = '<span class="suggest-hint">Thinking up analyses…</span>';
  try {
    const res = await fetch(`/suggest/${sessionId}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Suggestions failed");
    renderAiSuggestions(data.suggestions || []);
  } catch (err) {
    container.innerHTML = `<span class="suggest-hint suggest-error">Suggestions unavailable: ${escapeHtml(err.message)}</span>`;
  }
}

function renderAiSuggestions(suggestions) {
  const container = $("#ai-suggestions");
  if (!suggestions.length) {
    container.innerHTML = '<span class="suggest-hint">No suggestions returned.</span>';
    return;
  }
  container.innerHTML =
    '<span class="suggest-hint">Try one of these:</span>' +
    suggestions
      .map(
        (s) =>
          `<button class="chip" data-q="${escapeHtml(s.question)}" title="${escapeHtml(s.why)}">
             ${escapeHtml(s.question)}
           </button>`
      )
      .join("");
  container.querySelectorAll(".chip").forEach((btn) =>
    btn.addEventListener("click", () => askQuestion(btn.dataset.q))
  );
}

function showStatus(msg, isError = false) {
  uploadStatus.hidden = false;
  uploadStatus.textContent = msg;
  uploadStatus.classList.toggle("error", isError);
}

function renderAll(uploadResp, profileResp) {
  const { session, cleaning_report } = uploadResp;
  const { profile, suggested_charts } = profileResp;
  renderOverview(session, cleaning_report);
  renderColumns(profile.columns);
  renderMissingChart(profile.missing_value_matrix);
  renderCorrelationChart(profile.correlation_matrix);
  renderSuggestedCharts(suggested_charts);
}

function renderOverview(session, report) {
  $("#overview").hidden = false;
  $("#overview-stats").innerHTML = `
    <div class="stat"><span class="stat-label">Rows</span><span class="stat-value">${session.row_count.toLocaleString()}</span></div>
    <div class="stat"><span class="stat-label">Columns</span><span class="stat-value">${session.column_count}</span></div>
    <div class="stat"><span class="stat-label">Encoding</span><span class="stat-value">${session.encoding}</span></div>
    <div class="stat"><span class="stat-label">Duplicates removed</span><span class="stat-value">${report.duplicates_removed}</span></div>
  `;
  const reportLines = [];
  if (report.parsed_date_columns.length) {
    reportLines.push(`Parsed dates: <code>${report.parsed_date_columns.join(", ")}</code>`);
  }
  if (report.outlier_columns.length) {
    reportLines.push(`Outlier flags added: <code>${report.outlier_columns.join(", ")}</code>`);
  }
  $("#cleaning-report").innerHTML = reportLines.map((l) => `<p>${l}</p>`).join("");
}

// ---------- Column profile cards (redesigned for non-DS readers) ----------

// Friendly labels per dtype kind. The internal name is technical; users see plain English.
const KIND_DISPLAY = {
  numeric: { label: "Number", icon: "#" },
  datetime: { label: "Date", icon: "📅" },
  categorical: { label: "Category", icon: "≡" },
  boolean: { label: "Yes/No", icon: "◧" },
};

function _fmtNum(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  if (typeof n !== "number") return String(n);
  if (Math.abs(n) >= 1000) return n.toLocaleString(undefined, { maximumFractionDigits: 1 });
  if (Math.abs(n) >= 1) return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return n.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function _fmtDate(s) {
  if (!s) return "—";
  // Server sends ISO-ish strings like '2025-01-03 00:00:00'. Strip the time.
  return String(s).split(" ")[0].split("T")[0];
}

function renderColumns(cols) {
  $("#columns-section").hidden = false;
  $("#columns-grid").innerHTML = cols
    .filter((c) => !c.name.endsWith("_is_outlier"))
    .map(columnCard)
    .join("");
}

function columnCard(c) {
  const display = KIND_DISPLAY[c.kind] || { label: c.kind, icon: "·" };
  const total = c.null_count + (c.unique_count || 0); // rough denominator for null %
  const nullsLine =
    c.null_count === 0
      ? `<div class="col-row col-row-ok">✓ No missing values</div>`
      : `<div class="col-row col-row-warn">⚠ ${c.null_count.toLocaleString()} missing values</div>`;

  let bodyLines = "";
  if (c.kind === "numeric") {
    bodyLines = `
      <div class="col-row"><span class="col-row-k">Range</span>
        <span class="col-row-v">${_fmtNum(c.min)} → ${_fmtNum(c.max)}</span></div>
      <div class="col-row"><span class="col-row-k">Average</span>
        <span class="col-row-v">${_fmtNum(c.mean)}</span></div>
      <div class="col-row"><span class="col-row-k">Distinct values</span>
        <span class="col-row-v">${c.unique_count.toLocaleString()}</span></div>
    `;
  } else if (c.kind === "datetime") {
    bodyLines = `
      <div class="col-row"><span class="col-row-k">From</span>
        <span class="col-row-v">${_fmtDate(c.min)}</span></div>
      <div class="col-row"><span class="col-row-k">To</span>
        <span class="col-row-v">${_fmtDate(c.max)}</span></div>
      <div class="col-row"><span class="col-row-k">Distinct dates</span>
        <span class="col-row-v">${c.unique_count.toLocaleString()}</span></div>
    `;
  } else if (c.kind === "boolean") {
    bodyLines = `
      <div class="col-row"><span class="col-row-k">True</span>
        <span class="col-row-v">${(c.true_count || 0).toLocaleString()}</span></div>
      <div class="col-row"><span class="col-row-k">False</span>
        <span class="col-row-v">${(c.false_count || 0).toLocaleString()}</span></div>
    `;
  } else {
    // categorical
    const top = (c.top_values || []).slice(0, 3);
    const examples = top.length
      ? top.map((v) => `<code class="col-eg">${escapeHtml(v.value)}</code>`).join(" ")
      : '<span class="col-row-v">—</span>';
    const isUnique = c.unique_count === total;
    const subheading = isUnique
      ? `${c.unique_count.toLocaleString()} unique values (one per row)`
      : `${c.unique_count.toLocaleString()} ${c.unique_count === 1 ? "category" : "categories"}`;
    bodyLines = `
      <div class="col-row"><span class="col-row-k">${subheading}</span></div>
      ${top.length ? `<div class="col-row col-examples"><span class="col-row-k">Most common</span><span class="col-row-v">${examples}</span></div>` : ""}
    `;
  }

  return `
    <article class="column-card">
      <header class="col-head">
        <span class="col-name">${escapeHtml(c.name)}</span>
        <span class="col-kind kind-${c.kind}" title="${display.label}">${display.icon} ${display.label}</span>
      </header>
      <div class="col-body">
        ${bodyLines}
        ${nullsLine}
      </div>
    </article>
  `;
}

function renderMissingChart(mvm) {
  if (!mvm.columns.length) return;
  $("#missing-section").hidden = false;
  const target = document.getElementById("missing-chart");

  // Filter columns that actually have nulls so we don't show 21 zero-bars.
  const items = mvm.columns
    .map((c, i) => ({ col: c, pct: mvm.null_pct[i], count: mvm.null_counts[i] }))
    .filter((d) => d.count > 0)
    .sort((a, b) => b.pct - a.pct);

  if (items.length === 0) {
    target.innerHTML =
      '<div class="empty-good">' +
      '<span class="empty-icon">✓</span>' +
      '<div><strong>No missing values</strong>' +
      '<p>Every cell in every column has a value.</p></div>' +
      '</div>';
    return;
  }

  // Horizontal bar — labels read cleanly even with 20+ columns.
  Plotly.newPlot(
    target,
    [
      {
        type: "bar",
        orientation: "h",
        y: items.map((d) => d.col),
        x: items.map((d) => d.pct),
        marker: { color: "#fbbf24", line: { color: "rgba(255,255,255,0.1)", width: 1 } },
        text: items.map((d) => `${d.count.toLocaleString()} (${d.pct.toFixed(1)}%)`),
        textposition: "outside",
        textfont: { color: "#e2e8f0", size: 11 },
        hovertemplate: "<b>%{y}</b><br>%{x:.2f}% missing<extra></extra>",
        cliponaxis: false,
      },
    ],
    {
      ...PLOTLY_LAYOUT,
      height: Math.max(120, items.length * 28 + 60),
      xaxis: { title: "% missing", range: [0, 105], gridcolor: "rgba(148,163,184,0.15)" },
      yaxis: { automargin: true, ticksuffix: "  " },
      margin: { l: 140, r: 60, t: 20, b: 40 },
      showlegend: false,
    },
    PLOTLY_CONFIG
  );
}

function renderCorrelationChart(corr) {
  if (corr.columns.length < 2) return;
  $("#correlation-section").hidden = false;
  // Wider left + bottom margin + automargin so long column names don't clip.
  // Per-cell annotation text so users can read values directly.
  const annotations = [];
  for (let i = 0; i < corr.values.length; i++) {
    for (let j = 0; j < corr.values[i].length; j++) {
      const v = corr.values[i][j];
      annotations.push({
        x: corr.columns[j],
        y: corr.columns[i],
        text: v === null || Number.isNaN(v) ? "" : v.toFixed(2),
        showarrow: false,
        font: { color: Math.abs(v) > 0.6 ? "#ffffff" : "#0f172a", size: 11 },
      });
    }
  }
  Plotly.newPlot(
    "correlation-chart",
    [
      {
        type: "heatmap",
        z: corr.values,
        x: corr.columns,
        y: corr.columns,
        zmin: -1,
        zmax: 1,
        colorscale: "RdBu",
        reversescale: true,
        hovertemplate: "<b>%{x}</b> vs <b>%{y}</b><br>r = %{z:.3f}<extra></extra>",
        showscale: true,
      },
    ],
    {
      ...PLOTLY_LAYOUT,
      height: Math.max(280, corr.columns.length * 40 + 120),
      xaxis: { automargin: true, side: "bottom", tickangle: -30 },
      yaxis: { automargin: true, autorange: "reversed" },
      margin: { l: 120, r: 60, t: 30, b: 80 },
      annotations,
    },
    PLOTLY_CONFIG
  );
}

function renderSuggestedCharts(suggestions) {
  if (!suggestions.length) return;
  $("#suggested-section").hidden = false;
  $("#suggested-grid").innerHTML = suggestions
    .map(
      (s, i) => `
      <article class="suggested-card">
        <header>
          <span class="chart-kind">${s.kind}</span>
          <span class="chart-title">${s.title}</span>
        </header>
        <p class="chart-reason">${s.reason}</p>
        <p class="chart-cols">x: <code>${s.x}</code> · y: <code>${s.y}</code></p>
      </article>
    `
    )
    .join("");
}

// ---------- Chat / NLQ ----------

$("#clear-thread").addEventListener("click", () => {
  $("#chat-thread").innerHTML = "";
});

// ---------- 'What can I build?' AI feature ----------

$("#ideas-load").addEventListener("click", () => loadDataIdeas());

async function loadDataIdeas() {
  if (!currentSessionId) return;
  const grid = $("#ideas-grid");
  const btn = $("#ideas-load");
  grid.innerHTML = '<div class="ideas-loading"><span class="spinner"></span> Thinking up projects…</div>';
  btn.disabled = true;
  try {
    const res = await fetch(`/data_ideas/${currentSessionId}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to load ideas");
    renderDataIdeas(data.ideas || []);
    refreshUsageChip();
  } catch (err) {
    grid.innerHTML = `<div class="ideas-error">${escapeHtml(err.message)}</div>`;
  } finally {
    btn.disabled = false;
  }
}

const CATEGORY_LABEL = {
  analytics: "📊 Analytics",
  ml: "🤖 ML",
  dashboard: "📈 Dashboard",
  insight: "💡 Insight",
  segmentation: "🧩 Segmentation",
};

function renderDataIdeas(ideas) {
  const grid = $("#ideas-grid");
  if (!ideas.length) {
    grid.innerHTML = '<div class="ideas-error">No ideas returned.</div>';
    return;
  }
  grid.innerHTML = ideas
    .map((i) => {
      const howList = (i.how || []).map((h) => `<li>${escapeHtml(h)}</li>`).join("");
      return `
        <article class="idea-card">
          <header class="idea-head">
            <span class="idea-cat idea-cat-${i.category}">${CATEGORY_LABEL[i.category] || i.category}</span>
            <span class="idea-diff idea-diff-${i.difficulty}">${i.difficulty}</span>
          </header>
          <h3 class="idea-title">${escapeHtml(i.title)}</h3>
          <p class="idea-what">${escapeHtml(i.what)}</p>
          ${howList ? `<ul class="idea-how">${howList}</ul>` : ""}
        </article>
      `;
    })
    .join("");
}

$("#chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("#chat-input");
  const question = input.value.trim();
  if (!question || !currentSessionId) return;
  input.value = "";
  await askQuestion(question);
});

async function askQuestion(question) {
  const turn = appendChatTurn(question, /* loading */ true);
  try {
    const res = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: currentSessionId, question }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Question failed");
    renderChatTurn(turn, data);
  } catch (err) {
    turn.innerHTML = `
      <div class="chat-q">
        <span class="chat-q-text">${escapeHtml(question)}</span>
        <button class="chat-delete" aria-label="Remove this answer">${CLOSE_ICON_SVG}</button>
      </div>
      <div class="chat-error">Error: ${escapeHtml(err.message)}</div>`;
    turn.querySelector(".chat-delete").addEventListener("click", () => turn.remove());
    toast(err.message, "error");
  } finally {
    refreshUsageChip();
  }
}

function appendChatTurn(question, loading = false) {
  const thread = $("#chat-thread");
  const turn = document.createElement("article");
  turn.className = "chat-turn";
  turn.innerHTML = `<div class="chat-q">${escapeHtml(question)}</div>
    <div class="chat-loading">${loading ? '<span class="spinner"></span> Thinking…' : ""}</div>`;
  thread.prepend(turn);
  return turn;
}

// Chart kinds offered as in-place re-render buttons on every chat turn.
// These map 1:1 onto Plotly traces we already know how to render.
const CHART_KIND_OPTIONS = ["bar", "line", "scatter", "hist", "pie"];

function renderChatTurn(turn, data) {
  const { chart_spec, insight, tool_trace, from_cache, latency_s, followups } = data;
  const cacheBadge = from_cache
    ? '<span class="badge badge-cache">cached</span>'
    : `<span class="badge">${latency_s ?? "?"}s</span>`;

  const chartId = `chart-${Math.random().toString(36).slice(2, 8)}`;
  const traceLines = (tool_trace || [])
    .map(
      (t) =>
        `<div class="trace-line"><code>${t.tool}</code>(${escapeHtml(
          JSON.stringify(t.args)
        )}) → ${escapeHtml(JSON.stringify(t.result))}</div>`
    )
    .join("");

  const followupChips = (followups || []).length
    ? `<div class="followups">
         <span class="suggest-hint">Follow-ups:</span>
         ${followups
           .map(
             (q) =>
               `<button class="chip chip-followup" data-q="${escapeHtml(q)}">${escapeHtml(q)}</button>`
           )
           .join("")}
       </div>`
    : "";

  const originalQuestion = turn.querySelector(".chat-q").textContent;
  const hasChart = chart_spec && chart_spec.data && chart_spec.data.length;

  const kindToolbar = hasChart
    ? `<div class="chart-kinds">
         ${CHART_KIND_OPTIONS.map(
           (k) =>
             `<button class="kind-btn-mini ${k === chart_spec.kind ? "active" : ""}"
                      data-kind="${k}">${k}</button>`
         ).join("")}
       </div>`
    : "";

  // Overlay toggles shown for line charts only — most useful on time-series.
  const overlaysToolbar = hasChart && chart_spec.kind === "line"
    ? `<div class="chart-overlays">
         <span class="overlay-label">Overlays:</span>
         <button class="overlay-btn" data-overlay="movingAvg">+ Moving avg</button>
         <button class="overlay-btn" data-overlay="peaks">+ Peaks & dips</button>
         <button class="overlay-btn" data-overlay="cumulative">Cumulative</button>
       </div>`
    : "";

  turn.innerHTML = `
    <div class="chat-q">
      <span class="chat-q-text">${escapeHtml(originalQuestion)}</span>
      ${cacheBadge}
      <button class="chat-delete" aria-label="Remove this answer">${CLOSE_ICON_SVG}</button>
    </div>
    <div class="chat-insight">${insight ? escapeHtml(insight) : "(no insight returned)"}</div>
    ${kindToolbar}
    ${overlaysToolbar}
    <div id="${chartId}" class="chat-chart"></div>
    ${followupChips}
    <details class="chat-trace">
      <summary>Tool trace (${(tool_trace || []).length} steps)</summary>
      ${traceLines || "<em>no tool calls</em>"}
    </details>
  `;

  if (hasChart) {
    // Stash the current spec + overlays on the turn so kind switcher and
    // overlay toggles can re-render without re-asking the LLM.
    turn._chartSpec = { ...chart_spec };
    turn._chartId = chartId;
    turn._overlays = { movingAvg: false, peaks: false, cumulative: false };
    renderPlotlySpec(chartId, turn._chartSpec, turn._overlays);

    turn.querySelectorAll(".kind-btn-mini").forEach((btn) =>
      btn.addEventListener("click", () => {
        const newKind = btn.dataset.kind;
        turn._chartSpec.kind = newKind;
        turn.querySelectorAll(".kind-btn-mini").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        // Overlay toolbar only makes sense on line charts — show/hide.
        const overlaysEl = turn.querySelector(".chart-overlays");
        if (overlaysEl) overlaysEl.hidden = newKind !== "line";
        renderPlotlySpec(chartId, turn._chartSpec, turn._overlays);
      })
    );

    turn.querySelectorAll(".overlay-btn").forEach((btn) =>
      btn.addEventListener("click", () => {
        const key = btn.dataset.overlay;
        turn._overlays[key] = !turn._overlays[key];
        btn.classList.toggle("active", turn._overlays[key]);
        renderPlotlySpec(chartId, turn._chartSpec, turn._overlays);
      })
    );
  }

  turn.querySelectorAll(".chip-followup").forEach((btn) =>
    btn.addEventListener("click", () => askQuestion(btn.dataset.q))
  );

  const deleteBtn = turn.querySelector(".chat-delete");
  if (deleteBtn) {
    deleteBtn.addEventListener("click", () => {
      turn.classList.add("chat-turn-removing");
      setTimeout(() => turn.remove(), 200);
    });
  }
}

// Categorical palette used for bar / pie / multi-series charts.
// Tuned for the dark theme: vibrant but readable side-by-side.
const CATEGORICAL_COLORS = [
  "#38bdf8", "#818cf8", "#34d399", "#fbbf24",
  "#f472b6", "#22d3ee", "#a78bfa", "#fb923c",
  "#84cc16", "#fb7185",
];

function _formatValue(v) {
  if (typeof v !== "number" || !Number.isFinite(v)) return String(v);
  if (Math.abs(v) >= 1000) return v.toLocaleString(undefined, { maximumFractionDigits: 1 });
  if (Math.abs(v) >= 1) return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

// Compute a centered N-point moving average. Returns null for indices where
// the window doesn't fully fit so the overlay line has clean endpoints.
function _movingAverage(values, windowSize) {
  const half = Math.floor(windowSize / 2);
  const out = [];
  for (let i = 0; i < values.length; i++) {
    if (i < half || i > values.length - half - 1) {
      out.push(null);
      continue;
    }
    let sum = 0;
    for (let j = i - half; j <= i + half; j++) sum += values[j];
    out.push(sum / windowSize);
  }
  return out;
}

// Pick a sensible MA window based on series length.
// Daily data of ~700 points -> 30-day window. Short series -> ~5.
function _maWindow(n) {
  if (n < 30) return Math.max(3, Math.floor(n / 5));
  if (n < 120) return 7;
  if (n < 365) return 14;
  return 30;
}

// Indices of the top/bottom N values, dedup.
function _peakDipIndices(values, n) {
  const ranked = [...values.keys()].sort((a, b) => values[b] - values[a]);
  const peaks = ranked.slice(0, n);
  const dips = ranked.slice(-n).reverse();
  return { peaks, dips };
}

function renderPlotlySpec(divId, spec, overlays = {}) {
  const data = spec.data;
  const xs = data.map((r) => r[spec.x]);
  let ys = data.map((r) => r[spec.y]);

  // Cumulative toggle: replace the y series with running totals.
  // Only meaningful for ordered series (line/bar over time or category).
  if (overlays.cumulative && (spec.kind === "line" || spec.kind === "bar")) {
    let acc = 0;
    ys = ys.map((v) => {
      const n = typeof v === "number" && Number.isFinite(v) ? v : 0;
      acc += n;
      return acc;
    });
  }

  let traces;
  let extraLayout = {};
  const annotations = [];

  switch (spec.kind) {
    case "bar": {
      // One color per bar so categories are distinguishable at a glance.
      const barColors = xs.map((_, i) => CATEGORICAL_COLORS[i % CATEGORICAL_COLORS.length]);
      // Value labels on top of each bar — sized so they don't crash into one another.
      const labels = ys.map(_formatValue);
      traces = [
        {
          type: "bar",
          x: xs,
          y: ys,
          marker: {
            color: barColors,
            line: { color: "rgba(255,255,255,0.08)", width: 1 },
          },
          text: labels,
          textposition: "outside",
          textfont: { color: "#e2e8f0", size: 11 },
          cliponaxis: false,
          hovertemplate: "<b>%{x}</b><br>%{y:,.2f}<extra></extra>",
        },
      ];
      // Headroom above the tallest bar so 'outside' labels don't get clipped.
      const maxY = Math.max(...ys.filter((v) => Number.isFinite(v)), 0);
      extraLayout = {
        yaxis: { gridcolor: "rgba(148,163,184,0.15)", zerolinecolor: "rgba(148,163,184,0.3)", range: [0, maxY * 1.15] },
        xaxis: { gridcolor: "rgba(148,163,184,0.05)" },
        showlegend: false,
        bargap: 0.25,
      };
      break;
    }
    case "line": {
      // Detect ISO-ish dates so Plotly auto-formats the x axis as time
      // (continuous tick spacing like 'Jan 2024', 'Apr 2024', ...) instead
      // of cramming one categorical tick per data point.
      const xLooksLikeDates =
        xs.length > 0 &&
        xs.every((v) => typeof v === "string" && /^\d{4}-\d{2}-\d{2}/.test(v));
      const dense = xs.length > 30;
      traces = [
        {
          type: "scatter",
          mode: dense ? "lines" : "lines+markers",
          x: xs,
          y: ys,
          line: { color: "#38bdf8", width: dense ? 1.8 : 2.5, shape: "linear" },
          marker: { color: "#38bdf8", size: dense ? 0 : 8 },
          hovertemplate: xLooksLikeDates
            ? "<b>%{x|%b %d, %Y}</b><br>%{y:,.2f}<extra></extra>"
            : "<b>%{x}</b><br>%{y:,.2f}<extra></extra>",
        },
      ];
      const xaxis = {
        gridcolor: "rgba(148,163,184,0.05)",
        automargin: true,
      };
      if (xLooksLikeDates) {
        xaxis.type = "date";
        // Quick-zoom buttons above the chart — really useful for multi-year data.
        xaxis.rangeselector = {
          buttons: [
            { count: 1, label: "1m", step: "month", stepmode: "backward" },
            { count: 3, label: "3m", step: "month", stepmode: "backward" },
            { count: 6, label: "6m", step: "month", stepmode: "backward" },
            { count: 1, label: "1y", step: "year", stepmode: "backward" },
            { step: "all", label: "All" },
          ],
          bgcolor: "rgba(15,23,42,0.8)",
          activecolor: "#38bdf8",
          bordercolor: "rgba(148,163,184,0.2)",
          font: { color: "#e2e8f0", size: 11 },
          y: 1.15,
          yanchor: "top",
        };
        // Mini overview slider at the bottom so users can pan/zoom into a range.
        xaxis.rangeslider = { visible: true, thickness: 0.06,
                              bgcolor: "rgba(15,23,42,0.6)", bordercolor: "rgba(148,163,184,0.2)" };
      }
      extraLayout = {
        yaxis: { gridcolor: "rgba(148,163,184,0.15)" },
        xaxis,
        margin: { l: 60, r: 30, t: xLooksLikeDates ? 60 : 40, b: xLooksLikeDates ? 40 : 60 },
      };

      // --- Overlays for line charts ---
      if (overlays.movingAvg && ys.length >= 5) {
        const win = _maWindow(ys.length);
        const ma = _movingAverage(ys, win);
        traces.push({
          type: "scatter",
          mode: "lines",
          x: xs,
          y: ma,
          line: { color: "#fbbf24", width: 2.5, dash: "solid" },
          name: `${win}-pt moving avg`,
          hovertemplate: `${win}-pt MA<br>%{y:,.2f}<extra></extra>`,
          showlegend: true,
        });
        extraLayout.showlegend = true;
        extraLayout.legend = {
          font: { color: "#e2e8f0", size: 11 },
          bgcolor: "rgba(15,23,42,0.6)",
          orientation: "h",
          y: -0.18,
        };
      }

      if (overlays.peaks && ys.length >= 6) {
        const { peaks, dips } = _peakDipIndices(ys, 3);
        peaks.forEach((i) =>
          annotations.push({
            x: xs[i],
            y: ys[i],
            text: `▲ ${_formatValue(ys[i])}`,
            showarrow: true,
            arrowhead: 3,
            arrowcolor: "#34d399",
            ax: 0,
            ay: -28,
            bgcolor: "rgba(52,211,153,0.25)",
            bordercolor: "#34d399",
            font: { color: "#e2e8f0", size: 10 },
          })
        );
        dips.forEach((i) =>
          annotations.push({
            x: xs[i],
            y: ys[i],
            text: `▼ ${_formatValue(ys[i])}`,
            showarrow: true,
            arrowhead: 3,
            arrowcolor: "#f87171",
            ax: 0,
            ay: 28,
            bgcolor: "rgba(248,113,113,0.25)",
            bordercolor: "#f87171",
            font: { color: "#e2e8f0", size: 10 },
          })
        );
      }
      break;
    }
    case "scatter":
      traces = [
        {
          type: "scatter",
          mode: "markers",
          x: xs,
          y: ys,
          marker: { color: "#38bdf8", size: 10, opacity: 0.75,
                    line: { color: "rgba(255,255,255,0.15)", width: 1 } },
          hovertemplate: "%{x}, %{y}<extra></extra>",
        },
      ];
      extraLayout = {
        yaxis: { gridcolor: "rgba(148,163,184,0.15)" },
        xaxis: { gridcolor: "rgba(148,163,184,0.15)" },
      };
      break;
    case "hist":
      traces = [
        {
          type: "histogram",
          x: xs,
          marker: {
            color: "#38bdf8",
            line: { color: "rgba(255,255,255,0.1)", width: 1 },
          },
          hovertemplate: "%{x}<br>count: %{y}<extra></extra>",
        },
      ];
      extraLayout = {
        yaxis: { gridcolor: "rgba(148,163,184,0.15)", title: { text: "count" } },
        xaxis: { gridcolor: "rgba(148,163,184,0.05)" },
        bargap: 0.05,
      };
      break;
    case "pie": {
      const colors = xs.map((_, i) => CATEGORICAL_COLORS[i % CATEGORICAL_COLORS.length]);
      traces = [
        {
          type: "pie",
          labels: xs,
          values: ys,
          hole: 0.4,                    // donut style — modern + value in the middle is easier to read
          marker: { colors, line: { color: "#1e293b", width: 2 } },
          textinfo: "label+percent",
          textfont: { color: "#0f172a", size: 12 },
          hovertemplate: "<b>%{label}</b><br>%{value:,.0f} (%{percent})<extra></extra>",
        },
      ];
      extraLayout = { showlegend: true, legend: { font: { color: "#e2e8f0" } } };
      break;
    }
    default: {
      const barColors = xs.map((_, i) => CATEGORICAL_COLORS[i % CATEGORICAL_COLORS.length]);
      traces = [{ type: "bar", x: xs, y: ys, marker: { color: barColors } }];
    }
  }

  // Time-series gets extra height for the rangeselector buttons + rangeslider.
  const isTimeSeriesLine =
    spec.kind === "line" && extraLayout.xaxis && extraLayout.xaxis.type === "date";

  const title = overlays.cumulative ? `${spec.title} (cumulative)` : spec.title;

  Plotly.newPlot(
    divId,
    traces,
    {
      ...PLOTLY_LAYOUT,
      title: { text: title, font: { color: "#e2e8f0", size: 14 } },
      height: isTimeSeriesLine ? 420 : 340,
      ...extraLayout,
      ...(annotations.length ? { annotations: [
        ...(extraLayout.annotations || []),
        ...annotations,
      ] } : {}),
    },
    PLOTLY_CONFIG
  );
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// ---------- Chart builder (Tableau / Power BI style) ----------

const builderState = { kind: "bar", x: null, y: null, color: null, agg: "sum" };
let builderTimer = null;

function initBuilder(profile) {
  $("#builder-section").hidden = false;
  populateFieldPalette(profile);
  bindBuilderEvents();
  resetShelves();
}

function populateFieldPalette(profile) {
  const buckets = { numeric: [], datetime: [], categorical: [] };
  profile.columns.forEach((c) => {
    if (c.name.endsWith("_is_outlier")) return;
    const bucket = buckets[c.kind] || buckets.categorical;
    bucket.push(c);
  });
  for (const kind of ["numeric", "datetime", "categorical"]) {
    const el = document.getElementById(`fields-${kind}`);
    el.innerHTML = buckets[kind]
      .map(
        (c) =>
          `<div class="field-chip" draggable="true"
                 data-name="${escapeHtml(c.name)}" data-kind="${kind}">
             ${escapeHtml(c.name)}
           </div>`
      )
      .join("") || '<div class="field-empty">none</div>';
    el.querySelectorAll(".field-chip").forEach(bindFieldDrag);
  }
}

function bindFieldDrag(chip) {
  chip.addEventListener("dragstart", (e) => {
    e.dataTransfer.setData("text/plain", chip.dataset.name);
    e.dataTransfer.setData("text/kind", chip.dataset.kind);
    chip.classList.add("dragging");
  });
  chip.addEventListener("dragend", () => chip.classList.remove("dragging"));
}

function bindBuilderEvents() {
  document.querySelectorAll(".kind-btn").forEach((btn) =>
    btn.addEventListener("click", () => {
      document.querySelectorAll(".kind-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      builderState.kind = btn.dataset.kind;
      scheduleBuild();
    })
  );

  document.querySelectorAll(".shelf-drop").forEach((shelf) => {
    shelf.addEventListener("dragover", (e) => {
      e.preventDefault();
      shelf.classList.add("drop-hover");
    });
    shelf.addEventListener("dragleave", () => shelf.classList.remove("drop-hover"));
    shelf.addEventListener("drop", (e) => {
      e.preventDefault();
      shelf.classList.remove("drop-hover");
      const name = e.dataTransfer.getData("text/plain");
      const kind = e.dataTransfer.getData("text/kind");
      if (!name) return;
      const shelfKey = shelf.parentElement.dataset.shelf;
      builderState[shelfKey] = name;
      renderShelfPill(shelf, name, kind, shelfKey);
      scheduleBuild();
    });
  });

  $("#builder-agg").addEventListener("change", (e) => {
    builderState.agg = e.target.value;
    scheduleBuild();
  });

  $("#builder-clear").addEventListener("click", () => {
    builderState.x = builderState.y = builderState.color = null;
    resetShelves();
    $("#builder-chart").innerHTML = "";
    $("#builder-status").textContent = "";
    $("#builder-save").disabled = true;
  });

  $("#builder-save").addEventListener("click", () => saveBuiltChart());
}

function resetShelves() {
  ["x", "y", "color"].forEach((key) => {
    const drop = document.getElementById(`shelf-${key}`);
    drop.innerHTML = '<span class="shelf-placeholder">Drop a column here</span>';
  });
}

function renderShelfPill(shelfEl, name, kind, shelfKey) {
  shelfEl.innerHTML = `
    <span class="shelf-pill shelf-pill-${kind}">
      ${escapeHtml(name)}
      <button class="shelf-pill-x" data-shelf="${shelfKey}" aria-label="remove">${CLOSE_ICON_SVG}</button>
    </span>`;
  shelfEl.querySelector(".shelf-pill-x").addEventListener("click", () => {
    builderState[shelfKey] = null;
    shelfEl.innerHTML = '<span class="shelf-placeholder">Drop a column here</span>';
    scheduleBuild();
  });
}

function scheduleBuild() {
  clearTimeout(builderTimer);
  builderTimer = setTimeout(buildChart, 150);
}

async function buildChart() {
  if (!currentSessionId) return;
  const { kind, x, y, color, agg } = builderState;
  // Need at least X for any chart, and Y for non-hist/pie.
  if (!x) {
    $("#builder-status").textContent = "Drop a column on X to start.";
    $("#builder-save").disabled = true;
    return;
  }
  if (!y && !["hist", "pie"].includes(kind)) {
    $("#builder-status").textContent = "Drop a column on Y.";
    $("#builder-save").disabled = true;
    return;
  }
  $("#builder-status").innerHTML = '<span class="spinner"></span> Building…';
  try {
    const res = await fetch("/build_chart", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: currentSessionId,
        kind, x, y, color, agg,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Build failed");
    renderPlotlySpec("builder-chart", data.chart_spec);
    $("#builder-status").textContent = "Ready.";
    $("#builder-save").disabled = false;
  } catch (err) {
    $("#builder-status").textContent = `Error: ${err.message}`;
    $("#builder-save").disabled = true;
  }
}

async function saveBuiltChart() {
  const { kind, x, y, color, agg } = builderState;
  try {
    const res = await fetch("/build_chart", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: currentSessionId,
        kind, x, y, color, agg,
        save: true,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Save failed");
    toast("Chart saved to report.");
  } catch (err) {
    toast(`Save failed: ${err.message}`, "error");
  }
}
