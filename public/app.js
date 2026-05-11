const fieldCanvas = document.getElementById("field-canvas");
const particleCanvas = document.getElementById("particle-canvas");
const fieldCtx = fieldCanvas.getContext("2d", { alpha: false });
const particleCtx = particleCanvas.getContext("2d");

const controls = {
  datasetTitle: document.getElementById("dataset-title"),
  readout: document.getElementById("readout"),
  weekPill: document.getElementById("week-pill"),
  fieldName: document.getElementById("field-name"),
  levelSummary: document.getElementById("level-summary"),
  weekWindow: document.getElementById("week-window"),
  windBadge: document.getElementById("wind-badge"),
  variableMeta: document.getElementById("variable-meta"),
  variable: document.getElementById("variable-select"),
  layerControl: document.getElementById("layer-control"),
  layer: document.getElementById("layer-select"),
  time: document.getElementById("time-slider"),
  timeLabel: document.getElementById("time-label"),
  timelineRail: document.getElementById("timeline-rail"),
  play: document.getElementById("play-toggle"),
  back: document.getElementById("step-back"),
  forward: document.getElementById("step-forward"),
  projection: document.getElementById("projection-toggle"),
  wind: document.getElementById("wind-toggle"),
  opacity: document.getElementById("opacity-slider"),
  legendName: document.getElementById("legend-name"),
  legendMin: document.getElementById("legend-min"),
  legendMax: document.getElementById("legend-max"),
  legend: document.getElementById("legend-canvas"),
  loading: document.getElementById("loading"),
  assistantStatus: document.getElementById("assistant-status"),
  assistantInput: document.getElementById("assistant-input"),
  assistantSubmit: document.getElementById("assistant-submit"),
  assistantSteps: document.getElementById("assistant-steps"),
  assistantSummary: document.getElementById("assistant-summary"),
  assistantOutput: document.getElementById("assistant-output"),
  assistantSuggestions: document.getElementById("assistant-suggestions"),
};

const state = {
  manifest: null,
  variable: null,
  layerIndex: 0,
  layer: null,
  colorMeta: null,
  timeIndex: 0,
  field: null,
  windU: null,
  windV: null,
  projection: "globe",
  opacity: 0.86,
  windEnabled: true,
  playing: false,
  width: 0,
  height: 0,
  dpr: Math.min(window.devicePixelRatio || 1, 2),
  lon0: 118,
  lat0: 18,
  zoom: 1,
  dragging: false,
  dragStart: null,
  mouse: null,
  particles: [],
  land: null,
  cache: new Map(),
  loadToken: 0,
  windMeta: null,
  windPairLabel: null,
  assistantBusy: false,
  assistantSteps: [],
  assistantController: null,
};

const palettes = {
  temperature: [
    [28, 36, 68],
    [41, 92, 139],
    [78, 167, 168],
    [218, 219, 153],
    [221, 135, 73],
    [156, 49, 45],
  ],
  rain: [
    [8, 10, 10],
    [38, 87, 100],
    [63, 146, 137],
    [190, 202, 112],
    [231, 184, 79],
    [228, 101, 80],
  ],
  pressure: [
    [42, 54, 86],
    [65, 108, 137],
    [120, 151, 145],
    [210, 188, 133],
    [222, 134, 91],
    [166, 68, 64],
  ],
  wind: [
    [7, 11, 18],
    [37, 81, 113],
    [61, 151, 154],
    [170, 204, 154],
    [231, 184, 79],
  ],
  cloud: [
    [11, 15, 20],
    [55, 75, 85],
    [123, 139, 137],
    [199, 196, 176],
    [244, 239, 215],
  ],
  ice: [
    [11, 15, 20],
    [37, 91, 116],
    [89, 173, 186],
    [202, 238, 230],
    [247, 250, 246],
  ],
  flux: [
    [38, 48, 66],
    [50, 111, 129],
    [101, 156, 121],
    [220, 184, 91],
    [214, 89, 70],
  ],
  soil: [
    [45, 33, 35],
    [91, 71, 57],
    [134, 114, 75],
    [100, 151, 113],
    [72, 156, 173],
  ],
  radiation: [
    [7, 11, 18],
    [77, 67, 98],
    [160, 87, 89],
    [225, 156, 71],
    [248, 226, 142],
  ],
  height: [
    [16, 24, 28],
    [45, 91, 104],
    [87, 149, 135],
    [218, 185, 112],
    [230, 123, 91],
  ],
  humidity: [
    [8, 15, 20],
    [29, 77, 108],
    [47, 142, 149],
    [126, 194, 156],
    [222, 224, 166],
  ],
  ozone: [
    [10, 11, 18],
    [58, 58, 108],
    [119, 82, 141],
    [202, 118, 113],
    [236, 184, 112],
  ],
  velocity: [
    [58, 78, 108],
    [102, 151, 164],
    [219, 216, 178],
    [214, 132, 87],
    [147, 60, 66],
  ],
  scalar: [
    [12, 20, 26],
    [56, 101, 132],
    [100, 157, 149],
    [225, 184, 92],
    [229, 102, 80],
  ],
};

