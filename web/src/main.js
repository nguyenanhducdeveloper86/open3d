import "@phosphor-icons/web/regular";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import "./styles.css";

const REQUIRED_VIEWS = ["HERO_3Q", "FRONT", "BACK", "LEFT", "RIGHT", "TOP"];
const DEFAULT_HOUSE_PROMPT = "Production-quality stylized Scandinavian timber house prop, single-story modern cabin with a clean two-plane gabled roof, four walls, a door, two windows, a chimney, stone foundation, and front steps; clean bevels, separate semantic parts, realistic proportions, neutral studio materials, no floating or dangling roof bars, and six orthographic views.";
const MAX_REFERENCE_IMAGE_BYTES = 600 * 1024;
const MAX_REFERENCE_DATA_URL_LENGTH = 800000;

function readDraft() {
  try { return JSON.parse(localStorage.getItem("open3d.asset-draft") || "null"); } catch { return null; }
}

const savedDraft = readDraft();

const state = {
  inspect: null,
  report: null,
  history: [],
  versions: { schema_version: "0.1.0", current_version: null, current_checkpoint: null, can_undo: false, versions: [] },
  providers: [],
  agents: [
    { agent_id: "codex", label: "Codex", status: "CHECKING" },
    { agent_id: "claude", label: "Claude Code", status: "CHECKING" },
    { agent_id: "opencode", label: "OpenCode", status: "CHECKING" },
    { agent_id: "agy", label: "Agy Agent", status: "CHECKING" },
  ],
  agentPool: { mode: "DIRECT_CLI", status: "CHECKING" },
  production: null,
  workspace: null,
  activeView: "workspace",
  selectedAssetId: null,
  selectedInstanceId: null,
  selectedPart: null,
  selectedParts: [],
  inspectorTab: "inspector",
  viewportMode: "orbit",
  scenePlaceMode: false,
  pendingSpawn: null,
  dragAssetId: null,
  query: "",
  theme: "dark",
  busy: false,
  agentProvider: "codex",
  generationSource: savedDraft?.generation_source || "agent",
  generationQuality: savedDraft?.quality || "high",
  actionLog: [],
  createOpen: false,
  agentOpen: false,
  assetDraft: savedDraft,
  referenceImage: null,
  referenceImages: [],
  agentCreateAssetId: null,
  annotationMode: false,
  annotation: null,
  build: { status: "idle", agent: "", startedAt: 0 },
  agentMessages: [{ role: "agent", text: "Choose Codex, Claude Code, OpenCode, or Agy Agent. Open3D then runs Blender and QA. No local agent fallback." }],
};

const app = document.querySelector("#app");
app.innerHTML = `
  <div class="app-shell" data-theme="${state.theme}">
    <aside class="sidebar">
      <div class="brand"><span class="brand-mark"><i class="ph ph-cube"></i></span><span>OPEN3D<small>ARTIST WORKSPACE</small></span></div>
      <button class="workspace-switcher" id="project-switcher"><span class="workspace-dot"></span><span><b id="project-name">Loading project</b><small>Local workspace</small></span><i class="ph ph-caret-down"></i></button>
      <nav class="primary-nav" aria-label="Primary navigation">
        <button class="nav-item active" data-view="workspace"><i class="ph ph-squares-four"></i><span>Workspace</span><kbd>1</kbd></button>
        <button class="nav-item" data-view="qa"><i class="ph ph-shield-check"></i><span>Quality checks</span><span class="nav-count" id="qa-count">-</span></button>
        <button class="nav-item" data-view="history"><i class="ph ph-clock-counter-clockwise"></i><span>History</span><span class="nav-count" id="history-count">0</span></button>
        <button class="nav-item" data-view="providers"><i class="ph ph-sparkle"></i><span>Providers</span></button>
      </nav>
      <div class="sidebar-section">
        <div class="section-label"><span>PROJECT FILES</span><button class="section-action" id="quick-create" aria-label="Create asset"><i class="ph ph-plus"></i></button></div>
        <div class="file-tree"><div class="tree-row folder"><i class="ph ph-folder-open"></i><span>Assets</span></div><div class="tree-row selected"><i class="ph ph-cube"></i><span id="asset-file">asset.yaml</span><span class="tree-status"></span></div><div class="tree-row"><i class="ph ph-file-text"></i><span>QA report</span></div></div>
      </div>
      <div class="sidebar-footer"><div class="runtime-status"><span class="status-pulse"></span><span>OPEN3D RUNTIME</span><b id="runtime-status-value">CHECKING</b></div><div class="footer-links"><span>v0.1 alpha</span><a href="https://github.com/nguyenanhducdeveloper86/open3d" target="_blank" rel="noreferrer">GitHub <i class="ph ph-arrow-up-right"></i></a></div></div>
    </aside>
    <main class="main-shell">
      <header class="topbar"><div class="crumbs"><span>Projects</span><i class="ph ph-caret-right"></i><strong id="breadcrumb-name">Open3D asset</strong></div><label class="search-box"><i class="ph ph-magnifying-glass"></i><input id="search" type="search" placeholder="Search parts, checks, providers" /><kbd>⌘ K</kbd></label><div class="top-actions"><button class="top-action create-trigger" id="create-asset"><i class="ph ph-plus"></i><span>Create 3D asset</span></button><button class="top-action agent-trigger" id="open-agent" aria-controls="agent-drawer" aria-expanded="false"><i class="ph ph-sparkle"></i><span>Agent</span></button><button class="validate-button" id="validate"><i class="ph ph-shield-check"></i><span>Run QA</span></button><div class="avatar">DA</div></div></header>
      <section class="content-shell">
        <div class="content-heading"><div><div class="eyebrow">OPEN3D / LIVE ARTIFACT</div><h1 id="asset-title">Loading asset</h1><p id="asset-subtitle">Preparing the contract and GLB preview</p></div><div class="heading-meta"><span class="status-badge" id="qa-status"><span></span>Checking</span><span class="artifact-id" id="artifact-id">sha256:...</span></div></div>
        <div id="view-root"></div>
      </section>
    </main>
    <div class="modal-layer" id="create-layer" hidden>
      <div class="modal-backdrop" data-close-create></div>
      <form class="create-modal" id="create-form" aria-labelledby="create-title">
        <header class="modal-header"><div><div class="eyebrow">CREATE 3D ASSET</div><h2 id="create-title">Describe what should exist</h2><p>Choose a real generation path. Meshy runs preview/refine or image-to-3D at high detail; Codex/Claude/OpenCode run the Blender build through the sandbox.</p></div><button class="icon-button" type="button" id="create-close" aria-label="Close create asset dialog"><i class="ph ph-x"></i></button></header>
        <div class="create-layout">
          <div class="create-form-column">
            <div class="form-grid create-options"><label><span>GENERATION ENGINE</span><select id="create-generator"><option value="agent" ${state.generationSource === "agent" ? "selected" : ""}>External agent → Blender</option><option value="meshy-text" ${state.generationSource === "meshy-text" ? "selected" : ""}>Meshy Text → 3D · preview + refine</option><option value="meshy-image" ${state.generationSource === "meshy-image" ? "selected" : ""}>Meshy Image → 3D · one view</option><option value="meshy-multi" ${state.generationSource === "meshy-multi" ? "selected" : ""}>Meshy Multi-view → 3D · 1–4 views</option><option value="codex-image-meshy" ${state.generationSource === "codex-image-meshy" ? "selected" : ""}>Codex image → Meshy 3D</option><option value="all2api-image-meshy" ${state.generationSource === "all2api-image-meshy" ? "selected" : ""}>All2API image → Meshy 3D</option><option value="all2api-image-agent" ${state.generationSource === "all2api-image-agent" ? "selected" : ""}>All2API image → Agent Blender</option><option value="openai-image-meshy" ${state.generationSource === "openai-image-meshy" ? "selected" : ""}>OpenAI image → Meshy 3D</option></select></label><label><span>QUALITY PROFILE</span><select id="create-quality"><option value="draft" ${state.generationQuality === "draft" ? "selected" : ""}>Draft · 2K texture</option><option value="high" ${state.generationQuality === "high" ? "selected" : ""}>High · PBR + 4K</option><option value="hero" ${state.generationQuality === "hero" ? "selected" : ""}>Hero · PBR + 8K</option></select></label><label><span>ASSET ID</span><input id="create-id" name="brief_id" required maxlength="64" value="${escapeHtml(state.assetDraft?.brief_id || "PROP-SCANDI-HOUSE-001")}" /></label><label><span>REFERENCE PATH / NOTE</span><input id="create-reference" name="reference" maxlength="240" placeholder="Optional local path or note" value="${escapeHtml(state.assetDraft?.reference?.path || "")}" /></label></div>
            <label class="form-field"><span>GENERATION PROMPT</span><textarea id="create-prompt" name="prompt" required maxlength="4000" rows="9">${escapeHtml(state.assetDraft?.prompt || DEFAULT_HOUSE_PROMPT)}</textarea><small class="field-hint">Describe shape, materials, proportions, semantic parts, and game-ready constraints.</small></label>
            <div class="placement-note" id="create-placement"><i class="ph ph-map-pin"></i><span>Generated asset will be added to the Asset Library and placed at the scene origin.</span></div>
            <div class="reference-upload"><label class="reference-drop" for="create-reference-file"><input id="create-reference-file" type="file" accept="image/png,image/jpeg,image/webp" multiple /><i class="ph ph-image-square"></i><span id="reference-file-label">Attach reference image</span><small id="reference-file-hint">PNG, JPG, or WebP · compressed before upload</small></label><div class="reference-preview" id="reference-preview" hidden><img id="reference-preview-image" alt="Reference preview" /><div><b id="reference-preview-name"></b><small id="reference-preview-size"></small></div><button class="icon-button" type="button" id="reference-remove" aria-label="Remove reference image"><i class="ph ph-x"></i></button></div></div>
          </div>
          <aside class="create-preview" aria-label="Asset build plan">
            <div class="create-preview-header"><span>LIVE BUILD PLAN</span><b id="create-summary-state">READY</b></div>
            <div class="create-preview-asset"><small>ASSET ID</small><strong id="create-preview-id">PROP-SCANDI-HOUSE-001</strong></div>
            <div class="create-preview-prompt"><small>PROMPT PREVIEW</small><p id="create-preview-prompt">${escapeHtml(state.assetDraft?.prompt || DEFAULT_HOUSE_PROMPT)}</p><small>REFERENCE</small><p id="create-preview-reference">${escapeHtml(state.assetDraft?.reference?.path || "No reference attached")}</p></div>
            <ol class="create-flow" aria-label="Build pipeline"><li class="done"><span>01</span><div><b>Brief</b><small>Prompt + reference</small></div></li><li><span>02</span><div><b id="create-flow-step-two">Generator</b><small id="create-preview-agent">External agent</small></div></li><li><span>03</span><div><b id="create-flow-step-three">Build + quality</b><small id="create-flow-step-three-copy">Blender build, export GLB</small></div></li><li><span>04</span><div><b>QA gate</b><small>Contract + artifact checks</small></div></li></ol>
            <div class="create-agent-card"><div class="create-card-label">WHO BUILDS IT</div><div class="brief-agent"><label><span>EXTERNAL LLM</span><select id="create-agent"><option value="codex">Codex</option><option value="claude">Claude Code</option><option value="opencode">OpenCode</option><option value="agy">Agy Agent</option></select></label><span id="create-agent-status" class="agent-provider-status">Checking</span></div></div>
            <div class="view-contract"><div><span>REQUIRED OUTPUT</span><b>Six-view contract</b></div><div class="view-tags">${REQUIRED_VIEWS.map((view) => `<span>${view}</span>`).join("")}</div></div>
            <div class="form-boundary" id="create-boundary"><i class="ph ph-shield-check"></i><p>Remote generation requires explicit consent. Keys stay in the local runtime; Open3D never uses a local-agent fallback.</p></div>
          </aside>
        </div>
        <p class="form-status" id="create-status" aria-live="polite"></p>
        <footer class="modal-actions"><button class="quiet-button" type="button" id="create-cancel">Cancel</button><button class="quiet-button" type="submit"><i class="ph ph-floppy-disk"></i>Save draft</button><button class="primary-action compact" type="button" id="create-generate"><i class="ph ph-sparkle"></i>Generate 3D asset</button></footer>
      </form>
    </div>
    <div class="agent-backdrop" id="agent-backdrop" aria-hidden="true"></div>
    <aside class="agent-drawer" id="agent-drawer" aria-hidden="false" aria-labelledby="agent-title">
      <button class="agent-rail-tab" id="agent-rail-tab" type="button" aria-label="Open agent chat"><i class="ph ph-sparkle"></i><span>Agent</span></button>
      <header class="agent-header"><div><div class="eyebrow">LLM AGENTS</div><h2 id="agent-title">Asset build chat</h2><p id="agent-context">Select a part to give the agent a target.</p></div><button class="icon-button" id="close-agent" type="button" aria-label="Collapse agent chat" title="Collapse agent chat"><i class="ph ph-caret-right"></i></button></header>
      <div class="agent-policy"><i class="ph ph-shield-check"></i><span>External LLM → Blender sandbox → GLB + QA. No local agent fallback.</span></div>
      <section class="build-state" id="agent-build-state" hidden aria-live="polite"><div class="build-state-header"><span class="build-state-pulse"></span><div><b>BUILD IN PROGRESS</b><small id="build-state-detail">External LLM is authoring the staged build</small></div><time id="build-state-elapsed">00:00</time></div><div class="build-progress" aria-hidden="true"><span></span></div><p><i class="ph ph-lock-key"></i>Request locked. Keep this window open or close it safely; the build continues and duplicate runs are blocked.</p></section>
      <div class="agent-controls"><label><span>LLM EXECUTION</span><select id="agent-provider"><option value="codex">Codex</option><option value="claude">Claude Code</option><option value="opencode">OpenCode</option><option value="agy">Agy Agent</option></select></label><span class="agent-provider-status" id="agent-provider-status">Checking</span><span class="agent-provider-status" id="agent-pool-status">POOL CHECKING</span><button class="quiet-button agent-refresh" id="refresh-agents" type="button" title="Check LLM agents" aria-label="Check LLM agents"><i class="ph ph-arrows-clockwise"></i></button></div>
      <section class="agent-activity"><div class="activity-heading"><span>ACTION TRACE</span><button class="quiet-button" id="clear-actions" type="button">Clear</button></div><div id="agent-activity-list"><div class="activity-empty">No actions yet.</div></div></section>
      <div class="agent-thread" id="agent-thread" aria-live="polite"></div>
      <form class="agent-composer" id="agent-form"><div class="agent-mention-bar" id="agent-mentions" aria-live="polite"><span class="agent-mention-placeholder"><i class="ph ph-at"></i>Drop an asset here or type @asset</span></div><textarea id="agent-input" rows="2" placeholder="Try: build a production-quality Scandinavian timber house"></textarea><div class="agent-attachment" id="agent-attachment" hidden><i class="ph ph-image-square"></i><span id="agent-attachment-name"></span><button class="icon-button" type="button" id="agent-attachment-remove" aria-label="Remove attached reference"><i class="ph ph-x"></i></button></div><div><label class="agent-attach-button" for="agent-reference-file"><i class="ph ph-paperclip"></i>Reference<input id="agent-reference-file" type="file" accept="image/png,image/jpeg,image/webp" /></label><span id="agent-composer-note">LLM agent → Blender → QA</span><button class="primary-action compact" type="submit"><i class="ph ph-arrow-up-right"></i>Run build</button></div></form>
    </aside>
    <div class="build-monitor" id="build-monitor" hidden role="status"><span class="build-monitor-pulse"></span><div><b id="build-monitor-title">BUILD IN PROGRESS</b><small id="build-monitor-detail">External LLM request is running</small></div><time id="build-monitor-elapsed">00:00</time><button class="quiet-button" id="reopen-build" type="button">Open agent</button></div>
    <div class="toast-region" id="toasts" aria-live="polite"></div>
  </div>`;

