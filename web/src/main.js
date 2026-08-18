import "@phosphor-icons/web/regular";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import "./styles.css";

const state = {
  inspect: null,
  report: null,
  history: [],
  providers: [],
  production: null,
  activeView: "workspace",
  selectedPart: null,
  query: "",
  theme: "dark",
  busy: false,
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
        <div class="section-label"><span>PROJECT FILES</span><i class="ph ph-plus"></i></div>
        <div class="file-tree"><div class="tree-row folder"><i class="ph ph-folder-open"></i><span>Assets</span></div><div class="tree-row selected"><i class="ph ph-cube"></i><span id="asset-file">asset.yaml</span><span class="tree-status"></span></div><div class="tree-row"><i class="ph ph-file-text"></i><span>QA report</span></div></div>
      </div>
      <div class="sidebar-footer"><div class="runtime-status"><span class="status-pulse"></span><span>LOCAL RUNTIME</span><b>READY</b></div><div class="footer-links"><span>v0.1 alpha</span><a href="https://github.com/nguyenanhducdeveloper86/open3d" target="_blank" rel="noreferrer">GitHub <i class="ph ph-arrow-up-right"></i></a></div></div>
    </aside>
    <main class="main-shell">
      <header class="topbar"><div class="crumbs"><span>Projects</span><i class="ph ph-caret-right"></i><strong id="breadcrumb-name">Open3D asset</strong></div><label class="search-box"><i class="ph ph-magnifying-glass"></i><input id="search" type="search" placeholder="Search parts, checks, providers" /><kbd>⌘ K</kbd></label><div class="top-actions"><button class="validate-button" id="validate"><i class="ph ph-shield-check"></i><span>Run QA</span></button><div class="avatar">DA</div></div></header>
      <section class="content-shell">
        <div class="content-heading"><div><div class="eyebrow">OPEN3D / LIVE ARTIFACT</div><h1 id="asset-title">Loading asset</h1><p id="asset-subtitle">Preparing the contract and GLB preview</p></div><div class="heading-meta"><span class="status-badge" id="qa-status"><span></span>Checking</span><span class="artifact-id" id="artifact-id">sha256:...</span></div></div>
        <div id="view-root"></div>
      </section>
    </main>
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

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
  const type = response.headers.get("content-type") || "";
  const value = type.includes("json") ? await response.json() : await response.arrayBuffer();
  if (!response.ok) throw new Error(value?.error || `Request failed: ${response.status}`);
  return value;
}