const windVisuals = {
  particleDensity: 8000,
  particleMin: 1400,
  particleMax: 4200,
  particleLifetime: 70,
  fadeAlpha: 0.91,
  lineWidth: 1.8,
  strokeAlpha: 0.95,
  speedScale: 0.03,
  segmentSteps: 2,
};

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function mix(a, b, t) {
  return a + (b - a) * t;
}

function colorRange(variable) {
  const stats = variable.stats || {};
  if (variable.family === "rain") {
    const min = Number.isFinite(stats.min) ? Math.max(0, stats.min) : 0;
    const max = Number.isFinite(stats.p98) ? stats.p98 : stats.max;
    if (!Number.isFinite(max) || max <= min) {
      return { min: 0, max: 1 };
    }
    return { min, max };
  }

  const min = Number.isFinite(stats.p05) ? stats.p05 : stats.min;
  const max = Number.isFinite(stats.p95) ? stats.p95 : stats.max;
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) {
    return { min: 0, max: 1 };
  }
  return { min, max };
}

function normalizeColorValue(value, variable) {
  const { min, max } = colorRange(variable);
  const linear = clamp((value - min) / (max - min), 0, 1);
  if (variable.family === "rain") {
    return Math.log1p(linear * 24) / Math.log1p(24);
  }
  return linear;
}

function legendValueAt(t, variable) {
  const { min, max } = colorRange(variable);
  if (variable.family === "rain") {
    const linear = Math.expm1(t * Math.log1p(24)) / 24;
    return min + (max - min) * linear;
  }
  return min + (max - min) * t;
}

function colorFor(value, variable, alpha = 255) {
  if (!Number.isFinite(value)) {
    return [0, 0, 0, 0];
  }
  const ramp = palettes[variable.family] || palettes.scalar;
  const t = normalizeColorValue(value, variable);
  const scaled = t * (ramp.length - 1);
  const idx = Math.min(ramp.length - 2, Math.floor(scaled));
  const local = scaled - idx;
  const a = ramp[idx];
  const b = ramp[idx + 1];
  return [
    Math.round(mix(a[0], b[0], local)),
    Math.round(mix(a[1], b[1], local)),
    Math.round(mix(a[2], b[2], local)),
    alpha,
  ];
}

function formatValue(value, variable) {
  if (!Number.isFinite(value)) return "--";
  const id = variable.id;
  if (id.includes("temperature") || id.includes("dewpoint")) {
    const c = value > 170 ? value - 273.15 : value;
    return `${c.toFixed(1)} C`;
  }
  if (id.includes("stress")) {
    return `${value.toFixed(3)} N/m2`;
  }
  if (id.includes("wind")) {
    return `${value.toFixed(2)} m/s`;
  }
  if (id.includes("pressure")) {
    return value > 20000 ? `${(value / 100).toFixed(1)} hPa` : value.toFixed(1);
  }
  if (id.includes("geopotential")) {
    return value >= 1000 ? `${(value / 9.80665).toFixed(0)} gpm` : value.toFixed(1);
  }
  if (id.includes("height")) {
    return `${value.toFixed(0)} m`;
  }
  if (id.includes("humidity")) {
    return `${(value * 1000).toFixed(2)} g/kg`;
  }
  if (id.includes("cover") || id === "sea_ice_cover") {
    return `${(value * 100).toFixed(1)}%`;
  }
  if (id.includes("radiation") || id.includes("flux") || id.includes("heat")) {
    return `${value.toFixed(1)} W/m2`;
  }
  if (Math.abs(value) >= 1000) return value.toExponential(2);
  if (Math.abs(value) >= 10) return value.toFixed(1);
  if (Math.abs(value) >= 1) return value.toFixed(2);
  return value.toExponential(2);
}

function formatWeek(time) {
  if (!time) return "--";
  if (time.start && time.end) return `${time.start} - ${time.end}`;
  return time.label || time.iso || `step ${time.index + 1}`;
}

function assistantContext() {
  const time = state.manifest?.times?.[state.timeIndex] || null;
  return {
    variableId: state.variable?.id || null,
    variableLabel: state.variable?.label || null,
    variableFamily: state.variable?.family || null,
    layerIndex: state.layerIndex,
    layerLabel: state.layer?.label || "surface",
    timeIndex: state.timeIndex,
    week: time?.week || state.timeIndex + 1,
    weekWindow: time ? formatWeek(time) : null,
    projection: state.projection,
    centerLon: Number(state.lon0.toFixed(2)),
    centerLat: Number(state.lat0.toFixed(2)),
  };
}

function setAssistantBusy(busy) {
  state.assistantBusy = busy;
  controls.assistantSubmit.disabled = busy;
  controls.assistantInput.disabled = busy;
  controls.assistantStatus.textContent = busy ? "working" : "idle";
  controls.assistantSubmit.textContent = busy ? "analyzing..." : "analyze";
}