const shell = document.querySelector(".app-shell");
const viewRoot = document.querySelector("#view-root");
const toastRegion = document.querySelector("#toasts");
const gltfLoader = new GLTFLoader();
const viewer = { scene: null, camera: null, renderer: null, controls: null, root: null, sceneGroup: null, canvas: null, raycaster: new THREE.Raycaster(), pointer: new THREE.Vector2(), original: new Map(), templates: new Map(), instances: new Map(), resize: null, frame: 0 };

function toast(message, tone = "neutral") {
  const node = document.createElement("div");
  node.className = `toast ${tone}`;
  node.innerHTML = `<i class="ph ${tone === "error" ? "ph-warning-circle" : tone === "success" ? "ph-check-circle" : "ph-info"}"></i><span>${escapeHtml(message)}</span>`;
  toastRegion.append(node);
  setTimeout(() => node.remove(), 3600);
}

function setRuntimeStatus(status) {
  const node = document.querySelector("#runtime-status-value");
  if (node) node.textContent = status;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}

function qaValue(value) {
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return String(text ?? "-").length > 220 ? `${String(text).slice(0, 217)}...` : String(text ?? "-");
}

function qaCheckText(check) {
  if (check.message) return check.message;
  const hint = check.repair_hint ? ` · fix: ${check.repair_hint}` : "";
  return `expected ${qaValue(check.expected)} · actual ${qaValue(check.actual)}${hint}`;
}

function qaTriangles(report = state.report) {
  return report?.checks?.find((check) => check.check_id === "geometry.triangle_budget")?.actual?.triangles ?? "-";
}

function visualQaSummary(result) {
  const score = result?.visual_judge?.similarity_percent ?? result?.visual_loop?.attempts?.at(-1)?.similarity_percent;
  const attempts = result?.visual_loop?.attempts?.length;
  if (score == null && !attempts) return "";
  return [score == null ? "Visual score pending" : `Visual ${score}/100 (gate ≥85)`, attempts > 1 ? `${attempts} attempts` : ""].filter(Boolean).join(" · ");
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function createAssetIdFromPrompt(text) {
  const value = String(text || "");
  const patterns = [
    /\b(?:create|generate|build)\s+(?:a\s+)?new\s+asset\b[\s\S]{0,40}?\basset[_ -]?id\s*[:=]?\s*([A-Za-z][A-Za-z0-9_-]*)/i,
    /\b(?:tạo|tao)\s+(?:một\s+)?asset\s+mới[\s\S]{0,40}?\basset[_ -]?id\s*[:=]?\s*([A-Za-z][A-Za-z0-9_-]*)/i,
  ];
  for (const pattern of patterns) {
    const match = pattern.exec(value);
    if (!match) continue;
    let assetId = match[1];
    const continuation = value.slice(match.index + match[0].length).match(/^[ \t\r\n]+(\d[A-Za-z0-9_-]*)/);
    if (assetId.endsWith("-") && continuation) assetId += continuation[1];
    return assetId;
  }
  return null;
}

function beginAction(label, detail = "") {
  const action = { id: `${Date.now()}-${state.actionLog.length}`, label, detail, status: "queued", at: Date.now() };
  state.actionLog.push(action);
  renderAgentActivity();
  return action.id;
}

function updateAction(id, status, detail) {
  const action = state.actionLog.find((item) => item.id === id);
  if (!action) return;
  action.status = status;
  action.detail = detail;
  action.at = Date.now();
  renderAgentActivity();
}

function renderAgentActivity() {
  const root = document.querySelector("#agent-activity-list");
  if (!root) return;
  if (!state.actionLog.length) { root.innerHTML = `<div class="activity-empty">No actions yet.</div>`; return; }
  const labels = { queued: "QUEUED", running: "RUNNING", done: "DONE", failed: "FAILED", info: "INFO" };
  root.innerHTML = state.actionLog.slice(-10).reverse().map((action) => `<div class="activity-row"><span class="activity-dot ${action.status}"></span><div><b>${escapeHtml(action.label)}</b><small>${escapeHtml(action.detail || labels[action.status] || action.status)}</small></div><time>${new Date(action.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time></div>`).join("");
}

let buildTicker = null;

function formatElapsed(milliseconds) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function renderBuildStatus() {
  const running = state.build.status === "running";
  const elapsed = running ? formatElapsed(Date.now() - state.build.startedAt) : "00:00";
  const agent = state.agents.find((item) => item.agent_id === state.build.agent);
  const label = agent?.label || generationLabel(state.build.agent) || state.build.agent || "LLM agent";
  const detail = running ? `${label} is running the generation pipeline · QA follows automatically` : "";
  const panel = document.querySelector("#agent-build-state");
  const panelDetail = document.querySelector("#build-state-detail");
  const panelElapsed = document.querySelector("#build-state-elapsed");
  const monitor = document.querySelector("#build-monitor");
  const monitorDetail = document.querySelector("#build-monitor-detail");
  const monitorElapsed = document.querySelector("#build-monitor-elapsed");
  const monitorTitle = document.querySelector("#build-monitor-title");
  if (panel) panel.hidden = !running;
  if (panelDetail) panelDetail.textContent = detail;
  if (panelElapsed) panelElapsed.textContent = elapsed;
  if (monitor) monitor.hidden = !running || state.agentOpen;
  if (monitorDetail) monitorDetail.textContent = running ? `${label} · request locked` : "";
  if (monitorElapsed) monitorElapsed.textContent = elapsed;
  if (monitorTitle) monitorTitle.textContent = `${label.toUpperCase()} BUILD RUNNING`;
  document.querySelector("#agent-drawer")?.setAttribute("aria-busy", String(running));
  const runButton = document.querySelector("#agent-form button[type=submit]");
  if (runButton) {
    if (!runButton.dataset.idleText) runButton.dataset.idleText = runButton.innerHTML;
    runButton.disabled = running;
    runButton.innerHTML = running ? `<i class="build-spinner"></i>Build running` : runButton.dataset.idleText;
  }
  ["#agent-input", "#agent-provider", "#refresh-agents", "#agent-reference-file", "#create-reference-file", "#create-agent", "#create-generator", "#create-quality", "#create-generate", "#validate", "#apply-scale", "#comment-selected", "#annotate-tool", "#orbit-tool", "#grab-tool"].forEach((selector) => {
    const control = document.querySelector(selector);
    if (control) control.disabled = running;
  });
  renderCreateSummary();
}

function startBuildStatus(agent) {
  state.build = { status: "running", agent, startedAt: Date.now() };
  clearInterval(buildTicker);
  buildTicker = setInterval(renderBuildStatus, 1000);
  renderBuildStatus();
}

function stopBuildStatus() {
  clearInterval(buildTicker);
  buildTicker = null;
  state.build = { status: "idle", agent: "", startedAt: 0 };
  renderBuildStatus();
}

function renderAgentProviderStatus() {
  const select = document.querySelector("#agent-provider");
  const status = document.querySelector("#agent-provider-status");
  const poolStatus = document.querySelector("#agent-pool-status");
  if (!select || !status) return;
  select.value = state.agentProvider;
  const agent = state.agents.find((item) => item.agent_id === state.agentProvider) || { status: "UNAVAILABLE", reason: "NOT_FOUND" };
  status.className = `agent-provider-status ${agent.status.toLowerCase()}`;
  status.textContent = agent.status === "ACTIVE" ? `ACTIVE${state.agentPool?.status === "ACTIVE" ? " · POOL" : " · DIRECT"}` : agent.status === "AUTH_REQUIRED" ? "AUTH REQUIRED" : agent.reason || "UNAVAILABLE";
  if (poolStatus) {
    poolStatus.className = `agent-provider-status ${(state.agentPool?.status || "checking").toLowerCase()}`;
    poolStatus.textContent = state.agentPool?.status === "ACTIVE" ? "POOL ACTIVE" : state.agentPool?.mode === "DIRECT_CLI" ? "DIRECT AUTH" : `POOL ${state.agentPool?.status || "CHECKING"}`;
  }
}

async function refreshAgents() {
  const actionId = beginAction("Check LLM agents", "Checking Codex, Claude Code, OpenCode, and Agy authentication");
  updateAction(actionId, "running", "Checking external LLM execution");
  try {
    [state.agents, state.agentPool] = await Promise.all([api("/api/agents"), api("/api/agent-pool")]);
    renderAgentProviderStatus();
    syncCreateAgent();
    const ready = state.agents.filter((agent) => agent.status === "ACTIVE").map((agent) => agent.label).join(", ");
    updateAction(actionId, "done", ready ? `${ready} active` : "No authenticated LLM agent");
    addAgentMessage("agent", ready ? `${ready} active · ${state.agentPool?.status === "ACTIVE" ? "shared pool" : "direct CLI auth"}.` : "No authenticated external LLM agent. The build button is blocked until Codex, Claude Code, OpenCode, or Agy is authenticated.");
  } catch (error) {
    updateAction(actionId, "failed", error.message);
    addAgentMessage("agent", `Agent adapter check failed: ${error.message}`);
  }
}

function persistDraft(draft) {
  try { localStorage.setItem("open3d.asset-draft", JSON.stringify(draft)); } catch { /* localStorage can be disabled in a locked-down browser */ }
}

function renderReferenceImage() {
  const images = state.referenceImages?.length ? state.referenceImages : state.referenceImage ? [state.referenceImage] : [];
  const image = images[0] || null;
  const drop = document.querySelector(".reference-drop");
  const label = document.querySelector("#reference-file-label");
  const preview = document.querySelector("#reference-preview");
  const previewImage = document.querySelector("#reference-preview-image");
  const previewName = document.querySelector("#reference-preview-name");
  const previewSize = document.querySelector("#reference-preview-size");
  const attachment = document.querySelector("#agent-attachment");
  const attachmentName = document.querySelector("#agent-attachment-name");
  if (!drop || !label || !preview || !previewImage || !previewName || !previewSize) return;
  drop.classList.toggle("has-file", Boolean(image));
  label.textContent = image ? `${images.length} reference${images.length === 1 ? "" : "s"} attached` : "Attach reference image";
  preview.hidden = !image;
  if (image) {
    previewImage.src = image.data;
    previewName.textContent = image.name;
    previewSize.textContent = `${Math.round(image.data.length / 1024)} KB encoded${images.length > 1 ? ` · ${images.length} total` : ""}`;
  } else {
    previewImage.removeAttribute("src");
    previewName.textContent = "";
    previewSize.textContent = "";
  }
  if (attachment && attachmentName) {
    attachment.hidden = !image;
    attachmentName.textContent = image ? `Reference · ${image.name}` : "";
  }
  renderCreateSummary();
}

function readDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("Could not read the reference image"));
    reader.readAsDataURL(file);
  });
}

function compressReferenceImage(dataUrl, fileName) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      const scale = Math.min(1, 1600 / Math.max(image.naturalWidth, image.naturalHeight));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
      canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
      canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height);
      resolve({ name: `${fileName.replace(/\.[^.]+$/, "")}.jpg`, mime_type: "image/jpeg", data: canvas.toDataURL("image/jpeg", 0.78) });
    };
    image.onerror = () => reject(new Error("Reference image could not be decoded"));
    image.src = dataUrl;
  });
}

async function attachReferenceImage(event) {
  const files = [...(event.target.files || [])];
  if (!files.length) return;
  const status = document.querySelector("#create-status");
  try {
    const isCreate = event.target.id === "create-reference-file";
    if (!isCreate) files.splice(1);
    if (isCreate && document.querySelector("#create-generator")?.value !== "meshy-multi" && files.length > 1) throw new Error("This generation mode accepts one reference image");
    if (isCreate && files.length > 4) throw new Error("Multi-view generation accepts up to four reference images");
    const images = [];
    for (const file of files) {
      if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) throw new Error("Use PNG, JPG, or WebP reference images");
      let data = await readDataUrl(file);
      let image = { name: file.name, mime_type: file.type, data };
      if (file.size > MAX_REFERENCE_IMAGE_BYTES || data.length > MAX_REFERENCE_DATA_URL_LENGTH) image = await compressReferenceImage(data, file.name);
      if (image.data.length > MAX_REFERENCE_DATA_URL_LENGTH) throw new Error("Reference image is still too large after compression");
      images.push(image);
    }
    state.referenceImages = isCreate ? images : [];
    state.referenceImage = images[0];
    renderReferenceImage();
    if (status) status.textContent = `Attached ${images.length} reference image${images.length === 1 ? "" : "s"}.`;
    else toast(`Attached ${images.length} reference image${images.length === 1 ? "" : "s"}`, "success");
  } catch (error) {
    event.target.value = "";
    state.referenceImage = null;
    state.referenceImages = [];
    renderReferenceImage();
    if (status) status.textContent = error.message;
    else toast(error.message, "error");
  }
}

function removeReferenceImage() {
  state.referenceImage = null;
  state.referenceImages = [];
  ["#create-reference-file", "#agent-reference-file"].forEach((selector) => {
    const input = document.querySelector(selector);
    if (input) input.value = "";
  });
  renderReferenceImage();
}

