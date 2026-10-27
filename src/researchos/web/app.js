/* ResearchOS workspace UI — vanilla JS, no build step. */

const $ = (selector) => document.querySelector(selector);

const state = {
  graph: { nodes: [], edges: [] },
  selectedNode: null,
  busy: false,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function projectId() {
  return ($("#project-id").value || "default").trim() || "default";
}

function toast(message, bad = false) {
  const box = $("#toast");
  box.textContent = message;
  box.classList.toggle("bad", Boolean(bad));
  box.classList.add("show");
  window.clearTimeout(toast._timer);
  toast._timer = window.setTimeout(() => box.classList.remove("show"), 3200);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  let payload = null;
  try {
    payload = await response.json();
  } catch (error) {
    payload = null;
  }
  if (!response.ok) {
    const detail = payload && payload.detail ? payload.detail : response.statusText;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return payload;
}

function jsonRequest(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function setBusy(button, busy, label) {
  if (!button) return;
  if (busy) {
    button.dataset.label = button.textContent;
    button.textContent = label || "Working…";
    button.disabled = true;
  } else {
    button.textContent = button.dataset.label || button.textContent;
    button.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Health, notes, graph
// ---------------------------------------------------------------------------

async function loadHealth() {
  const dot = $("#health-dot");
  try {
    const data = await api("/health");
    $("#stat-nodes").textContent = data.graph_nodes;
    $("#stat-edges").textContent = data.graph_edges;
    dot.classList.add("ok");
    dot.classList.remove("bad");
    $("#health-label").textContent = `v${data.version} · online`;
  } catch (error) {
    dot.classList.add("bad");
    dot.classList.remove("ok");
    $("#health-label").textContent = "offline";
  }
}

async function loadNotes() {
  const list = $("#notes-list");
  try {
    const data = await api(`/api/notes?project_id=${encodeURIComponent(projectId())}`);
    list.replaceChildren();
    if (!data.notes.length) {
      list.append(el("li", "empty", "No notes yet."));
      return;
    }
    for (const note of data.notes) {
      const item = el("li");
      if (note.title) item.append(el("span", "note-title", note.title));
      item.append(el("span", "note-body", note.content));
      list.append(item);
    }
  } catch (error) {
    list.replaceChildren(el("li", "empty", `Could not load notes: ${error.message}`));
  }
}

async function loadGraph() {
  try {
    state.graph = await api("/api/graph/data");
    renderGraph();
    renderPapers();
  } catch (error) {
    toast(`Graph unavailable: ${error.message}`, true);
  }
}

function renderPapers() {
  const list = $("#papers-list");
  const papers = state.graph.nodes
    .filter((node) => node.node_type === "paper")
    .filter((node) => {
      const project = (node.metadata && node.metadata.project_id) || "default";
      return project === projectId();
    })
    .sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));

  list.replaceChildren();
  if (!papers.length) {
    list.append(el("li", "empty", "No papers ingested yet."));
    return;
  }

  for (const paper of papers) {
    const title =
      (paper.metadata && paper.metadata.title) ||
      paper.summary ||
      paper.content ||
      "Untitled paper";
    const meta = paper.metadata || {};
    const item = el("li");
    item.style.cursor = "pointer";
    item.append(el("span", "note-title", title));
    const details = [meta.year, paper.status].filter(Boolean).join(" · ");
    if (details) item.append(el("span", "hint", details));
    item.addEventListener("click", () => showTrace(paper.id));
    list.append(item);
  }
}

const NODE_COLORS = {
  paper: "#38bdf8",
  claim: "#34d399",
  method: "#a78bfa",
  result: "#f472b6",
  finding: "#fbbf24",
  hypothesis: "#fb923c",
  note: "#c084fc",
  generic: "#94a3b8",
};

function nodeColor(node) {
  if (node.status === "superseded") return "#ef4444";
  if (node.status === "contested") return "#f59e0b";
  return NODE_COLORS[node.node_type] || NODE_COLORS.generic;
}

function layoutGraph(nodes, edges, width, height) {
  const positions = new Map();
  const radius = Math.min(width, height) * 0.34;
  nodes.forEach((node, index) => {
    const angle = (index / Math.max(nodes.length, 1)) * Math.PI * 2;
    positions.set(node.id, {
      x: width / 2 + Math.cos(angle) * radius,
      y: height / 2 + Math.sin(angle) * radius,
      vx: 0,
      vy: 0,
    });
  });

  const iterations = nodes.length > 90 ? 90 : 160;
  for (let step = 0; step < iterations; step += 1) {
    const cooling = 1 - step / iterations;

    // Repulsion between every pair (bounded for UI-scale graphs).
    for (let i = 0; i < nodes.length; i += 1) {
      const a = positions.get(nodes[i].id);
      for (let j = i + 1; j < nodes.length; j += 1) {
        const b = positions.get(nodes[j].id);
        let dx = a.x - b.x;
        let dy = a.y - b.y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
        const force = (2400 * cooling) / (dist * dist);
        dx = (dx / dist) * force;
        dy = (dy / dist) * force;
        a.vx += dx;
        a.vy += dy;
        b.vx -= dx;
        b.vy -= dy;
      }
    }

    // Spring attraction along edges.
    for (const edge of edges) {
      const a = positions.get(edge.source_id);
      const b = positions.get(edge.target_id);
      if (!a || !b) continue;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const force = (dist - 90) * 0.008 * cooling;
      a.vx += (dx / dist) * force;
      a.vy += (dy / dist) * force;
      b.vx -= (dx / dist) * force;
      b.vy -= (dy / dist) * force;
    }

    // Gravity toward center + velocity clamp.
    for (const node of nodes) {
      const p = positions.get(node.id);
      p.vx += (width / 2 - p.x) * 0.0025;
      p.vy += (height / 2 - p.y) * 0.0025;
      p.vx = Math.max(-12, Math.min(12, p.vx));
      p.vy = Math.max(-12, Math.min(12, p.vy));
      p.x = Math.max(18, Math.min(width - 18, p.x + p.vx));
      p.y = Math.max(18, Math.min(height - 18, p.y + p.vy));
      p.vx *= 0.72;
      p.vy *= 0.72;
    }
  }

  return positions;
}

function renderGraph() {
  const svg = $("#graph");
  const width = Math.max(svg.clientWidth || 420, 320);
  const height = Math.max(svg.clientHeight || 260, 220);
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.replaceChildren();

  const nodes = state.graph.nodes;
  const edges = state.graph.edges;
  if (!nodes.length) {
    const message = document.createElementNS("http://www.w3.org/2000/svg", "text");
    message.setAttribute("x", String(width / 2));
    message.setAttribute("y", String(height / 2));
    message.setAttribute("text-anchor", "middle");
    message.setAttribute("fill", "#64748b");
    message.setAttribute("font-size", "12");
    message.textContent = "Ingest a paper or note to build the graph.";
    svg.append(message);
    return;
  }

  const positions = layoutGraph(nodes, edges, width, height);
  const degree = new Map();
  for (const edge of edges) {
    degree.set(edge.source_id, (degree.get(edge.source_id) || 0) + 1);
    degree.set(edge.target_id, (degree.get(edge.target_id) || 0) + 1);
  }

  for (const edge of edges) {
    const a = positions.get(edge.source_id);
    const b = positions.get(edge.target_id);
    if (!a || !b) continue;
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", String(a.x));
    line.setAttribute("y1", String(a.y));
    line.setAttribute("x2", String(b.x));
    line.setAttribute("y2", String(b.y));
    line.setAttribute("class", `edge ${edge.relation_type}`);
    svg.append(line);
  }

  for (const node of nodes) {
    const p = positions.get(node.id);
    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    const radius = 4 + Math.min(5, degree.get(node.id) || 0);
    circle.setAttribute("cx", String(p.x));
    circle.setAttribute("cy", String(p.y));
    circle.setAttribute("r", String(radius));
    circle.setAttribute("class", "node");
    circle.setAttribute("fill", nodeColor(node));
    circle.setAttribute("data-node-id", node.id);
    circle.setAttribute("title", `${node.node_type} · ${node.status}`);
    circle.addEventListener("click", () => showTrace(node.id));
    svg.append(circle);

    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", String(p.x));
    label.setAttribute("y", String(p.y + radius + 9));
    label.setAttribute("text-anchor", "middle");
    label.setAttribute("class", "label");
    const words = (node.summary || node.content || node.node_type || "").split(/\s+/);
    label.textContent = words.slice(0, 3).join(" ").slice(0, 28);
    svg.append(label);
  }
}

// ---------------------------------------------------------------------------
// Research Trace
// ---------------------------------------------------------------------------

function traceStep(node, relation, tone = "", extra = "") {
  const step = el("div", `trace-step ${tone}`.trim());
  const title = el("strong", null, `[${node.node_id || node.id}] ${node.node_type || ""}`);
  step.append(title);
  if (relation) step.append(el("span", "relation", ` ← ${relation}`));
  if (extra) step.append(el("span", "relation", ` ${extra}`));
  step.append(el("span", "content", (node.content || node.summary || "").slice(0, 220)));
  return step;
}

async function showTrace(nodeId) {
  if (!nodeId) return;
  state.selectedNode = nodeId;
  const panel = $("#trace-panel");
  panel.replaceChildren(el("p", "hint", "Building trace…"));

  let trace;
  try {
    trace = await jsonRequest("/api/trace", { node_id: nodeId });
  } catch (error) {
    panel.replaceChildren(el("p", "hint", `Trace failed: ${error.message}`));
    return;
  }

  panel.replaceChildren();
  const head = el("div");
  head.append(el("h3", null, "Research Trace"));
  head.append(el("p", "hint", `Answer node ${trace.answer_node_id}`));
  panel.append(head);

  const chain = el("div", "trace-section");
  chain.append(el("h4", null, `Provenance chain (${trace.provenance_chain.length})`));
  if (!trace.provenance_chain.length) {
    chain.append(el("p", "hint", "No provenance edges recorded for this node."));
  }
  for (const step of trace.provenance_chain) {
    chain.append(traceStep(step, step.edge_relation));
  }
  panel.append(chain);

  if (trace.superseded_claims.length) {
    const section = el("div", "trace-section");
    section.append(el("h4", null, `Superseded claims (${trace.superseded_claims.length})`));
    for (const node of trace.superseded_claims) {
      const step = traceStep(node, null, "bad", `→ ${node.superseded_by || "?"}`);
      step.addEventListener("click", () => showTrace(node.id));
      step.style.cursor = "pointer";
      section.append(step);
    }
    panel.append(section);
  }

  if (trace.contradictions.length) {
    const section = el("div", "trace-section");
    section.append(el("h4", null, `Contradictions (${trace.contradictions.length})`));
    for (const item of trace.contradictions) {
      const step = traceStep(
        { node_id: item.node_id, content: item.content, node_type: item.relation },
        null,
        "warn",
        `confidence ${Number(item.confidence || 0).toFixed(2)}`,
      );
      if (item.evidence) step.append(el("span", "content", item.evidence));
      section.append(step);
    }
    panel.append(section);
  }

  const sources = el("div", "trace-section");
  sources.append(el("h4", null, `Source papers (${trace.source_papers.length})`));
  if (!trace.source_papers.length) {
    sources.append(el("p", "hint", "No paper node found in this chain."));
  }
  for (const node of trace.source_papers) {
    sources.append(traceStep(node, null, "ok"));
  }
  panel.append(sources);
}

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------

function addMessage(role, text, meta) {
  const article = el("article", `message ${role}`);
  article.append(el("div", "message-body", text));
  if (meta && meta.length) {
    const bar = el("div", "meta");
    for (const item of meta) bar.append(item);
    article.append(bar);
  }
  $("#messages").append(article);
  $("#messages").scrollTop = $("#messages").scrollHeight;
  return article;
}

async function askQuestion(query) {
  if (state.busy) return;
  state.busy = true;
  const button = $("#chat-form button");
  setBusy(button, true, "Thinking…");

  addMessage("user", query);

  const budget = Number($("#token-budget").value) || 2048;

  try {
    const response = await jsonRequest("/api/chat", {
      query,
      include_trace: true,
      token_budget: budget,
    });

    const badge = $("#intent-badge");
    if (response.intent) {
      badge.hidden = false;
      badge.textContent = response.intent.replace(/_/g, " ");
    }

    const meta = [];
    for (const nodeId of response.cited_nodes) {
      const chip = el("button", "chip", `[${nodeId.slice(0, 8)}]`);
      chip.type = "button";
      chip.addEventListener("click", () => showTrace(nodeId));
      meta.push(chip);
    }

    const usage = response.metadata && response.metadata.context_usage;
    if (usage) {
      const dropped = usage.nodes_dropped
        ? ` · ${usage.nodes_dropped} dropped`
        : "";
      meta.push(
        el(
          "span",
          "context-usage",
          `Context ${usage.nodes_used}/${usage.nodes_retrieved} nodes · ` +
            `${usage.tokens_used}/${usage.token_budget} tokens${dropped}`,
        ),
      );
    }

    const search = response.external_search;
    if (search && search.status) {
      const bad = search.status === "error" || search.status === "partial";
      meta.push(
        el(
          "span",
          `context-usage${bad ? " over" : ""}`,
          `search: ${search.status}`,
        ),
      );
    }

    const article = addMessage(
      "assistant",
      response.answer || "No answer was produced by the pipeline.",
      meta,
    );

    for (const alert of response.alerts || []) {
      const tone = alert.type === "superseded" ? "alert bad" : "alert";
      article.append(el("div", tone, alert.message || JSON.stringify(alert)));
    }

    if (response.cited_nodes.length) {
      showTrace(response.cited_nodes[0]);
    }
    loadHealth();
  } catch (error) {
    addMessage("assistant", `Request failed: ${error.message}`);
  } finally {
    state.busy = false;
    setBusy(button, false);
  }
}

// ---------------------------------------------------------------------------
// Forms
// ---------------------------------------------------------------------------

$("#paper-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type=submit]");
  const data = new FormData(form);
  const authors = String(data.get("authors") || "")
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean);
  const yearValue = String(data.get("year") || "").trim();

  setBusy(button, true, "Ingesting…");
  try {
    const response = await jsonRequest("/api/papers/ingest", {
      project_id: projectId(),
      title: String(data.get("title") || "").trim(),
      authors,
      year: yearValue ? Number(yearValue) : null,
      doi: String(data.get("doi") || "").trim(),
      abstract: String(data.get("abstract") || "").trim(),
    });
    toast(`Ingested ${response.claim_node_ids.length} claims.`);
    form.reset();
    await Promise.all([loadHealth(), loadGraph(), loadNotes()]);
  } catch (error) {
    toast(`Ingest failed: ${error.message}`, true);
  } finally {
    setBusy(button, false);
  }
});