function renderAssistantSteps() {
  controls.assistantSteps.replaceChildren();
  for (const step of state.assistantSteps) {
    const row = document.createElement("div");
    row.className = `assistant-step ${step.status}`;

    const text = document.createElement("div");
    text.className = "assistant-step-text";

    const head = document.createElement("div");
    head.className = "assistant-step-head";

    const title = document.createElement("div");
    title.className = "assistant-step-title";
    title.textContent = step.label;

    const stateTag = document.createElement("div");
    stateTag.className = "assistant-step-state";
    stateTag.textContent = step.status === "done" ? "done" : step.status === "error" ? "error" : step.status === "active" ? "working" : "queued";

    head.append(title, stateTag);

    const progress = document.createElement("div");
    progress.className = "assistant-step-progress";
    const progressBar = document.createElement("div");
    progressBar.className = "assistant-step-progress-bar";
    progressBar.style.width = `${Math.round((step.progress ?? 0) * 100)}%`;
    progress.appendChild(progressBar);

    const detail = document.createElement("div");
    detail.className = "assistant-step-detail";
    detail.textContent = step.detail || (step.status === "done" ? "completed" : step.status === "active" ? "working..." : "waiting...");

    text.append(head, progress, detail);
    row.append(text);
    controls.assistantSteps.appendChild(row);
  }
}

function resetAssistantView() {
  state.assistantSteps = [];
  controls.assistantSummary.textContent = "Preparing analysis...";
  controls.assistantOutput.textContent = "Waiting for assistant response...";
  controls.assistantSuggestions.replaceChildren();
  renderAssistantSteps();
}

function updateAssistantPhase(phase, label, detail = "", progress = null) {
  const index = state.assistantSteps.findIndex((step) => step.id === phase);
  if (index === -1) {
    state.assistantSteps.push({
      id: phase,
      label: label || phase,
      status: "active",
      detail: detail || "working...",
      progress: progress ?? 0.08,
    });
  } else {
    state.assistantSteps = state.assistantSteps.map((step, stepIndex) => {
      if (stepIndex < index) {
        return { ...step, status: step.status === "error" ? "error" : "done", progress: 1, detail: step.detail || "completed" };
      }
      if (stepIndex === index) {
        return {
          ...step,
          label: label || step.label,
          status: "active",
          detail: detail || step.detail,
          progress: progress ?? step.progress ?? 0.08,
        };
      }
      return step;
    });
  }
  renderAssistantSteps();
}

function finishAssistantPhases() {
  state.assistantSteps = state.assistantSteps.map((step) => ({
    ...step,
    status: step.status === "error" ? "error" : "done",
    progress: step.status === "error" ? step.progress ?? 0 : 1,
    detail: step.status === "error" ? step.detail : step.detail || "completed",
  }));
  renderAssistantSteps();
}

function failAssistant(errorMessage) {
  if (!state.assistantSteps.length) {
    state.assistantSteps = [{ id: "error", label: "Assistant failed", status: "error", detail: errorMessage, progress: 1 }];
  } else {
    state.assistantSteps = state.assistantSteps.map((step, index) => {
      if (index === state.assistantSteps.length - 1 && step.status === "active") {
        return { ...step, status: "error", detail: errorMessage, progress: 1 };
      }
      return step;
    });
  }
  renderAssistantSteps();
  controls.assistantStatus.textContent = "error";
  controls.assistantSummary.textContent = "Assistant failed.";
  controls.assistantOutput.textContent = errorMessage;
}

function renderAssistantSuggestions(items = []) {
  controls.assistantSuggestions.replaceChildren();
  for (const item of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "assistant-chip";
    button.textContent = item.label || `${item.variableLabel || item.variableId} / W${(item.timeIndex ?? 0) + 1}`;
    button.addEventListener("click", () => {
      if (!item.variableId) return;
      setField(item.variableId, Number(item.timeIndex ?? state.timeIndex), Number(item.layerIndex ?? 0));
    });
    controls.assistantSuggestions.appendChild(button);
  }
}

function renderAssistantResult(result) {
  const resolved = result.resolved;
  const resolvedText = resolved
    ? `Resolved: ${resolved.variableLabel || resolved.variableId} / ${resolved.region || "--"} / ${resolved.resolutionSource || "question"}`
    : null;
  controls.assistantSummary.textContent = resolvedText ? `${result.summary || "Analysis complete."}\n${resolvedText}` : result.summary || "Analysis complete.";
  controls.assistantOutput.textContent = result.report || "No report returned.";
  renderAssistantSuggestions(result.suggestions || []);
}

async function runAssistantQuestion() {
  const question = controls.assistantInput.value.trim();
  if (!question || !state.manifest || !state.variable) return;
  state.assistantController?.abort();
  state.assistantController = new AbortController();
  setAssistantBusy(true);
  resetAssistantView();

  try {
    const response = await fetch("http://127.0.0.1:8765/api/forecast-assistant", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        datasetSource: state.manifest.source,
        context: assistantContext(),
      }),
      signal: state.assistantController.signal,
    });

    if (!response.ok || !response.body) {
      const message = `assistant request failed (${response.status})`;
      throw new Error(message);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.type === "phase") {
          updateAssistantPhase(event.phase, event.label, event.detail || "working...", event.progress ?? null);
          controls.assistantStatus.textContent = event.label || "working";
        } else if (event.type === "result") {
          finishAssistantPhases();
          controls.assistantStatus.textContent = "ready";
          renderAssistantResult(event.result || {});
        } else if (event.type === "error") {
          throw new Error(event.message || "assistant failed");
        }
      }
    }
  } catch (error) {
    if (error.name !== "AbortError") {
      failAssistant(error.message || "assistant failed");
    }
  } finally {
    state.assistantController = null;
    setAssistantBusy(false);
  }
}