function readBriefForm() {
  const id = document.querySelector("#create-id").value.trim().toUpperCase().replace(/[^A-Z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 64);
  const prompt = document.querySelector("#create-prompt").value.trim();
  const referencePath = document.querySelector("#create-reference").value.trim();
  const generator = document.querySelector("#create-generator")?.value || state.generationSource || "agent";
  const quality = document.querySelector("#create-quality")?.value || state.generationQuality || "high";
  const references = state.referenceImages?.length ? state.referenceImages : state.referenceImage ? [state.referenceImage] : [];
  return { id, prompt, referencePath, generator, quality, references };
}

function setInspectorTab(tab) {
  if (!['inspector', 'contract'].includes(tab)) return;
  state.inspectorTab = tab;
  document.querySelectorAll('[data-inspector-tab]').forEach((button) => {
    const active = button.dataset.inspectorTab === tab;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
  });
  document.querySelector('#inspector-pane')?.toggleAttribute('hidden', tab !== 'inspector');
  document.querySelector('#contract-pane')?.toggleAttribute('hidden', tab !== 'contract');
}

function generationLabel(source) {
  return ({
    agent: state.agents.find((item) => item.agent_id === state.agentProvider)?.label || "External agent",
    "meshy-text": "Meshy Text → 3D",
    "meshy-image": "Meshy Image → 3D",
    "meshy-multi": "Meshy Multi-view → 3D",
    "codex-image-meshy": "Codex Image → Meshy 3D",
    "all2api-image-meshy": "All2API Image → Meshy 3D",
    "all2api-image-agent": "All2API Image → Agent Blender",
    "openai-image-meshy": "OpenAI Image → Meshy 3D",
  })[source] || source;
}

function providerConfigured(providerId) {
  return state.providers.some((provider) => provider.provider_id === providerId && provider.configured);
}

function createGeneratorReady(source) {
  if (source === "agent") return state.agents.some((agent) => agent.agent_id === state.agentProvider && agent.status === "ACTIVE");
  if (source === "meshy-text") return providerConfigured("meshy-text-to-3d");
  if (source === "meshy-image") return providerConfigured("meshy-image-to-3d");
  if (source === "meshy-multi") return providerConfigured("meshy-multi-image-to-3d");
  if (source === "codex-image-meshy") return providerConfigured("meshy-image-to-3d") && providerConfigured("codex-cli-image");
  if (source === "all2api-image-meshy") return providerConfigured("meshy-image-to-3d") && providerConfigured("all2api-image");
  if (source === "all2api-image-agent") return providerConfigured("all2api-image") && state.agents.some((agent) => agent.agent_id === state.agentProvider && agent.status === "ACTIVE");
  if (source === "openai-image-meshy") return providerConfigured("meshy-image-to-3d") && providerConfigured("openai-image");
  return false;
}

function createGeneratorNeedsImage(source) {
  return ["meshy-image", "meshy-multi"].includes(source);
}

function syncCreateGenerator() {
  const source = document.querySelector("#create-generator")?.value || state.generationSource || "agent";
  const multi = source === "meshy-multi";
  const input = document.querySelector("#create-reference-file");
  const agentCard = document.querySelector(".create-agent-card");
  const hint = document.querySelector("#reference-file-hint");
  const boundary = document.querySelector("#create-boundary p");
  if (input) input.multiple = multi;
  if (agentCard) agentCard.hidden = !["agent", "all2api-image-agent"].includes(source);
  if (hint) hint.textContent = source === "agent" ? "PNG, JPG, or WebP · attached to the external agent" : source === "all2api-image-agent" ? "Prompt → All2API reference image → selected external agent" : multi ? "PNG, JPG, or WebP · first image is the primary view · up to 4" : createGeneratorNeedsImage(source) ? "PNG, JPG, or WebP · one primary view" : "Optional · Meshy uses the text prompt directly";
  if (boundary) boundary.textContent = source === "agent" ? "Only an authenticated external agent can start this build. Open3D runs Blender and QA with no local fallback." : source === "all2api-image-agent" ? "All2API creates the reference image, then the selected external agent runs Blender and QA. No local fallback." : "Remote generation requires explicit consent. Keys stay in the local runtime; Open3D adopts only a verified GLB.";
  const quality = document.querySelector("#create-quality");
  if (quality) quality.disabled = source === "agent";
  state.generationSource = source;
  renderCreateSummary();
}

function renderCreateSummary() {
  const id = document.querySelector("#create-id")?.value.trim().toUpperCase() || "PROP-SCANDI-HOUSE-001";
  const prompt = document.querySelector("#create-prompt")?.value.trim() || "Add a production brief to preview the build.";
  const source = document.querySelector("#create-generator")?.value || state.generationSource || "agent";
  const agent = state.agents.find((item) => item.agent_id === state.agentProvider);
  const running = state.build.status === "running";
  const ready = createGeneratorReady(source);
  const references = state.referenceImages?.length ? state.referenceImages : state.referenceImage ? [state.referenceImage] : [];
  const hasRequiredReference = !createGeneratorNeedsImage(source) || references.length > 0;
  const status = running ? "BUILD RUNNING" : !hasRequiredReference ? "REFERENCE REQUIRED" : ready ? "READY TO BUILD" : source === "agent" ? agent?.status === "CHECKING" ? "CHECKING AGENT" : "AUTH REQUIRED" : "PROVIDER KEY REQUIRED";
  const reference = document.querySelector("#create-reference")?.value.trim();
  const idNode = document.querySelector("#create-preview-id");
  const promptNode = document.querySelector("#create-preview-prompt");
  const agentNode = document.querySelector("#create-preview-agent");
  const statusNode = document.querySelector("#create-summary-state");
  const referenceNode = document.querySelector("#create-preview-reference");
  if (idNode) idNode.textContent = id;
  if (promptNode) promptNode.textContent = prompt;
  if (agentNode) agentNode.textContent = generationLabel(source);
  if (referenceNode) referenceNode.textContent = reference || (references.length ? `${references.length} attached image${references.length === 1 ? "" : "s"}` : source === "agent" ? "No reference attached" : "Prompt-driven");
  if (statusNode) {
    statusNode.textContent = status;
    statusNode.className = running ? "running" : ready ? "ready" : "blocked";
  }
  const stepTwo = document.querySelector("#create-flow-step-two");
  const stepThree = document.querySelector("#create-flow-step-three");
  const stepThreeCopy = document.querySelector("#create-flow-step-three-copy");
  if (stepTwo) stepTwo.textContent = source === "agent" ? "External LLM" : source === "all2api-image-agent" ? "All2API image" : "AI generation";
  if (stepThree) stepThree.textContent = ["agent", "all2api-image-agent"].includes(source) ? "Blender build" : "Refine + PBR";
  if (stepThreeCopy) stepThreeCopy.textContent = source === "agent" ? "Author, run, export GLB" : source === "all2api-image-agent" ? "Reference → agent → GLB" : source === "meshy-text" ? "Preview → refine → GLB" : "Texture, normalize, export GLB";
  document.querySelectorAll(".create-flow li").forEach((step, index) => step.classList.toggle("active", running && index > 0 && index < 3));
  const generate = document.querySelector("#create-generate");
  if (generate) { generate.disabled = running || !ready || !hasRequiredReference; generate.innerHTML = source === "agent" ? `<i class="ph ph-sparkle"></i>Generate with agent` : `<i class="ph ph-sparkle"></i>Generate high-quality 3D`; }
}

function saveBriefState(brief, generation = "draft-only") {
  state.assetDraft = {
    schema_version: "0.1.0", brief_id: brief.id, prompt: brief.prompt,
    reference: { path: brief.referencePath, kind: brief.referencePath || state.referenceImage ? "attached" : "not-attached", image: state.referenceImage ? { name: state.referenceImage.name, mime_type: state.referenceImage.mime_type } : null },
    views: REQUIRED_VIEWS, generation, generation_source: brief.generator, quality: brief.quality,
  };
  persistDraft(state.assetDraft);
}

function syncCreateAgent() {
  const select = document.querySelector("#create-agent");
  const status = document.querySelector("#create-agent-status");
  if (!select || !status) return;
  select.value = state.agentProvider;
  const agent = state.agents.find((item) => item.agent_id === state.agentProvider) || { status: "CHECKING", reason: "CHECKING" };
  status.className = `agent-provider-status ${agent.status.toLowerCase()}`;
  status.textContent = agent.status === "ACTIVE" ? "ACTIVE" : agent.reason || agent.status;
  renderCreateSummary();
}

function openCreateAsset(spawnPosition = null) {
  state.createOpen = true;
  state.pendingSpawn = spawnPosition ? { position: { x: Number(spawnPosition.x.toFixed(3)), y: Number(spawnPosition.y.toFixed(3)), z: Number(spawnPosition.z.toFixed(3)) } } : null;
  const layer = document.querySelector("#create-layer");
  layer.hidden = false;
  document.querySelector("#create-status").textContent = state.assetDraft ? "Loaded the last local brief draft." : "";
  const placement = document.querySelector("#create-placement");
  if (placement) placement.innerHTML = state.pendingSpawn
    ? `<i class="ph ph-map-pin"></i><span>Spawn point set: ${state.pendingSpawn.position.x}, ${state.pendingSpawn.position.y}, ${state.pendingSpawn.position.z}</span>`
    : `<i class="ph ph-books"></i><span>Generated asset will be added to the Asset Library and placed at the scene origin.</span>`;
  syncCreateAgent();
  syncCreateGenerator();
  renderReferenceImage();
  renderCreateSummary();
  document.querySelector("#create-id").focus();
}

function closeCreateAsset() {
  state.createOpen = false;
  state.pendingSpawn = null;
  document.querySelector("#create-layer").hidden = true;
}

function saveAssetDraft(event) {
  event.preventDefault();
  const brief = readBriefForm();
  const status = document.querySelector("#create-status");
  if (!brief.id || !brief.prompt) { status.textContent = "Asset ID and prompt are required."; return; }
  saveBriefState(brief);
  closeCreateAsset();
  toast(`Saved brief ${brief.id}`, "success");
  addAgentMessage("agent", `Brief ${brief.id} is ready. Open the agent drawer when you want to generate it with Blender.`);
  openAgent();
}

function contractForAsset(assetId = state.selectedAssetId) {
  return state.workspace?.assets.find((asset) => asset.asset_id === assetId)?.contract || (assetId === state.inspect?.current?.asset_id ? state.inspect?.contract : null);
}

function selectedContractPart(partId = state.selectedPart, assetId = state.selectedAssetId) {
  return contractForAsset(assetId)?.parts.find((part) => part.part_id.toLowerCase() === String(partId || "").toLowerCase());
}

function selectedWorkspaceAsset() {
  return state.workspace?.assets.find((asset) => asset.asset_id === state.selectedAssetId) || state.workspace?.assets.find((asset) => asset.asset_id === state.inspect?.current?.asset_id) || null;
}

function workspaceAssetById(assetId) {
  const normalized = String(assetId ?? "").trim().replace(/^@/, "").toLowerCase();
  return normalized ? (state.workspace?.assets || []).find((asset) => String(asset.asset_id).toLowerCase() === normalized) || null : null;
}

function extractAssetMentions(text) {
  const value = String(text || "");
  return (state.workspace?.assets || []).map((asset) => {
    const pattern = new RegExp(`(^|[^A-Za-z0-9_-])@?${escapeRegExp(asset.asset_id)}(?=$|[^A-Za-z0-9_-])`, "i");
    const match = pattern.exec(value);
    return match ? { asset, index: match.index + match[1].length } : null;
  }).filter(Boolean).sort((left, right) => left.index - right.index || right.asset.asset_id.length - left.asset.asset_id.length).map((item) => item.asset);
}

function removeAgentMention(assetId) {
  const input = document.querySelector("#agent-input");
  if (!input) return;
  input.value = input.value.replace(new RegExp(`@?${escapeRegExp(assetId)}(?=$|\\s|[.,!?;:)])`, "gi"), "").replace(/[ \t]{2,}/g, " ").trim();
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.focus();
}

function renderAgentMentions() {
  const root = document.querySelector("#agent-mentions");
  const input = document.querySelector("#agent-input");
  if (!root || !input) return;
  const mentions = extractAssetMentions(input.value);
  root.classList.toggle("has-mentions", Boolean(mentions.length));
  root.innerHTML = mentions.length
    ? `<span class="agent-mention-label"><i class="ph ph-at"></i>MENTIONS</span>${mentions.map((asset) => `<button class="agent-mention-chip" type="button" data-remove-agent-mention="${escapeHtml(asset.asset_id)}" aria-label="Remove @${escapeHtml(asset.asset_id)}">@${escapeHtml(asset.asset_id)}<i class="ph ph-x"></i></button>`).join("")}`
    : `<span class="agent-mention-placeholder"><i class="ph ph-at"></i>Drop an asset here or type @asset</span>`;
  root.querySelectorAll("[data-remove-agent-mention]").forEach((button) => button.addEventListener("click", () => removeAgentMention(button.dataset.removeAgentMention)));
}

function droppedWorkspaceAsset(event) {
  const value = event.dataTransfer?.getData("application/x-open3d-asset") || event.dataTransfer?.getData("text/plain") || state.dragAssetId;
  return workspaceAssetById(value);
}

function clearAgentAssetDropState() {
  document.querySelector("#agent-input")?.classList.remove("is-asset-drop-target");
  document.querySelector("#agent-mentions")?.classList.remove("is-asset-drop-target");
}

function insertAgentAssetMention(event) {
  const asset = droppedWorkspaceAsset(event);
  const input = document.querySelector("#agent-input");
  if (!asset || !input) return;
  event.preventDefault();
  const start = input.selectionStart ?? input.value.length;
  const end = input.selectionEnd ?? start;
  const before = input.value.slice(0, start);
  const after = input.value.slice(end);
  const prefix = before && !/\s$/.test(before) ? " " : "";
  const suffix = after && !/^\s/.test(after) ? " " : " ";
  input.setRangeText(`${prefix}@${asset.asset_id}${suffix}`, start, end, "end");
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.focus();
  clearAgentAssetDropState();
  toast(`Mentioned @${asset.asset_id}`, "success");
}

function selectedAssetContract() {
  return contractForAsset();
}

function selectedAssetInstances(assetId = state.selectedAssetId) {
  return (state.workspace?.scene?.instances || []).filter((instance) => instance.asset_id === assetId);
}

function instanceTransformKey(instance) {
  return JSON.stringify([instance.position, instance.rotation, instance.scale]);
}

function selectionKey(selection) {
  return `${selection.assetId || ""}::${selection.instanceId || ""}::${selection.partId}`;
}

function selectedPartDescriptors() {
  if (state.selectedParts.length) return state.selectedParts;
  const part = selectedContractPart();
  return part ? [{ assetId: state.selectedAssetId, instanceId: state.selectedInstanceId, partId: part.part_id, role: part.role || "semantic part" }] : [];
}

function isPartSelected(partId, assetId = state.selectedAssetId, instanceId = state.selectedInstanceId) {
  return selectedPartDescriptors().some((selection) => selection.partId === partId && selection.assetId === assetId && selection.instanceId === instanceId);
}

function selectedAgentTarget() {
  const selections = state.annotation?.partId
    ? [{ assetId: state.annotation.assetId || state.selectedAssetId, instanceId: state.annotation.instanceId || state.selectedInstanceId, partId: state.annotation.partId, role: selectedContractPart(state.annotation.partId, state.annotation.assetId || state.selectedAssetId)?.role || "semantic part" }]
    : selectedPartDescriptors();
  return selections.length ? { parts: selections, partId: selections[0].partId, role: selections[0].role } : null;
}

function renderAgentTarget() {
  if (state.agentCreateAssetId) {
    const context = document.querySelector("#agent-context");
    const note = document.querySelector("#agent-composer-note");
    const input = document.querySelector("#agent-input");
    if (context) context.textContent = `New asset · ${state.agentCreateAssetId}`;
    if (note) note.textContent = `Create ${state.agentCreateAssetId} · LLM → Blender → QA`;
    if (input && !input.value.trim()) input.placeholder = `Describe ${state.agentCreateAssetId}`;
    renderAgentMentions();
    return;
  }
  const target = selectedAgentTarget();
  const marked = state.annotation ? " · marked area" : "";
  const asset = selectedWorkspaceAsset();
  const context = document.querySelector("#agent-context");
  const note = document.querySelector("#agent-composer-note");
  const input = document.querySelector("#agent-input");
  const targetLabel = target?.parts?.map((part) => part.partId).join(" + ");
  if (context) context.textContent = target ? `${asset?.asset_id || "Asset"} · ${targetLabel}${marked}` : state.annotation ? `${asset?.asset_id || "Asset"} · marked viewport area` : `${asset?.asset_id || "Asset"} · select a subject component or mark an area.`;
  if (note) note.textContent = target ? `Target ${targetLabel}${marked} · LLM → Blender → QA` : state.annotation ? "Marked area · LLM → Blender → QA" : "Whole asset · LLM → Blender → QA";
  if (input && !input.value.trim()) input.placeholder = target ? `Describe the fix for ${targetLabel}` : state.annotation ? "Describe what is wrong in the marked area" : "Try: build a production-quality Scandinavian timber house";
  renderAgentMentions();
}

function addAgentMessage(role, text, patch = null) {
  state.agentMessages.push({ role, text, patch });
  renderAgentThread();
}

function renderAgentThread() {
  const thread = document.querySelector("#agent-thread");
  if (!thread) return;
  thread.innerHTML = state.agentMessages.map((message, index) => {
    const patch = message.patch;
    const patchState = patch?.status || "pending";
    const scales = patch ? Object.entries(patch.scales).map(([axis, factor]) => `${axis.toUpperCase()} × ${factor}`).join(" · ") : "";
    const action = patch && patchState === "pending" ? `<div class="agent-patch-actions"><button class="quiet-button" data-agent-action="reject" data-message-index="${index}">Reject</button><button class="primary-action compact" data-agent-action="apply" data-message-index="${index}">Apply patch</button></div>` : patch ? `<span class="patch-state ${patchState}">${patchState === "applied" ? "Applied" : patchState === "rejected" ? "Rejected" : patchState === "applying" ? "Applying" : "Failed"}</span>` : "";
    return `<article class="agent-message ${message.role}"><div class="agent-message-meta">${message.role === "agent" ? "LLM AGENT" : "YOU"}</div><p>${escapeHtml(message.text)}</p>${patch ? `<div class="agent-patch"><span>PATCH PREVIEW</span><b>${escapeHtml(patch.partId)}</b><small>${escapeHtml(scales)}</small>${action}</div>` : ""}</article>`;
  }).join("");
  thread.querySelectorAll("[data-agent-action]").forEach((button) => button.addEventListener("click", () => {
    const index = Number(button.dataset.messageIndex);
    if (button.dataset.agentAction === "apply") applyAgentPatch(index);
    else rejectAgentPatch(index);
  }));
  thread.scrollTop = thread.scrollHeight;
  renderAgentTarget();
}

function openAgent() {
  state.agentOpen = true;
  const drawer = document.querySelector("#agent-drawer");
  shell.classList.add("agent-is-open");
  drawer.classList.add("is-open");
  drawer.setAttribute("aria-hidden", "false");
  document.querySelector("#open-agent")?.setAttribute("aria-expanded", "true");
  document.querySelector("#agent-backdrop").classList.add("is-open");
  renderAgentProviderStatus();
  renderAgentActivity();
  renderAgentThread();
  renderBuildStatus();
  document.querySelector("#agent-input").focus();
}

function closeAgent() {
  state.agentOpen = false;
  shell.classList.remove("agent-is-open");
  document.querySelector("#agent-drawer").classList.remove("is-open");
  document.querySelector("#agent-drawer").setAttribute("aria-hidden", "false");
  document.querySelector("#open-agent")?.setAttribute("aria-expanded", "false");
  document.querySelector("#agent-backdrop").classList.remove("is-open");
  renderBuildStatus();
}

async function executeAgentBuild(text, options = {}) {
  if (state.build.status === "running") {
    toast("A build is already running. Open the build monitor to follow it.");
    openAgent();
    return;
  }
  const provider = state.agents.find((item) => item.agent_id === state.agentProvider);
  const label = provider?.label || state.agentProvider;
  const createAssetId = options.create ? options.createAssetId || createAssetIdFromPrompt(text) : null;
  state.agentCreateAssetId = createAssetId;
  renderAgentTarget();
  const mentionedAssets = extractAssetMentions(text).filter((asset) => asset.asset_id !== createAssetId);
  const mentionedAssetId = mentionedAssets[0]?.asset_id || "";
  const selectedTarget = options.create ? null : selectedAgentTarget();
  const target = mentionedAssetId && selectedTarget?.parts?.some((part) => part.assetId !== mentionedAssetId) ? null : selectedTarget;
  const targetAssetId = mentionedAssetId || state.selectedAssetId || state.inspect?.current?.asset_id;
  const markedContext = !options.create && state.annotation && (!mentionedAssetId || state.annotation.assetId === mentionedAssetId) ? `Marked viewport area: x=${state.annotation.x.toFixed(3)}, y=${state.annotation.y.toFixed(3)}, width=${state.annotation.width.toFixed(3)}, height=${state.annotation.height.toFixed(3)} in normalized viewport coordinates. A cropped viewport reference is attached.` : "";
  const targetParts = target?.parts?.map((part) => `- ${part.partId} (${part.role})`).join("\n");
  const mentionContext = mentionedAssets.length ? `Referenced workspace assets:\n${mentionedAssets.map((asset) => `- ${asset.asset_id} (${asset.kind})`).join("\n")}` : "";
  const referenceNote = options.referencePath ? `Reference path/note supplied by the user: ${options.referencePath}` : "";
  const requestPrompt = target
    ? [mentionContext, `Target semantic parts:\n${targetParts}`, markedContext, referenceNote, "Edit scope: modify only these selected parts; preserve all other semantic parts, part IDs, contract dimensions, and QA requirements unless the user explicitly requests a coordinated change.", `User request: ${text}`].filter(Boolean).join("\n")
    : [mentionContext, referenceNote, markedContext, text].filter(Boolean).join("\n");
  const mentionLabel = mentionedAssets.length ? `Assets: ${mentionedAssets.map((asset) => `@${asset.asset_id}`).join(" + ")}` : "";
  const targetLabel = target ? `Targets: ${target.parts.map((part) => part.partId).join(" + ")}` : state.annotation && !mentionedAssetId ? "Target: marked viewport area" : "";
  const messageTarget = [mentionLabel, targetLabel].filter(Boolean).join("\n");
  const messageText = messageTarget ? `${messageTarget}\n\n${text}` : text;
  if (provider?.status !== "ACTIVE") {
    addAgentMessage("user", messageText);
    const actionId = beginAction(`${label} request`, "Starting external LLM → Blender → QA");
    updateAction(actionId, "failed", provider?.reason || "AUTH_REQUIRED");
    addAgentMessage("agent", `${label} is not active (${provider?.reason || "AUTH_REQUIRED"}). Authenticate the external LLM first; Open3D will not use a local fallback.`);
    return;
  }
  const attachment = state.referenceImage;
  state.referenceImage = null;
  renderReferenceImage();
  addAgentMessage("user", attachment ? `${messageText}\n\nReference image attached: ${attachment.name}` : messageText);
  startBuildStatus(state.agentProvider);
  const actionId = beginAction(`${label} request`, "Starting external LLM → Blender → QA");
  addAgentMessage("agent", `Sending this request to ${label}. ${attachment ? "It will inventory the reference with an img2threejs-style spec, then author the staged Blender build." : "It will author the staged Blender build."} Open3D will run Blender and validate the resulting GLB.`);
  updateAction(actionId, "running", attachment ? "LLM is writing reference_spec.json, asset.json, and build.py" : "LLM is authoring asset.json and build.py");
  try {
    const request = { agent: state.agentProvider, prompt: requestPrompt, timeout: 900 };
    if (!options.create) request.asset_id = targetAssetId;
    if (mentionedAssets.length) request.referenced_asset_ids = mentionedAssets.map((asset) => asset.asset_id);
    if (options.create) request.create_asset = true;
    if (options.spawn) request.spawn = options.spawn;
    if (attachment) {
      request.reference_image = attachment;
      request.reference_pipeline = "img2threejs";
    }
    const result = await api("/api/agent/build", { method: "POST", body: JSON.stringify(request) });
    const failedChecks = result.report?.checks?.filter((check) => check.status !== "PASS").map((check) => `${check.check_id}: ${qaCheckText(check)}`).join("\n") || "";
    const visualSummary = visualQaSummary(result);
    const output = [result.error, result.reason, visualSummary, failedChecks && `QA failures:\n${failedChecks}`, result.cli?.stderr, result.cli?.stdout].filter(Boolean).join("\n\n").slice(0, 6000) || "No build output";
    if (result.status === "PASS") {
      updateAction(actionId, "running", `Blender finished · QA ${result.mutation?.report?.status || "checking"}`);
      await refreshAfterMutation();
      state.agentCreateAssetId = null;
      renderAgentTarget();
      updateAction(actionId, "done", `GLB adopted · QA ${result.mutation?.report?.status || "PASS"}${visualSummary ? ` · ${visualSummary}` : ""}`);
      addAgentMessage("agent", `${label} built the asset successfully. Blender ran in ${result.blender?.sandbox || "the sandbox"}; the GLB, contract, checkpoint, and QA report are now current.${visualSummary ? ` ${visualSummary}.` : ""}`);
      toast("LLM Blender build completed", "success");
    } else {
      updateAction(actionId, "failed", result.reason || "Agent build failed");
      addAgentMessage("agent", `${label} · ${result.status}\n\n${output}`);
    }
  } catch (error) {
    updateAction(actionId, "failed", error.message);
    addAgentMessage("agent", `${label} could not be reached: ${error.message}`);
  } finally {
    stopBuildStatus();
  }
}

async function submitAgentMessage(event) {
  event.preventDefault();
  const input = document.querySelector("#agent-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  renderAgentMentions();
  const createAssetId = createAssetIdFromPrompt(text);
  await executeAgentBuild(text, createAssetId ? { create: true, createAssetId } : {});
}

async function generateAssetFromBrief() {
  const brief = readBriefForm();
  const status = document.querySelector("#create-status");
  if (!brief.id || !brief.prompt) { status.textContent = "Asset ID and prompt are required."; return; }
  if (createGeneratorNeedsImage(brief.generator) && !brief.references.length) { status.textContent = "Attach at least one reference image for this mode."; return; }
  const spawn = state.pendingSpawn;
  state.generationSource = brief.generator;
  state.generationQuality = brief.quality;
  saveBriefState(brief, "generation-requested");
  closeCreateAsset();
  if (brief.generator === "agent") {
    state.referenceImages = [];
    openAgent();
    await executeAgentBuild(`Create a new asset with asset_id ${brief.id}. ${brief.prompt}`, { create: true, createAssetId: brief.id, spawn, referencePath: brief.referencePath });
    return;
  }
  const label = generationLabel(brief.generator);
  const all2apiAgent = brief.generator === "all2api-image-agent";
  const actionId = beginAction(`${label} request`, "Starting remote generation pipeline");
  addAgentMessage("user", `Create ${brief.id} with ${label}.\n\n${brief.prompt}`);
  state.agentCreateAssetId = brief.id;
  openAgent();
  startBuildStatus(brief.generator);
  addAgentMessage("agent", all2apiAgent ? `${label} started. All2API will create a reference image, then ${state.agentProvider} will inventory it with img2threejs-style passes before Blender and QA.` : `${label} started. The pipeline will generate/refine the asset, normalize semantic parts, verify the GLB, and refresh this workspace.`);
  updateAction(actionId, "running", all2apiAgent ? "Generating reference / img2threejs spec / Blender build" : "Generating reference / Meshy geometry");
  try {
    const mode = brief.generator === "meshy-multi" ? "multi_image" : brief.generator === "meshy-image" ? "image" : "text";
    const request = all2apiAgent
      ? { asset_id: brief.id, agent: state.agentProvider, prompt: brief.prompt, quality: brief.quality, consent: true, timeout: 900 }
      : { asset_id: brief.id, prompt: brief.prompt, mode, quality: brief.quality, consent: true, timeout: 900 };
    if (!all2apiAgent && (mode === "image" || mode === "multi_image")) request.image_urls = brief.references.map((image) => image.data);
    if (!all2apiAgent && brief.generator === "codex-image-meshy") request.reference_provider = "codex-cli";
    if (!all2apiAgent && brief.generator === "all2api-image-meshy") request.reference_provider = "all2api";
    if (!all2apiAgent && brief.generator === "openai-image-meshy") request.reference_provider = "openai";
    if (spawn) request.spawn = spawn;
    const result = await api(all2apiAgent ? "/api/generation/all2api-agent" : "/api/generation/meshy", { method: "POST", body: JSON.stringify(request) });
    const failedChecks = result.mutation?.report?.checks?.filter((check) => check.status !== "PASS").map((check) => `${check.check_id}: ${qaCheckText(check)}`).join("\n") || "";
    const visualSummary = visualQaSummary(result);
    const output = [result.error, result.reason, visualSummary, failedChecks && `QA failures:\n${failedChecks}`].filter(Boolean).join("\n\n").slice(0, 6000) || "No generation output";
    if (result.status === "PASS") {
      updateAction(actionId, "running", "GLB verified · refreshing preview and version history");
      await refreshAfterMutation();
      state.agentCreateAssetId = null;
      renderAgentTarget();
      updateAction(actionId, "done", `GLB adopted · QA ${result.mutation?.report?.status || "PASS"}${visualSummary ? ` · ${visualSummary}` : ""}`);
      addAgentMessage("agent", `${label} completed. The new GLB, semantic contract, QA report, and asset version are current in the workspace.${visualSummary ? ` ${visualSummary}.` : ""}`);
      toast("High-quality 3D generation completed", "success");
    } else {
      updateAction(actionId, "failed", result.reason || "Generation failed");
      addAgentMessage("agent", `${label} · ${result.status}\n\n${output}`);
    }
  } catch (error) {
    updateAction(actionId, "failed", error.message);
    addAgentMessage("agent", `${label} could not complete: ${error.message}`);
  } finally {
    state.referenceImage = null;
    state.referenceImages = [];
    renderReferenceImage();
    stopBuildStatus();
  }
}

async function applyAgentPatch(index) {
  const message = state.agentMessages[index];
  if (!message?.patch || message.patch.status) return;
  const { partId, scales } = message.patch;
  message.patch.status = "applying";
  renderAgentThread();
  const actionId = beginAction(`Apply patch · ${partId}`, "Writing the approved allowlisted edit");
  updateAction(actionId, "running", "Creating a checkpoint and rebuilding GLB");
  try {
    const body = { part_id: partId, ...Object.fromEntries(Object.entries(scales).map(([axis, factor]) => [`scale_${axis}`, factor])) };
    await api("/api/edit-part", { method: "POST", body: JSON.stringify(body) });
    message.patch.status = "applied";
    message.text = `Applied the approved scale edit to ${partId}. The viewer, QA report, and history are refreshing.`;
    toast(`Applied agent patch to ${partId}`, "success");
    updateAction(actionId, "running", "Refreshing viewer, QA, and history");
    await refreshAfterMutation();
    updateAction(actionId, "done", "GLB, QA, and history refreshed");
  } catch (error) {
    message.patch.status = "failed";
    message.text = `The patch was not applied: ${error.message}`;
    updateAction(actionId, "failed", error.message);
    toast(error.message, "error");
  }
  renderAgentThread();
}

function rejectAgentPatch(index) {
  const message = state.agentMessages[index];
  if (!message?.patch || message.patch.status) return;
  message.patch.status = "rejected";
  message.text = "Patch rejected. The current artifact was not changed.";
  renderAgentThread();
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
  const type = response.headers.get("content-type") || "";
  const value = type.includes("json") ? await response.json() : await response.arrayBuffer();
  if (!response.ok) throw new Error(value?.error || `Request failed: ${response.status}`);
  return value;
}

async function loadState() {
  try {
    const [inspect, report, history, providers, workspace, versions] = await Promise.all([api("/api/inspect"), api("/api/validate"), api("/api/history"), api("/api/providers"), api("/api/workspace"), api("/api/versions")]);
    state.inspect = inspect;
    state.report = report;
    state.history = history;
    state.providers = providers;
    state.workspace = workspace;
    state.versions = versions;
    state.production = await api("/api/production/state").catch((error) => ({ status: "UNAVAILABLE", error: error.message }));
    [state.agents, state.agentPool] = await Promise.all([
      api("/api/agents").catch(() => state.agents),
      api("/api/agent-pool").catch(() => state.agentPool),
    ]);
    if (!state.agents.some((agent) => agent.agent_id === state.agentProvider && agent.status === "ACTIVE")) {
      state.agentProvider = state.agents.find((agent) => agent.status === "ACTIVE")?.agent_id || "codex";
    }
    state.selectedAssetId = inspect.current.asset_id;
    state.selectedInstanceId = workspace.scene?.instances?.find((instance) => instance.asset_id === state.selectedAssetId)?.instance_id || null;
    state.selectedPart = null;
    setRuntimeStatus("READY");
    hydrateHeader();
    renderView();
    renderAgentProviderStatus();
    await loadArtifact();
  } catch (error) {
    state.inspect = null;
    renderConnectionError(error);
    toast(error.message, "error");
  }
}

function renderConnectionError(error) {
  disposeViewer();
  setRuntimeStatus("OFFLINE");
  document.querySelector("#project-name").textContent = "Offline workspace";
  document.querySelector("#breadcrumb-name").textContent = "Connection required";
  document.querySelector("#asset-title").textContent = "Workspace offline";
  document.querySelector("#asset-subtitle").textContent = "The viewer API is not connected yet.";
  document.querySelector("#artifact-id").textContent = "API unavailable";
  document.querySelector("#qa-status").className = "status-badge fail";
  document.querySelector("#qa-status").innerHTML = "<span></span>Offline";
  viewRoot.innerHTML = `<section class="connection-state"><i class="ph ph-plugs-connected"></i><div><div class="eyebrow">LOCAL CONNECTION</div><h2>Connect the Open3D runtime</h2><p>${escapeHtml(error.message)}. Start <code>python3 -m open3d_artist serve examples/watering-can</code>, then retry.</p><button class="primary-action compact" id="retry-connection"><i class="ph ph-arrow-clockwise"></i>Retry connection</button></div></section>`;
  document.querySelector("#retry-connection").addEventListener("click", loadState);
}

function hydrateHeader() {
  const { project, current, contract } = state.inspect;
  const title = contract.name || contract.asset_id;
  document.querySelector("#project-name").textContent = project.project_id;
  document.querySelector("#breadcrumb-name").textContent = title;
  document.querySelector("#asset-file").textContent = `${contract.asset_id}.yaml`;
  document.querySelector("#asset-title").textContent = title;
  document.querySelector("#asset-subtitle").textContent = `${contract.kind} / ${contract.units} / ${contract.parts.length} semantic parts`;
  document.querySelector("#artifact-id").textContent = current.glb_artifact;
  setQaBadge(state.report.status);
  document.querySelector("#history-count").textContent = state.history.length;
  document.querySelector("#qa-count").textContent = state.report.checks?.filter((check) => check.status !== "PASS").length ? "!" : "OK";
}

function setQaBadge(status) {
  const badge = document.querySelector("#qa-status");
  badge.className = `status-badge ${status.toLowerCase()}`;
  badge.innerHTML = `<span></span>${escapeHtml(status === "PASS" ? "QA passing" : status === "WARN" ? "Needs review" : "QA failed")}`;
}

function renderView() {
  disposeViewer();
  document.querySelector(".content-shell")?.classList.toggle("is-editing", state.activeView === "workspace");
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === state.activeView));
  if (state.activeView === "qa") return renderQa();
  if (state.activeView === "history") return renderHistory();
  if (state.activeView === "providers") return renderProviders();
  renderWorkspace();
}