$("#upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type=submit]");
  const data = new FormData(form);
  data.set("project_id", projectId());

  setBusy(button, true, "Parsing…");
  try {
    const response = await api("/api/papers/upload", { method: "POST", body: data });
    toast(`Parsed PDF into ${response.claim_node_ids.length} claims.`);
    form.reset();
    await Promise.all([loadHealth(), loadGraph()]);
  } catch (error) {
    toast(`PDF ingest failed: ${error.message}`, true);
  } finally {
    setBusy(button, false);
  }
});

$("#note-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type=submit]");
  const data = new FormData(form);

  setBusy(button, true, "Saving…");
  try {
    await jsonRequest("/api/notes", {
      project_id: projectId(),
      title: String(data.get("title") || "").trim(),
      content: String(data.get("content") || "").trim(),
    });
    form.reset();
    toast("Note saved.");
    await Promise.all([loadHealth(), loadGraph(), loadNotes()]);
  } catch (error) {
    toast(`Could not save note: ${error.message}`, true);
  } finally {
    setBusy(button, false);
  }
});

$("#chat-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = $("#chat-input");
  const query = input.value.trim();
  if (!query) return;
  input.value = "";
  askQuestion(query);
});

$("#chat-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    $("#chat-form").requestSubmit();
  }
});

$("#refresh-btn").addEventListener("click", () => {
  Promise.all([loadHealth(), loadNotes(), loadGraph()]);
});

$("#demo-btn").addEventListener("click", async () => {
  const button = $("#demo-btn");
  setBusy(button, true, "Loading…");
  try {
    const response = await jsonRequest("/api/demo/seed", {
      project_id: projectId(),
    });
    toast(response.message || "Demo corpus loaded.");
    await Promise.all([loadHealth(), loadNotes(), loadGraph()]);
  } catch (error) {
    toast(`Demo corpus failed: ${error.message}`, true);
  } finally {
    setBusy(button, false);
  }
});

$("#project-id").addEventListener("change", () => {
  loadNotes();
  renderPapers();
  toast(`Project: ${projectId()}`);
});

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

let resizeTimer = null;
window.addEventListener("resize", () => {
  window.clearTimeout(resizeTimer);
  resizeTimer = window.setTimeout(renderGraph, 180);
});

Promise.all([loadHealth(), loadNotes(), loadGraph()]);