function resize() {
  state.dpr = Math.min(window.devicePixelRatio || 1, 2);
  state.width = Math.floor(window.innerWidth * state.dpr);
  state.height = Math.floor(window.innerHeight * state.dpr);
  for (const canvas of [fieldCanvas, particleCanvas]) {
    canvas.width = state.width;
    canvas.height = state.height;
    canvas.style.width = `${window.innerWidth}px`;
    canvas.style.height = `${window.innerHeight}px`;
  }
  renderField();
  resetParticles();
}

function sphereRadius() {
  return Math.min(state.width, state.height) * 0.43 * state.zoom;
}

function project(lon, lat) {
  if (state.projection === "plate") {
    const x = ((lon + 180) / 360) * state.width;
    const y = ((90 - lat) / 180) * state.height;
    return [x, y, true];
  }
  const lonRad = ((lon - state.lon0) * Math.PI) / 180;
  const latRad = (lat * Math.PI) / 180;
  const lat0 = (state.lat0 * Math.PI) / 180;
  const cosLat = Math.cos(latRad);
  const visible = Math.sin(lat0) * Math.sin(latRad) + Math.cos(lat0) * cosLat * Math.cos(lonRad);
  if (visible <= 0) return [0, 0, false];
  const r = sphereRadius();
  const x = state.width / 2 + r * cosLat * Math.sin(lonRad);
  const y = state.height / 2 - r * (Math.cos(lat0) * Math.sin(latRad) - Math.sin(lat0) * cosLat * Math.cos(lonRad));
  return [x, y, true];
}

function invert(x, y) {
  if (state.projection === "plate") {
    return [(x / state.width) * 360 - 180, 90 - (y / state.height) * 180, true];
  }
  const r = sphereRadius();
  const dx = (x - state.width / 2) / r;
  const dy = -(y - state.height / 2) / r;
  const rho = Math.sqrt(dx * dx + dy * dy);
  if (rho > 1) return [0, 0, false];
  if (rho < 1e-8) return [state.lon0, state.lat0, true];
  const c = Math.asin(rho);
  const lat0 = (state.lat0 * Math.PI) / 180;
  const lon0 = (state.lon0 * Math.PI) / 180;
  const lat = Math.asin(Math.cos(c) * Math.sin(lat0) + (dy * Math.sin(c) * Math.cos(lat0)) / rho);
  const lon = lon0 + Math.atan2(dx * Math.sin(c), rho * Math.cos(lat0) * Math.cos(c) - dy * Math.sin(lat0) * Math.sin(c));
  return [((((lon * 180) / Math.PI + 540) % 360) - 180), (lat * 180) / Math.PI, true];
}

function sampleGridNearest(grid, lon, lat, variable = state.variable) {
  if (!grid) return NaN;
  const [nLat, nLon] = variable.shape;
  const y = clamp(Math.round(((90 - lat) / 180) * (nLat - 1)), 0, nLat - 1);
  const normalizedLon = ((lon % 360) + 360) % 360;
  const x = clamp(Math.round((normalizedLon / 360) * nLon) % nLon, 0, nLon - 1);
  return grid[y * nLon + x];
}

function shouldSmoothField(variable = state.variable) {
  return variable?.family === "temperature" || variable?.family === "rain";
}

function sampleGridSmooth(grid, lon, lat, variable = state.variable) {
  if (!grid) return NaN;
  const [nLat, nLon] = variable.shape;
  const y = clamp(((90 - lat) / 180) * (nLat - 1), 0, nLat - 1);
  const normalizedLon = ((lon % 360) + 360) % 360;
  const x = (((normalizedLon / 360) * nLon) % nLon + nLon) % nLon;

  const y0 = Math.floor(y);
  const y1 = Math.min(y0 + 1, nLat - 1);
  const x0 = Math.floor(x) % nLon;
  const x1 = (x0 + 1) % nLon;
  const ty = y - y0;
  const tx = x - Math.floor(x);

  const v00 = grid[y0 * nLon + x0];
  const v01 = grid[y0 * nLon + x1];
  const v10 = grid[y1 * nLon + x0];
  const v11 = grid[y1 * nLon + x1];

  if ([v00, v01, v10, v11].some((value) => !Number.isFinite(value))) {
    return sampleGridNearest(grid, lon, lat, variable);
  }

  const top = mix(v00, v01, tx);
  const bottom = mix(v10, v11, tx);
  return mix(top, bottom, ty);
}

function sampleGrid(grid, lon, lat, variable = state.variable, smooth = shouldSmoothField(variable)) {
  return smooth ? sampleGridSmooth(grid, lon, lat, variable) : sampleGridNearest(grid, lon, lat, variable);
}

