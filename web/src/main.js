import "@phosphor-icons/web/regular";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import "./styles.css";

const REQUIRED_VIEWS = ["HERO_3Q", "FRONT", "BACK", "LEFT", "RIGHT", "TOP"];
const DEFAULT_HOUSE_PROMPT = "Production-quality stylized Scandinavian timber house prop, single-story modern cabin with a gabled roof, four walls, a door, two windows, and a chimney; clean bevels, separate semantic parts, realistic proportions, neutral studio materials, and six orthographic views.";
const MAX_REFERENCE_IMAGE_BYTES = 600 * 1024;
const MAX_REFERENCE_DATA_URL_LENGTH = 800000;

function readDraft() {
  try { return JSON.parse(localStorage.getItem("open3d.asset-draft") || "null"); } catch { return null; }
}

const state = {
  inspect: null,
  report: null,
  history: [],
  providers: [],
  agents: [
    { agent_id: "codex", label: "Codex", status: "CHECKING" },
    { agent_id: "claude", label: "Claude Code", status: "CHECKING" },
    { agent_id: "opencode", label: "OpenCode", status: "CHECKING" },
  ],
  agentPool: { mode: "DIRECT_CLI", status: "CHECKING" },
  production: null,
  activeView: "workspace",
  selectedPart: null,
  query: "",
  theme: "dark",
  busy: false,
  agentProvider: "codex",
  actionLog: [],
  createOpen: false,
  agentOpen: false,
  assetDraft: readDraft(),
  referenceImage: null,
  agentMessages: [{ role: "agent", text: "Choose an active LLM agent. Every prompt is executed by Codex, Claude Code, or OpenCode, then Open3D runs Blender and QA. There is no local agent fallback." }],
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
      <div class="sidebar-footer"><div class="runtime-status"><span class="status-pulse"></span><span>OPEN3D RUNTIME</span><b>READY</b></div><div class="footer-links"><span>v0.1 alpha</span><a href="https://github.com/nguyenanhducdeveloper86/open3d" target="_blank" rel="noreferrer">GitHub <i class="ph ph-arrow-up-right"></i></a></div></div>
    </aside>
    <main class="main-shell">
      <header class="topbar"><div class="crumbs"><span>Projects</span><i class="ph ph-caret-right"></i><strong id="breadcrumb-name">Open3D asset</strong></div><label class="search-box"><i class="ph ph-magnifying-glass"></i><input id="search" type="search" placeholder="Search parts, checks, providers" /><kbd>⌘ K</kbd></label><div class="top-actions"><button class="top-action create-trigger" id="create-asset"><i class="ph ph-plus"></i><span>Create asset</span></button><button class="top-action agent-trigger" id="open-agent"><i class="ph ph-sparkle"></i><span>Agent</span></button><button class="validate-button" id="validate"><i class="ph ph-shield-check"></i><span>Run QA</span></button><div class="avatar">DA</div></div></header>
      <section class="content-shell">
        <div class="content-heading"><div><div class="eyebrow">OPEN3D / LIVE ARTIFACT</div><h1 id="asset-title">Loading asset</h1><p id="asset-subtitle">Preparing the contract and GLB preview</p></div><div class="heading-meta"><span class="status-badge" id="qa-status"><span></span>Checking</span><span class="artifact-id" id="artifact-id">sha256:...</span></div></div>
        <div id="view-root"></div>
      </section>
    </main>
    <div class="modal-layer" id="create-layer" hidden>
      <div class="modal-backdrop" data-close-create></div>
      <form class="create-modal" id="create-form" aria-labelledby="create-title">
        <header class="modal-header"><div><div class="eyebrow">CREATE ASSET</div><h2 id="create-title">Start from a production brief</h2><p>Save the prompt and reference boundary before a recipe or provider runs.</p></div><button class="icon-button" type="button" id="create-close" aria-label="Close create asset dialog"><i class="ph ph-x"></i></button></header>
        <div class="form-grid"><label><span>ASSET ID</span><input id="create-id" name="brief_id" required maxlength="64" value="${escapeHtml(state.assetDraft?.brief_id || "PROP-SCANDI-HOUSE-001")}" /></label><label><span>REFERENCE PATH / NOTE</span><input id="create-reference" name="reference" maxlength="240" placeholder="Optional local path or note" value="${escapeHtml(state.assetDraft?.reference?.path || "")}" /></label></div>
        <label class="form-field"><span>GENERATION PROMPT</span><textarea id="create-prompt" name="prompt" required maxlength="4000" rows="6">${escapeHtml(state.assetDraft?.prompt || DEFAULT_HOUSE_PROMPT)}</textarea></label>
        <div class="reference-upload"><label class="reference-drop" for="create-reference-file"><input id="create-reference-file" type="file" accept="image/png,image/jpeg,image/webp" /><i class="ph ph-image-square"></i><span id="reference-file-label">Attach reference image</span><small>PNG, JPG, or WebP · compressed before upload</small></label><div class="reference-preview" id="reference-preview" hidden><img id="reference-preview-image" alt="Reference preview" /><div><b id="reference-preview-name"></b><small id="reference-preview-size"></small></div><button class="icon-button" type="button" id="reference-remove" aria-label="Remove reference image"><i class="ph ph-x"></i></button></div></div>
        <div class="view-contract"><div><span>REQUIRED OUTPUT</span><b>Six-view contract</b></div><div class="view-tags">${REQUIRED_VIEWS.map((view) => `<span>${view}</span>`).join("")}</div></div>
        <div class="form-boundary"><i class="ph ph-info"></i><p>The selected external LLM will inspect the prompt and optional reference, author <code>asset.json</code> + <code>build.py</code>, then Open3D runs Blender and QA before adoption.</p></div>
        <div class="brief-agent"><label><span>BUILD AGENT</span><select id="create-agent"><option value="codex">Codex</option><option value="claude">Claude Code</option><option value="opencode">OpenCode</option></select></label><span id="create-agent-status" class="agent-provider-status">Checking</span></div>
        <p class="form-status" id="create-status" aria-live="polite"></p>
        <footer class="modal-actions"><button class="quiet-button" type="button" id="create-cancel">Cancel</button><button class="quiet-button" type="submit"><i class="ph ph-floppy-disk"></i>Save brief</button><button class="primary-action compact" type="button" id="create-generate"><i class="ph ph-sparkle"></i>Generate asset</button></footer>
      </form>
    </div>
    <div class="agent-backdrop" id="agent-backdrop"></div>
    <aside class="agent-drawer" id="agent-drawer" aria-hidden="true" aria-labelledby="agent-title">
      <header class="agent-header"><div><div class="eyebrow">LLM AGENTS</div><h2 id="agent-title">Asset build chat</h2><p id="agent-context">Select a part to give the agent a target.</p></div><button class="icon-button" id="close-agent" aria-label="Close agent chat"><i class="ph ph-x"></i></button></header>
      <div class="agent-policy"><i class="ph ph-shield-check"></i><span>Codex, Claude Code, and OpenCode author the staged build. Open3D runs Blender in the sandbox and replaces the artifact only after GLB/QA checks pass. No local agent fallback.</span></div>
      <div class="agent-controls"><label><span>LLM EXECUTION</span><select id="agent-provider"><option value="codex">Codex</option><option value="claude">Claude Code</option><option value="opencode">OpenCode</option></select></label><span class="agent-provider-status" id="agent-provider-status">Checking</span><span class="agent-provider-status" id="agent-pool-status">POOL CHECKING</span><button class="quiet-button agent-refresh" id="refresh-agents" type="button" title="Check LLM agents" aria-label="Check LLM agents"><i class="ph ph-arrows-clockwise"></i></button></div>
      <section class="agent-activity"><div class="activity-heading"><span>ACTION TRACE</span><button class="quiet-button" id="clear-actions" type="button">Clear</button></div><div id="agent-activity-list"><div class="activity-empty">No actions yet.</div></div></section>
      <div class="agent-thread" id="agent-thread" aria-live="polite"></div>
      <form class="agent-composer" id="agent-form"><textarea id="agent-input" rows="2" placeholder="Try: build a production-quality Scandinavian timber house"></textarea><div class="agent-attachment" id="agent-attachment" hidden><i class="ph ph-image-square"></i><span id="agent-attachment-name"></span><button class="icon-button" type="button" id="agent-attachment-remove" aria-label="Remove attached reference"><i class="ph ph-x"></i></button></div><div><label class="agent-attach-button" for="agent-reference-file"><i class="ph ph-paperclip"></i>Reference<input id="agent-reference-file" type="file" accept="image/png,image/jpeg,image/webp" /></label><span id="agent-composer-note">LLM agent → Blender → QA</span><button class="primary-action compact" type="submit"><i class="ph ph-arrow-up-right"></i>Run build</button></div></form>
    </aside>
    <div class="toast-region" id="toasts" aria-live="polite"></div>
  </div>`;

const shell = document.querySelector(".app-shell");
const viewRoot = document.querySelector("#view-root");
const toastRegion = document.querySelector("#toasts");
const gltfLoader = new GLTFLoader();
const viewer = { scene: null, camera: null, renderer: null, controls: null, root: null, canvas: null, raycaster: new THREE.Raycaster(), pointer: new THREE.Vector2(), original: new Map(), resize: null, frame: 0, data: null };

function toast(message, tone = "neutral") {
  const node = document.createElement("div");
  node.className = `toast ${tone}`;
  node.innerHTML = `<i class="ph ${tone === "error" ? "ph-warning-circle" : tone === "success" ? "ph-check-circle" : "ph-info"}"></i><span>${escapeHtml(message)}</span>`;
  toastRegion.append(node);
  setTimeout(() => node.remove(), 3600);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
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
  const actionId = beginAction("Check LLM agents", "Checking Codex, Claude Code, and OpenCode authentication");
  updateAction(actionId, "running", "Checking external LLM execution");
  try {
    [state.agents, state.agentPool] = await Promise.all([api("/api/agents"), api("/api/agent-pool")]);
    renderAgentProviderStatus();
    syncCreateAgent();
    const ready = state.agents.filter((agent) => agent.status === "ACTIVE").map((agent) => agent.label).join(", ");
    updateAction(actionId, "done", ready ? `${ready} active` : "No authenticated LLM agent");
    addAgentMessage("agent", ready ? `${ready} active · ${state.agentPool?.status === "ACTIVE" ? "shared pool" : "direct CLI auth"}.` : "No authenticated external LLM agent. The build button is blocked until Codex, Claude Code, or OpenCode is authenticated.");
  } catch (error) {
    updateAction(actionId, "failed", error.message);
    addAgentMessage("agent", `Agent adapter check failed: ${error.message}`);
  }
}

function persistDraft(draft) {
  try { localStorage.setItem("open3d.asset-draft", JSON.stringify(draft)); } catch { /* localStorage can be disabled in a locked-down browser */ }
}

function renderReferenceImage() {
  const image = state.referenceImage;
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
  label.textContent = image ? "Reference attached" : "Attach reference image";
  preview.hidden = !image;
  if (image) {
    previewImage.src = image.data;
    previewName.textContent = image.name;
    previewSize.textContent = `${Math.round(image.data.length / 1024)} KB encoded`;
  } else {
    previewImage.removeAttribute("src");
    previewName.textContent = "";
    previewSize.textContent = "";
  }
  if (attachment && attachmentName) {
    attachment.hidden = !image;
    attachmentName.textContent = image ? `Reference · ${image.name}` : "";
  }
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
  const file = event.target.files?.[0];
  if (!file) return;
  const status = document.querySelector("#create-status");
  try {
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) throw new Error("Use a PNG, JPG, or WebP reference image");
    let data = await readDataUrl(file);
    let image = { name: file.name, mime_type: file.type, data };
    if (file.size > MAX_REFERENCE_IMAGE_BYTES || data.length > MAX_REFERENCE_DATA_URL_LENGTH) image = await compressReferenceImage(data, file.name);
    if (image.data.length > MAX_REFERENCE_DATA_URL_LENGTH) throw new Error("Reference image is still too large after compression");
    state.referenceImage = image;
    renderReferenceImage();
    if (status) status.textContent = `Attached ${file.name}. It will be staged for the external LLM.`;
    else toast(`Attached ${file.name}`, "success");
  } catch (error) {
    event.target.value = "";
    state.referenceImage = null;
    renderReferenceImage();
    if (status) status.textContent = error.message;
    else toast(error.message, "error");
  }
}

function removeReferenceImage() {
  state.referenceImage = null;
  const input = document.querySelector("#create-reference-file");
  if (input) input.value = "";
  renderReferenceImage();
}

function readBriefForm() {
  const id = document.querySelector("#create-id").value.trim().toUpperCase().replace(/[^A-Z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 64);
  const prompt = document.querySelector("#create-prompt").value.trim();
  const referencePath = document.querySelector("#create-reference").value.trim();
  return { id, prompt, referencePath };
}

function saveBriefState(brief, generation = "draft-only") {
  state.assetDraft = {
    schema_version: "0.1.0", brief_id: brief.id, prompt: brief.prompt,
    reference: { path: brief.referencePath, kind: brief.referencePath || state.referenceImage ? "attached" : "not-attached", image: state.referenceImage ? { name: state.referenceImage.name, mime_type: state.referenceImage.mime_type } : null },
    views: REQUIRED_VIEWS, generation,
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
}

function openCreateAsset() {
  state.createOpen = true;
  const layer = document.querySelector("#create-layer");
  layer.hidden = false;
  document.querySelector("#create-status").textContent = state.assetDraft ? "Loaded the last local brief draft." : "";
  syncCreateAgent();
  renderReferenceImage();
  document.querySelector("#create-id").focus();
}

function closeCreateAsset() {
  state.createOpen = false;
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

function selectedContractPart(partId = state.selectedPart) {
  return state.inspect?.contract.parts.find((part) => part.part_id.toLowerCase() === String(partId || "").toLowerCase());
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
  const selected = selectedContractPart();
  const context = document.querySelector("#agent-context");
  if (context) context.textContent = selected ? `Target: ${selected.part_id} · ${selected.role || "semantic part"}` : "Select a part to give the agent a target.";
}

function openAgent() {
  state.agentOpen = true;
  const drawer = document.querySelector("#agent-drawer");
  drawer.classList.add("is-open");
  drawer.setAttribute("aria-hidden", "false");
  document.querySelector("#agent-backdrop").classList.add("is-open");
  renderAgentProviderStatus();
  renderAgentActivity();
  renderAgentThread();
  document.querySelector("#agent-input").focus();
}

function closeAgent() {
  state.agentOpen = false;
  document.querySelector("#agent-drawer").classList.remove("is-open");
  document.querySelector("#agent-drawer").setAttribute("aria-hidden", "true");
  document.querySelector("#agent-backdrop").classList.remove("is-open");
}

async function executeAgentBuild(text) {
  const attachment = state.referenceImage;
  state.referenceImage = null;
  renderReferenceImage();
  addAgentMessage("user", attachment ? `${text}\n\nReference image attached: ${attachment.name}` : text);
  const provider = state.agents.find((item) => item.agent_id === state.agentProvider);
  const label = provider?.label || state.agentProvider;
  const actionId = beginAction(`${label} request`, "Starting external LLM → Blender → QA");
  if (provider?.status !== "ACTIVE") {
    updateAction(actionId, "failed", provider?.reason || "AUTH_REQUIRED");
    return addAgentMessage("agent", `${label} is not active (${provider?.reason || "AUTH_REQUIRED"}). Authenticate the external LLM first; Open3D will not use a local fallback.`);
  }
  addAgentMessage("agent", `Sending this request to ${label}. It will author a staged Blender build, then Open3D will run Blender and validate the resulting GLB.`);
  updateAction(actionId, "running", "LLM is authoring asset.json and build.py");
  try {
    const request = { agent: state.agentProvider, prompt: text, timeout: 900 };
    if (attachment) request.reference_image = attachment;
    const result = await api("/api/agent/build", { method: "POST", body: JSON.stringify(request) });
    const output = (result.cli?.stdout || result.cli?.stderr || result.error || result.reason || "No build output").slice(0, 6000);
    if (result.status === "PASS") {
      updateAction(actionId, "running", `Blender finished · QA ${result.mutation?.report?.status || "checking"}`);
      await refreshAfterMutation();
      updateAction(actionId, "done", `GLB adopted · QA ${result.mutation?.report?.status || "PASS"}`);
      addAgentMessage("agent", `${label} built the asset successfully. Blender ran in ${result.blender?.sandbox || "the sandbox"}; the GLB, contract, checkpoint, and QA report are now current.`);
      toast("LLM Blender build completed", "success");
    } else {
      updateAction(actionId, "failed", result.reason || "Agent build failed");
      addAgentMessage("agent", `${label} · ${result.status}\n\n${output}`);
    }
  } catch (error) {
    updateAction(actionId, "failed", error.message);
    addAgentMessage("agent", `${label} could not be reached: ${error.message}`);
  }
}

async function submitAgentMessage(event) {
  event.preventDefault();
  const input = document.querySelector("#agent-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  await executeAgentBuild(text);
}

async function generateAssetFromBrief() {
  const brief = readBriefForm();
  const status = document.querySelector("#create-status");
  if (!brief.id || !brief.prompt) { status.textContent = "Asset ID and prompt are required."; return; }
  saveBriefState(brief, "generation-requested");
  closeCreateAsset();
  openAgent();
  await executeAgentBuild(brief.prompt);
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
    const [inspect, report, history, providers] = await Promise.all([api("/api/inspect"), api("/api/validate"), api("/api/history"), api("/api/providers")]);
    state.inspect = inspect;
    state.report = report;
    state.history = history;
    state.providers = providers;
    state.production = await api("/api/production/state").catch((error) => ({ status: "UNAVAILABLE", error: error.message }));
    [state.agents, state.agentPool] = await Promise.all([
      api("/api/agents").catch(() => state.agents),
      api("/api/agent-pool").catch(() => state.agentPool),
    ]);
    if (!state.agents.some((agent) => agent.agent_id === state.agentProvider && agent.status === "ACTIVE")) {
      state.agentProvider = state.agents.find((agent) => agent.status === "ACTIVE")?.agent_id || "codex";
    }
    state.selectedPart = inspect.contract.parts[0]?.part_id || null;
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
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === state.activeView));
  if (state.activeView === "qa") return renderQa();
  if (state.activeView === "history") return renderHistory();
  if (state.activeView === "providers") return renderProviders();
  renderWorkspace();
}

function renderWorkspace() {
  const contract = state.inspect.contract;
  const query = state.query.toLowerCase();
  const parts = contract.parts.filter((part) => `${part.part_id} ${part.role}`.toLowerCase().includes(query));
  viewRoot.innerHTML = `<div class="workspace-grid"><section class="stage-panel"><div class="stage-toolbar"><div class="toolbar-group"><button class="tool-button active" id="orbit-tool" title="Orbit"><i class="ph ph-cursor"></i><span>Orbit</span></button><button class="tool-button" id="frame-tool" title="Frame asset"><i class="ph ph-frame-corners"></i></button><button class="tool-button" id="grid-tool" title="Toggle grid"><i class="ph ph-grid-four"></i></button></div><div class="stage-readout"><span class="live-dot"></span>GLB / ${escapeHtml(state.inspect.current.qa_status)}</div></div><div class="viewport" id="viewport"><div class="viewport-hint"><span>Drag to orbit</span><span>Scroll to zoom</span></div><div class="viewport-crosshair"><i class="ph ph-crosshair"></i></div></div><div class="stage-footer"><span><i class="ph ph-cube"></i>${escapeHtml(contract.asset_id)}</span><span id="mesh-readout">Loading geometry</span><span><i class="ph ph-arrows-out-cardinal"></i>${escapeHtml(contract.units)}</span></div></section><aside class="inspector-panel"><div class="inspector-tabs"><button class="inspector-tab active">Inspector</button><button class="inspector-tab">Contract</button></div><div class="inspector-scroll"><section class="panel-section selected-part-section"><div class="section-heading"><span>SELECTED PART</span><button class="quiet-button" id="clear-selection">Clear</button></div><div id="selected-part"></div></section><section class="panel-section"><div class="section-heading"><span>SEMANTIC PARTS</span><span class="section-count">${parts.length}/${contract.parts.length}</span></div><div class="part-list" id="part-list">${parts.map((part) => partRow(part)).join("")}</div></section><section class="panel-section"><div class="section-heading"><span>CONTRACT SNAPSHOT</span><i class="ph ph-lock-key"></i></div><div class="metric-grid"><div><small>WIDTH</small><b>${contract.dimensions.width}${contract.units}</b></div><div><small>DEPTH</small><b>${contract.dimensions.depth}${contract.units}</b></div><div><small>HEIGHT</small><b>${contract.dimensions.height}${contract.units}</b></div><div><small>TRIANGLES</small><b>${state.report.metrics?.triangles ?? "-"}</b></div></div></section></div></aside></div>`;
  document.querySelector("#selected-part").innerHTML = selectedPartMarkup();
  document.querySelector("#part-list").querySelectorAll("button").forEach((button) => button.addEventListener("click", () => selectPart(button.dataset.part)));
  document.querySelector("#clear-selection").addEventListener("click", () => { state.selectedPart = null; renderView(); highlightPart(null); });
  document.querySelector("#frame-tool").addEventListener("click", frameAsset);
  document.querySelector("#grid-tool").addEventListener("click", toggleGrid);
  mountViewer();
}

function partRow(part) {
  const active = part.part_id === state.selectedPart ? "active" : "";
  return `<button class="part-row ${active}" data-part="${escapeHtml(part.part_id)}"><span class="part-swatch swatch-${Math.abs(hash(part.part_id)) % 5}"></span><span><b>${escapeHtml(part.part_id)}</b><small>${escapeHtml(part.role || "semantic part")}</small></span><i class="ph ph-caret-right"></i></button>`;
}

function selectedPartMarkup() {
  const part = state.inspect.contract.parts.find((item) => item.part_id === state.selectedPart);
  if (!part) return `<div class="empty-selection"><i class="ph ph-cursor-click"></i><p>Select a semantic part in the list or the viewport.</p></div>`;
  return `<div class="selected-part"><div class="selected-title"><span class="large-swatch swatch-${Math.abs(hash(part.part_id)) % 5}"></span><div><h2>${escapeHtml(part.part_id)}</h2><span>${escapeHtml(part.role || "semantic part")}</span></div><span class="selection-check"><i class="ph ph-check"></i></span></div><div class="field-label">SCALE FACTOR</div><div class="scale-fields"><label>X<input id="scale-x" type="number" min="0.01" step="0.05" value="1" /></label><label>Y<input id="scale-y" type="number" min="0.01" step="0.05" value="1" /></label><label>Z<input id="scale-z" type="number" min="0.01" step="0.05" value="1" /></label></div><button class="primary-action" id="apply-scale"><i class="ph ph-arrows-out"></i>Apply scale edit</button></div>`;
}

function renderQa() {
  const checks = state.report?.checks || [];
  viewRoot.innerHTML = `<div class="detail-view"><div class="detail-toolbar"><div><div class="eyebrow">DETERMINISTIC QA</div><h2>Quality gate</h2><p>Stable checks run against the current contract and GLB artifact.</p></div><button class="primary-action compact" id="rerun-qa"><i class="ph ph-arrow-clockwise"></i>Run again</button></div><div class="qa-layout"><section class="qa-summary"><div class="qa-score ${state.report.status.toLowerCase()}"><span>${state.report.status === "PASS" ? "100" : "!"}</span><small>GATE STATUS</small></div><div class="qa-metrics"><div><small>CHECKS</small><b>${checks.length}</b></div><div><small>TRIANGLES</small><b>${state.report.metrics?.triangles ?? "-"}</b></div><div><small>ARTIFACT</small><b>${state.inspect.current.glb_artifact.slice(7, 15)}</b></div></div></section><section class="check-list">${checks.map((check) => `<div class="check-row"><span class="check-icon ${check.status.toLowerCase()}"><i class="ph ${check.status === "PASS" ? "ph-check" : check.status === "WARN" ? "ph-warning" : "ph-x"}"></i></span><div><b>${escapeHtml(check.check_id)}</b><p>${escapeHtml(check.message)}</p></div><span class="check-status ${check.status.toLowerCase()}">${escapeHtml(check.status)}</span></div>`).join("")}</section></div></div>`;
  const production = state.production || {}, renders = production.renders || {};
  const cards = ["HERO_3Q", "FRONT", "BACK", "LEFT", "RIGHT", "TOP"].map((view) => renders[view] ? `<figure class="render-card"><img src="${escapeHtml(renders[view])}" alt="${view} render"><figcaption>${view}</figcaption></figure>` : `<div class="render-card unavailable"><span>${view}</span><small>UNAVAILABLE</small></div>`).join("");
  const adapters = Object.entries(production.adapters || {}).map(([name, value]) => `<span>${escapeHtml(name)}: ${escapeHtml(value)}</span>`).join("") || "No adapter receipt";
  viewRoot.querySelector(".detail-view").insertAdjacentHTML("beforeend", `<section class="release-proof"><div class="section-heading"><span>PRODUCTION RELEASE</span><span>${escapeHtml(production.promotion?.state || "UNAVAILABLE")}</span></div><p>Receipt: ${escapeHtml(production.receipt?.brief?.id || "UNAVAILABLE")}</p><p>Release proof: ${escapeHtml(production.release_verification?.status || "UNAVAILABLE")} · approval remains ${escapeHtml(production.release?.approval || "UNAVAILABLE")}</p><div class="adapter-tags">${adapters}</div><div class="render-grid">${cards}</div></section>`);
  document.querySelector("#rerun-qa").addEventListener("click", runQa);
}

function renderHistory() {
  viewRoot.innerHTML = `<div class="detail-view"><div class="detail-toolbar"><div><div class="eyebrow">IMMUTABLE OPERATIONS</div><h2>History</h2><p>Every edit is checkpointed before mutation and can be rolled back exactly.</p></div></div><div class="timeline">${state.history.length ? state.history.slice().reverse().map((item) => `<article class="timeline-row"><span class="timeline-dot"></span><div><div class="timeline-meta"><span>${escapeHtml(item.name || "checkpoint")}</span><time>${escapeHtml(item.operation_id || "system")}</time></div><h3>${escapeHtml(item.note || item.status || "Operation complete")}</h3><p>${escapeHtml(item.result_checkpoint || item.input_checkpoint || "")}</p></div>${item.input_checkpoint ? `<button class="quiet-button rollback" data-checkpoint="${escapeHtml(item.input_checkpoint)}">Rollback</button>` : ""}</article>`).join("") : `<div class="empty-state"><i class="ph ph-clock-counter-clockwise"></i><h3>No operations yet</h3><p>Edit a part to create the first checkpoint.</p></div>`}</div>`;
  document.querySelectorAll(".rollback").forEach((button) => button.addEventListener("click", () => rollback(button.dataset.checkpoint)));
}

function renderProviders() {
  viewRoot.innerHTML = `<div class="detail-view"><div class="detail-toolbar"><div><div class="eyebrow">EXTENSION CATALOG</div><h2>Providers</h2><p>Remote generation is opt-in. API keys stay in the local runtime.</p></div></div><div class="provider-list">${state.providers.map((provider) => `<article class="provider-row"><div class="provider-icon ${provider.network ? "remote" : "local"}"><i class="ph ${provider.network ? "ph-cloud-arrow-up" : "ph-shapes"}"></i></div><div class="provider-copy"><div><h3>${escapeHtml(provider.label)}</h3><span class="provider-id">${escapeHtml(provider.provider_id)}</span></div><p>${provider.network ? "Uploads image data only after consent. Results are verified as GLB before CAS storage." : "Dependency-free deterministic baseline for offline work."}</p><div class="provider-tags"><span>${provider.configured ? "Configured" : "Not configured"}</span><span>${provider.requires_consent ? "Consent required" : "Offline"}</span><span>${escapeHtml(provider.license)}</span></div></div><div class="provider-state ${provider.configured ? "ready" : "muted"}"><span></span>${provider.configured ? "Ready" : "Unavailable"}</div></article>`).join("")}</div><div class="provider-note"><i class="ph ph-lock-key-open"></i><div><b>Privacy boundary</b><p>Open3D does not persist provider keys, and the browser never receives them. Use the CLI or local API with an explicit consent flag.</p></div></div></div>`;
}

function hash(value) { return [...value].reduce((total, character) => ((total << 5) - total + character.charCodeAt(0)) | 0, 0); }

function selectPart(partId) { state.selectedPart = partId; renderView(); loadArtifact(); }

function disposeViewer() {
  if (viewer.resize) viewer.resize.disconnect();
  if (viewer.controls) viewer.controls.dispose();
  if (viewer.frame) cancelAnimationFrame(viewer.frame);
  if (viewer.renderer) { viewer.renderer.dispose(); viewer.renderer.domElement.remove(); }
  viewer.scene = null; viewer.camera = null; viewer.renderer = null; viewer.controls = null; viewer.root = null; viewer.canvas = null; viewer.resize = null; viewer.frame = 0;
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
  controls.minDistance = 0.2;
  controls.maxDistance = 20;
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
  viewer.scene = scene; viewer.camera = camera; viewer.renderer = renderer; viewer.controls = controls; viewer.canvas = renderer.domElement;
  viewer.resize = new ResizeObserver(() => resizeViewer(viewport));
  viewer.resize.observe(viewport);
  renderer.domElement.addEventListener("pointerdown", pickPart);
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
  const data = viewer.data || await api("/api/artifact/current");
  viewer.data = data;
  gltfLoader.parse(data, "", (gltf) => {
    if (viewer.root) viewer.scene.remove(viewer.root);
    viewer.original.clear(); viewer.root = gltf.scene;
    viewer.root.traverse((node) => {
      const parentPart = node.userData?.open3d?.part_id || node.userData?.part_id || node.name;
      if (node.isMesh) {
        node.userData.partId = parentPart;
        node.castShadow = true; node.receiveShadow = true;
        const materials = Array.isArray(node.material) ? node.material : [node.material];
        viewer.original.set(node.uuid, materials.map((material) => ({ material, color: material.color?.clone(), emissive: material.emissive?.clone(), intensity: material.emissiveIntensity })));
      }
    });
    viewer.scene.add(viewer.root);
    frameAsset();
    document.querySelector("#mesh-readout").textContent = `${viewer.root.getObjectByProperty("isMesh", true) ? countMeshes(viewer.root) : 0} render meshes`;
    highlightPart(state.selectedPart);
  }, (error) => toast(`GLB parse failed: ${error.message || error}`, "error"));
}

function countMeshes(root) { let count = 0; root.traverse((node) => { if (node.isMesh) count++; }); return count; }

function pickPart(event) {
  if (!viewer.root) return;
  const rect = viewer.canvas.getBoundingClientRect();
  viewer.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  viewer.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  viewer.raycaster.setFromCamera(viewer.pointer, viewer.camera);
  const hit = viewer.raycaster.intersectObject(viewer.root, true)[0];
  if (hit?.object?.userData?.partId) selectPart(hit.object.userData.partId);
}

function highlightPart(partId) {
  if (!viewer.root) return;
  viewer.root.traverse((node) => {
    if (!node.isMesh) return;
    const selected = partId && node.userData.partId === partId;
    const entries = viewer.original.get(node.uuid) || [];
    entries.forEach(({ material, color, emissive, intensity }) => {
      if (selected && material.emissive) { material.emissive.setHex(0x9cff80); material.emissiveIntensity = 0.4; material.color?.setHex(0xb9ffc0); }
      else { if (color && material.color) material.color.copy(color); if (emissive && material.emissive) material.emissive.copy(emissive); material.emissiveIntensity = intensity || 0; }
    });
  });
}

function frameAsset() {
  if (!viewer.root) return;
  const bounds = new THREE.Box3().setFromObject(viewer.root); const sphere = bounds.getBoundingSphere(new THREE.Sphere());
  const distance = Math.max(sphere.radius * 2.8, 1); const direction = new THREE.Vector3(1, 0.72, 1).normalize();
  viewer.camera.position.copy(sphere.center).add(direction.multiplyScalar(distance)); viewer.controls.target.copy(sphere.center); viewer.controls.update();
}

function toggleGrid() { const grid = viewer.scene?.getObjectByName("open3d-grid"); if (grid) grid.visible = !grid.visible; }

async function runQa(source = "workspace") {
  const actionId = beginAction(source === "agent" ? "Agent QA" : "Run QA", "Validating current GLB and contract");
  updateAction(actionId, "running", "Reading current artifact");
  try { state.report = await api("/api/validate"); setQaBadge(state.report.status); hydrateHeader(); if (state.activeView === "qa") renderView(); updateAction(actionId, state.report.status === "PASS" ? "done" : "failed", `QA ${state.report.status}`); toast("QA report refreshed", "success"); } catch (error) { updateAction(actionId, "failed", error.message); toast(error.message, "error"); }
}

async function applyScale() {
  const partId = state.selectedPart; if (!partId) return;
  const values = Object.fromEntries(["x", "y", "z"].map((axis) => [axis, Number(document.querySelector(`#scale-${axis}`).value)]));
  try { state.busy = true; await api("/api/edit-part", { method: "POST", body: JSON.stringify({ part_id: partId, scale_x: values.x, scale_y: values.y, scale_z: values.z }) }); toast(`Scaled ${partId}`, "success"); await refreshAfterMutation(); } catch (error) { toast(error.message, "error"); } finally { state.busy = false; }
}