function renderWorkspace() {
  const asset = selectedWorkspaceAsset() || { asset_id: state.inspect.current.asset_id, contract: state.inspect.contract, qa_status: state.inspect.current.qa_status };
  const contract = asset.contract;
  const assets = state.workspace?.assets || [asset];
  const query = state.query.toLowerCase();
  const parts = contract.parts.filter((part) => `${part.part_id} ${part.role}`.toLowerCase().includes(query));
  const selectedCount = selectedPartDescriptors().length;
  const qaStatus = asset.qa_status || (asset.asset_id === state.inspect.current.asset_id ? state.report.status : "UNVERIFIED");
  const selectedVersion = currentAssetVersion(asset);
  const versionCount = assetVersions(asset.asset_id).length || 1;
  const canUndo = asset.asset_id === state.inspect.current.asset_id && state.versions?.can_undo;
  viewRoot.innerHTML = `
    <div class="workspace-shell">
      <div class="workspace-topline">
        <div class="workspace-context"><div class="eyebrow">EDIT WORKSPACE</div><div class="workspace-title-row"><h1>${escapeHtml(asset.name || asset.asset_id)}</h1><span class="workspace-status ${String(qaStatus).toLowerCase()}"><i class="ph ph-check-circle"></i>${escapeHtml(qaStatus)}</span></div><p><span id="workspace-selection-copy">${selectedCount ? `${selectedCount} subject${selectedCount === 1 ? "" : "s"} selected` : "Select a subject component to edit or comment"}</span> · Shift-click adds subjects to one agent request</p></div>
        <div class="workspace-actions"><button class="top-action version-action" id="workspace-history"><i class="ph ph-clock-counter-clockwise"></i><span>${escapeHtml(selectedVersion?.version_id || "v001")} · ${versionCount} versions</span></button><button class="top-action undo-action" id="workspace-undo" type="button" ${canUndo ? "" : "disabled"} title="Undo the latest asset version"><i class="ph ph-arrow-u-up-left"></i><span>Undo</span><kbd>⌘Z</kbd></button><button class="top-action" id="workspace-agent"><i class="ph ph-sparkle"></i><span>Open agent</span></button><button class="primary-action compact" id="workspace-generate"><i class="ph ph-plus"></i> Create 3D asset</button></div>
      </div>
      <div class="workspace-grid">
        <aside class="asset-library-panel"><div class="library-header"><div><div class="eyebrow">SCENE LIBRARY</div><h2>Assets</h2><span>${assets.length} asset${assets.length === 1 ? "" : "s"} · ${state.workspace?.scene?.instances?.length || 0} instance${(state.workspace?.scene?.instances?.length || 0) === 1 ? "" : "s"}</span></div><button class="icon-button" id="library-generate" title="Create a 3D asset" aria-label="Create a 3D asset"><i class="ph ph-plus"></i></button></div><div class="library-hint"><i class="ph ph-hand-pointing"></i><span>Drag to place · click to inspect · + to add another instance</span></div><div class="asset-library-list">${assets.map((item) => assetLibraryCard(item)).join("")}</div></aside>
        <section class="stage-panel"><div class="stage-toolbar"><div class="stage-toolbar-left"><div class="stage-tool-copy"><b>3D CANVAS</b><small>Orbit · transform · zoom</small></div><div class="toolbar-group"><button class="tool-button active" id="orbit-tool" title="Orbit 360"><i class="ph ph-cursor"></i><span>Orbit</span></button><button class="tool-button" id="grab-tool" title="Transform selected asset with drag and keyboard"><i class="ph ph-hand-grabbing"></i><span>Transform</span></button><button class="tool-button" id="annotate-tool" title="Mark an area to comment with the agent"><i class="ph ph-pencil-simple"></i><span>Mark area</span></button><button class="tool-button" id="generate-here-tool" title="Click a position to generate an asset"><i class="ph ph-map-pin-plus"></i><span>Place asset</span></button><button class="tool-button" id="focus-part-tool" title="Focus selected part" aria-label="Focus selected part"><i class="ph ph-crosshair"></i></button><button class="tool-button" id="frame-tool" title="Frame scene" aria-label="Frame scene"><i class="ph ph-frame-corners"></i></button><button class="tool-button" id="zoom-out-tool" title="Zoom out" aria-label="Zoom out"><i class="ph ph-minus"></i></button><button class="tool-button" id="zoom-in-tool" title="Zoom in" aria-label="Zoom in"><i class="ph ph-plus"></i></button><button class="tool-button" id="grid-tool" title="Toggle grid" aria-label="Toggle grid"><i class="ph ph-grid-four"></i></button></div></div><div class="stage-readout"><span class="live-dot"></span>SCENE / ${assets.length} ASSET${assets.length === 1 ? "" : "S"}</div></div><div class="viewport" id="viewport"><div class="viewport-hint"><span>Click part to select</span><span>Shift-click multi-select</span><span>Drag orbit · wheel zoom</span><span>Drop asset to place</span></div><div class="transform-hud" id="transform-hud" hidden><div class="transform-hud-head"><div><span>TRANSFORM MODE</span><b id="transform-target">Select an asset</b></div><span class="transform-save-status" id="transform-save-status">Saved</span></div><div class="transform-values"><span>POS <b id="transform-position">0.00, 0.00, 0.00</b></span><span>ROT <b id="transform-rotation">0°, 0°, 0°</b></span></div><div class="transform-keys"><span><kbd>← ↑ ↓ →</kbd> move</span><span><kbd>R / F</kbd> height</span><span><kbd>Q / E</kbd> turn</span><span><kbd>Shift</kbd> ×5 · <kbd>Alt</kbd> fine</span></div></div><div class="viewport-annotation-layer" id="annotation-layer" aria-hidden="true"><div class="annotation-box" id="annotation-box" hidden><span>MARKED AREA</span></div><div class="annotation-actions" id="annotation-actions" hidden><span id="annotation-label">Area marked</span><button class="quiet-button" id="annotation-comment" type="button"><i class="ph ph-chat-circle-text"></i>Comment</button><button class="icon-button" id="annotation-clear" type="button" aria-label="Clear marked area"><i class="ph ph-x"></i></button></div></div><div class="viewport-crosshair"><i class="ph ph-crosshair"></i></div></div><div class="stage-footer"><span><i class="ph ph-cube"></i>${escapeHtml(contract.asset_id)}</span><span id="mesh-readout">Loading scene</span><span><i class="ph ph-arrows-out-cardinal"></i>${escapeHtml(contract.units)}</span></div></section>
        <aside class="inspector-panel"><div class="inspector-tabs" role="tablist"><button class="inspector-tab active" id="inspector-tab-inspector" data-inspector-tab="inspector" role="tab" aria-selected="true">Inspector</button><button class="inspector-tab" id="inspector-tab-contract" data-inspector-tab="contract" role="tab" aria-selected="false">Contract</button></div><div class="inspector-scroll"><div id="inspector-pane" role="tabpanel" aria-labelledby="inspector-tab-inspector"><section class="panel-section selected-part-section"><div class="section-heading"><span>SELECTION</span><span class="section-count">${selectedCount}</span><button class="quiet-button" id="clear-selection">Clear</button></div><div id="selected-part"></div></section><section class="panel-section"><div class="section-heading"><span>SUBJECT COMPONENTS</span><span class="section-count">${parts.length}/${contract.parts.length}</span></div><div class="part-selection-help">Click one · Shift-click to add several to the agent request</div><div class="part-list" id="part-list">${parts.length ? parts.map((part) => partRow(part)).join("") : `<div class="empty-part-list">No matching components.</div>`}</div></section></div><div id="contract-pane" role="tabpanel" aria-labelledby="inspector-tab-contract" hidden><section class="panel-section contract-panel-section"><div class="section-heading"><span>CONTRACT</span><i class="ph ph-lock-key"></i></div><p class="contract-copy">Protected dimensions and semantic IDs are sent with every external agent build.</p><div class="metric-grid"><div><small>WIDTH</small><b>${contract.dimensions.width}${contract.units}</b></div><div><small>DEPTH</small><b>${contract.dimensions.depth}${contract.units}</b></div><div><small>HEIGHT</small><b>${contract.dimensions.height}${contract.units}</b></div><div><small>TRIANGLES</small><b>${asset.asset_id === state.inspect.current.asset_id ? qaTriangles() : "-"}</b></div></div><div class="contract-subsection"><div class="section-heading"><span>REQUIRED VIEWS</span><span class="section-count">${REQUIRED_VIEWS.length}</span></div><div class="view-tags contract-view-tags">${REQUIRED_VIEWS.map((view) => `<span>${view}</span>`).join("")}</div></div><div class="contract-agent-note"><i class="ph ph-sparkle"></i><span>Comment from Inspector to target a part. The agent preserves this contract unless you ask for a coordinated change.</span></div></section></div></div></aside>
      </div>
    </div>`;
  document.querySelector("#inspector-pane")?.insertAdjacentHTML("afterbegin", `<section class="panel-section asset-details-section">${selectedAssetDetailsMarkup(asset, contract, qaStatus)}</section>`);
  document.querySelector("#selected-part").innerHTML = selectedPartMarkup();
  document.querySelector("#asset-versions")?.addEventListener("click", openHistory);
  document.querySelector("#asset-undo")?.addEventListener("click", undoAsset);
  document.querySelectorAll("[data-inspector-tab]").forEach((button) => button.addEventListener("click", () => setInspectorTab(button.dataset.inspectorTab)));
  setInspectorTab(state.inspectorTab);
  document.querySelector("#part-list")?.querySelectorAll("button").forEach((button) => button.addEventListener("click", (event) => selectPart(button.dataset.part, false, event.shiftKey)));
  document.querySelectorAll("[data-library-asset]").forEach((card) => {
    card.addEventListener("click", () => selectWorkspaceAsset(card.dataset.libraryAsset));
    card.addEventListener("dragstart", (event) => { state.dragAssetId = card.dataset.libraryAsset; event.dataTransfer.setData("application/x-open3d-asset", state.dragAssetId); event.dataTransfer.setData("text/plain", state.dragAssetId); event.dataTransfer.effectAllowed = "copy"; });
    card.addEventListener("dragend", () => { state.dragAssetId = null; document.querySelector("#viewport")?.classList.remove("is-drop-target"); clearAgentAssetDropState(); });
  });
  document.querySelectorAll("[data-library-add]").forEach((button) => button.addEventListener("click", (event) => { event.stopPropagation(); addAssetToScene(button.dataset.libraryAdd); }));
  document.querySelectorAll("[data-library-remove]").forEach((button) => button.addEventListener("click", (event) => { event.stopPropagation(); removeSceneInstance(button.dataset.libraryRemove); }));
  document.querySelector("#library-generate").addEventListener("click", () => openCreateAsset());
  document.querySelector("#workspace-generate").addEventListener("click", () => openCreateAsset());
  document.querySelector("#workspace-history").addEventListener("click", openHistory);
  document.querySelector("#workspace-undo").addEventListener("click", undoAsset);
  document.querySelector("#workspace-agent").addEventListener("click", openAgent);
  document.querySelector("#comment-selected")?.addEventListener("click", openAgent);
  document.querySelector("#clear-selection").addEventListener("click", () => { state.selectedPart = null; state.selectedParts = []; clearAnnotation(); updateSelectionUI(); highlightPart(null); renderAgentThread(); });
  document.querySelector("#orbit-tool").addEventListener("click", () => setViewportMode("orbit"));
  document.querySelector("#grab-tool").addEventListener("click", () => setViewportMode("grab"));
  document.querySelector("#generate-here-tool").addEventListener("click", toggleScenePlaceMode);
  document.querySelector("#focus-part-tool").addEventListener("click", frameSelectedPart);
  document.querySelector("#frame-tool").addEventListener("click", frameAsset);
  document.querySelector("#zoom-out-tool").addEventListener("click", () => zoomViewer(1.2));
  document.querySelector("#zoom-in-tool").addEventListener("click", () => zoomViewer(0.82));
  document.querySelector("#grid-tool").addEventListener("click", toggleGrid);
  document.querySelector("#annotate-tool").addEventListener("click", toggleAnnotationMode);
  document.querySelector("#annotation-comment").addEventListener("click", openAgent);
  document.querySelector("#annotation-clear").addEventListener("click", clearAnnotation);
  const viewport = document.querySelector("#viewport");
  viewport.addEventListener("dragover", (event) => { if (state.dragAssetId) { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; viewport.classList.add("is-drop-target"); } });
  viewport.addEventListener("dragleave", () => viewport.classList.remove("is-drop-target"));
  viewport.addEventListener("drop", (event) => { event.preventDefault(); viewport.classList.remove("is-drop-target"); const assetId = state.dragAssetId || event.dataTransfer.getData("text/plain"); const point = groundPoint(event); state.dragAssetId = null; if (assetId && point) addAssetToScene(assetId, point); });
  mountViewer();
  setViewportMode(state.viewportMode);
  bindAnnotationLayer();
  renderAnnotationLayer();
}