async function loadGrid(variable, layerIndex, timeIndex) {
  const key = `${variable.slug}:${layerIndex}:${timeIndex}`;
  if (state.cache.has(key)) return state.cache.get(key);
  const layer = (variable.layers && variable.layers[layerIndex]) || {
    files: variable.files || [],
    stats: variable.stats,
    label: "surface",
  };
  const entry = layer.files.find((file) => file.time === timeIndex);
  if (!entry) throw new Error(`missing field ${key}`);
  const res = await fetch(entry.path);
  if (!res.ok) throw new Error(`failed to load ${entry.path}`);
  const buffer = await res.arrayBuffer();
  const grid = new Float32Array(buffer);
  state.cache.set(key, grid);
  return grid;
}

function variableById(id) {
  return state.manifest.variables.find((item) => item.id === id);
}

function vectorPairFor(variable) {
  const pairs = state.manifest.vectorPairs || [];
  if (variable.domain === "upper") {
    return pairs.find((pair) => pair.domain === "upper");
  }
  return pairs.find((pair) => pair.domain === "surface");
}

async function loadVectorPair(variable, layerIndex, timeIndex) {
  const pair = vectorPairFor(variable);
  if (!pair) return [null, null, null, null];
  const u = variableById(pair.u);
  const v = variableById(pair.v);
  if (!u || !v) return [null, null, null, null];
  const vectorLayer = pair.layerMode === "matched" ? layerIndex : 0;
  const maxLayer = Math.min((u.layers || []).length, (v.layers || []).length) - 1;
  if (vectorLayer > maxLayer) return [null, null, null, null];
  const [windU, windV] = await Promise.all([loadGrid(u, vectorLayer, timeIndex), loadGrid(v, vectorLayer, timeIndex)]);
  return [windU, windV, u, pair.label];
}

async function setField(variableId = state.variable.id, timeIndex = state.timeIndex, requestedLayer = state.layerIndex) {
  const token = ++state.loadToken;
  controls.loading.classList.remove("hidden");
  const variable = variableById(variableId);
  const layers = variable.layers || [{ index: 0, label: "surface", files: variable.files || [], stats: variable.stats }];
  const layerIndex = clamp(requestedLayer, 0, layers.length - 1);
  const layer = layers[layerIndex];
  state.variable = variable;
  state.layerIndex = layerIndex;
  state.layer = layer;
  state.colorMeta = { ...variable, stats: layer.stats || variable.stats };
  state.timeIndex = timeIndex;
  controls.variable.value = variable.id;
  renderLayerOptions(variable, layerIndex);
  controls.time.value = String(timeIndex);
  controls.timeLabel.textContent = formatWeek(state.manifest.times[timeIndex]);
  const [field, vector] = await Promise.all([
    loadGrid(variable, layerIndex, timeIndex),
    loadVectorPair(variable, layerIndex, timeIndex),
  ]);
  if (token !== state.loadToken) return;
  state.field = field;
  [state.windU, state.windV, state.windMeta, state.windPairLabel] = vector;

  updateStatus();
  updateTimeline();
  drawLegend();
  renderField();
  resetParticles();
  controls.loading.classList.add("hidden");
}

