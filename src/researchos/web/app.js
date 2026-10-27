/* ResearchOS workspace UI — vanilla JS, no build step. */

const $ = (selector) => document.querySelector(selector);

const state = {
  graph: { nodes: [], edges: [] },
  graphStatus: "loading",
  graphLoadPromise: null,
  graphRequestId: 0,
  notesRequestId: 0,
  traceRequestId: 0,
  activeProject: "default",
  selectedNode: null,
  busy: false,
};

const PROJECTS_STORAGE_KEY = "researchos.recent-project-labels";
const ACTIVE_PROJECT_STORAGE_KEY = "researchos.active-project-label";
const MAX_RECENT_PROJECTS = 8;

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

function updateRecentProjects(project) {
  const status = $("#project-status");
  try {
    const stored = localStorage.getItem(PROJECTS_STORAGE_KEY);
    const projects = stored === null ? [] : JSON.parse(stored);
    if (!Array.isArray(projects) || !projects.every((item) => typeof item === "string")) {
      throw new Error("Saved project labels have an invalid format.");
    }
    const recent = [project, ...projects.filter((item) => item !== project)]
      .slice(0, MAX_RECENT_PROJECTS);
    localStorage.setItem(PROJECTS_STORAGE_KEY, JSON.stringify(recent));
    localStorage.setItem(ACTIVE_PROJECT_STORAGE_KEY, project);
    const options = $("#recent-projects");
    options.replaceChildren(...recent.map((item) => {
      const option = document.createElement("option");
      option.value = item;
      return option;
    }));
    status.dataset.state = "success";
    status.textContent = `Current label: ${project}. Recent labels are stored in this browser; workspace data is not.`;
  } catch (error) {
    status.dataset.state = "failure";
    status.textContent = `Could not remember this project label in the browser: ${error.message}`;
  }
}

function initializeProjectShell() {
  const status = $("#project-status");
  let restoreError = null;
  try {
    const active = localStorage.getItem(ACTIVE_PROJECT_STORAGE_KEY);
    if (active) $("#project-id").value = active;
  } catch (error) {
    restoreError = error;
  }
  state.activeProject = projectId();
  updateRecentProjects(projectId());
  if (restoreError) {
    status.dataset.state = "failure";
    status.textContent = `Could not restore the project label from this browser: ${restoreError.message}`;
  }
}

function toast(message, bad = false) {
  const box = $("#toast");
  box.textContent = message;
  box.classList.toggle("bad", Boolean(bad));
  box.classList.add("show");
  window.clearTimeout(toast._timer);
  toast._timer = window.setTimeout(() => box.classList.remove("show"), 3200);
}

function formatErrorDetail(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      if (!item || typeof item !== "object") return String(item);
      const location = Array.isArray(item.loc)
        ? item.loc.filter((part) => part !== "body").join(".")
        : "";
      const message = typeof item.msg === "string"
        ? item.msg
        : "Request validation failed";
      return location ? `${location}: ${message}` : message;
    }).filter(Boolean);
    if (messages.length) return messages.join("; ");
  }
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return "";
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    if (response.ok) throw new Error("Server returned an invalid JSON response.");
  }
  if (!response.ok) {
    const detail = formatErrorDetail(payload && payload.detail);
    throw new Error(detail || `Request failed (${response.status})`);
  }
  if (payload === null) throw new Error("Server returned an empty response.");
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
    if (!data || typeof data.version !== "string" ||
        !Number.isFinite(data.graph_nodes) || !Number.isFinite(data.graph_edges)) {
      throw new Error("The health response did not match the documented schema.");
    }
    $("#stat-nodes").textContent = data.graph_nodes;
    $("#stat-edges").textContent = data.graph_edges;
    dot.classList.add("ok");
    dot.classList.remove("bad");
    $("#health-label").textContent = `v${data.version} · online`;
    $("#health-label").removeAttribute("title");
  } catch (error) {
    $("#stat-nodes").textContent = "—";
    $("#stat-edges").textContent = "—";
    dot.classList.add("bad");
    dot.classList.remove("ok");
    $("#health-label").textContent = "API unavailable";
    $("#health-label").title = `Health check failed: ${error.message}`;
  }
}