function assetLibraryCard(asset) {
  const active = asset.asset_id === state.selectedAssetId ? "active" : "";
  const assetInstances = selectedAssetInstances(asset.asset_id);
  const instances = assetInstances.length;
  const versions = assetVersions(asset.asset_id);
  const version = currentAssetVersion(asset);
  const overlapCount = instances - new Set(assetInstances.map(instanceTransformKey)).size;
  const overlapNote = overlapCount ? ` · ${overlapCount} overlapping` : "";
  const instanceRows = instances ? assetInstances.map((instance, index) => `<div class="asset-instance-row"><span>Instance ${index + 1}${overlapCount && index ? " · overlapping" : ""}</span><button class="quiet-button" data-library-remove="${escapeHtml(instance.instance_id)}" type="button">Remove</button></div>`).join("") : `<div class="asset-instance-empty">Catalog only · 0 in scene</div>`;
  const versionNote = version ? ` · ${version.version_id}` : versions.length ? ` · ${versions.length} versions` : "";
  return `<article class="asset-library-card ${active}" data-library-asset="${escapeHtml(asset.asset_id)}" draggable="true"><span class="asset-library-swatch swatch-${Math.abs(hash(asset.asset_id)) % 5}"></span><div><b>${escapeHtml(asset.name || asset.asset_id)}</b><small>${escapeHtml(asset.kind)} · ${instances} in scene${overlapNote}${versionNote}</small>${instanceRows}</div><button class="icon-button" data-library-add="${escapeHtml(asset.asset_id)}" title="Add instance" aria-label="Add ${escapeHtml(asset.asset_id)} to scene"><i class="ph ph-plus"></i></button></article>`;
}

function selectedAssetDetailsMarkup(asset, contract, qaStatus) {
  const dimensions = contract.dimensions || {};
  const count = selectedAssetInstances(asset.asset_id).length;
  const versions = assetVersions(asset.asset_id);
  const version = currentAssetVersion(asset);
  const isCurrent = asset.asset_id === state.inspect.current.asset_id;
  return `<div class="section-heading"><span>ASSET DETAILS</span><span class="section-count">${count} instance${count === 1 ? "" : "s"}</span></div><div class="asset-detail-title"><b>${escapeHtml(asset.name || asset.asset_id)}</b><span class="workspace-status ${String(qaStatus).toLowerCase()}">${escapeHtml(qaStatus)}</span></div><div class="asset-detail-grid"><span><small>DIMENSIONS</small><b>${dimensions.width ?? "-"} × ${dimensions.depth ?? "-"} × ${dimensions.height ?? "-"} ${escapeHtml(contract.units || "")}</b></span><span><small>SOURCE</small><b>${escapeHtml(asset.geometry_source || "UNKNOWN")}</b></span></div><div class="asset-version-row"><span><small>VERSION</small><b>${escapeHtml(version?.version_id || "v001")} · ${versions.length || 1} saved</b></span><button class="quiet-button" id="asset-versions" type="button">View versions</button></div>${isCurrent ? `<button class="quiet-button asset-undo-button" id="asset-undo" type="button" ${state.versions?.can_undo ? "" : "disabled"}><i class="ph ph-arrow-u-up-left"></i>Undo latest version</button>` : ""}`;
}