function drawLegend() {
  const ctx = controls.legend.getContext("2d");
  const width = controls.legend.width;
  const height = controls.legend.height;
  const img = ctx.createImageData(width, height);
  const { min, max } = colorRange(state.colorMeta);
  for (let x = 0; x < width; x += 1) {
    const value = legendValueAt(x / (width - 1), state.colorMeta);
    const color = colorFor(value, state.colorMeta, 255);
    for (let y = 0; y < height; y += 1) {
      const idx = (y * width + x) * 4;
      img.data[idx] = color[0];
      img.data[idx + 1] = color[1];
      img.data[idx + 2] = color[2];
      img.data[idx + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  controls.legendName.textContent = state.variable.label;
  controls.legendMin.textContent = formatValue(min, state.colorMeta);
  controls.legendMax.textContent = formatValue(max, state.colorMeta);
}

function drawSphereBase() {
  fieldCtx.fillStyle = "#020303";
  fieldCtx.fillRect(0, 0, state.width, state.height);
  if (state.projection === "globe") {
    const r = sphereRadius();
    const gradient = fieldCtx.createRadialGradient(
      state.width * 0.42,
      state.height * 0.38,
      r * 0.1,
      state.width / 2,
      state.height / 2,
      r,
    );
    gradient.addColorStop(0, "#111b1c");
    gradient.addColorStop(0.68, "#060909");
    gradient.addColorStop(1, "#010202");
    fieldCtx.beginPath();
    fieldCtx.arc(state.width / 2, state.height / 2, r, 0, Math.PI * 2);
    fieldCtx.fillStyle = gradient;
    fieldCtx.fill();
  } else {
    fieldCtx.fillStyle = "#050707";
    fieldCtx.fillRect(0, 0, state.width, state.height);
  }
}

function renderField() {
  if (!state.field || !state.variable || !state.width || !state.height) return;
  drawSphereBase();

  const scale = state.projection === "globe" ? 2 : 3;
  const w = Math.max(1, Math.floor(state.width / scale));
  const h = Math.max(1, Math.floor(state.height / scale));
  const scratch = document.createElement("canvas");
  scratch.width = w;
  scratch.height = h;
  const ctx = scratch.getContext("2d");
  const img = ctx.createImageData(w, h);
  const alpha = Math.round(255 * state.opacity);

  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      const [lon, lat, ok] = invert((x + 0.5) * scale, (y + 0.5) * scale);
      const idx = (y * w + x) * 4;
      if (!ok) {
        img.data[idx + 3] = 0;
        continue;
      }
      const value = sampleGrid(state.field, lon, lat);
      const color = colorFor(value, state.colorMeta, alpha);
      img.data[idx] = color[0];
      img.data[idx + 1] = color[1];
      img.data[idx + 2] = color[2];
      img.data[idx + 3] = color[3];
    }
  }

  ctx.putImageData(img, 0, 0);
  if (state.projection === "globe") {
    fieldCtx.save();
    fieldCtx.beginPath();
    fieldCtx.arc(state.width / 2, state.height / 2, sphereRadius(), 0, Math.PI * 2);
    fieldCtx.clip();
    fieldCtx.drawImage(scratch, 0, 0, state.width, state.height);
    fieldCtx.restore();
  } else {
    fieldCtx.drawImage(scratch, 0, 0, state.width, state.height);
  }

  drawGraticule();
  drawLand();
  drawReadout();
}

function strokeProjectedLine(points, strokeStyle, lineWidth) {
  fieldCtx.beginPath();
  let drawing = false;
  for (const [lon, lat] of points) {
    const [x, y, visible] = project(lon, lat);
    if (!visible) {
      drawing = false;
      continue;
    }
    if (!drawing) {
      fieldCtx.moveTo(x, y);
      drawing = true;
    } else {
      fieldCtx.lineTo(x, y);
    }
  }
  fieldCtx.strokeStyle = strokeStyle;
  fieldCtx.lineWidth = lineWidth;
  fieldCtx.stroke();
}

function drawGraticule() {
  fieldCtx.save();
  fieldCtx.globalAlpha = 0.46;
  for (let lat = -60; lat <= 60; lat += 30) {
    const points = [];
    for (let lon = -180; lon <= 180; lon += 2) points.push([lon, lat]);
    strokeProjectedLine(points, "rgba(241,239,226,0.16)", state.dpr);
  }
  for (let lon = -180; lon < 180; lon += 30) {
    const points = [];
    for (let lat = -88; lat <= 88; lat += 2) points.push([lon, lat]);
    strokeProjectedLine(points, "rgba(241,239,226,0.12)", state.dpr);
  }
  if (state.projection === "globe") {
    fieldCtx.beginPath();
    fieldCtx.arc(state.width / 2, state.height / 2, sphereRadius(), 0, Math.PI * 2);
    fieldCtx.strokeStyle = "rgba(241,239,226,0.32)";
    fieldCtx.lineWidth = state.dpr;
    fieldCtx.stroke();
  }
  fieldCtx.restore();
}

function decodeArc(topology, arcIndex) {
  const reverse = arcIndex < 0;
  const arc = topology.arcs[reverse ? ~arcIndex : arcIndex];
  const scale = topology.transform.scale;
  const translate = topology.transform.translate;
  let x = 0;
  let y = 0;
  const points = arc.map((point) => {
    x += point[0];
    y += point[1];
    return [x * scale[0] + translate[0], y * scale[1] + translate[1]];
  });
  return reverse ? points.reverse() : points;
}

function geometryRings(topology, geometry) {
  if (!geometry) return [];
  if (geometry.type === "Polygon") return geometry.arcs;
  if (geometry.type === "MultiPolygon") return geometry.arcs.flat();
  if (geometry.type === "GeometryCollection") return geometry.geometries.flatMap((item) => geometryRings(topology, item));
  return [];
}

function drawLand() {
  if (!state.land) return;
  const topology = state.land;
  const landObject = topology.objects.land || Object.values(topology.objects)[0];
  const geometries = landObject.type === "GeometryCollection" ? landObject.geometries : [landObject];
  fieldCtx.save();
  fieldCtx.strokeStyle = "rgba(245,240,218,0.46)";
  fieldCtx.lineWidth = state.dpr * 0.7;
  fieldCtx.fillStyle = "rgba(0,0,0,0.12)";
  for (const geometry of geometries) {
    for (const ring of geometryRings(topology, geometry)) {
      const points = ring.flatMap((arcIndex) => decodeArc(topology, arcIndex));
      fieldCtx.beginPath();
      let started = false;
      for (const point of points) {
        const [x, y, visible] = project(point[0], point[1]);
        if (!visible) {
          started = false;
          continue;
        }
        if (!started) {
          fieldCtx.moveTo(x, y);
          started = true;
        } else {
          fieldCtx.lineTo(x, y);
        }
      }
      if (started) fieldCtx.stroke();
    }
  }
  fieldCtx.restore();
}

function drawReadout() {
  if (!state.variable) return;
  const time = state.manifest.times[state.timeIndex];
  const layerText = state.layer && state.layer.label !== "surface" ? `\n${state.layer.label}` : "";
  const windText = state.windEnabled && state.windPairLabel && state.windU && state.windV ? `\nvector: ${state.windPairLabel}` : "";
  let pointer = "";
  if (state.mouse) {
    const [lon, lat, ok] = invert(state.mouse.x, state.mouse.y);
    if (ok) {
      const value = sampleGrid(state.field, lon, lat);
      pointer = `\n${lat.toFixed(2)}, ${lon.toFixed(2)}  ${formatValue(value, state.colorMeta)}`;
    }
  }
  controls.readout.textContent = `${state.variable.label}${layerText}\n${formatWeek(time)}${windText}${pointer}`;
}

function randomParticle() {
  return {
    lon: Math.random() * 360 - 180,
    lat: Math.asin(Math.random() * 2 - 1) * (180 / Math.PI),
    age: Math.floor(Math.random() * windVisuals.particleLifetime),
  };
}

function resetParticles() {
  const count = clamp(
    Math.floor((state.width * state.height) / windVisuals.particleDensity),
    windVisuals.particleMin,
    windVisuals.particleMax,
  );
  state.particles = Array.from({ length: count }, randomParticle);
  particleCtx.clearRect(0, 0, state.width, state.height);
}

function drawParticles() {
  requestAnimationFrame(drawParticles);
  if (!state.windEnabled || !state.windU || !state.windV || !state.width) return;
  particleCtx.save();
  particleCtx.globalCompositeOperation = "destination-in";
  particleCtx.fillStyle = `rgba(0,0,0,${windVisuals.fadeAlpha})`;
  particleCtx.fillRect(0, 0, state.width, state.height);
  particleCtx.restore();

  particleCtx.save();
  particleCtx.lineWidth = state.dpr * windVisuals.lineWidth;
  particleCtx.strokeStyle = `rgba(235,224,190,${windVisuals.strokeAlpha})`;
  particleCtx.beginPath();

  for (const p of state.particles) {
    if (p.age++ > windVisuals.particleLifetime) {
      Object.assign(p, randomParticle());
      continue;
    }

    let lon = p.lon;
    let lat = p.lat;
    let ok = true;

    for (let step = 0; step < windVisuals.segmentSteps; step += 1) {
      const u = sampleGrid(state.windU, lon, lat, state.windMeta || state.variable);
      const v = sampleGrid(state.windV, lon, lat, state.windMeta || state.variable);
      if (!Number.isFinite(u) || !Number.isFinite(v)) {
        ok = false;
        break;
      }
      const [x0, y0, ok0] = project(lon, lat);
      const cosLat = Math.max(0.16, Math.cos((lat * Math.PI) / 180));
      lon = ((((lon + (u * windVisuals.speedScale) / cosLat + 540) % 360) + 360) % 360) - 180;
      lat = clamp(lat + v * windVisuals.speedScale, -88, 88);
      const [x1, y1, ok1] = project(lon, lat);
      if (ok0 && ok1 && Math.abs(x1 - x0) < state.width * 0.35) {
        particleCtx.moveTo(x0, y0);
        particleCtx.lineTo(x1, y1);
      }
    }

    if (!ok) {
      Object.assign(p, randomParticle());
      continue;
    }

    p.lon = lon;
    p.lat = lat;
  }
  particleCtx.stroke();
  particleCtx.restore();
}

function stepTime(delta) {
  const count = state.manifest.times.length;
  const next = (state.timeIndex + delta + count) % count;
  setField(state.variable.id, next, state.layerIndex);
}

function updateStatus() {
  const time = state.manifest.times[state.timeIndex];
  const layerLabel = state.layer?.label || "surface";
  controls.weekPill.textContent = `W${time.week || time.index + 1}`;
  controls.fieldName.textContent = state.variable.label;
  controls.levelSummary.textContent = layerLabel;
  controls.weekWindow.textContent = formatWeek(time);
  controls.windBadge.textContent = state.windEnabled && state.windPairLabel && state.windU && state.windV ? state.windPairLabel : "off";
  controls.variableMeta.textContent = state.variable.domain === "upper" ? "upper air / pressure" : "surface field";
}

function updateTimeline() {
  const buttons = controls.timelineRail.querySelectorAll(".timeline-mark");
  buttons.forEach((button, index) => {
    button.classList.toggle("active", index === state.timeIndex);
  });
}

function renderTimeline() {
  controls.timelineRail.replaceChildren();
  const times = state.manifest.times;
  controls.timelineRail.style.gridTemplateColumns = `repeat(${times.length}, minmax(0, 1fr))`;
  for (const time of times) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "timeline-mark";
    button.dataset.timeIndex = String(time.index);
    const strong = document.createElement("strong");
    strong.textContent = `W${time.week || time.index + 1}`;
    const span = document.createElement("span");
    span.textContent = time.start && time.end ? `${time.start.slice(5)} - ${time.end.slice(5)}` : time.label;
    button.append(strong, span);
    button.addEventListener("click", () => setField(state.variable.id, Number(button.dataset.timeIndex), state.layerIndex));
    controls.timelineRail.appendChild(button);
  }
}

