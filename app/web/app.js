"use strict";

const form = document.getElementById("solve-form");
const submitBtn = document.getElementById("submit-btn");
const resultCard = document.getElementById("result-card");
const resultBody = document.getElementById("result-body");
const errorCard = document.getElementById("error-card");
const errorBody = document.getElementById("error-body");

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function fractionText(frac) {
  if (!frac) return "";
  if (frac.is_integer) return frac.decimal.toString();
  return `${frac.decimal.toFixed(6)}（精确值 ${frac.exact}）`;
}

function badge(status) {
  const map = {
    unique: ['unique', '唯一确定'],
    pending: ['pending', '待核'],
    infeasible: ['infeasible', '不可行'],
  };
  const [cls, text] = map[status] || ['error', '错误'];
  return `<span class="badge ${cls}">${text}</span>`;
}

function renderEdgeTable(edges) {
  const rows = edges.map((e) => `
    <tr>
      <td>${e.sequence_no}</td>
      <td class="mono">${escapeHtml(e.edge_id)}</td>
      <td class="mono">${escapeHtml(e.from_intersection_id)}</td>
      <td class="mono">${escapeHtml(e.to_intersection_id)}</td>
      <td>${e.length_m}</td>
    </tr>`).join("");
  return `
    <div class="scroll-x">
      <table>
        <thead><tr><th>序号</th><th>路段 ID</th><th>起点路口</th><th>终点路口</th><th>长度（米）</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

function renderNodeSequences(sequences) {
  const items = sequences
    .map((seq) => `<li class="mono">${seq.map(escapeHtml).join(" → ")}</li>`)
    .join("");
  return `<ul>${items}</ul>`;
}

function renderHopTable(hops) {
  const rows = hops.map((h) => `
    <tr>
      <td>${h.hop}</td>
      <td class="mono">${escapeHtml(h.from_node)} → ${escapeHtml(h.to_node)}</td>
      <td>${h.shortest_length_m}</td>
      <td>${h.shortest_path_count}</td>
      <td class="mono">${h.edge_ids ? h.edge_ids.map(escapeHtml).join(" → ") : "—"}</td>
    </tr>`).join("");
  return `
    <h3>逐跳最短路明细</h3>
    <div class="scroll-x">
      <table>
        <thead><tr><th>跳次</th><th>路口对</th><th>最短长度（米）</th><th>最短路径条数</th><th>路段序列</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

function renderResult(data) {
  errorCard.hidden = true;
  resultCard.hidden = false;
  let html = `<div class="result-summary">${badge(data.status)} <p>${escapeHtml(data.message)}</p>`;
  if (data.minimum_squared_distance_sum) {
    html += `<p>最小平方距离总和：<strong>${fractionText(data.minimum_squared_distance_sum)}</strong> 米²</p>`;
  }
  html += `<p>各定位点半径内候选路口数：<span class="mono">[${data.candidate_counts.join(", ")}]</span></p></div>`;

  if (data.status === "unique") {
    html += `<h3>匹配路口序列</h3><p class="mono">${data.matched_node_sequence.map(escapeHtml).join(" → ")}</p>`;
    html += `<h3>依次经过的路段（${data.edge_sequence.length} 条）</h3>`;
    html += renderEdgeTable(data.edge_sequence);
    if (data.hop_details && data.hop_details.length) html += renderHopTable(data.hop_details);
    html += `<div class="download-row"><a href="${data.download_url}" download="edge_sequence.csv">下载路段 ID CSV</a></div>`;
  } else if (data.status === "pending") {
    html += `<div class="warn-box">结果待人工核验，<strong>不导出确定路径</strong>。</div>`;
    if (data.optimal_node_sequence_count !== undefined) {
      html += `<h3>达到最优的路口序列（共 ${data.optimal_node_sequence_count} 条，最多展示 50 条）</h3>`;
      html += renderNodeSequences(data.optimal_node_sequences || []);
    }
    if (data.ambiguity && data.ambiguity.type === "edge_sequence") {
      html += `<h3>存在多种最短路段序列的路口对</h3><ul>`;
      for (const h of data.ambiguity.non_unique_hops) {
        html += `<li class="mono">${escapeHtml(h.from_node)} → ${escapeHtml(h.to_node)}：最短长度 ${h.shortest_length_m} 米，最短路段序列 ${h.shortest_path_count} 条</li>`;
      }
      html += `</ul>`;
    }
    if (data.hop_details && data.hop_details.length) html += renderHopTable(data.hop_details);
  } else {
    html += `<div class="error-box">不可行，未产生结果文件。</div>`;
    if (data.infeasible_detail && data.infeasible_detail.hops) {
      html += `<h3>受阻路口对明细</h3><div class="scroll-x"><table>
        <thead><tr><th>起点路口</th><th>终点路口</th><th>原因</th><th>最短路长（米）</th><th>里程上限（米）</th></tr></thead><tbody>`;
      for (const hop of data.infeasible_detail.hops) {
        for (const pair of hop.blocked_pairs) {
          html += `<tr>
            <td class="mono">${escapeHtml(pair.from_node)}</td>
            <td class="mono">${escapeHtml(pair.to_node)}</td>
            <td>${pair.reason === "unreachable" ? "有向不可达" : "超过速度允许里程"}</td>
            <td>${pair.shortest_length_m ?? "—"}</td>
            <td>${pair.budget_m ?? "—"}</td>
          </tr>`;
        }
      }
      html += `</tbody></table></div>`;
    }
  }
  resultBody.innerHTML = html;
}

function renderError(payload) {
  resultCard.hidden = true;
  errorCard.hidden = false;
  const message = payload && payload.message ? payload.message : "未知错误，请检查输入后重试。";
  const code = payload && payload.reason_code ? `<code>${escapeHtml(payload.reason_code)}</code> ` : "";
  errorBody.innerHTML = `${code}${escapeHtml(message)}`;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  submitBtn.disabled = true;
  submitBtn.textContent = "求解中…";
  try {
    const response = await fetch("/api/solve", { method: "POST", body: new FormData(form) });
    const payload = await response.json();
    if (response.ok) renderResult(payload);
    else renderError(payload);
  } catch (err) {
    renderError({ message: `请求失败：${err.message}` });
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "求解";
  }
});

async function setFileInput(input, url, filename) {
  const res = await fetch(url);
  const blob = await res.blob();
  const file = new File([blob], filename, { type: "text/csv" });
  const transfer = new DataTransfer();
  transfer.items.add(file);
  input.files = transfer.files;
}

document.getElementById("sample-btn").addEventListener("click", async () => {
  try {
    await Promise.all([
      setFileInput(form.elements.intersections, "/static/samples/intersections.csv", "intersections.csv"),
      setFileInput(form.elements.edges, "/static/samples/edges.csv", "edges.csv"),
      setFileInput(form.elements.track, "/static/samples/track.csv", "track.csv"),
    ]);
    form.elements.snap_radius.value = "20";
    form.elements.max_speed.value = "15";
  } catch (err) {
    renderError({ message: `示例数据加载失败：${err.message}` });
  }
});