async function loadState() {
  try {
    const [inspect, report, history, providers, production] = await Promise.all([api("/api/inspect"), api("/api/validate"), api("/api/history"), api("/api/providers"), api("/api/production/state")]);
    state.inspect = inspect;
    state.report = report;
    state.history = history;
    state.providers = providers;
    state.production = production;
    state.selectedPart = inspect.contract.parts[0]?.part_id || null;
    hydrateHeader();
    renderView();
    await loadArtifact();
  } catch (error) {
    toast(error.message, "error");
    document.querySelector("#asset-subtitle").textContent = "Start `open3d serve` with a built web bundle to connect this workspace";
  }
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
  viewRoot.innerHTML = `<div class="workspace-grid"><section class="stage-panel"><div class="stage-toolbar"><div class="toolbar-group"><button class="tool-button active" id="orbit-tool" title="Orbit"><i class="ph ph-cursor"></i><span>Orbit</span></button><button class="tool-button" id="frame-tool" title="Frame asset"><i class="ph ph-frame-corners"></i></button><button class="tool-button" id="grid-tool" title="Toggle grid"><i class="ph ph-grid-four"></i></button></div><div class="stage-readout"><span class="live-dot"></span>GLB / ${escapeHtml(state.inspect.current.qa_status)}</div></div><div class="viewport" id="viewport"><div class="viewport-hint"><span>Drag to orbit</span><span>Scroll to zoom</span></div><div class="viewport-crosshair"><i class="ph ph-crosshair"></i></div></div><div class="stage-footer"><span><i class="ph ph-cube"></i>${escapeHtml(contract.asset_id)}</span><span id="mesh-readout">Loading geometry</span><span><i class="ph ph-arrows-out-cardinal"></i>${escapeHtml(contract.units)}</span></div></section><aside class="inspector-panel"><div class="inspector-tabs"><button class="inspector-tab active">Inspector</button><button class="inspector-tab">Contract</button></div><div class="inspector-scroll"><section class="panel-section selected-part-section"><div class="section-heading"><span>SELECTED PART</span><button class="quiet-button" id="clear-selection">Clear</button></div><div id="selected-part"></div></section><section class="panel-section"><div class="section-heading"><span>SEMANTIC PARTS</span><span class="section-count">${parts.length}/${contract.parts.length}</span></div><div class="part-list" id="part-list">${parts.map((part) => partRow(part)).join("")}</div></section><section class="panel-section"><div class="section-heading"><span>CONTRACT SNAPSHOT</span><i class="ph ph-lock-key"></i></div><div class="metric-grid"><div><small>WIDTH</small><b>${contract.dimensions.width}${contract.units}</b></div><div><small>DEPTH</small><b>${contract.dimensions.depth}${contract.units}</b></div><div><small>HEIGHT</small><b>${contract.dimensions.height}${contract.units}</b></div><div><small>TRIANGLES</small><b>${state.report.metrics?.triangles ?? "-"}</b></div></div></section></div></aside></div><div class="command-bar"><div class="command-icon"><i class="ph ph-magic-wand"></i></div><input id="command-input" placeholder="Describe a direct edit, for example: scale spout x 1.2" /><button id="command-run"><span>Apply</span><i class="ph ph-arrow-up-right"></i></button><span class="command-note">Local operation</span></div>`;
  document.querySelector("#selected-part").innerHTML = selectedPartMarkup();
  document.querySelector("#part-list").querySelectorAll("button").forEach((button) => button.addEventListener("click", () => selectPart(button.dataset.part)));
  document.querySelector("#clear-selection").addEventListener("click", () => { state.selectedPart = null; renderView(); highlightPart(null); });
  document.querySelector("#command-run").addEventListener("click", runCommand);
  document.querySelector("#command-input").addEventListener("keydown", (event) => { if (event.key === "Enter") runCommand(); });
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

async function runQa() {
  try { state.report = await api("/api/validate"); setQaBadge(state.report.status); hydrateHeader(); if (state.activeView === "qa") renderView(); toast("QA report refreshed", "success"); } catch (error) { toast(error.message, "error"); }
}

async function applyScale() {
  const partId = state.selectedPart; if (!partId) return;
  const values = Object.fromEntries(["x", "y", "z"].map((axis) => [axis, Number(document.querySelector(`#scale-${axis}`).value)]));
  try { state.busy = true; await api("/api/edit-part", { method: "POST", body: JSON.stringify({ part_id: partId, scale_x: values.x, scale_y: values.y, scale_z: values.z }) }); toast(`Scaled ${partId}`, "success"); await refreshAfterMutation(); } catch (error) { toast(error.message, "error"); } finally { state.busy = false; }
}

async function runCommand() {
  const input = document.querySelector("#command-input"); const match = input?.value.match(/^scale\s+([\w.-]+)\s+([xyz])\s+([\d.]+)$/i);
  if (!match) return toast("Use: scale part-id x 1.2", "neutral");
  try { await api("/api/edit-part", { method: "POST", body: JSON.stringify({ part_id: match[1], [`scale_${match[2].toLowerCase()}`]: Number(match[3]) }) }); toast(`Applied scale to ${match[1]}`, "success"); input.value = ""; await refreshAfterMutation(); } catch (error) { toast(error.message, "error"); }
}

async function refreshAfterMutation() { const [inspect, report, history] = await Promise.all([api("/api/inspect"), api("/api/validate"), api("/api/history")]); state.inspect = inspect; state.report = report; state.history = history; viewer.data = null; hydrateHeader(); renderView(); await loadArtifact(); }

async function rollback(checkpoint) {
  if (!checkpoint || !confirm("Restore this checkpoint?")) return;
  try { await api("/api/rollback", { method: "POST", body: JSON.stringify({ checkpoint_id: checkpoint }) }); toast("Checkpoint restored", "success"); await refreshAfterMutation(); } catch (error) { toast(error.message, "error"); }
}

document.querySelectorAll(".nav-item").forEach((item) => item.addEventListener("click", () => { state.activeView = item.dataset.view; renderView(); }));
document.querySelector("#validate").addEventListener("click", runQa);
document.querySelector("#search").addEventListener("input", (event) => { state.query = event.target.value; if (state.activeView === "workspace") renderView(); });
document.addEventListener("keydown", (event) => { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); document.querySelector("#search").focus(); } });
document.addEventListener("click", (event) => { if (event.target.closest("#apply-scale")) applyScale(); });

loadState();