async function removeSceneInstance(instanceId) {
  const instance = state.workspace?.scene?.instances?.find((item) => item.instance_id === instanceId);
  if (!instance || !confirm(`Remove this ${instance.asset_id} instance from the scene? The asset remains in the library.`)) return;
  try {
    await api("/api/scene/instances/remove", { method: "POST", body: JSON.stringify({ instance_id: instanceId }) });
    state.workspace = await api("/api/workspace");
    if (state.selectedInstanceId === instanceId) state.selectedInstanceId = selectedAssetInstances(state.selectedAssetId)[0]?.instance_id || null;
    renderView();
    await loadArtifact();
    toast("Instance removed from scene; asset retained in library.", "success");
  } catch (error) { toast(error.message, "error"); }
}

function partRow(part) {
  const active = isPartSelected(part.part_id) ? "active" : "";
  return `<button class="part-row ${active}" data-part="${escapeHtml(part.part_id)}" aria-pressed="${active ? "true" : "false"}"><span class="part-swatch swatch-${Math.abs(hash(part.part_id)) % 5}"></span><span><b>${escapeHtml(part.part_id)}</b><small>${escapeHtml(part.role || "semantic part")}</small></span><i class="part-row-check ph ph-check"></i><i class="ph ph-caret-right"></i></button>`;
}

function selectWorkspaceAsset(assetId) {
  const asset = state.workspace?.assets.find((item) => item.asset_id === assetId);
  if (!asset) return;
  state.selectedAssetId = asset.asset_id;
  state.selectedInstanceId = selectedAssetInstances(asset.asset_id)[0]?.instance_id || null;
  state.selectedPart = null;
  state.selectedParts = [];
  state.annotation = null;
  state.annotationMode = false;
  renderView();
  loadArtifact();
}

function assetVersions(assetId) {
  return (state.versions?.versions || []).filter((version) => version.asset_id === assetId);
}

function currentAssetVersion(asset) {
  const versions = assetVersions(asset.asset_id);
  return versions.find((version) => version.contract_artifact === asset.contract_artifact && version.glb_artifact === asset.glb_artifact) || versions.at(-1) || null;
}

async function addAssetToScene(assetId, position = null) {
  try {
    await api("/api/scene/instances", { method: "POST", body: JSON.stringify({ asset_id: assetId, transform: position ? { position } : undefined }) });
    state.workspace = await api("/api/workspace");
    state.selectedAssetId = assetId;
    state.selectedInstanceId = selectedAssetInstances(assetId).at(-1)?.instance_id || null;
    state.selectedPart = null;
    state.selectedParts = [];
    renderView();
    await loadArtifact();
    toast(`Added ${assetId} to scene`, "success");
  } catch (error) {
    toast(error.message, "error");
  }
}

function toggleScenePlaceMode() {
  state.scenePlaceMode = !state.scenePlaceMode;
  if (state.scenePlaceMode) setViewportMode("orbit");
  document.querySelector("#generate-here-tool")?.classList.toggle("active", state.scenePlaceMode);
  document.querySelector("#viewport")?.classList.toggle("is-placing", state.scenePlaceMode);
  toast(state.scenePlaceMode ? "Click a ground position to generate an asset" : "Generate-here mode closed");
}

function selectedPartMarkup() {
  const selections = selectedPartDescriptors();
  if (!selections.length) return `<div class="empty-selection"><i class="ph ph-cursor-click"></i><p>Select a subject component in the list or click the model.</p><small>Shift-click lets the agent edit several related parts together.</small></div>`;
  const primary = selections[0];
  const part = selectedContractPart(primary.partId, primary.assetId) || { part_id: primary.partId, role: primary.role };
  const editable = selections.length === 1 && primary.assetId === state.inspect.current.asset_id;
  const selectionList = selections.map((selection) => `<span class="selection-chip"><i class="part-swatch swatch-${Math.abs(hash(selection.partId)) % 5}"></i>${escapeHtml(selection.partId)}</span>`).join("");
  const controls = editable ? `<div class="field-label">SCALE FACTOR</div><div class="scale-fields"><label>X<input id="scale-x" type="number" min="0.01" step="0.05" value="1" /></label><label>Y<input id="scale-y" type="number" min="0.01" step="0.05" value="1" /></label><label>Z<input id="scale-z" type="number" min="0.01" step="0.05" value="1" /></label></div><button class="primary-action" id="apply-scale"><i class="ph ph-arrows-out"></i>Apply scale edit</button>` : `<div class="selection-agent-note"><i class="ph ph-sparkle"></i><span>${selections.length > 1 ? "These components will be sent together to the external LLM." : "This asset is ready for an external LLM edit."}</span></div>`;
  return `<div class="selected-part"><div class="selected-title"><span class="large-swatch swatch-${Math.abs(hash(part.part_id)) % 5}"></span><div><h2>${selections.length === 1 ? escapeHtml(part.part_id) : `${selections.length} subjects selected`}</h2><span>${selections.length === 1 ? escapeHtml(part.role || "semantic part") : "one agent request"}</span></div><span class="selection-check"><i class="ph ph-check"></i></span></div><div class="selected-asset-note">${escapeHtml(primary.assetId || state.selectedAssetId || "")} · ${editable ? "direct scale edit available" : "agent edit target"}</div>${selections.length > 1 ? `<div class="selection-chips">${selectionList}</div>` : ""}${controls}<button class="quiet-button part-comment-button" id="comment-selected" type="button"><i class="ph ph-chat-circle-text"></i>${selections.length > 1 ? "Comment on selected subjects" : "Comment with agent"}</button></div>`;
}

function renderQa() {
  const checks = state.report?.checks || [];
  viewRoot.innerHTML = `<div class="detail-view"><div class="detail-toolbar"><div><div class="eyebrow">DETERMINISTIC QA</div><h2>Production quality gate</h2><p>Contract, GLB structure, material breakup, normals, and silhouette checks run before adoption.</p></div><button class="primary-action compact" id="rerun-qa"><i class="ph ph-arrow-clockwise"></i>Run again</button></div><div class="qa-layout"><section class="qa-summary"><div class="qa-score ${state.report.status.toLowerCase()}"><span>${state.report.status === "PASS" ? "100" : "!"}</span><small>GATE STATUS</small></div><div class="qa-metrics"><div><small>CHECKS</small><b>${checks.length}</b></div><div><small>TRIANGLES</small><b>${qaTriangles()}</b></div><div><small>ARTIFACT</small><b>${state.inspect.current.glb_artifact.slice(7, 15)}</b></div></div></section><section class="check-list">${checks.map((check) => `<div class="check-row"><span class="check-icon ${check.status.toLowerCase()}"><i class="ph ${check.status === "PASS" ? "ph-check" : check.status === "WARN" ? "ph-warning" : "ph-x"}"></i></span><div><b>${escapeHtml(check.check_id)}</b><p>${escapeHtml(qaCheckText(check))}</p></div><span class="check-status ${check.status.toLowerCase()}">${escapeHtml(check.status)}</span></div>`).join("")}</section></div></div>`;
  const production = state.production || {}, renders = production.renders || {};
  const cards = ["HERO_3Q", "FRONT", "BACK", "LEFT", "RIGHT", "TOP"].map((view) => renders[view] ? `<figure class="render-card"><img src="${escapeHtml(renders[view])}" alt="${view} render"><figcaption>${view}</figcaption></figure>` : `<div class="render-card unavailable"><span>${view}</span><small>UNAVAILABLE</small></div>`).join("");
  const adapters = Object.entries(production.adapters || {}).map(([name, value]) => `<span>${escapeHtml(name)}: ${escapeHtml(value)}</span>`).join("") || "No adapter receipt";
  viewRoot.querySelector(".detail-view").insertAdjacentHTML("beforeend", `<section class="release-proof"><div class="section-heading"><span>PRODUCTION RELEASE</span><span>${escapeHtml(production.promotion?.state || "UNAVAILABLE")}</span></div><p>Receipt: ${escapeHtml(production.receipt?.brief?.id || "UNAVAILABLE")}</p><p>Release proof: ${escapeHtml(production.release_verification?.status || "UNAVAILABLE")} · approval remains ${escapeHtml(production.release?.approval || "UNAVAILABLE")}</p><div class="adapter-tags">${adapters}</div><div class="render-grid">${cards}</div></section>`);
  document.querySelector("#rerun-qa").addEventListener("click", runQa);
}

function openHistory() {
  state.activeView = "history";
  renderView();
}

async function undoAsset() {
  if (state.busy) return;
  if (state.selectedAssetId !== state.inspect.current.asset_id || !state.versions?.can_undo) { toast("No previous version for the current asset."); return; }
  const current = state.versions.versions.find((version) => version.current);
  const index = state.versions.versions.indexOf(current);
  const previous = index > 0 ? state.versions.versions[index - 1] : null;
  if (!current || !previous || !confirm(`Undo ${current.version_id} and restore ${previous.version_id}?`)) return;
  try {
    state.busy = true;
    const result = await api("/api/undo", { method: "POST", body: JSON.stringify({}) });
    if (result.status === "NOOP") { toast("No previous asset version to undo."); return; }
    toast(`Restored ${result.restored_version?.version_id || previous.version_id}`, "success");
    await refreshAfterMutation();
  } catch (error) { toast(`Undo failed: ${error.message}`, "error"); }
  finally { state.busy = false; }
}

async function restoreVersion(checkpoint, versionId = "this version") {
  if (state.busy || !checkpoint || !confirm(`Restore ${versionId}? Newer saved versions will remain available.`)) return;
  try {
    state.busy = true;
    await api("/api/rollback", { method: "POST", body: JSON.stringify({ checkpoint_id: checkpoint }) });
    toast(`Restored ${versionId}`, "success");
    await refreshAfterMutation();
  } catch (error) { toast(`Restore failed: ${error.message}`, "error"); }
  finally { state.busy = false; }
}

function renderHistory() {
  const historyAssetId = state.selectedAssetId || state.inspect.current.asset_id;
  const versions = (state.versions?.versions || []).filter((version) => version.asset_id === historyAssetId);
  const current = versions.find((version) => version.current);
  const viewingCurrent = historyAssetId === state.inspect.current.asset_id;
  const versionRows = versions.length ? versions.slice().reverse().map((version) => `<article class="version-row ${version.current ? "current" : ""}"><span class="version-dot"></span><div><div class="timeline-meta"><span>${escapeHtml(version.version_id)}</span><time>${escapeHtml(version.asset_id || "asset")}</time></div><h3>${escapeHtml(version.note || "Saved asset version")}</h3><p>${escapeHtml(version.operation || "asset")}${version.operation_id ? ` · ${escapeHtml(version.operation_id)}` : ""}</p></div><div class="version-row-actions">${version.current ? `<span class="version-current">CURRENT</span>` : `<button class="quiet-button version-restore" data-version-restore="${escapeHtml(version.checkpoint_id)}" data-version-label="${escapeHtml(version.version_id)}" type="button">Restore</button>`}</div></article>`).join("") : `<div class="empty-state"><i class="ph ph-git-branch"></i><h3>No saved versions yet</h3><p>The initial asset version will appear here.</p></div>`;
  const operations = state.history.length ? state.history.slice().reverse().map((item) => `<article class="timeline-row"><span class="timeline-dot"></span><div><div class="timeline-meta"><span>${escapeHtml(item.name || "checkpoint")}</span><time>${escapeHtml(item.operation_id || "system")}</time></div><h3>${escapeHtml(item.note || item.status || "Operation complete")}</h3><p>${escapeHtml(item.result_checkpoint || item.input_checkpoint || "")}</p></div>${item.input_checkpoint ? `<button class="quiet-button rollback" data-checkpoint="${escapeHtml(item.input_checkpoint)}" type="button">Rollback</button>` : ""}</article>`).join("") : `<div class="empty-state"><i class="ph ph-clock-counter-clockwise"></i><h3>No operations yet</h3><p>Edit a part or run an agent build to create the first operation.</p></div>`;
  viewRoot.innerHTML = `<div class="detail-view"><div class="detail-toolbar"><div><div class="eyebrow">IMMUTABLE ASSET VERSIONS</div><h2>Versions</h2><p>Every accepted asset state is content-addressed and can be restored without losing the newer version.</p></div><button class="primary-action compact" id="history-undo" type="button" ${viewingCurrent && state.versions?.can_undo ? "" : "disabled"}><i class="ph ph-arrow-u-up-left"></i>Undo latest</button></div><section class="version-history"><div class="version-history-heading"><div><b>${escapeHtml(current?.version_id || "v001")}</b><span>${viewingCurrent ? "current version" : escapeHtml(historyAssetId)}</span></div><span>${versions.length} saved version${versions.length === 1 ? "" : "s"}</span></div><div class="version-list">${versionRows}</div></section><section class="operation-history"><div class="section-heading"><span>OPERATION LOG</span><span>${state.history.length}</span></div><div class="timeline">${operations}</div></section></div>`;
  document.querySelector("#history-undo")?.addEventListener("click", undoAsset);
  document.querySelectorAll(".version-restore").forEach((button) => button.addEventListener("click", () => restoreVersion(button.dataset.versionRestore, button.dataset.versionLabel)));
  document.querySelectorAll(".rollback").forEach((button) => button.addEventListener("click", () => restoreVersion(button.dataset.checkpoint, "checkpoint")));
}

function renderProviders() {
  viewRoot.innerHTML = `<div class="detail-view"><div class="detail-toolbar"><div><div class="eyebrow">EXTENSION CATALOG</div><h2>Providers</h2><p>Remote generation is opt-in. API keys stay in the local runtime.</p></div></div><div class="provider-list">${state.providers.map((provider) => `<article class="provider-row"><div class="provider-icon ${provider.network ? "remote" : "local"}"><i class="ph ${provider.network ? "ph-cloud-arrow-up" : "ph-shapes"}"></i></div><div class="provider-copy"><div><h3>${escapeHtml(provider.label)}</h3><span class="provider-id">${escapeHtml(provider.provider_id)}</span></div><p>${provider.network ? "Uploads image data only after consent. Results are verified as GLB before CAS storage." : "Dependency-free deterministic baseline for offline work."}</p><div class="provider-tags"><span>${provider.configured ? "Configured" : "Not configured"}</span><span>${provider.requires_consent ? "Consent required" : "Offline"}</span><span>${escapeHtml(provider.license)}</span></div></div><div class="provider-state ${provider.configured ? "ready" : "muted"}"><span></span>${provider.configured ? "Ready" : "Unavailable"}</div></article>`).join("")}</div><div class="provider-note"><i class="ph ph-lock-key-open"></i><div><b>Privacy boundary</b><p>Open3D does not persist provider keys, and the browser never receives them. Use the CLI or local API with an explicit consent flag.</p></div></div></div>`;
}

function hash(value) { return [...value].reduce((total, character) => ((total << 5) - total + character.charCodeAt(0)) | 0, 0); }

function selectSceneSelection({ assetId = state.selectedAssetId, instanceId = state.selectedInstanceId, partId = null }, preserveAnnotation = false, additive = false) {
  const canAdd = additive && partId && state.selectedAssetId === assetId && state.selectedInstanceId === instanceId;
  state.selectedAssetId = assetId;
  state.selectedInstanceId = instanceId;
  if (canAdd) {
    const descriptor = { assetId, instanceId, partId, role: selectedContractPart(partId, assetId)?.role || "semantic part" };
    const key = selectionKey(descriptor);
    state.selectedParts = state.selectedParts.some((selection) => selectionKey(selection) === key)
      ? state.selectedParts.filter((selection) => selectionKey(selection) !== key)
      : [...selectedPartDescriptors(), descriptor];
    state.selectedPart = state.selectedParts.at(-1)?.partId || null;
  } else {
    state.selectedPart = partId;
    state.selectedParts = partId ? [{ assetId, instanceId, partId, role: selectedContractPart(partId, assetId)?.role || "semantic part" }] : [];
  }
  if (!preserveAnnotation) {
    state.annotationMode = false;
    annotationDraft = null;
    state.annotation = null;
    if (state.referenceImage?.name.startsWith("marked-area-")) removeReferenceImage();
  }
  updateSelectionUI();
  highlightPart();
  renderAnnotationLayer();
  renderTransformHud();
  renderAgentThread();
}

