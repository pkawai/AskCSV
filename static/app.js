// AskCSV frontend. PR #3 wires upload -> profile -> charts. NLQ chat lands in PR #6.

const $ = (sel) => document.querySelector(sel);
const fileInput = $("#csv-file");
const uploadStatus = $("#upload-status");

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
    showStatus(`Uploaded ${file.name} → session ${data.session.session_id}`);
    const profRes = await fetch(`/profile/${data.session.session_id}`);
    const profData = await profRes.json();
    if (!profRes.ok) throw new Error(profData.error || "Profile failed");
    renderAll(data, profData);
  } catch (err) {
    showStatus(`Error: ${err.message}`, true);
  }
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