function bindEvents() {
  window.addEventListener("resize", resize);
  fieldCanvas.addEventListener("pointerdown", (event) => {
    state.dragging = true;
    state.dragStart = {
      x: event.clientX,
      y: event.clientY,
      lon0: state.lon0,
      lat0: state.lat0,
    };
    fieldCanvas.setPointerCapture(event.pointerId);
  });
  fieldCanvas.addEventListener("pointermove", (event) => {
    state.mouse = { x: event.clientX * state.dpr, y: event.clientY * state.dpr };
    if (state.dragging && state.dragStart) {
      const dx = event.clientX - state.dragStart.x;
      const dy = event.clientY - state.dragStart.y;
      state.lon0 = ((((state.dragStart.lon0 - dx * 0.35 + 540) % 360) + 360) % 360) - 180;
      state.lat0 = clamp(state.dragStart.lat0 + dy * 0.25, -80, 80);
      renderField();
      resetParticles();
    } else {
      drawReadout();
    }
  });
  fieldCanvas.addEventListener("pointerup", (event) => {
    state.dragging = false;
    fieldCanvas.releasePointerCapture(event.pointerId);
  });
  fieldCanvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    state.zoom = clamp(state.zoom * (event.deltaY > 0 ? 0.92 : 1.08), 0.72, 1.85);
    renderField();
    resetParticles();
  }, { passive: false });

  controls.variable.addEventListener("change", () => setField(controls.variable.value, state.timeIndex, 0));
  controls.layer.addEventListener("change", () => setField(state.variable.id, state.timeIndex, Number(controls.layer.value)));
  controls.time.addEventListener("input", () => setField(state.variable.id, Number(controls.time.value), state.layerIndex));
  controls.back.addEventListener("click", () => stepTime(-1));
  controls.forward.addEventListener("click", () => stepTime(1));
  controls.play.addEventListener("click", () => {
    state.playing = !state.playing;
    controls.play.textContent = state.playing ? "pause" : "play";
  });
  controls.projection.addEventListener("click", () => {
    state.projection = state.projection === "globe" ? "plate" : "globe";
    controls.projection.textContent = state.projection;
    renderField();
    resetParticles();
  });
  controls.wind.addEventListener("click", () => {
    state.windEnabled = !state.windEnabled;
    controls.wind.textContent = state.windEnabled ? "wind on" : "wind off";
    if (!state.windEnabled) particleCtx.clearRect(0, 0, state.width, state.height);
    updateStatus();
  });
  controls.opacity.addEventListener("input", () => {
    state.opacity = Number(controls.opacity.value) / 100;
    renderField();
  });
  controls.assistantSubmit.addEventListener("click", () => runAssistantQuestion());
  controls.assistantInput.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      runAssistantQuestion();
    }
  });
  setInterval(() => {
    if (state.playing && state.variable) stepTime(1);
  }, 1800);
}