function selectPart(partId, preserveAnnotation = false, additive = false) {
  selectSceneSelection({ partId }, preserveAnnotation, additive);
}

function updateSelectionUI() {
  const panel = document.querySelector("#selected-part");
  if (panel) {
    panel.innerHTML = selectedPartMarkup();
    panel.querySelector("#comment-selected")?.addEventListener("click", openAgent);
  }
  document.querySelectorAll("#part-list .part-row").forEach((row) => {
    const active = isPartSelected(row.dataset.part);
    row.classList.toggle("active", active);
    row.setAttribute("aria-pressed", String(active));
  });
  const count = document.querySelector("#workspace-selection-copy");
  if (count) count.textContent = state.selectedParts.length ? `${state.selectedParts.length} subject${state.selectedParts.length === 1 ? "" : "s"} selected` : "Select a subject component to edit or comment";
}

function setViewportMode(mode) {
  state.viewportMode = mode;
  if (viewer.controls) viewer.controls.enabled = mode === "orbit" && !state.scenePlaceMode;
  document.querySelector("#orbit-tool")?.classList.toggle("active", mode === "orbit");
  document.querySelector("#grab-tool")?.classList.toggle("active", mode === "grab");
  document.querySelector("#viewport")?.classList.toggle("is-grabbing", mode === "grab");
  renderTransformHud();
}

function disposeViewer() {
  objectDrag = null;
  if (viewer.resize) viewer.resize.disconnect();
  if (viewer.controls) viewer.controls.dispose();
  if (viewer.frame) cancelAnimationFrame(viewer.frame);
  if (viewer.renderer) { viewer.renderer.dispose(); viewer.renderer.domElement.remove(); }
  viewer.scene = null; viewer.camera = null; viewer.renderer = null; viewer.controls = null; viewer.root = null; viewer.sceneGroup = null; viewer.canvas = null; viewer.resize = null; viewer.frame = 0; viewer.original.clear(); viewer.templates.clear(); viewer.instances.clear();
}

function mountViewer() {
  const viewport = document.querySelector("#viewport");
  if (!viewport) return;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x101311);
  const camera = new THREE.PerspectiveCamera(38, 1, 0.01, 1000);
  camera.position.set(2.4, 1.8, 3.1);
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.15;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  viewport.append(renderer.domElement);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.minPolarAngle = 0.01;
  controls.maxPolarAngle = Math.PI - 0.01;
  controls.minAzimuthAngle = -Infinity;
  controls.maxAzimuthAngle = Infinity;
  controls.enablePan = true;
  controls.minDistance = 0.02;
  controls.maxDistance = 1000;
  controls.enabled = state.viewportMode === "orbit";
  scene.add(new THREE.HemisphereLight(0xe5f2e9, 0x161b18, 2.2));
  const key = new THREE.DirectionalLight(0xffffff, 3.3);
  key.position.set(3, 5, 4);
  key.castShadow = true;
  scene.add(key);
  const rim = new THREE.DirectionalLight(0x89ff7a, 1.2);
  rim.position.set(-4, 2, -3);
  scene.add(rim);
  const grid = new THREE.GridHelper(5, 20, 0x39453d, 0x222b26);
  grid.name = "open3d-grid";
  scene.add(grid);
  const sceneGroup = new THREE.Group();
  sceneGroup.name = "open3d-scene";
  scene.add(sceneGroup);
  viewer.scene = scene; viewer.camera = camera; viewer.renderer = renderer; viewer.controls = controls; viewer.canvas = renderer.domElement; viewer.sceneGroup = sceneGroup; viewer.root = sceneGroup;
  viewer.resize = new ResizeObserver(() => resizeViewer(viewport));
  viewer.resize.observe(viewport);
  renderer.domElement.addEventListener("pointerdown", handleViewportPointerDown);
  renderer.domElement.addEventListener("pointermove", handleViewportPointerMove);
  renderer.domElement.addEventListener("pointerup", handleViewportPointerUp);
  renderer.domElement.addEventListener("pointercancel", handleViewportPointerUp);
  const animate = () => { controls.update(); renderer.render(scene, camera); viewer.frame = requestAnimationFrame(animate); };
  animate();
  resizeViewer(viewport);
}

function resizeViewer(viewport) {
  if (!viewer.renderer) return;
  const width = viewport.clientWidth; const height = viewport.clientHeight;
  viewer.camera.aspect = width / Math.max(height, 1); viewer.camera.updateProjectionMatrix(); viewer.renderer.setSize(width, height, false);
}

async function loadArtifact() {
  if (!viewer.scene) return;
  state.workspace = state.workspace || await api("/api/workspace");
  const group = viewer.sceneGroup || viewer.root;
  if (!group) return;
  while (group.children.length) group.remove(group.children[0]);
  viewer.original.clear(); viewer.templates.clear(); viewer.instances.clear();
  let meshCount = 0;
  const renderedTransforms = new Set();
  const assets = new Map((state.workspace.assets || []).map((asset) => [asset.asset_id, asset]));
  const instances = [...(state.workspace.scene?.instances || [])].sort((left, right) => Number(right.instance_id === state.selectedInstanceId) - Number(left.instance_id === state.selectedInstanceId));
  for (const instance of instances) {
    const asset = assets.get(instance.asset_id);
    if (!asset) continue;
    const transformKey = `${instance.asset_id}:${instanceTransformKey(instance)}`;
    if (renderedTransforms.has(transformKey)) continue;
    renderedTransforms.add(transformKey);
    try {
      let template = viewer.templates.get(asset.asset_id);
      if (!template) {
        template = await parseGlb(await api(`/api/assets/${encodeURIComponent(asset.asset_id)}/artifact`));
        viewer.templates.set(asset.asset_id, template);
      }
      const root = template.clone(true);
      root.userData.instanceId = instance.instance_id;
      root.userData.assetId = instance.asset_id;
      root.position.set(instance.position.x, instance.position.y, instance.position.z);
      root.rotation.set(instance.rotation.x, instance.rotation.y, instance.rotation.z);
      root.scale.set(instance.scale.x, instance.scale.y, instance.scale.z);
      root.traverse((node) => {
        const parentPart = node.userData?.open3d?.part_id || node.userData?.part_id || node.name;
        if (node.isMesh) {
          node.userData.partId = parentPart;
          node.userData.instanceId = instance.instance_id;
          node.userData.assetId = instance.asset_id;
          node.castShadow = true; node.receiveShadow = true;
          const sourceMaterials = Array.isArray(node.material) ? node.material : [node.material];
          const materials = sourceMaterials.map((material) => material?.clone?.() || material);
          node.material = Array.isArray(node.material) ? materials : materials[0];
          viewer.original.set(node.uuid, materials.map((material) => ({ material, color: material.color?.clone(), emissive: material.emissive?.clone(), intensity: material.emissiveIntensity })));
          meshCount += 1;
        }
      });
      group.add(root);
      viewer.instances.set(instance.instance_id, root);
    } catch (error) {
      toast(`GLB parse failed for ${asset.asset_id}: ${error.message || error}`, "error");
    }
  }
  updateZoomLimits();
  frameAsset();
  const readout = document.querySelector("#mesh-readout");
  if (readout) readout.textContent = `${meshCount} render meshes · ${viewer.instances.size}/${instances.length} rendered scene instances`;
  highlightPart();
  renderTransformHud();
}

function parseGlb(data) {
  return new Promise((resolve, reject) => gltfLoader.parse(data, "", (gltf) => resolve(gltf.scene), reject));
}

function countMeshes(root) { let count = 0; root.traverse((node) => { if (node.isMesh) count++; }); return count; }

let objectDrag = null;
let transformSaveTimer = null;

function activeInstanceRoot() {
  return state.viewportMode === "grab" && state.selectedInstanceId ? viewer.instances.get(state.selectedInstanceId) : null;
}

function transformPayload(root) {
  return {
    position: { x: root.position.x, y: root.position.y, z: root.position.z },
    rotation: { x: root.rotation.x, y: root.rotation.y, z: root.rotation.z },
    scale: { x: root.scale.x, y: root.scale.y, z: root.scale.z },
  };
}

function syncInstanceState(instanceId, root) {
  const instance = state.workspace?.scene?.instances?.find((item) => item.instance_id === instanceId);
  if (!instance) return;
  const transform = transformPayload(root);
  Object.assign(instance, transform);
}

function queueInstanceTransformSave() {
  const instanceId = state.selectedInstanceId;
  const root = instanceId ? viewer.instances.get(instanceId) : null;
  if (!root) return;
  syncInstanceState(instanceId, root);
  const payload = transformPayload(root);
  const status = document.querySelector("#transform-save-status");
  if (status) { status.textContent = "Saving..."; status.className = "transform-save-status saving"; }
  clearTimeout(transformSaveTimer);
  transformSaveTimer = setTimeout(async () => {
    try {
      await api(`/api/scene/instances/${encodeURIComponent(instanceId)}/update`, { method: "POST", body: JSON.stringify({ transform: payload }) });
      const savedStatus = document.querySelector("#transform-save-status");
      if (savedStatus) { savedStatus.textContent = "Saved"; savedStatus.className = "transform-save-status saved"; }
    } catch (error) {
      const failedStatus = document.querySelector("#transform-save-status");
      if (failedStatus) { failedStatus.textContent = "Not saved"; failedStatus.className = "transform-save-status failed"; }
      toast(`Transform was not saved: ${error.message}`, "error");
    }
  }, 180);
}

function setTransformSaveStatus(text, className = "saved") {
  const status = document.querySelector("#transform-save-status");
  if (status) { status.textContent = text; status.className = `transform-save-status ${className}`; }
}

function renderTransformHud() {
  const hud = document.querySelector("#transform-hud");
  const root = activeInstanceRoot();
  if (!hud) return;
  const visible = Boolean(root);
  hud.hidden = !visible;
  document.querySelector("#viewport")?.classList.toggle("is-transforming", visible);
  if (!visible) return;
  const instance = state.workspace?.scene?.instances?.find((item) => item.instance_id === state.selectedInstanceId);
  const asset = state.workspace?.assets?.find((item) => item.asset_id === instance?.asset_id);
  const target = document.querySelector("#transform-target");
  const position = document.querySelector("#transform-position");
  const rotation = document.querySelector("#transform-rotation");
  if (target) target.textContent = asset?.name || instance?.asset_id || "Selected asset";
  if (position) position.textContent = [root.position.x, root.position.y, root.position.z].map((value) => value.toFixed(2)).join(", ");
  if (rotation) rotation.textContent = [root.rotation.x, root.rotation.y, root.rotation.z].map((value) => `${Math.round(THREE.MathUtils.radToDeg(value))}°`).join(", ");
}

function nudgeSelectedAsset(key, event) {
  if (state.activeView !== "workspace" || state.agentOpen || state.createOpen || state.scenePlaceMode) return false;
  const tag = event.target?.tagName;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(tag) || event.isComposing) return false;
  const root = activeInstanceRoot();
  if (!root) return false;
  const step = event.altKey ? 0.01 : event.shiftKey ? 0.25 : 0.05;
  const angle = THREE.MathUtils.degToRad(event.altKey ? 3 : event.shiftKey ? 45 : 15);
  switch (key.toLowerCase()) {
    case "arrowleft": root.position.x -= step; break;
    case "arrowright": root.position.x += step; break;
    case "arrowup": root.position.z -= step; break;
    case "arrowdown": root.position.z += step; break;
    case "r": root.position.y += step; break;
    case "f": root.position.y = Math.max(0, root.position.y - step); break;
    case "q": root.rotation.y += angle; break;
    case "e": root.rotation.y -= angle; break;
    default: return false;
  }
  event.preventDefault();
  syncInstanceState(state.selectedInstanceId, root);
  renderTransformHud();
  queueInstanceTransformSave();
  return true;
}

function handleViewportPointerDown(event) {
  if (state.scenePlaceMode) { event.preventDefault(); return; }
  const hit = partAtClientPoint(event);
  if (hit?.partId) selectSceneSelection(hit, false, event.shiftKey);
  if (state.viewportMode !== "grab" || !viewer.root) return;
  const root = viewer.instances.get(state.selectedInstanceId);
  if (!root) { toast("Select an asset before using Transform mode."); return; }
  event.preventDefault();
  objectDrag = { pointerId: event.pointerId, lastX: event.clientX, lastY: event.clientY, root, target: hit?.partId ? hit.object : root };
  if (objectDrag.target !== root) setTransformSaveStatus("Session only", "session");
  viewer.canvas.setPointerCapture(event.pointerId);
}

function handleViewportPointerMove(event) {
  if (!objectDrag || !objectDrag.root) return;
  const deltaX = event.clientX - objectDrag.lastX;
  const deltaY = event.clientY - objectDrag.lastY;
  objectDrag.lastX = event.clientX;
  objectDrag.lastY = event.clientY;
  const target = objectDrag.target || objectDrag.root;
  target.rotation.y += deltaX * 0.01;
  target.rotation.x += deltaY * 0.01;
  if (target === objectDrag.root) syncInstanceState(state.selectedInstanceId, objectDrag.root);
  renderTransformHud();
}

function handleViewportPointerUp(event) {
  if (state.scenePlaceMode) {
    const point = groundPoint(event);
    state.scenePlaceMode = false;
    setViewportMode(state.viewportMode);
    document.querySelector("#generate-here-tool")?.classList.remove("active");
    document.querySelector("#viewport")?.classList.remove("is-placing");
    if (point) openCreateAsset(point);
    return;
  }
  if (!objectDrag) return;
  if (viewer.canvas.hasPointerCapture(event.pointerId)) viewer.canvas.releasePointerCapture(event.pointerId);
  if (objectDrag.target === objectDrag.root) queueInstanceTransformSave();
  objectDrag = null;
}

function partAtClientPoint(event) {
  if (!viewer.root || !viewer.canvas) return null;
  const rect = viewer.canvas.getBoundingClientRect();
  viewer.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  viewer.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  viewer.raycaster.setFromCamera(viewer.pointer, viewer.camera);
  const hit = viewer.raycaster.intersectObject(viewer.root, true)[0];
  if (!hit?.object?.userData?.partId) return null;
  return { partId: hit.object.userData.partId, instanceId: hit.object.userData.instanceId, assetId: hit.object.userData.assetId, object: hit.object };
}

function groundPoint(event) {
  if (!viewer.canvas || !viewer.camera) return null;
  const rect = viewer.canvas.getBoundingClientRect();
  viewer.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  viewer.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  viewer.raycaster.setFromCamera(viewer.pointer, viewer.camera);
  const point = new THREE.Vector3();
  return viewer.raycaster.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), point) ? point : null;
}

function pickPart(event) {
  const hit = partAtClientPoint(event);
  if (hit?.partId) selectSceneSelection(hit, false, event.shiftKey);
}

function highlightPart() {
  if (!viewer.root) return;
  viewer.root.traverse((node) => {
    if (!node.isMesh) return;
    const selectedAsset = node.userData.assetId === state.selectedAssetId && node.userData.instanceId === state.selectedInstanceId;
    const selectedPart = isPartSelected(node.userData.partId, node.userData.assetId, node.userData.instanceId);
    const entries = viewer.original.get(node.uuid) || [];
    entries.forEach(({ material, color, emissive, intensity }) => {
      if ((selectedAsset || selectedPart) && material.emissive) { material.emissive.setHex(selectedPart ? 0x9cff80 : 0x6f9fff); material.emissiveIntensity = selectedPart ? 0.4 : 0.16; material.color?.setHex(selectedPart ? 0xb9ffc0 : 0xaecbff); }
      else { if (color && material.color) material.color.copy(color); if (emissive && material.emissive) material.emissive.copy(emissive); material.emissiveIntensity = intensity || 0; }
    });
  });
}