async function refreshAfterMutation() { const [inspect, report, history] = await Promise.all([api("/api/inspect"), api("/api/validate"), api("/api/history")]); state.inspect = inspect; state.report = report; state.history = history; viewer.data = null; hydrateHeader(); renderView(); await loadArtifact(); }

async function rollback(checkpoint) {
  if (!checkpoint || !confirm("Restore this checkpoint?")) return;
  try { await api("/api/rollback", { method: "POST", body: JSON.stringify({ checkpoint_id: checkpoint }) }); toast("Checkpoint restored", "success"); await refreshAfterMutation(); } catch (error) { toast(error.message, "error"); }
}

document.querySelectorAll(".nav-item").forEach((item) => item.addEventListener("click", () => { state.activeView = item.dataset.view; renderView(); }));
document.querySelector("#validate").addEventListener("click", runQa);
document.querySelector("#search").addEventListener("input", (event) => { state.query = event.target.value; if (state.activeView === "workspace") renderView(); });
document.querySelector("#create-asset").addEventListener("click", openCreateAsset);
document.querySelector("#quick-create").addEventListener("click", openCreateAsset);
document.querySelector("#create-form").addEventListener("submit", saveAssetDraft);
document.querySelector("#create-generate").addEventListener("click", generateAssetFromBrief);
document.querySelector("#create-reference-file").addEventListener("change", attachReferenceImage);
document.querySelector("#agent-reference-file").addEventListener("change", attachReferenceImage);
document.querySelector("#reference-remove").addEventListener("click", removeReferenceImage);
document.querySelector("#agent-attachment-remove").addEventListener("click", removeReferenceImage);
document.querySelector("#create-agent").addEventListener("change", (event) => { state.agentProvider = event.target.value; renderAgentProviderStatus(); syncCreateAgent(); });
document.querySelector("#create-close").addEventListener("click", closeCreateAsset);
document.querySelector("#create-cancel").addEventListener("click", closeCreateAsset);
document.querySelector("[data-close-create]").addEventListener("click", closeCreateAsset);
document.querySelector("#open-agent").addEventListener("click", openAgent);
document.querySelector("#close-agent").addEventListener("click", closeAgent);
document.querySelector("#agent-backdrop").addEventListener("click", closeAgent);
document.querySelector("#agent-form").addEventListener("submit", submitAgentMessage);
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
  if (event.key === "Escape") { if (state.createOpen) closeCreateAsset(); else if (state.agentOpen) closeAgent(); }
});
document.addEventListener("click", (event) => { if (event.target.closest("#apply-scale")) applyScale(); });

loadState();