async function loadNotes() {
  const list = $("#notes-list");
  const requestId = ++state.notesRequestId;
  list.dataset.state = "loading";
  list.replaceChildren(el("li", "empty state-message state-loading", "Loading notes…"));
  try {
    const data = await api(`/api/notes?project_id=${encodeURIComponent(projectId())}`);
    if (requestId !== state.notesRequestId) return;
    if (!data || !Array.isArray(data.notes)) {
      throw new Error("The notes response did not contain a notes list.");
    }
    list.replaceChildren();
    if (!data.notes.length) {
      list.dataset.state = "empty";
      list.append(el("li", "empty state-message state-empty", "No notes yet."));
      return;
    }
    list.dataset.state = "success";
    for (const note of data.notes) {
      if (!note || typeof note.content !== "string") {
        throw new Error("The notes response contained an invalid note.");
      }
      const item = el("li");
      if (note.title) item.append(el("span", "note-title", note.title));
      item.append(el("span", "note-body", note.content));
      list.append(item);
    }
  } catch (error) {
    if (requestId !== state.notesRequestId) return;
    list.dataset.state = "failure";
    list.replaceChildren(el("li", "empty state-message state-failure", `Could not load notes: ${error.message}`));
  }
}

async function loadGraph() {
  const requestId = ++state.graphRequestId;
  state.graphStatus = "loading";
  state.graph = { nodes: [], edges: [] };
  renderGraph();
  renderPapers();
  const request = api("/api/graph/data");
  state.graphLoadPromise = request;
  try {
    const data = await request;
    if (requestId !== state.graphRequestId) return;
    if (!data || !Array.isArray(data.nodes) || !Array.isArray(data.edges)) {
      throw new Error("The graph response did not contain nodes and edges.");
    }
    state.graph = data;
    state.graphStatus = data.nodes.length ? "success" : "empty";
    renderGraph();
    renderPapers();
  } catch (error) {
    if (requestId !== state.graphRequestId) return;
    state.graphStatus = "failure";
    state.graph = { nodes: [], edges: [] };
    renderGraph();
    renderPapers();
    toast(`Graph unavailable: ${error.message}`, true);
  } finally {
    if (requestId === state.graphRequestId) state.graphLoadPromise = null;
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
  if (state.graphStatus === "loading") {
    list.dataset.state = "loading";
    list.append(el("li", "empty state-message state-loading", "Loading papers…"));
    return;
  }
  if (state.graphStatus === "failure") {
    list.dataset.state = "failure";
    list.append(el("li", "empty state-message state-failure", "Papers unavailable because the graph could not be loaded."));
    return;
  }
  if (!papers.length) {
    list.dataset.state = "empty";
    list.append(el("li", "empty state-message state-empty", "No papers ingested for this project yet."));
    return;
  }
  list.dataset.state = "success";

  for (const paper of papers) {
    const title =
      (paper.metadata && paper.metadata.title) ||
      paper.summary ||
      paper.content ||
      "Untitled paper";
    const meta = paper.metadata || {};
    const item = el("li");
    const openButton = el("button", "paper-open");
    openButton.type = "button";
    openButton.append(el("span", "note-title", title));
    const details = [
      meta.year,
      paper.status,
      `Access status: ${meta.access_status || "not provided by API"}`,
    ].filter(Boolean).join(" · ");
    openButton.append(el("span", "hint", details));
    openButton.addEventListener("click", () => showTrace(paper.id));
    item.append(openButton);

    const evidenceIds = state.graph.edges
      .filter((edge) => edge.source_id === paper.id && edge.relation_type === "extracted_from")
      .map((edge) => edge.target_id);
    const evidenceNodes = evidenceIds
      .map((id) => graphNode(id))
      .filter(Boolean);
    const evidenceList = el("details", "paper-evidence");
    evidenceList.append(el("summary", null, `Inspect evidence (${evidenceNodes.length})`));
    if (!evidenceNodes.length) {
      evidenceList.append(el("p", "hint", "No extracted evidence nodes are available for this paper."));
    } else {
      for (const evidence of evidenceNodes) {
        const evidenceButton = el(
          "button",
          "evidence-open",
          (evidence.content || evidence.summary || "Untitled evidence").slice(0, 180),
        );
        evidenceButton.type = "button";
        const location = [
          evidence.metadata && evidence.metadata.section,
          evidence.metadata && evidence.metadata.page != null
            ? `page ${evidence.metadata.page}`
            : null,
        ].filter(Boolean).join(" · ");
        evidenceButton.append(el(
          "span",
          "hint",
          location || "Page/section not provided by API",
        ));
        evidenceButton.addEventListener("click", () => showTrace(evidence.id));
        evidenceList.append(evidenceButton);
      }
    }
    item.append(evidenceList);
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
  if (state.graphStatus === "loading" || state.graphStatus === "failure") {
    const message = document.createElementNS("http://www.w3.org/2000/svg", "text");
    message.setAttribute("x", String(width / 2));
    message.setAttribute("y", String(height / 2));
    message.setAttribute("text-anchor", "middle");
    message.setAttribute("fill", state.graphStatus === "failure" ? "#ef4444" : "#64748b");
    message.setAttribute("font-size", "12");
    message.textContent = state.graphStatus === "loading"
      ? "Loading graph…"
      : "Graph unavailable. Refresh to try again.";
    svg.append(message);
    return;
  }
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

function graphNode(nodeId) {
  return state.graph.nodes.find((node) => node.id === nodeId);
}

function sourcePaperFor(node) {
  if (node.node_type === "paper") return node;
  const edge = state.graph.edges.find(
    (item) => item.target_id === node.id && item.relation_type === "extracted_from",
  );
  return edge ? graphNode(edge.source_id) : null;
}

function metadataLine(container, label, value) {
  if (value === undefined || value === null || value === "") return;
  const line = el("p", "evidence-metadata-line");
  line.append(el("strong", null, `${label}: `), document.createTextNode(String(value)));
  container.append(line);
}

function renderEvidenceMetadata(node, heading = "Evidence metadata") {
  const metadata = node.metadata || {};
  const sourcePaper = sourcePaperFor(node);
  const sourceMetadata = sourcePaper ? sourcePaper.metadata || {} : metadata;
  const section = el("div", "trace-section evidence-details");
  section.append(el("h4", null, heading));

  const title = sourceMetadata.title ||
    (node.node_type === "paper" ? node.summary : metadata.source_paper) ||
    node.summary ||
    "Not provided by API";
  metadataLine(section, "Title", title);
  const authorsValue = sourceMetadata.authors || metadata.authors;
  const authors = Array.isArray(authorsValue) ? authorsValue.join(", ") : authorsValue;
  metadataLine(section, "Authors", authors || "Not provided by API");
  metadataLine(section, "Year", sourceMetadata.year ?? metadata.year ?? "Not provided by API");
  metadataLine(section, "DOI", sourceMetadata.doi || metadata.doi || metadata.source_doi || "Not provided by API");
  metadataLine(section, "arXiv", sourceMetadata.arxiv_id || metadata.arxiv_id || "Not provided by API");
  const sourceUrl = sourceMetadata.url || metadata.url;
  if (sourceUrl) {
    try {
      const url = new URL(sourceUrl);
      if (url.protocol === "http:" || url.protocol === "https:") {
        const line = el("p", "evidence-metadata-line");
        line.append(el("strong", null, "Source URL: "));
        const link = el("a", null, url.href);
        link.href = url.href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        line.append(link);
        section.append(line);
      }
    } catch {
      metadataLine(section, "Source URL", "Unavailable (invalid URL in API response)");
    }
  } else {
    metadataLine(section, "Source URL", "Not provided by API");
  }

  const accessStatus = sourceMetadata.access_status || metadata.access_status;
  metadataLine(
    section,
    "Access status",
    typeof accessStatus === "string" && accessStatus.trim()
      ? accessStatus
      : "Not provided by API; full-text access is unverified",
  );

  if (node.node_type !== "paper") {
    metadataLine(section, "Section", metadata.section || "Not provided by API");
    metadataLine(section, "Page", metadata.page ?? "Not provided by API");
    metadataLine(section, "Extraction confidence", metadata.confidence ?? "Not provided by API");
  } else if (sourceMetadata.page_count !== undefined && sourceMetadata.page_count !== null) {
    metadataLine(section, "PDF page count", sourceMetadata.page_count);
  }
  return section;
}

async function showTrace(nodeId) {
  if (!nodeId) return;
  const requestId = ++state.traceRequestId;
  const panel = $("#trace-panel");
  panel.replaceChildren(el("p", "hint", "Checking citation…"));

  if (state.graphStatus === "loading" && state.graphLoadPromise) {
    await state.graphLoadPromise;
  }
  if (requestId !== state.traceRequestId) return;
  if (state.graphStatus === "failure") {
    panel.replaceChildren(el("p", "state-message state-failure", "Citation could not be verified because the knowledge graph is unavailable."));
    return;
  }
  if (!state.graph.nodes.some((node) => node.id === nodeId)) {
    state.selectedNode = null;
    panel.replaceChildren(el("p", "state-message state-failure", `Unresolvable citation: node ${nodeId} is not present in the loaded graph.`));
    return;
  }

  state.selectedNode = nodeId;
  panel.replaceChildren(el("p", "hint", "Building trace…"));

  let trace;
  try {
    trace = await jsonRequest("/api/trace", { node_id: nodeId });
    if (requestId !== state.traceRequestId) return;
    if (!trace || trace.answer_node_id !== nodeId ||
        !Array.isArray(trace.provenance_chain) ||
        !Array.isArray(trace.superseded_claims) ||
        !Array.isArray(trace.contradictions) ||
        !Array.isArray(trace.source_papers)) {
      throw new Error("The trace response did not match the documented schema.");
    }
  } catch (error) {
    if (requestId !== state.traceRequestId) return;
    panel.replaceChildren(el("p", "state-message state-failure", `Trace failed: ${error.message}`));
    return;
  }

  if (requestId !== state.traceRequestId) return;
  panel.replaceChildren();
  const head = el("div");
  head.append(el("h3", null, "Research Trace"));
  head.append(el("p", "hint", `Answer node ${trace.answer_node_id}`));
  const summary = el("div", "trace-summary");
  summary.append(
    el("span", null, `Provenance: ${trace.provenance_chain.length}`),
    el("span", null, `Superseded: ${trace.superseded_claims.length}`),
    el("span", null, `Contradictions: ${trace.contradictions.length}`),
    el("span", null, `Sources: ${trace.source_papers.length}`),
    el("span", null, "Blocked steps: not reported by API"),
  );
  head.append(summary);
  panel.append(head);
  const selected = graphNode(nodeId);
  if (selected) panel.append(renderEvidenceMetadata(selected, "Selected source/evidence"));

  const chain = el("div", "trace-section");
  chain.append(el("h4", null, `Provenance chain (${trace.provenance_chain.length})`));
  if (!trace.provenance_chain.length) {
    chain.append(el("p", "hint", "No provenance edges recorded for this node."));
  }
  for (const step of trace.provenance_chain) {
    chain.append(traceStep(step, step.edge_relation));
  }
  panel.append(chain);

  const superseded = el("div", "trace-section");
  superseded.append(el("h4", null, `Superseded claims (${trace.superseded_claims.length})`));
  if (!trace.superseded_claims.length) {
    superseded.append(el("p", "hint", "No superseded claims recorded for this trace."));
  }
  for (const node of trace.superseded_claims) {
    const step = traceStep(node, null, "bad", `→ ${node.superseded_by || "?"}`);
    step.addEventListener("click", () => showTrace(node.id));
    step.style.cursor = "pointer";
    superseded.append(step);
  }
  panel.append(superseded);

  const contradictions = el("div", "trace-section");
  contradictions.append(el("h4", null, `Contradictions (${trace.contradictions.length})`));
  if (!trace.contradictions.length) {
    contradictions.append(el("p", "hint", "No contradictions recorded for this trace."));
  }
  for (const item of trace.contradictions) {
    const step = traceStep(
      { node_id: item.node_id, content: item.content, node_type: item.relation },
      null,
      "warn",
      `confidence ${Number(item.confidence || 0).toFixed(2)}`,
    );
    if (item.evidence) step.append(el("span", "content", item.evidence));
    contradictions.append(step);
  }
  panel.append(contradictions);

  const sources = el("div", "trace-section");
  sources.append(el("h4", null, `Source papers (${trace.source_papers.length})`));
  if (!trace.source_papers.length) {
    sources.append(el("p", "hint", "No paper node found in this chain."));
  }
  for (const node of trace.source_papers) {
    sources.append(traceStep(node, null, "ok"));
    const source = graphNode(node.id);
    if (source) sources.append(renderEvidenceMetadata(source));
  }
  panel.append(sources);
}

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------

function addMessage(role, text, meta, stateClass = "") {
  const article = el("article", `message ${role} ${stateClass}`.trim());
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

function citationIds(answer, reportedIds) {
  const inlineIds = Array.from(
    answer.matchAll(/\[(?:Node:)?([A-Za-z0-9_-]{6,})\]/g),
    (match) => match[1],
  );
  return Array.from(new Set([...reportedIds, ...inlineIds]));
}

function markdownText(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\\/g, "\\\\")
    .replace(/([`*_{}\[\]()#+\-.!|])/g, "\\$1");
}

async function markdownReport(query, intent, answer, citedNodes) {
  if (state.graphStatus === "loading" && state.graphLoadPromise) {
    await state.graphLoadPromise;
  }
  if (state.graphStatus === "failure") {
    throw new Error("Cannot verify citations because the knowledge graph is unavailable.");
  }

  const citations = [];
  for (const nodeId of citedNodes) {
    const node = graphNode(nodeId);
    if (!node) {
      throw new Error(`Citation ${nodeId} is not present in the loaded graph.`);
    }
    const trace = await jsonRequest("/api/trace", { node_id: nodeId });
    if (!trace || trace.answer_node_id !== nodeId ||
        !Array.isArray(trace.provenance_chain) ||
        !Array.isArray(trace.superseded_claims) ||
        !Array.isArray(trace.contradictions) ||
        !Array.isArray(trace.source_papers)) {
      throw new Error(`Citation ${nodeId} could not be verified by the trace API.`);
    }
    citations.push({ node, trace });
  }

  const lines = [
    "# ResearchOS research report",
    "",
    `**Question:** ${markdownText(query)}`,
    `**Intent:** ${markdownText(intent || "Not provided by API")}`,
    "",
    "## Answer",
    "",
    ...answer.split("\n").map((line) => markdownText(line)),
    "",
    "## Citations and provenance",
    "",
  ];
  if (!citations.length) {
    lines.push("The API returned no citations for this answer.");
  }
  for (const { node, trace } of citations) {
    const metadata = node.metadata || {};
    const title = metadata.title || node.summary || node.content || "Not provided by API";
    lines.push(
      `- **Node ${markdownText(node.id)}** (${markdownText(node.node_type)}): ${markdownText(title)}`,
      `  - Provenance steps: ${trace.provenance_chain.length}`,
      `  - Superseded claims: ${trace.superseded_claims.length}`,
      `  - Contradictions: ${trace.contradictions.length}`,
      `  - Source papers: ${trace.source_papers.length}`,
    );
    for (const source of trace.source_papers) {
      const graphSource = graphNode(source.id);
      const sourceTitle = graphSource?.metadata?.title || source.summary || source.content || "Not provided by API";
      lines.push(`  - Source ${markdownText(source.id)}: ${markdownText(sourceTitle)}`);
    }
  }
  lines.push("", "_Exported from the live ResearchOS answer and verified graph traces._");
  return lines.join("\n");
}

async function exportMarkdownReport(button, query, intent, answer, citedNodes) {
  button.disabled = true;
  const originalLabel = button.textContent;
  button.textContent = "Verifying citations…";
  try {
    const content = await markdownReport(query, intent, answer, citedNodes);
    const blobUrl = URL.createObjectURL(new Blob([content], { type: "text/markdown;charset=utf-8" }));
    const link = el("a");
    const slug = query.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 48) || "research";
    link.href = blobUrl;
    link.download = `researchos-report-${new Date().toISOString().slice(0, 10)}-${slug}.md`;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(blobUrl), 0);
    toast("Markdown report exported with verified citation traces.");
  } catch (error) {
    toast(`Report export failed: ${error.message}`, true);
  } finally {
    button.disabled = false;
    button.textContent = originalLabel;
  }
}

async function askQuestion(query) {
  if (state.busy) return;
  state.busy = true;
  const button = $("#chat-form button");
  setBusy(button, true, "Running…");
  const status = $("#chat-status");
  status.dataset.state = "running";
  status.textContent = "Connecting to the research progress stream…";
  const progress = $("#stream-progress");
  const steps = $("#stream-steps");
  progress.hidden = false;
  steps.replaceChildren();

  addMessage("user", query);

  let settled = false;
  let failedAgents = 0;
  let source;
  try {
    source = new EventSource(`/api/stream?query=${encodeURIComponent(query)}`);
  } catch (error) {
    state.busy = false;
    setBusy(button, false);
    status.dataset.state = "failure";
    status.textContent = `Could not open the progress stream: ${error.message}`;
    addMessage("assistant", status.textContent, null, "failure");
    return;
  }
  const finish = () => {
    if (settled) return false;
    settled = true;
    source.close();
    state.busy = false;
    setBusy(button, false);
    return true;
  };
  const failStream = (message) => {
    if (!finish()) return;
    status.dataset.state = "failure";
    status.textContent = message;
    addMessage(
      "assistant",
      `${message} The server may still be processing the question; retrying could run it again.`,
      null,
      "failure",
    );
  };

  source.addEventListener("start", (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (!payload || typeof payload.message !== "string") {
        throw new Error("The start event did not match the documented contract.");
      }
      status.textContent = payload.message;
    } catch (error) {
      failStream(`Progress stream failed: ${error.message}`);
    }
  });

  source.addEventListener("agent_completed", (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (!payload || typeof payload.agent !== "string" ||
          typeof payload.success !== "boolean" ||
          !Number.isFinite(payload.duration_ms)) {
        throw new Error("An agent event did not match the documented contract.");
      }
      const failed = !payload.success;
      if (failed) failedAgents += 1;
      const item = el(
        "li",
        null,
        failed
          ? `${payload.agent}: reported failure`
          : `${payload.agent}: completed (${Math.round(payload.duration_ms)} ms)`,
      );
      item.dataset.state = failed ? "failure" : "success";
      steps.append(item);
      status.textContent = failed
        ? `${payload.agent} reported a failure; the pipeline may continue.`
        : `${payload.agent} completed.`;
    } catch (error) {
      failStream(`Progress stream failed: ${error.message}`);
    }
  });

  source.addEventListener("done", (event) => {
    try {
      const payload = JSON.parse(event.data);
      const data = payload && payload.data;
      const result = data && data.result;
      if (!payload || typeof payload.success !== "boolean" ||
          !data || typeof data !== "object" || Array.isArray(data) ||
          (result !== null && (typeof result !== "object" || Array.isArray(result)))) {
        throw new Error("The final event did not match the documented contract.");
      }
      const answer = typeof result?.answer === "string" ? result.answer.trim() : "";
      const reportedCitations = result?.cited_nodes ?? [];
      const alerts = result?.alerts ?? [];
      if (!Array.isArray(reportedCitations) ||
          !reportedCitations.every((nodeId) => typeof nodeId === "string" && nodeId.length > 0) ||
          !Array.isArray(alerts) ||
          !alerts.every((alert) => alert && typeof alert === "object")) {
        throw new Error("The final event contained invalid answer metadata.");
      }
      if (data.intent !== undefined && typeof data.intent !== "string") {
        throw new Error("The final event contained an invalid intent.");
      }
      const citedNodes = citationIds(answer, reportedCitations);
      if (!finish()) return;

      const badge = $("#intent-badge");
      if (data.intent) {
        badge.hidden = false;
        badge.textContent = data.intent.replace(/_/g, " ");
      }
      const meta = citedNodes.map((nodeId) => {
        const chip = el("button", "chip", `[${nodeId.slice(0, 8)}]`);
        chip.type = "button";
        chip.addEventListener("click", () => showTrace(nodeId));
        return chip;
      });
      if (answer) {
        const exportButton = el("button", "chip", "Export Markdown");
        exportButton.type = "button";
        exportButton.addEventListener("click", () => {
          exportMarkdownReport(exportButton, query, data.intent, answer, citedNodes);
        });
        meta.push(exportButton);
      }
      const article = addMessage(
        "assistant",
        answer || "The API returned no answer. This is an empty result, not a successful research answer.",
        meta,
        answer ? "" : "empty-result",
      );
      for (const alert of alerts) {
        const tone = alert.type === "superseded" ? "alert bad" : "alert";
        article.append(el("div", tone, alert.message || JSON.stringify(alert)));
      }
      if (answer && (failedAgents > 0 || !payload.success)) {
        status.dataset.state = "partial";
        status.textContent = `Answer received, but ${failedAgents || "the pipeline"} reported failure. The API does not define formal partial-result semantics.`;
      } else if (answer) {
        status.dataset.state = "success";
        status.textContent = `Answer received; ${steps.children.length} agent step(s) reported. End-to-end completion semantics are not defined by this API.`;
      } else if (payload.success) {
        status.dataset.state = "empty";
        status.textContent = "Empty result: the stream ended without an answer.";
      } else {
        status.dataset.state = "failure";
        status.textContent = "The pipeline reported failure and returned no answer.";
      }
      if (citedNodes.length) showTrace(citedNodes[0]);
      loadHealth();
    } catch (error) {
      failStream(`Progress stream failed: ${error.message}`);
    }
  });

  source.onerror = () => {
    failStream("Progress stream disconnected before a final event.");
  };

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

function applyProjectSelection() {
  const selectedProject = projectId();
  if (selectedProject === state.activeProject) return;
  state.activeProject = selectedProject;
  updateRecentProjects(selectedProject);
  loadNotes();
  renderPapers();
  toast(`Project: ${selectedProject}`);
}

$("#project-id").addEventListener("change", applyProjectSelection);
$("#project-id").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    applyProjectSelection();
    event.currentTarget.blur();
  }
});
$("#project-open").addEventListener("click", applyProjectSelection);

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

let resizeTimer = null;
window.addEventListener("resize", () => {
  window.clearTimeout(resizeTimer);
  resizeTimer = window.setTimeout(renderGraph, 180);
});

initializeProjectShell();
Promise.all([loadHealth(), loadNotes(), loadGraph()]);