function updateZoomLimits() {
  if (!viewer.root || !viewer.controls || !viewer.camera) return;
  const bounds = new THREE.Box3().setFromObject(viewer.root);
  if (bounds.isEmpty()) return;
  const sphere = bounds.getBoundingSphere(new THREE.Sphere());
  const radius = Math.max(sphere.radius, 0.1);
  viewer.controls.minDistance = 0.02;
  viewer.controls.maxDistance = Math.max(radius * 40, 100);
  viewer.camera.near = Math.max(radius * 0.0001, 0.001);
  viewer.camera.far = Math.max(radius * 100, 1000);
  viewer.camera.updateProjectionMatrix();
}

function frameAsset() {
  if (!viewer.root) return;
  const bounds = new THREE.Box3().setFromObject(viewer.root); const sphere = bounds.getBoundingSphere(new THREE.Sphere());
  const distance = Math.max(sphere.radius * 2.8, 1); const direction = new THREE.Vector3(1, 0.72, 1).normalize();
  viewer.camera.position.copy(sphere.center).add(direction.multiplyScalar(distance)); viewer.controls.target.copy(sphere.center); viewer.controls.update();
}

function frameSelectedPart() {
  const selections = selectedPartDescriptors();
  if (!viewer.root || !selections.length) return frameAsset();
  const bounds = new THREE.Box3();
  viewer.root.traverse((node) => { if (node.isMesh && selections.some((selection) => selection.partId === node.userData.partId && selection.assetId === node.userData.assetId && selection.instanceId === node.userData.instanceId)) bounds.expandByObject(node); });
  if (bounds.isEmpty()) return frameAsset();
  const sphere = bounds.getBoundingSphere(new THREE.Sphere());
  const distance = Math.max(sphere.radius * 3.2, 0.35);
  const direction = new THREE.Vector3(1, 0.72, 1).normalize();
  viewer.camera.position.copy(sphere.center).add(direction.multiplyScalar(distance));
  viewer.controls.target.copy(sphere.center);
  viewer.controls.update();
}

function zoomViewer(factor) {
  if (!viewer.camera || !viewer.controls) return;
  const offset = viewer.camera.position.clone().sub(viewer.controls.target).multiplyScalar(factor);
  const distance = THREE.MathUtils.clamp(offset.length(), viewer.controls.minDistance, viewer.controls.maxDistance);
  viewer.camera.position.copy(viewer.controls.target).add(offset.normalize().multiplyScalar(distance));
  viewer.controls.update();
}

let annotationDraft = null;

function annotationPoint(event, layer) {
  const rect = layer.getBoundingClientRect();
  return { x: THREE.MathUtils.clamp(event.clientX - rect.left, 0, rect.width), y: THREE.MathUtils.clamp(event.clientY - rect.top, 0, rect.height) };
}

function renderAnnotationLayer() {
  const layer = document.querySelector("#annotation-layer");
  const box = document.querySelector("#annotation-box");
  const actions = document.querySelector("#annotation-actions");
  const label = document.querySelector("#annotation-label");
  const tool = document.querySelector("#annotate-tool");
  if (!layer || !box || !actions) return;
  const viewport = document.querySelector("#viewport");
  const width = viewport?.clientWidth || 1;
  const height = viewport?.clientHeight || 1;
  const rect = annotationDraft || (state.annotation ? { x: state.annotation.x * width, y: state.annotation.y * height, width: state.annotation.width * width, height: state.annotation.height * height } : null);
  layer.classList.toggle("is-active", state.annotationMode);
  viewport?.classList.toggle("is-annotating", state.annotationMode);
  layer.setAttribute("aria-hidden", String(!state.annotationMode && !state.annotation));
  tool?.classList.toggle("active", state.annotationMode);
  if (!rect) { box.hidden = true; actions.hidden = true; return; }
  box.hidden = false;
  box.style.left = `${rect.x}px`;
  box.style.top = `${rect.y}px`;
  box.style.width = `${Math.max(rect.width, 1)}px`;
  box.style.height = `${Math.max(rect.height, 1)}px`;
  actions.hidden = !state.annotation;
  actions.style.left = `${Math.min(Math.max(rect.x, 8), Math.max(width - 188, 8))}px`;
  actions.style.top = `${Math.min(rect.y + rect.height + 8, Math.max(height - 42, 8))}px`;
  if (label && state.annotation) label.textContent = state.annotation.partId ? `Marked ${state.annotation.partId}` : "Marked area";
}

function toggleAnnotationMode() {
  if (state.build.status === "running") { toast("Build in progress. Wait before marking another area."); return; }
  state.annotationMode = !state.annotationMode;
  annotationDraft = null;
  if (state.annotationMode) state.annotation = null;
  renderAnnotationLayer();
  renderAgentTarget();
}

function clearAnnotation() {
  state.annotationMode = false;
  annotationDraft = null;
  state.annotation = null;
  if (state.referenceImage?.name.startsWith("marked-area-")) removeReferenceImage();
  renderAnnotationLayer();
  renderAgentTarget();
}

function bindAnnotationLayer() {
  const layer = document.querySelector("#annotation-layer");
  if (!layer) return;
  layer.addEventListener("pointerdown", (event) => {
    if (!state.annotationMode) return;
    event.preventDefault();
    event.stopPropagation();
    const point = annotationPoint(event, layer);
    annotationDraft = { startX: point.x, startY: point.y, x: point.x, y: point.y, width: 0, height: 0 };
    layer.setPointerCapture(event.pointerId);
    renderAnnotationLayer();
  });
  layer.addEventListener("pointermove", (event) => {
    if (!annotationDraft) return;
    const point = annotationPoint(event, layer);
    annotationDraft.x = Math.min(annotationDraft.startX, point.x);
    annotationDraft.y = Math.min(annotationDraft.startY, point.y);
    annotationDraft.width = Math.abs(point.x - annotationDraft.startX);
    annotationDraft.height = Math.abs(point.y - annotationDraft.startY);
    renderAnnotationLayer();
  });
  layer.addEventListener("pointerup", async (event) => {
    if (!annotationDraft) return;
    event.preventDefault();
    event.stopPropagation();
    const draft = { ...annotationDraft };
    annotationDraft = null;
    if (layer.hasPointerCapture(event.pointerId)) layer.releasePointerCapture(event.pointerId);
    if (draft.width < 16 || draft.height < 16) { renderAnnotationLayer(); return; }
    const rect = layer.getBoundingClientRect();
    const center = { clientX: rect.left + draft.x + draft.width / 2, clientY: rect.top + draft.y + draft.height / 2 };
    const hit = partAtClientPoint(center);
    const partId = hit?.partId || null;
    state.annotation = { x: draft.x / rect.width, y: draft.y / rect.height, width: draft.width / rect.width, height: draft.height / rect.height, partId, assetId: hit?.assetId || state.selectedAssetId, instanceId: hit?.instanceId || state.selectedInstanceId };
    state.annotationMode = false;
    try { await captureAnnotationReference(state.annotation); } catch (error) { toast(error.message, "error"); }
    if (partId) {
      selectSceneSelection(hit, true);
    } else {
      renderAnnotationLayer();
      renderAgentTarget();
    }
  });
}

async function captureAnnotationReference(annotation) {
  const source = viewer.canvas;
  const viewport = document.querySelector("#viewport");
  if (!source || !viewport) return;
  const viewportRect = viewport.getBoundingClientRect();
  const scaleX = source.width / Math.max(viewportRect.width, 1);
  const scaleY = source.height / Math.max(viewportRect.height, 1);
  const sourceX = Math.max(0, Math.floor(annotation.x * viewportRect.width * scaleX));
  const sourceY = Math.max(0, Math.floor(annotation.y * viewportRect.height * scaleY));
  const sourceWidth = Math.max(1, Math.min(source.width - sourceX, Math.floor(annotation.width * viewportRect.width * scaleX)));
  const sourceHeight = Math.max(1, Math.min(source.height - sourceY, Math.floor(annotation.height * viewportRect.height * scaleY)));
  const output = document.createElement("canvas");
  const outputScale = Math.min(1, 1100 / Math.max(sourceWidth, sourceHeight));
  output.width = Math.max(1, Math.round(sourceWidth * outputScale));
  output.height = Math.max(1, Math.round(sourceHeight * outputScale));
  output.getContext("2d").drawImage(source, sourceX, sourceY, sourceWidth, sourceHeight, 0, 0, output.width, output.height);
  const name = `marked-area-${annotation.partId || "asset"}.jpg`;
  let image = { name, mime_type: "image/jpeg", data: output.toDataURL("image/jpeg", 0.72) };
  if (image.data.length > MAX_REFERENCE_DATA_URL_LENGTH) image = await compressReferenceImage(image.data, name);
  if (image.data.length > MAX_REFERENCE_DATA_URL_LENGTH) throw new Error("Marked area is too large after compression");
  state.referenceImage = image;
  renderReferenceImage();
  toast("Marked area attached to the agent request", "success");
}

function toggleGrid() { const grid = viewer.scene?.getObjectByName("open3d-grid"); if (grid) grid.visible = !grid.visible; }

async function runQa(source = "workspace") {
  if (state.build.status === "running") { toast("Build in progress. QA will run after the GLB is adopted."); return; }
  const actionId = beginAction(source === "agent" ? "Agent QA" : "Run QA", "Validating current GLB and contract");
  updateAction(actionId, "running", "Reading current artifact");
  try { state.report = await api("/api/validate"); setQaBadge(state.report.status); hydrateHeader(); if (state.activeView === "qa") renderView(); updateAction(actionId, state.report.status === "PASS" ? "done" : "failed", `QA ${state.report.status}`); toast("QA report refreshed", "success"); } catch (error) { updateAction(actionId, "failed", error.message); toast(error.message, "error"); }
}

async function applyScale() {
  if (state.build.status === "running") { toast("Build in progress. Wait for the current artifact to finish."); return; }
  const selections = selectedPartDescriptors();
  if (selections.length !== 1 || selections[0].assetId !== state.inspect.current.asset_id) { toast("Scale edit needs one part from the current asset."); return; }
  const partId = selections[0].partId; if (!partId) return;
  const values = Object.fromEntries(["x", "y", "z"].map((axis) => [axis, Number(document.querySelector(`#scale-${axis}`).value)]));
  try { state.busy = true; await api("/api/edit-part", { method: "POST", body: JSON.stringify({ part_id: partId, scale_x: values.x, scale_y: values.y, scale_z: values.z }) }); toast(`Scaled ${partId}`, "success"); await refreshAfterMutation(); } catch (error) { toast(error.message, "error"); } finally { state.busy = false; }
}

async function refreshAfterMutation() { const previousAssetId = state.selectedAssetId; const previousPart = state.selectedPart; const [inspect, report, history, workspace, versions] = await Promise.all([api("/api/inspect"), api("/api/validate"), api("/api/history"), api("/api/workspace"), api("/api/versions")]); state.inspect = inspect; state.report = report; state.history = history; state.workspace = workspace; state.versions = versions; state.selectedAssetId = inspect.current.asset_id; state.selectedInstanceId = workspace.scene?.instances?.find((instance) => instance.asset_id === state.selectedAssetId)?.instance_id || null; state.selectedPart = previousAssetId === state.selectedAssetId && selectedAssetContract()?.parts.some((part) => part.part_id === previousPart) ? previousPart : null; state.selectedParts = []; hydrateHeader(); renderView(); await loadArtifact(); }

document.querySelectorAll(".nav-item").forEach((item) => item.addEventListener("click", () => { state.activeView = item.dataset.view; renderView(); if (state.activeView === "workspace") loadArtifact(); }));
document.querySelector("#validate").addEventListener("click", runQa);
document.querySelector("#search").addEventListener("input", (event) => { state.query = event.target.value; if (state.activeView === "workspace") renderView(); });
document.querySelector("#create-asset").addEventListener("click", () => openCreateAsset());
document.querySelector("#quick-create").addEventListener("click", () => openCreateAsset());
document.querySelector("#create-form").addEventListener("submit", saveAssetDraft);
document.querySelector("#create-generate").addEventListener("click", generateAssetFromBrief);
document.querySelector("#create-reference-file").addEventListener("change", attachReferenceImage);
document.querySelector("#agent-reference-file").addEventListener("change", attachReferenceImage);
document.querySelector("#reference-remove").addEventListener("click", removeReferenceImage);
document.querySelector("#agent-attachment-remove").addEventListener("click", removeReferenceImage);
document.querySelectorAll("#create-id, #create-prompt, #create-reference").forEach((input) => input.addEventListener("input", renderCreateSummary));
document.querySelector("#create-generator").addEventListener("change", (event) => { state.generationSource = event.target.value; if (event.target.value !== "meshy-multi" && state.referenceImages.length > 1) { state.referenceImages = state.referenceImages.slice(0, 1); state.referenceImage = state.referenceImages[0] || null; } syncCreateGenerator(); renderReferenceImage(); });
document.querySelector("#create-quality").addEventListener("change", (event) => { state.generationQuality = event.target.value; renderCreateSummary(); });
document.querySelector("#create-agent").addEventListener("change", (event) => { state.agentProvider = event.target.value; renderAgentProviderStatus(); syncCreateAgent(); renderCreateSummary(); });
document.querySelector("#create-close").addEventListener("click", closeCreateAsset);
document.querySelector("#create-cancel").addEventListener("click", closeCreateAsset);
document.querySelector("[data-close-create]").addEventListener("click", closeCreateAsset);
document.querySelector("#open-agent").addEventListener("click", openAgent);
document.querySelector("#reopen-build").addEventListener("click", openAgent);
document.querySelector("#agent-rail-tab").addEventListener("click", openAgent);
document.querySelector("#close-agent").addEventListener("click", closeAgent);
document.querySelector("#agent-backdrop").addEventListener("click", closeAgent);
document.querySelector("#agent-form").addEventListener("submit", submitAgentMessage);
document.querySelector("#agent-input").addEventListener("input", renderAgentMentions);
["#agent-input", "#agent-mentions"].forEach((selector) => {
  const target = document.querySelector(selector);
  target?.addEventListener("dragover", (event) => {
    if (!droppedWorkspaceAsset(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    target.classList.add("is-asset-drop-target");
  });
  target?.addEventListener("dragleave", () => target.classList.remove("is-asset-drop-target"));
  target?.addEventListener("drop", insertAgentAssetMention);
});
document.querySelector("#refresh-agents").addEventListener("click", refreshAgents);
document.querySelector("#agent-provider").addEventListener("change", (event) => {
  state.agentProvider = event.target.value;
  const agent = state.agents.find((item) => item.agent_id === state.agentProvider);
  renderAgentProviderStatus();
  const note = document.querySelector("#agent-composer-note");
  if (note) note.textContent = "LLM agent → Blender → QA";
  const actionId = beginAction(`Connect · ${agent?.label || state.agentProvider}`, agent?.status === "ACTIVE" ? "External LLM selected" : agent?.reason || "Agent unavailable");
  updateAction(actionId, agent?.status === "ACTIVE" ? "done" : "failed", agent?.status === "ACTIVE" ? "Ready for build requests" : agent?.reason || "Unavailable");
});
document.querySelector("#clear-actions").addEventListener("click", () => { state.actionLog = []; renderAgentActivity(); });
document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); document.querySelector("#search").focus(); }
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "j") { event.preventDefault(); state.agentOpen ? closeAgent() : openAgent(); }
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z" && state.activeView === "workspace" && !state.agentOpen && !state.createOpen && !["INPUT", "TEXTAREA", "SELECT"].includes(event.target?.tagName) && !event.isComposing) { event.preventDefault(); undoAsset(); return; }
  if (nudgeSelectedAsset(event.key, event)) return;
  if (event.key === "Escape") { if (state.createOpen) closeCreateAsset(); else if (state.agentOpen) closeAgent(); }
});
document.addEventListener("click", (event) => { if (event.target.closest("#apply-scale")) applyScale(); });

renderAgentMentions();
loadState();