async function loadLand() {
  try {
    const res = await fetch("data/land-110m.json");
    if (res.ok) state.land = await res.json();
  } catch {
    state.land = null;
  }
}

function renderLayerOptions(variable, selectedIndex) {
  const layers = variable.layers || [{ index: 0, label: "surface" }];
  controls.layer.replaceChildren();
  for (const layer of layers) {
    const option = document.createElement("option");
    option.value = String(layer.index);
    option.textContent = layer.label;
    controls.layer.appendChild(option);
  }
  controls.layer.value = String(selectedIndex);
  controls.layerControl.classList.toggle("hidden", layers.length <= 1);
}

function renderVariableOptions() {
  controls.variable.replaceChildren();
  const groups = [
    ["surface", "Surface"],
    ["upper", "Upper air"],
  ];
  for (const [domain, label] of groups) {
    const variables = state.manifest.variables.filter((variable) => (variable.domain || "surface") === domain);
    if (!variables.length) continue;
    const group = document.createElement("optgroup");
    group.label = label;
    for (const variable of variables) {
      const option = document.createElement("option");
      option.value = variable.id;
      option.textContent = variable.label;
      group.appendChild(option);
    }
    controls.variable.appendChild(group);
  }
}

async function init() {
  bindEvents();
  resize();
  resetAssistantView();
  controls.assistantSummary.textContent = "Ready to analyze forecast questions.";
  controls.assistantOutput.textContent = "Ask a question such as: Will Europe see extreme heat over the next 3 weeks?";
  const [manifest] = await Promise.all([
    fetch("data/manifest.json").then((res) => res.json()),
    loadLand(),
  ]);
  state.manifest = manifest;
  controls.datasetTitle.textContent = `${manifest.source} / ${manifest.dimensions.latitude}x${manifest.dimensions.longitude}`;
  renderVariableOptions();
  renderTimeline();
  controls.time.max = String(manifest.times.length - 1);
  const defaultVariable = variableById("10m_u_component_of_wind") || manifest.variables[0];
  await setField(defaultVariable.id, 0);
  drawParticles();
}

init().catch((error) => {
  console.error(error);
  controls.loading.textContent = error.message;
});
