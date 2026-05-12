// AskCSV frontend. PR #3 wires upload -> profile -> charts. NLQ chat lands in PR #6.

const $ = (sel) => document.querySelector(sel);
const fileInput = $("#csv-file");
const uploadStatus = $("#upload-status");

let currentSessionId = null;

const PLOTLY_LAYOUT = {
  paper_bgcolor: "#1e293b",
  plot_bgcolor: "#1e293b",
  font: { color: "#e2e8f0" },
  margin: { l: 50, r: 30, t: 40, b: 60 },
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

function renderColumns(cols) {
  $("#columns-section").hidden = false;
  $("#columns-grid").innerHTML = cols
    .filter((c) => !c.name.endsWith("_is_outlier"))
    .map(columnCard)
    .join("");
}

function columnCard(c) {
  const stats = [];
  if (c.kind === "numeric") {
    stats.push(`min ${c.min}`, `max ${c.max}`, `mean ${c.mean}`);
  } else if (c.kind === "datetime") {
    stats.push(`${c.min} → ${c.max}`);
  } else if (c.kind === "boolean") {
    stats.push(`true ${c.true_count}`, `false ${c.false_count}`);
  } else if (c.kind === "categorical") {
    stats.push(`${c.unique_count} unique`);
    if (c.top_values && c.top_values.length) {
      stats.push(`top: ${c.top_values.slice(0, 2).map((v) => v.value).join(", ")}`);
    }
  }
  return `
    <article class="column-card">
      <header>
        <span class="col-name">${c.name}</span>
        <span class="col-kind kind-${c.kind}">${c.kind}</span>
      </header>
      <div class="col-stats">${stats.join(" · ")}</div>
      <div class="col-meta">nulls: ${c.null_count} · unique: ${c.unique_count}</div>
    </article>
  `;
}

function renderMissingChart(mvm) {
  if (!mvm.columns.length) return;
  $("#missing-section").hidden = false;
  Plotly.newPlot(
    "missing-chart",
    [
      {
        type: "bar",
        x: mvm.columns,
        y: mvm.null_pct,
        marker: { color: "#38bdf8" },
        hovertemplate: "%{x}<br>nulls: %{y}%<extra></extra>",
      },
    ],
    { ...PLOTLY_LAYOUT, yaxis: { title: "null %" }, height: 280 },
    { displayModeBar: false, responsive: true }
  );
}

function renderCorrelationChart(corr) {
  if (corr.columns.length < 2) return;
  $("#correlation-section").hidden = false;
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
        hovertemplate: "%{x} vs %{y}<br>r = %{z}<extra></extra>",
      },
    ],
    { ...PLOTLY_LAYOUT, height: 320 },
    { displayModeBar: false, responsive: true }
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
    turn.innerHTML = `<div class="chat-q">${escapeHtml(question)}</div>
      <div class="chat-error">Error: ${escapeHtml(err.message)}</div>`;
  }
}

function appendChatTurn(question, loading = false) {
  const thread = $("#chat-thread");
  const turn = document.createElement("article");
  turn.className = "chat-turn";
  turn.innerHTML = `<div class="chat-q">${escapeHtml(question)}</div>
    <div class="chat-loading">${loading ? "Thinking…" : ""}</div>`;
  thread.prepend(turn);
  return turn;
}

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

  turn.innerHTML = `
    <div class="chat-q">${escapeHtml(turn.querySelector(".chat-q").textContent)} ${cacheBadge}</div>
    <div class="chat-insight">${insight ? escapeHtml(insight) : "(no insight returned)"}</div>
    <div id="${chartId}" class="chat-chart"></div>
    ${followupChips}
    <details class="chat-trace">
      <summary>Tool trace (${(tool_trace || []).length} steps)</summary>
      ${traceLines || "<em>no tool calls</em>"}
    </details>
  `;

  if (chart_spec && chart_spec.data && chart_spec.data.length) {
    renderPlotlySpec(chartId, chart_spec);
  }
  turn.querySelectorAll(".chip-followup").forEach((btn) =>
    btn.addEventListener("click", () => askQuestion(btn.dataset.q))
  );
}

function renderPlotlySpec(divId, spec) {
  const data = spec.data;
  const xs = data.map((r) => r[spec.x]);
  const ys = data.map((r) => r[spec.y]);
  let traces;
  switch (spec.kind) {
    case "bar":
      traces = [{ type: "bar", x: xs, y: ys, marker: { color: "#38bdf8" } }];
      break;
    case "line":
      traces = [{ type: "scatter", mode: "lines+markers", x: xs, y: ys, line: { color: "#38bdf8" } }];
      break;
    case "scatter":
      traces = [{ type: "scatter", mode: "markers", x: xs, y: ys, marker: { color: "#38bdf8" } }];
      break;
    case "hist":
      traces = [{ type: "histogram", x: xs, marker: { color: "#38bdf8" } }];
      break;
    case "pie":
      traces = [{ type: "pie", labels: xs, values: ys }];
      break;
    default:
      traces = [{ type: "bar", x: xs, y: ys, marker: { color: "#38bdf8" } }];
  }
  Plotly.newPlot(
    divId,
    traces,
    { ...PLOTLY_LAYOUT, title: { text: spec.title }, height: 320 },
    { displayModeBar: false, responsive: true }
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
