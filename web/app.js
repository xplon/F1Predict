const state = {
  events: [],
  report: null,
  packet: null,
  predictionExplanation: null,
  predictionExplanationLoading: false,
  predictionExplanationError: null,
  impactTraceSidecar: null,
  researchPlan: null,
  sourceCandidates: null,
  researchPreflight: null,
  chronological: null,
  analysis: null,
  mvpGate: null,
  season: null,
  officialStandings: null,
  readiness: null,
  intake: null,
  marketReadiness: null,
  sourceReadiness: null,
  improvement: null,
  calibration: null,
  modelErrorReview: null,
  postEventReview: null,
  simulatorCalibration: null,
  freeze: null,
  predictionLoading: false,
  predictionError: null,
  replayLap: null,
  replayPlaying: false,
  replayTimer: null,
  diagnosticsLoaded: false,
  diagnosticsLoading: false,
  diagnosticsSlowPanels: []
};

let predictionRequestSeq = 0;
const DIAGNOSTIC_PANEL_TIMEOUT_MS = 12000;

const driverNames = {
  antonelli: "Antonelli",
  russell: "Russell",
  hamilton: "Hamilton",
  leclerc: "Leclerc",
  piastri: "Piastri",
  norris: "Norris",
  verstappen: "Verstappen",
  hadjar: "Hadjar",
  alonso: "Alonso",
  stroll: "Stroll",
  albon: "Albon",
  sainz: "Sainz",
  gasly: "Gasly",
  colapinto: "Colapinto",
  ocon: "Ocon",
  bearman: "Bearman",
  hulkenberg: "Hulkenberg",
  bortoleto: "Bortoleto",
  lawson: "Lawson",
  lindblad: "Lindblad",
  bottas: "Bottas",
  perez: "Perez"
};

const teamNames = {
  mercedes: "Mercedes",
  ferrari: "Ferrari",
  mclaren: "McLaren",
  red_bull: "Red Bull",
  aston_martin: "Aston Martin",
  williams: "Williams",
  alpine: "Alpine",
  haas: "Haas",
  audi: "Audi",
  racing_bulls: "Racing Bulls",
  cadillac: "Cadillac"
};

const colors = {
  antonelli: "#45c4b0",
  russell: "#7ddc88",
  hamilton: "#f44f63",
  leclerc: "#ff7a7a",
  piastri: "#f4b860",
  norris: "#ffd166",
  verstappen: "#74a7ff",
  hadjar: "#a89bff",
  alonso: "#4dd0e1",
  stroll: "#80cbc4",
  albon: "#81d4fa",
  sainz: "#90caf9",
  gasly: "#ce93d8",
  colapinto: "#7bbcff",
  ocon: "#ffab91",
  bearman: "#ffcc80",
  hulkenberg: "#c5e1a5",
  bortoleto: "#aed581",
  lawson: "#bcaaa4",
  lindblad: "#9aa8ff",
  bottas: "#b7b7c9",
  perez: "#d3c4b2"
};

const trackImageCache = new Map();

const technicalMetrics = new Set([
  "power_unit",
  "energy_recovery",
  "straight_line_speed",
  "drag_efficiency",
  "low_speed_traction",
  "launch_performance",
  "weight",
  "upgrade_effect",
  "tyre_deg",
  "reliability",
  "strategy",
  "wet_skill"
]);

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

async function postJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;"
  }[char]));
}

async function init() {
  state.events = await getJson("/api/events");
  const select = document.getElementById("eventSelect");
  select.innerHTML = state.events
    .map(event => `<option value="${event.event_id}">${event.round_number}. ${event.name}</option>`)
    .join("");
  select.value = "british_gp";
  document.getElementById("refreshButton").addEventListener("click", refreshAll);
  document.getElementById("loadDiagnosticsButton").addEventListener("click", toggleDiagnostics);
  document.getElementById("predictionExplanationButton").addEventListener("click", askPredictionExplanation);
  document.querySelectorAll("[data-question]").forEach(button => {
    button.addEventListener("click", () => {
      document.getElementById("predictionExplanationQuestion").value = button.dataset.question || "";
      askPredictionExplanation();
    });
  });
  select.addEventListener("change", loadPrediction);
  document.getElementById("replayPlayButton").addEventListener("click", toggleReplayPlayback);
  document.getElementById("replayLapSlider").addEventListener("input", event => {
    setReplayLap(Number(event.target.value));
  });
  await loadPrediction();
}

async function refreshAll() {
  await loadPrediction();
  if (diagnosticsVisible()) {
    await loadDashboardPanels();
  }
}

async function loadDashboardPanels() {
  state.diagnosticsLoading = true;
  state.diagnosticsSlowPanels = [];
  renderDiagnosticsButton();
  const results = await Promise.all([
    ["season", loadSeasonForecast],
    ["officialStandings", loadOfficialStandings],
    ["chronologicalReplay", loadChronologicalReplay],
    ["replayAnalysis", loadReplayAnalysis],
    ["mvpGate", loadMvpGate],
    ["formalReadiness", loadFormalReadiness],
    ["readinessIntake", loadReadinessIntake],
    ["marketReadiness", loadMarketReadiness],
    ["sourceReadiness", loadSourceReadiness],
    ["improvementPlan", loadImprovementPlan],
    ["calibration", loadCalibrationReport],
    ["modelErrorReview", loadModelErrorReview],
    ["postEventReview", loadPostEventReview],
    ["simulatorCalibration", loadSimulatorCalibration],
    ["replayFreeze", loadReplayFreeze]
  ].map(([label, loader]) => loadDiagnosticPanel(label, loader)));
  state.diagnosticsSlowPanels = results
    .filter(result => result.status === "timeout")
    .map(result => result.label);
  state.diagnosticsSlowPanels.forEach(markDiagnosticPanelTimeout);
  state.diagnosticsLoaded = true;
  state.diagnosticsLoading = false;
  renderDiagnosticsButton();
}

function loadDiagnosticPanel(label, loader) {
  let timeoutId = null;
  const task = Promise.resolve()
    .then(loader)
    .then(
      () => ({ label, status: "loaded" }),
      () => ({ label, status: "failed" })
    );
  const timeout = new Promise(resolve => {
    timeoutId = window.setTimeout(
      () => resolve({ label, status: "timeout" }),
      DIAGNOSTIC_PANEL_TIMEOUT_MS
    );
  });
  return Promise.race([task, timeout]).finally(() => {
    if (timeoutId !== null) {
      window.clearTimeout(timeoutId);
    }
  });
}

function markDiagnosticPanelTimeout(label) {
  const statusIdByLabel = {
    season: "seasonStatus",
    officialStandings: "officialStatus",
    chronologicalReplay: "chronologicalStatus",
    replayAnalysis: "analysisStatus",
    mvpGate: "mvpGateStatus",
    formalReadiness: "readinessStatus",
    readinessIntake: "intakeStatus",
    marketReadiness: "marketReadinessStatus",
    sourceReadiness: "sourceReadinessStatus",
    improvementPlan: "improvementStatus",
    calibration: "calibrationStatus",
    modelErrorReview: "modelErrorStatus",
    postEventReview: "postEventReviewStatus",
    simulatorCalibration: "simulatorCalibrationStatus",
    replayFreeze: "freezeStatus"
  };
  const element = document.getElementById(statusIdByLabel[label]);
  if (element) {
    element.textContent = "后台加载中";
  }
}

function diagnosticsVisible() {
  return document.body.classList.contains("show-diagnostics");
}

async function toggleDiagnostics() {
  document.body.classList.toggle("show-diagnostics");
  renderDiagnosticsButton();
  if (diagnosticsVisible() && !state.diagnosticsLoaded && !state.diagnosticsLoading) {
    await loadPredictionDiagnostics();
    await loadDashboardPanels();
  }
}

function renderDiagnosticsButton() {
  const button = document.getElementById("loadDiagnosticsButton");
  if (!button) {
    return;
  }
  button.classList.toggle("active", diagnosticsVisible());
  if (state.diagnosticsLoading) {
    button.textContent = "诊断加载中";
  } else if (diagnosticsVisible() && state.diagnosticsSlowPanels.length) {
    button.textContent = "诊断面板已展开";
  } else if (diagnosticsVisible()) {
    button.textContent = "隐藏诊断面板";
  } else {
    button.textContent = "加载诊断面板";
  }
}

async function loadPrediction() {
  stopReplayPlayback();
  const eventId = document.getElementById("eventSelect").value;
  const encoded = encodeURIComponent(eventId);
  const requestSeq = (predictionRequestSeq += 1);
  state.predictionLoading = true;
  state.predictionError = null;
  state.report = null;
  state.packet = null;
  state.predictionExplanation = null;
  state.predictionExplanationLoading = false;
  state.predictionExplanationError = null;
  state.impactTraceSidecar = null;
  state.researchPlan = null;
  state.sourceCandidates = null;
  state.researchPreflight = null;
  resetReplayLap([]);
  renderPredictionPending(eventId);
  try {
    let packet = null;
    let report = null;
    try {
      packet = await getJson(`/api/v2/prediction-packets/latest?event_id=${encoded}`);
      report = normalizePredictionReport(packet.prediction);
    } catch {
      report = normalizePredictionReport(await getJson(`/api/prediction?event_id=${encoded}`));
    }
    if (requestSeq !== predictionRequestSeq) {
      return;
    }
    state.packet = packet;
    state.report = report;
    state.predictionLoading = false;
    resetReplayLap(predictionReplayRows(report));
    render();
    loadPredictionAuxiliaryPanels(encoded, requestSeq, Boolean(packet));
  } catch (error) {
    if (requestSeq !== predictionRequestSeq) {
      return;
    }
    state.predictionLoading = false;
    state.predictionError = error;
    renderPredictionPending(eventId);
  }
}

function loadPredictionAuxiliaryPanels(encodedEventId, requestSeq, packetLoadedFromCache = false) {
  const requests = [
    ["impactTraceSidecar", `/api/v2/prediction-impact-traces/latest?event_id=${encodedEventId}&limit=24`]
  ];
  if (diagnosticsVisible()) {
    requests.push(
      ["researchPlan", `/api/codex-research-plan?event_id=${encodedEventId}`],
      ["sourceCandidates", `/api/source-candidates?event_id=${encodedEventId}`],
      ["researchPreflight", `/api/research-preflight?event_id=${encodedEventId}`]
    );
  }
  if (!packetLoadedFromCache) {
    requests.unshift([
      "packet",
      `/api/prediction-packet?event_id=${encodedEventId}&iterations=1200&isolated_impact_limit=12`
    ]);
  }
  requests.forEach(([stateKey, url]) => {
    getJson(url)
      .then(payload => {
        if (requestSeq !== predictionRequestSeq) {
          return;
        }
        state[stateKey] = payload;
        render();
      })
      .catch(() => {
        if (requestSeq !== predictionRequestSeq) {
          return;
        }
        state[stateKey] = null;
        render();
      });
  });
}

async function loadPredictionDiagnostics() {
  const eventId = document.getElementById("eventSelect").value;
  const encoded = encodeURIComponent(eventId);
  const requestSeq = predictionRequestSeq;
  await Promise.allSettled([
    ["researchPlan", `/api/codex-research-plan?event_id=${encoded}`],
    ["sourceCandidates", `/api/source-candidates?event_id=${encoded}`],
    ["researchPreflight", `/api/research-preflight?event_id=${encoded}`]
  ].map(([stateKey, url]) => (
    getJson(url).then(payload => {
      if (requestSeq === predictionRequestSeq) {
        state[stateKey] = payload;
      }
    }).catch(() => {
      if (requestSeq === predictionRequestSeq) {
        state[stateKey] = null;
      }
    })
  )));
  render();
}

async function loadReplayAnalysis() {
  state.analysis = await getJson("/api/replay-analysis");
  renderReplayAnalysis();
}

async function loadMvpGate() {
  state.mvpGate = await getJson("/api/mvp-gate");
  renderMvpGate();
}

async function loadChronologicalReplay() {
  state.chronological = await getJson("/api/chronological-replay");
  renderChronologicalReplay();
}

async function loadSeasonForecast() {
  state.season = await getJson("/api/season-forecast?iterations=1200");
  renderSeasonForecast();
}

async function loadOfficialStandings() {
  state.officialStandings = await getJson("/api/official-standings");
  renderOfficialStandings();
}

async function loadFormalReadiness() {
  state.readiness = await getJson("/api/formal-readiness?iterations=800");
  renderFormalReadiness();
}

async function loadReadinessIntake() {
  state.intake = await getJson("/api/readiness-intake?limit=8");
  renderReadinessIntake();
}

async function loadMarketReadiness() {
  state.marketReadiness = await getJson("/api/market-readiness");
  renderMarketReadiness();
}

async function loadSourceReadiness() {
  state.sourceReadiness = await getJson("/api/source-readiness");
  renderSourceReadiness();
}

async function loadImprovementPlan() {
  state.improvement = await getJson("/api/improvement-plan");
  renderImprovementPlan();
}

async function loadCalibrationReport() {
  state.calibration = await getJson("/api/calibration-report?iterations=800");
  renderCalibrationReport();
}

async function loadModelErrorReview() {
  state.modelErrorReview = await getJson("/api/model-error-review?iterations=800");
  renderModelErrorReview();
}

async function loadPostEventReview() {
  const eventId = document.getElementById("eventSelect").value || "british_gp";
  try {
    state.postEventReview = await getJson(`/api/post-event-review?event_id=${encodeURIComponent(eventId)}`);
  } catch (error) {
    state.postEventReview = {
      event_id: eventId,
      status: "unavailable",
      error: String(error?.message || error)
    };
  }
  renderPostEventReview();
}

async function loadSimulatorCalibration() {
  state.simulatorCalibration = await getJson("/api/simulator-calibration?iterations=800");
  renderSimulatorCalibration();
}

async function loadReplayFreeze() {
  state.freeze = await getJson("/api/replay-freeze-manifest?iterations=1200");
  renderReplayFreeze();
}

function replayRows() {
  return predictionReplayRows(state.report);
}

function predictionReplayRows(report) {
  if (!report) {
    return [];
  }
  const rows = replayPayloadRows(report.simulation_replay) || replayPayloadRows(report.representative_lap) || [];
  return normalizeReplayRows(rows);
}

function normalizePredictionReport(payload) {
  const report = payload?.prediction?.event && (payload.prediction.simulation_replay || payload.prediction.representative_lap)
    ? payload.prediction
    : payload;
  if (report && Array.isArray(report.race_probabilities)) {
    return {
      ...report,
      race_probabilities: normalizeRaceProbabilities(report.race_probabilities)
    };
  }
  return report;
}

function normalizeRaceProbabilities(rows) {
  return rows
    .filter(row => row && row.driver_id)
    .map(row => ({ ...row }))
    .sort((a, b) => {
      const finishDelta = finiteNumber(a.average_finish, 999) - finiteNumber(b.average_finish, 999);
      if (finishDelta) return finishDelta;
      const pointDelta = finiteNumber(b.expected_points, 0) - finiteNumber(a.expected_points, 0);
      if (pointDelta) return pointDelta;
      const podiumDelta = finiteNumber(b.podium, 0) - finiteNumber(a.podium, 0);
      if (podiumDelta) return podiumDelta;
      const winDelta = finiteNumber(b.win, 0) - finiteNumber(a.win, 0);
      if (winDelta) return winDelta;
      return String(a.driver_id).localeCompare(String(b.driver_id));
    })
    .map((row, index) => ({
      ...row,
      expected_rank: index + 1
    }));
}

function nonEmptyArray(value) {
  return Array.isArray(value) && value.length ? value : null;
}

function replayPayloadRows(value) {
  return nonEmptyArray(value) || nonEmptyArray(value?.rows);
}

function normalizeReplayRows(rows) {
  if (!Array.isArray(rows) || !rows.length) {
    return [];
  }
  const normalized = rows
    .map((row, index) => ({
      ...row,
      _sourceIndex: index,
      lap: finiteNumber(row.lap),
      position: finiteNumber(row.position),
      grid_position: finiteNumber(row.grid_position),
      gap_to_leader: finiteNumber(row.gap_to_leader),
      cumulative_time: finiteNumber(row.cumulative_time),
      lap_time: finiteNumber(row.lap_time),
      tyre_age: finiteNumber(row.tyre_age)
    }))
    .filter(row => row.lap != null);
  const byLap = new Map();
  normalized.forEach(row => {
    const key = String(row.lap);
    const group = byLap.get(key) || [];
    group.push(row);
    byLap.set(key, group);
  });

  const firstLap = Math.min(...normalized.map(row => row.lap));
  const gridByDriver = new Map(
    [...(byLap.get(String(firstLap)) || [])]
      .sort((a, b) => replayRankKey(a) - replayRankKey(b))
      .map((row, index) => [row.driver_id, row.grid_position || index + 1])
  );

  byLap.forEach(group => {
    const ranked = [...group].sort((a, b) => {
      const rankDelta = replayRankKey(a) - replayRankKey(b);
      return rankDelta || a._sourceIndex - b._sourceIndex;
    });
    const leader = ranked[0] || {};
    ranked.forEach((row, index) => {
      if (row.position == null) {
        row.position = index + 1;
      }
      if (row.grid_position == null) {
        if (!gridByDriver.has(row.driver_id)) {
          gridByDriver.set(row.driver_id, gridByDriver.size + 1);
        }
        row.grid_position = gridByDriver.get(row.driver_id);
      }
      if (row.gap_to_leader == null && !row.dnf) {
        row.gap_to_leader = replayGapFromLeader(row, leader);
      }
    });
  });

  return normalized
    .sort((a, b) => a._sourceIndex - b._sourceIndex)
    .map(({ _sourceIndex, ...row }) => row);
}

function finiteNumber(value, fallback = null) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function replayRankKey(row) {
  if (row.position != null) {
    return row.position;
  }
  if (row.dnf) {
    return 1000 + (row.grid_position || row._sourceIndex || 0);
  }
  if (row.cumulative_time != null) {
    return row.cumulative_time;
  }
  if (row.gap_to_leader != null) {
    return row.gap_to_leader;
  }
  if (row.lap_time != null) {
    return row.lap_time;
  }
  if (row.grid_position != null) {
    return row.grid_position;
  }
  return 10000 + (row._sourceIndex || 0);
}

function replayGapFromLeader(row, leader) {
  if (row.cumulative_time != null && leader.cumulative_time != null) {
    return Math.max(0, row.cumulative_time - leader.cumulative_time);
  }
  if (row.lap_time != null && leader.lap_time != null) {
    return Math.max(0, row.lap_time - leader.lap_time);
  }
  return null;
}

function replayLapBounds(rows) {
  const laps = rows
    .map(row => Number(row.lap))
    .filter(lap => Number.isFinite(lap));
  if (!laps.length) {
    return null;
  }
  return {
    min: Math.min(...laps),
    max: Math.max(...laps)
  };
}

function replaySourceCounts(report = state.report) {
  return {
    simulation: (replayPayloadRows(report?.simulation_replay) || []).length,
    representative: (replayPayloadRows(report?.representative_lap) || []).length
  };
}

function replayUnavailableLines(report = state.report) {
  const selectedEvent = document.getElementById("eventSelect")?.value || "unknown";
  const eventId = report?.event?.event_id || selectedEvent;
  if (state.predictionLoading) {
    return [`event ${eventId}`, "prediction is still loading"];
  }
  if (state.predictionError) {
    const message = String(state.predictionError?.message || state.predictionError || "unknown error");
    return [`event ${eventId}`, `prediction API error: ${message.slice(0, 140)}`];
  }
  if (!report) {
    return [`event ${eventId}`, "no prediction report loaded"];
  }
  const counts = replaySourceCounts(report);
  return [
    `event ${eventId}`,
    `simulation_replay rows=${counts.simulation}; representative_lap rows=${counts.representative}`
  ];
}

function resetReplayLap(rows) {
  const bounds = replayLapBounds(rows);
  state.replayLap = bounds ? bounds.min : null;
}

function setReplayLap(value) {
  const rows = replayRows();
  const bounds = replayLapBounds(rows);
  if (!bounds) {
    state.replayLap = null;
    renderReplayControls(rows);
    renderReplayFrame(rows);
    return;
  }
  const lap = Math.min(bounds.max, Math.max(bounds.min, Math.round(Number(value) || bounds.min)));
  state.replayLap = lap;
  renderReplayControls(rows);
  renderReplayFrame(rows);
  drawReplayTrack(state.report.event, rows);
  drawReplayChart(rows);
  if (state.report?.event) {
    drawTrack(state.report.event);
  }
}

function toggleReplayPlayback() {
  if (state.replayPlaying) {
    stopReplayPlayback();
    renderReplayControls(replayRows());
    return;
  }
  const rows = replayRows();
  const bounds = replayLapBounds(rows);
  if (!bounds) {
    return;
  }
  state.replayPlaying = true;
  state.replayTimer = window.setInterval(() => {
    const next = state.replayLap == null || state.replayLap >= bounds.max
      ? bounds.min
      : state.replayLap + 1;
    setReplayLap(next);
  }, 650);
  renderReplayControls(rows);
}

function stopReplayPlayback() {
  if (state.replayTimer) {
    window.clearInterval(state.replayTimer);
    state.replayTimer = null;
  }
  state.replayPlaying = false;
}

function render() {
  const report = state.report;
  if (!report) {
    renderPredictionPending(document.getElementById("eventSelect").value);
    return;
  }
  const replayRows = predictionReplayRows(report);
  document.getElementById("eventTitle").textContent = report.event.name;
  document.getElementById("eventMeta").textContent = `Round ${report.event.round_number} | ${report.event.track_type} | ${report.event.laps} laps`;
  document.getElementById("iterationMeta").textContent = `${report.iterations.toLocaleString()} diagnostic sims | replay ${replayRows.length.toLocaleString()} rows`;
  drawTrack(report.event);
  renderReplayControls(replayRows);
  renderReplayFrame(replayRows);
  drawReplayTrack(report.event, replayRows);
  drawReplayChart(replayRows);
  renderStrategyTrace(replayRows);
  renderProbabilityTable(report.race_probabilities);
  renderCoreDecisionSummary();
  renderPredictionAnomalyAudit();
  renderPredictionExplanation();
  renderEdgeTable(report.market_edges);
  renderPredictionPacket();
  renderAiJudgement(report.ai_judgement);
  renderResearchPlan();
  renderSourceCandidates();
  renderResearchPreflight();
  const traceablePrediction = currentTraceablePrediction(report);
  renderEvidenceImpact(traceablePrediction);
  renderTechnicalFactorTrace(traceablePrediction);
  renderEvidenceQuality(report.evidence_quality || []);
  renderEvidence(report.evidence);
  renderFeatures(report.feature_adjustments || []);
  renderSeasonForecast();
  renderOfficialStandings();
  renderChronologicalReplay();
  renderReplayAnalysis();
  renderMvpGate();
  renderFormalReadiness();
  renderReadinessIntake();
  renderMarketReadiness();
  renderSourceReadiness();
  renderImprovementPlan();
  renderCalibrationReport();
  renderModelErrorReview();
  renderSimulatorCalibration();
  renderReplayFreeze();
}

function currentTraceablePrediction(fallbackReport = state.report) {
  return state.packet?.prediction || fallbackReport || {};
}

async function askPredictionExplanation() {
  const input = document.getElementById("predictionExplanationQuestion");
  const question = String(input?.value || "").trim();
  if (!question) {
    state.predictionExplanationError = new Error("请输入要解释的问题。");
    state.predictionExplanation = null;
    renderPredictionExplanation();
    return;
  }
  const eventId = document.getElementById("eventSelect").value || state.report?.event?.event_id || "british_gp";
  state.predictionExplanationLoading = true;
  state.predictionExplanationError = null;
  renderPredictionExplanation();
  try {
    state.predictionExplanation = await postJson("/api/v2/prediction-explanations", {
      event_id: eventId,
      question,
      max_evidence: 6
    });
  } catch (error) {
    state.predictionExplanation = null;
    state.predictionExplanationError = error;
  } finally {
    state.predictionExplanationLoading = false;
    renderPredictionExplanation();
  }
}

function renderPredictionPending(eventId) {
  const event = state.events.find(item => item.event_id === eventId) || {};
  const isError = Boolean(state.predictionError);
  const title = isError ? "Prediction failed" : "Loading prediction";
  const detail = isError
    ? String(state.predictionError?.message || state.predictionError || "Unknown prediction error")
    : "Running event simulation; replay controls unlock when the selected simulation returns.";

  document.getElementById("eventTitle").textContent = event.name || "Race";
  document.getElementById("eventMeta").textContent = event.round_number
    ? `Round ${event.round_number} | ${event.track_type || "track"} | ${event.laps || "n/a"} laps`
    : "";
  document.getElementById("iterationMeta").textContent = title;
  document.getElementById("probabilityTable").innerHTML = `<p>${escapeHtml(detail)}</p>`;
  document.getElementById("coreDecisionStatus").textContent = title;
  document.getElementById("coreDecisionSummary").innerHTML = `<p>${escapeHtml(detail)}</p>`;
  document.getElementById("predictionAnomalyStatus").textContent = title;
  document.getElementById("predictionAnomalySummary").innerHTML = "";
  document.getElementById("predictionAnomalyList").innerHTML = `<p>${escapeHtml(detail)}</p>`;
  document.getElementById("edgeTable").innerHTML = "";
  document.getElementById("packetSummary").innerHTML = "";
  document.getElementById("aiJudgement").innerHTML = "";
  document.getElementById("researchPlanSummary").innerHTML = "";
  document.getElementById("researchPlanList").innerHTML = "";
  document.getElementById("sourceCandidateStatus").textContent = title;
  document.getElementById("sourceCandidateSummary").innerHTML = "";
  document.getElementById("sourceCandidateList").innerHTML = `<p>${escapeHtml(detail)}</p>`;
  document.getElementById("researchPreflightStatus").textContent = title;
  document.getElementById("researchPreflightSummary").innerHTML = "";
  document.getElementById("researchPreflightList").innerHTML = `<p>${escapeHtml(detail)}</p>`;
  document.getElementById("evidenceImpactList").innerHTML = "";
  document.getElementById("technicalTraceStatus").textContent = title;
  document.getElementById("technicalTraceList").innerHTML = `<p>${escapeHtml(detail)}</p>`;
  document.getElementById("evidenceQualityList").innerHTML = "";
  document.getElementById("evidenceList").innerHTML = "";
  document.getElementById("featureList").innerHTML = "";
  if (event.event_id) {
    drawTrack(event);
  }
  renderReplayPending(title, detail);
}

function renderReplayPending(title, detail) {
  const slider = document.getElementById("replayLapSlider");
  const button = document.getElementById("replayPlayButton");
  slider.disabled = true;
  button.disabled = true;
  button.textContent = "Play";
  document.getElementById("replayLapMeta").textContent = title;
  document.getElementById("replayFrame").innerHTML = `
    <article class="replay-frame-card">
      <span class="pill">${escapeHtml(title)}</span>
      <p>${escapeHtml(detail)}</p>
    </article>
  `;
  document.getElementById("strategyTrace").innerHTML = `<p>${escapeHtml(detail)}</p>`;
  [
    ["replayTrackCanvas", title],
    ["lapCanvas", title]
  ].forEach(([id, canvasTitle]) => {
    const canvas = document.getElementById(id);
    const ctx = canvas.getContext("2d");
    drawCanvasNotice(ctx, canvas.width, canvas.height, canvasTitle, [detail]);
  });
}

function renderCoreDecisionSummary() {
  const report = state.report;
  const packet = state.packet || {};
  const sidecar = state.impactTraceSidecar || {};
  const audit = packet.prediction_anomaly_audit || {};
  const cache = packet.cache_context || {};
  const coverage = sidecar.coverage || {};
  const formalTrace = sidecar.formal_readiness || {};
  const raceRows = Array.isArray(report?.race_probabilities)
    ? report.race_probabilities.slice().sort((a, b) => Number(a.average_finish || 99) - Number(b.average_finish || 99))
    : [];
  const topDrivers = raceRows.slice(0, 5)
    .map((row, index) => `${index + 1}. ${driverNames[row.driver_id] || row.driver_id}`)
    .join(" / ");
  const materialTraces = Array.isArray(sidecar.traces)
    ? sidecar.traces
        .filter(row => ["material_prediction_change", "small_prediction_change"].includes(row.impact_status))
        .sort((a, b) => tracePriority(b) - tracePriority(a))
        .slice(0, 3)
    : [];
  const traceCards = materialTraces.map(trace => {
    const source = (trace.supporting_sources || [])[0] || {};
    const changed = (trace.changed_factors || [])[0] || {};
    const predictionText = firstPredictionChangeText(trace);
    return `
      <article class="core-decision-card important">
        <h3>${escapeHtml(source.publisher || "来源化信息")}: ${escapeHtml(shortHash(source.title || trace.claim_id || trace.impact_trace_id))}</h3>
        <p>${escapeHtml(targetDisplay(changed.target_type, changed.target_id))} 的 ${escapeHtml(factorLabel(changed.factor))}：${escapeHtml(directionLabel(changed.direction))}。</p>
        <p>${escapeHtml(predictionText || trace.interpretation_zh || "同种子影响追踪已生成。")}</p>
        <div class="pill-row">
          <span class="pill">${escapeHtml(impactStatusLabel(trace.impact_status))}</span>
          <span class="pill">${escapeHtml(magnitudeLabel(trace.probability_delta_bucket))}</span>
        </div>
      </article>
    `;
  }).join("");
  const anomalyCards = (audit.anomalies || []).slice(0, 2).map(row => `
    <article class="core-decision-card warning">
      <h3>${escapeHtml(anomalyCodeLabel(row.code))}</h3>
      <p>${escapeHtml(row.summary_zh || row.model_risk_zh || "该预测仍需复核。")}</p>
      <p>${escapeHtml(row.recommended_action_zh || "需要补充来源化信息或复核模型传导。")}</p>
    </article>
  `).join("");
  document.getElementById("coreDecisionStatus").textContent = formalTrace.formal_ready
    ? "正式解释链已缓存，预测仍是诊断级"
    : "解释链未完全就绪";
  document.getElementById("coreDecisionSummary").innerHTML = [
    `
      <article class="core-decision-card ${packet.status === "diagnostic_only" ? "warning" : "important"}">
        <h3>当前预测状态</h3>
        <p>Run：${escapeHtml(shortHash(cache.run_id || sidecar.source_run?.run_id || ""))}；状态：${escapeHtml(packet.status || "未知")}。</p>
        <p>${escapeHtml((packet.blocker_codes || []).join("，") || "没有阻塞项")}。</p>
        <div class="pill-row">
          <span class="pill">${packet.formal_edge_ready ? "可进入正式复核" : "仍是诊断预测"}</span>
          <span class="pill">${escapeHtml((packet.warning_codes || [])[0] || "无警告")}</span>
        </div>
      </article>
    `,
    `
      <article class="core-decision-card important">
        <h3>排名摘要</h3>
        <p>${escapeHtml(topDrivers || "暂无排名。")}</p>
        <p>排序按平均完赛名次展示；完整概率表在上方面板。</p>
      </article>
    `,
    `
      <article class="core-decision-card important">
        <h3>解释链覆盖</h3>
        <p>来源化状态更新：${escapeHtml(coverage.impact_trace_covered_claim_count || 0)} / ${escapeHtml(coverage.impact_trace_claim_count || 0)}。</p>
        <p>${escapeHtml(formalTrace.status_zh || "完整影响追踪缓存尚未生成。")}</p>
        <div class="pill-row">
          <span class="pill">${formalTrace.formal_ready ? "同迭代全覆盖" : "诊断解释"}</span>
          <span class="pill">${escapeHtml(sidecar.trace_generation?.comparison_status || "missing")}</span>
        </div>
      </article>
    `,
    `
      <article class="core-decision-card ${Number(audit.anomaly_count || 0) ? "warning" : "important"}">
        <h3>剩余异常</h3>
        <p>${escapeHtml(audit.summary_zh || "异常审计尚未加载。")}</p>
      </article>
    `,
    traceCards,
    anomalyCards
  ].filter(Boolean).join("");
}

function firstPredictionChangeText(trace) {
  const points = Array.isArray(trace.expected_points_delta) ? trace.expected_points_delta[0] : null;
  if (points?.driver_id) {
    const direction = Number(points.expected_points_delta || 0) >= 0 ? "上升" : "下降";
    return `${driverNames[points.driver_id] || points.driver_id} 的期望积分${direction} ${Math.abs(Number(points.expected_points_delta || 0)).toFixed(3)}。`;
  }
  const ranks = Array.isArray(trace.rank_delta) ? trace.rank_delta.find(row => Number(row.expected_rank_delta || 0) !== 0) : null;
  if (ranks?.driver_id) {
    const delta = Number(ranks.expected_rank_delta || 0);
    return `${driverNames[ranks.driver_id] || ranks.driver_id} 的预测名次变化 ${delta > 0 ? "+" : ""}${delta}。`;
  }
  return "";
}

function renderPredictionPacket() {
  const packet = state.packet;
  if (!packet) {
    return;
  }
  document.getElementById("packetStatus").textContent =
    `${packet.status} | formal ready: ${packet.formal_edge_ready ? "yes" : "no"}`;
  const market = packet.market_context || {};
  const codex = packet.codex_context || {};
  const sidecar = state.impactTraceSidecar || {};
  const sidecarCoverage = sidecar.coverage || {};
  const formalTrace = sidecar.formal_readiness || {};
  const intake = codex.intake || {};
  const cache = packet.cache_context || {};
  const blockers = packet.blocker_codes || [];
  const warnings = packet.warning_codes || [];
  const blockedDevelopment = packet.prediction?.blocked_development_evidence || {};
  const blockerText = blockers.length
    ? blockers.map(code => `<span class="pill">${escapeHtml(code)}</span>`).join("")
    : "<span class=\"pill\">no blockers</span>";
  const warningText = warnings.length
    ? warnings.map(code => `<span class="pill">${escapeHtml(code)}</span>`).join("")
    : "<span class=\"pill\">no warnings</span>";
  document.getElementById("packetSummary").innerHTML = `
    <div class="packet-hash">${escapeHtml(String(packet.packet_payload_sha256 || "").slice(0, 18))}</div>
    <div class="packet-grid">
      <div><span>读取方式</span><strong>${cache.source ? "已注册缓存" : "实时生成"}</strong></div>
      <div><span>Run</span><strong>${escapeHtml(shortHash(cache.run_id))}</strong></div>
      <div><span>BeliefState</span><strong>${escapeHtml(shortHash(codex.belief_state_id))}</strong></div>
      <div><span>状态更新</span><strong>${codex.state_update_count || 0}</strong></div>
      <div><span>影响追踪</span><strong>${codex.prediction_impact_trace_count || 0}</strong></div>
      <div><span>单条重跑</span><strong>${codex.isolated_prediction_impact_count || 0}</strong></div>
      <div><span>完整追踪缓存</span><strong>${sidecar.trace_count ? `${sidecarCoverage.impact_trace_covered_claim_count || 0}/${sidecarCoverage.impact_trace_claim_count || 0}` : "未生成"}</strong></div>
      <div><span>追踪口径</span><strong>${escapeHtml(sidecar.trace_generation?.comparison_status || "missing")}</strong></div>
      <div><span>正式解释</span><strong>${escapeHtml(formalTrace.formal_ready ? "已就绪" : formalTrace.status || "未就绪")}</strong></div>
      <div><span>原始来源</span><strong>${packet.prediction?.belief_state?.raw_sources?.length || 0}</strong></div>
      <div><span>开发 seed 已分离</span><strong>${blockedDevelopment.claim_count || codex.blocked_development_evidence_count || 0}</strong></div>
      <div><span>异常审计</span><strong>${packet.prediction_anomaly_audit?.anomaly_count || 0}</strong></div>
      <div><span>市场快照</span><strong>${market.usable_snapshot_count || 0}</strong></div>
      <div><span>弱证据</span><strong>${codex.weak_evidence_quality_count || 0}</strong></div>
      <div><span>预检</span><strong>${escapeHtml(intake.research_preflight_status || "missing")}</strong></div>
    </div>
    <div class="packet-flags">${blockerText}</div>
    <div class="packet-flags">${warningText}</div>
  `;
}

function renderPredictionAnomalyAudit() {
  const audit = state.packet?.prediction_anomaly_audit || currentTraceablePrediction()?.prediction_anomaly_audit || null;
  const statusElement = document.getElementById("predictionAnomalyStatus");
  const summaryElement = document.getElementById("predictionAnomalySummary");
  const listElement = document.getElementById("predictionAnomalyList");
  if (!audit) {
    statusElement.textContent = "等待预测包";
    summaryElement.innerHTML = "";
    listElement.innerHTML = "<p>当前预测包还没有异常审计。</p>";
    return;
  }
  const coverage = audit.coverage || {};
  const anomalies = Array.isArray(audit.anomalies) ? audit.anomalies : [];
  statusElement.textContent = anomalyStatusLabel(audit.status);
  summaryElement.innerHTML = [
    ["异常", audit.anomaly_count || 0],
    ["高优先级", audit.high_severity_count || 0],
    ["中优先级", audit.medium_severity_count || 0],
    ["状态更新", coverage.state_update_count || 0],
    ["单条重跑", coverage.isolated_trace_count || 0],
    ["路由记录", coverage.route_only_trace_count || 0]
  ].map(([label, value]) => `
    <article class="metric-card ${label === "高优先级" && Number(value) ? "metric-alert" : ""}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
    </article>
  `).join("");
  listElement.innerHTML = anomalies.length
    ? anomalies.map(row => renderPredictionAnomalyCard(row)).join("")
    : `<article class="anomaly-card"><span class="pill">未发现主要异常</span><p>${escapeHtml(audit.summary_zh || "当前规则没有发现明显冲突。")}</p></article>`;
}

function renderPredictionAnomalyCard(row) {
  const drivers = (row.driver_ids || [])
    .map(id => driverNames[id] || id)
    .filter(Boolean)
    .join(" / ");
  const target = row.target_type === "team"
    ? (teamNames[row.target_id] || row.target_id)
    : row.team_id
      ? `${teamNames[row.team_id] || row.team_id}${drivers ? ` | ${drivers}` : ""}`
      : (drivers || row.target_id || "预测运行");
  const sources = (row.supporting_sources || [])
    .slice(0, 3)
    .map(source => `<span class="pill">${escapeHtml(source.publisher || source.source_type_zh || "来源")}: ${escapeHtml(shortHash(source.title || source.source_id))}</span>`)
    .join("");
  const chain = (row.source_to_prediction_chain || [])
    .slice(0, 5)
    .map(stage => `<p><strong>${escapeHtml(stage.stage || "")}</strong>：${escapeHtml(stage.text_zh || "")}</p>`)
    .join("");
  const severityClass = String(row.severity || "low").replace(/[^a-z0-9_-]/gi, "");
  return `
    <article class="anomaly-card anomaly-${severityClass}">
      <div class="anomaly-head">
        <h3>${escapeHtml(target)}</h3>
        <span class="pill">${escapeHtml(severityLabel(row.severity))}</span>
        <span class="pill">${escapeHtml(anomalyCodeLabel(row.code))}</span>
        <span class="pill">${escapeHtml(traceStatusLabel(row.trace_status))}</span>
      </div>
      <p>${escapeHtml(row.expected_rank_summary_zh || "")}</p>
      <p>${escapeHtml(row.evidence_summary_zh || "")}</p>
      <p>${escapeHtml(row.model_risk_zh || "")}</p>
      <p>${escapeHtml(row.recommended_action_zh || "")}</p>
      <div class="quality-flags">${sources || "<span class=\"pill\">来源摘要不足</span>"}</div>
      <div class="anomaly-chain">${chain}</div>
    </article>
  `;
}

function renderPredictionExplanation() {
  const statusElement = document.getElementById("predictionExplanationStatus");
  const resultElement = document.getElementById("predictionExplanationResult");
  if (!statusElement || !resultElement) {
    return;
  }
  if (state.predictionExplanationLoading) {
    statusElement.textContent = "正在生成解释";
    resultElement.innerHTML = `<article class="explanation-card"><p>正在读取注册预测包、BeliefState、状态更新账本和同种子影响 trace。</p></article>`;
    return;
  }
  if (state.predictionExplanationError) {
    statusElement.textContent = "解释生成失败";
    resultElement.innerHTML = `<article class="explanation-card warning"><p>${escapeHtml(state.predictionExplanationError.message || "解释接口返回错误。")}</p></article>`;
    return;
  }
  const explanation = state.predictionExplanation;
  if (!explanation) {
    statusElement.textContent = "按问题筛选直接/间接影响 trace";
    resultElement.innerHTML = `
      <article class="explanation-card">
        <p>选择示例问题或输入中文问题后，系统会只用当前注册预测包回答，并标出哪些影响 trace 直接作用于所问对象，哪些只是竞争格局的间接影响。</p>
      </article>
    `;
    return;
  }
  statusElement.textContent = `${questionTypeLabel(explanation.question_type)} | ${escapeHtml(shortHash(explanation.run_id))}`;
  const answer = String(explanation.answer || "")
    .split(/\n{2,}/)
    .filter(Boolean)
    .map(paragraph => `<p>${escapeHtml(paragraph)}</p>`)
    .join("");
  const limitations = (explanation.limitations || [])
    .slice(0, 4)
    .map(item => `<span class="pill">${escapeHtml(item)}</span>`)
    .join("");
  const context = explanation.evidence_context || {};
  const impact = context.prediction_impact_trace_context || {};
  const traces = (impact.top_traces || []).slice(0, 5);
  const traceCards = traces.length
    ? traces.map(trace => renderExplanationTraceCard(trace)).join("")
    : `<article class="explanation-trace-card"><p>当前问题没有匹配到可展示的影响 trace。</p></article>`;
  const counts = [
    ["原始来源", context.belief_state_context?.raw_source_count || 0],
    ["状态更新", context.belief_state_context?.state_update_count || 0],
    ["影响记录", impact.total_prediction_impact_trace_count || 0],
    ["问题相关", impact.selected_prediction_impact_trace_count || 0]
  ].map(([label, value]) => `
    <div class="metric-card">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
    </div>
  `).join("");
  resultElement.innerHTML = `
    <article class="explanation-card">
      <div class="explanation-head">
        <h3>${escapeHtml(explanation.question || "预测解释")}</h3>
        <span class="pill">${escapeHtml(questionTypeLabel(explanation.question_type))}</span>
        <span class="pill">${escapeHtml(explanation.confidence || "diagnostic")}</span>
      </div>
      <div class="explanation-answer">${answer}</div>
      <div class="quality-flags">${limitations || "<span class=\"pill\">无额外限制说明</span>"}</div>
    </article>
    <div class="metric-grid">${counts}</div>
    <div class="explanation-trace-list">${traceCards}</div>
  `;
}

function renderExplanationTraceCard(trace) {
  const changed = (trace.changed_factors || [])
    .slice(0, 3)
    .map(factor => `${factor.target_label || targetDisplay(factor.target_type, factor.target_id)} ${factor.factor_label || factorLabel(factor.factor)} ${factor.direction_label || ""}`)
    .join("；");
  const points = (trace.points_changes || [])
    .slice(0, 3)
    .map(row => `${row.driver_name || driverNames[row.driver_id] || row.driver_id}${row.direction_label || ""}${row.magnitude_label || ""}`)
    .join("；");
  const ranks = (trace.rank_changes || [])
    .slice(0, 3)
    .map(row => `${row.driver_name || driverNames[row.driver_id] || row.driver_id}${row.direction_label || ""}${row.magnitude_label || ""}`)
    .join("；");
  const relevance = trace.relevance_scope_label || traceRelevanceLabel(trace.relevance_scope);
  return `
    <article class="explanation-trace-card ${trace.relevance_scope === "indirect_competition" ? "indirect" : ""}">
      <div class="explanation-head">
        <h3>${escapeHtml(trace.trace_type_label || traceTypeLabel(trace.trace_type))}</h3>
        <span class="pill">${escapeHtml(relevance)}</span>
        <span class="pill">${escapeHtml(trace.probability_delta_label || magnitudeLabel(trace.probability_delta_bucket))}</span>
      </div>
      <p>${escapeHtml(changed || "整体状态对比")}</p>
      <p>${escapeHtml(points || ranks || "该 trace 对所选车手没有显著点数/排名变化。")}</p>
      <p>${escapeHtml(trace.claim_id || trace.update_id_or_group_id || trace.impact_trace_id || "")}</p>
    </article>
  `;
}

function rowsAtReplayLap(rows, lap = state.replayLap) {
  if (lap == null) {
    return [];
  }
  return rows
    .filter(row => Number(row.lap) === Number(lap))
    .map(row => ({
      ...row,
      lap: Number(row.lap),
      position: Number(row.position),
      gap_to_leader: row.gap_to_leader == null ? null : Number(row.gap_to_leader),
      lap_time: row.lap_time == null ? null : Number(row.lap_time)
    }))
    .filter(row => Number.isFinite(row.position))
    .sort((a, b) => a.position - b.position);
}

function renderReplayControls(rows) {
  const bounds = replayLapBounds(rows);
  const slider = document.getElementById("replayLapSlider");
  const button = document.getElementById("replayPlayButton");
  const meta = document.getElementById("replayLapMeta");
  if (!bounds) {
    slider.disabled = true;
    button.disabled = true;
    button.textContent = "Play";
    meta.textContent = `Replay unavailable | ${replayUnavailableLines()[1]}`;
    return;
  }
  if (state.replayLap == null) {
    state.replayLap = bounds.min;
  }
  slider.disabled = false;
  button.disabled = false;
  slider.min = String(bounds.min);
  slider.max = String(bounds.max);
  slider.value = String(state.replayLap);
  button.textContent = state.replayPlaying ? "Pause" : "Play";
  const frame = rowsAtReplayLap(rows);
  const leader = frame[0];
  const leaderName = leader ? driverNames[leader.driver_id] || leader.driver_id : "n/a";
  meta.textContent = `Lap ${state.replayLap}/${bounds.max} | leader ${leaderName}`;
}

function renderReplayFrame(rows) {
  const element = document.getElementById("replayFrame");
  const frame = rowsAtReplayLap(rows).slice(0, 8);
  if (!frame.length) {
    const detail = replayUnavailableLines();
    element.innerHTML = `
      <article class="replay-frame-card">
        <span class="pill">no frame</span>
        ${detail.map(line => `<p>${escapeHtml(line)}</p>`).join("")}
      </article>
    `;
    return;
  }
  element.innerHTML = frame.map(row => {
    const color = colors[row.driver_id] || "#f3f6fb";
    const gap = row.gap_to_leader == null ? "n/a" : `${row.gap_to_leader.toFixed(1)}s`;
    const pit = row.pit_stop ? "pit" : row.dnf ? "dnf" : row.track_status || "green";
    const tyre = row.compound ? `${row.compound} ${row.tyre_age || ""}`.trim() : "compound n/a";
    return `
      <article class="replay-frame-card">
        <div class="replay-driver">
          <span class="driver-dot" style="background:${color}"></span>
          <strong>P${row.position} ${escapeHtml(driverNames[row.driver_id] || row.driver_id)}</strong>
        </div>
        <p>${escapeHtml(tyre)} | ${escapeHtml(pit)} | gap ${escapeHtml(gap)}</p>
      </article>
    `;
  }).join("");
}

function drawTrack(event) {
  const points = Array.isArray(event.track_map) ? event.track_map : [];
  const audit = trackMapAudit(event);
  const canvas = document.getElementById("trackCanvas");
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#10151f";
  ctx.fillRect(0, 0, width, height);
  ctx.lineJoin = "round";
  ctx.lineCap = "round";

  renderTrackAudit(audit);
  if (audit.assetPath && drawTrackAsset(ctx, width, height, audit, event)) {
    return;
  }
  if (points.length < 4) {
    drawCanvasNotice(ctx, width, height, "Track map unavailable", [
      "no official asset or geometry profile found",
      `${audit.source} | ${audit.quality}`
    ]);
    return;
  }

  const scaled = points.map(([x, y]) => [x * width, y * height]);
  ctx.strokeStyle = "#2f384a";
  ctx.lineWidth = 34;
  path(ctx, scaled);
  ctx.stroke();

  ctx.strokeStyle = "#45c4b0";
  ctx.lineWidth = 6;
  path(ctx, scaled);
  ctx.stroke();

  if (scaled.length > 1) {
    const [sx, sy] = scaled[0];
    ctx.fillStyle = "#f4b860";
    ctx.beginPath();
    ctx.arc(sx, sy, 8, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#f3f6fb";
    ctx.font = "14px system-ui";
    ctx.fillText("Start", sx + 12, sy - 12);
  }
}

function trackMapAudit(event) {
  const refs = event.feature_refs || {};
  const provenance = refs.event_input_provenance || {};
  const asset = event.track_map_asset || refs.track_map_asset || provenance.track_map_asset || {};
  const track = provenance.track_map || refs.circuit_profile || {};
  const source = asset.source || track.source || refs.event_source || "unknown";
  const quality = asset.quality || track.quality || "unknown";
  const visualVerified = asset.visual_verified === true || track.visual_verified === true || refs.circuit_profile?.visual_verified === true;
  return {
    source,
    quality,
    visualVerified,
    assetPath: asset.web_path || null,
    assetSourceUrl: asset.source_url || null,
    geometryOverlay: asset.geometry_overlay || null,
    circuitShortName: asset.circuit_short_name || null,
    pointCount: track.source_point_count || (Array.isArray(event.track_map) ? event.track_map.length : 0),
    capturedAt: asset.captured_at || track.captured_at || null
  };
}

function renderTrackAudit(audit) {
  const element = document.getElementById("trackAudit");
  const status = audit.assetPath
    ? audit.geometryOverlay ? "official track map + replay overlay" : "official track map"
    : audit.visualVerified ? "visual verified geometry" : "geometry fallback";
  element.innerHTML = `
    <article class="track-audit-card ${audit.assetPath || audit.visualVerified ? "verified" : "pending"}">
      <span class="pill">${escapeHtml(status)}</span>
      <p>${escapeHtml(audit.source)} | ${escapeHtml(audit.quality)} | ${escapeHtml(audit.circuitShortName || "circuit verified")}</p>
      <p>${audit.capturedAt ? `captured ${escapeHtml(shortDate(audit.capturedAt))}` : "local official visual asset"}</p>
    </article>
  `;
}

function drawTrackAsset(ctx, width, height, audit, event) {
  const bounds = drawTrackAssetImage(ctx, width, height, audit, "Loading track map", [
    audit.assetPath,
    `${audit.source} | ${audit.quality}`
  ], () => {
    if (state.report?.event?.event_id === event.event_id) {
      drawTrack(event);
    }
  });
  return bounds !== false;
}

function drawTrackAssetImage(ctx, width, height, audit, loadingTitle, loadingLines, onReady) {
  if (!audit.assetPath) {
    return false;
  }
  const imageSrc = versionedTrackAssetPath(audit);
  let cached = trackImageCache.get(imageSrc);
  if (!cached) {
    cached = { image: new Image(), loaded: false, failed: false, callbacks: [] };
    cached.image.onload = () => {
      cached.loaded = true;
      cached.callbacks.splice(0).forEach(callback => callback());
    };
    cached.image.onerror = () => {
      cached.failed = true;
      cached.callbacks.splice(0).forEach(callback => callback());
    };
    cached.image.src = imageSrc;
    trackImageCache.set(imageSrc, cached);
  }
  if (cached.failed) {
    return false;
  }
  if (!cached.loaded) {
    if (typeof onReady === "function") {
      cached.callbacks.push(onReady);
    }
    drawCanvasNotice(ctx, width, height, loadingTitle, loadingLines);
    return null;
  }
  const image = cached.image;
  const margin = 26;
  const availableWidth = width - margin * 2;
  const availableHeight = height - margin * 2;
  const scale = Math.min(availableWidth / image.naturalWidth, availableHeight / image.naturalHeight);
  const drawWidth = image.naturalWidth * scale;
  const drawHeight = image.naturalHeight * scale;
  const x = (width - drawWidth) / 2;
  const y = (height - drawHeight) / 2;
  ctx.drawImage(image, x, y, drawWidth, drawHeight);
  return { x, y, width: drawWidth, height: drawHeight };
}

function versionedTrackAssetPath(audit) {
  const version = audit.capturedAt || audit.assetSourceUrl || audit.circuitShortName || "asset";
  const separator = audit.assetPath.includes("?") ? "&" : "?";
  return `${audit.assetPath}${separator}v=${encodeURIComponent(version)}`;
}

function drawReplayTrack(event, rows) {
  const canvas = document.getElementById("replayTrackCanvas");
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#10151f";
  ctx.fillRect(0, 0, width, height);

  const points = Array.isArray(event.track_map) ? event.track_map : [];
  const audit = trackMapAudit(event);
  if (!rows.length) {
    drawCanvasNotice(ctx, width, height, "Replay track unavailable", replayUnavailableLines());
    return;
  }
  if (audit.assetPath) {
    const bounds = drawTrackAssetImage(ctx, width, height, audit, "Loading replay track map", [
      audit.assetPath,
      `${audit.source} | ${audit.quality}`
    ], () => {
      if (state.report?.event?.event_id === event.event_id) {
        drawReplayTrack(event, replayRows());
      }
    });
    if (bounds === null) {
      return;
    }
    if (bounds) {
      if (points.length >= 4) {
        const replayPath = trackOverlayPoints(points, bounds, audit);
        drawReplayMarkers(
          ctx,
          width,
          height,
          event,
          replayPath.length >= 4 ? replayPath : fitTrackPointsInBox(points, bounds.x, bounds.y, bounds.width, bounds.height, 8),
          rows,
          audit
        );
      } else {
        drawReplayProgressRail(ctx, width, height, rows);
      }
      return;
    }
  }
  if (points.length >= 4) {
    const scaled = fitTrackPoints(points, width, height, 28);
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.strokeStyle = "#2f384a";
    ctx.lineWidth = 24;
    path(ctx, scaled);
    ctx.stroke();
    ctx.strokeStyle = "#45c4b0";
    ctx.lineWidth = 5;
    path(ctx, scaled);
    ctx.stroke();

    if (scaled.length > 1) {
      const [sx, sy] = scaled[0];
      ctx.fillStyle = "#f4b860";
      ctx.beginPath();
      ctx.arc(sx, sy, 6, 0, Math.PI * 2);
      ctx.fill();
    }
    drawReplayMarkers(ctx, width, height, event, scaled, rows, audit);
    return;
  }
  if (points.length < 4) {
    drawCanvasNotice(ctx, width, height, "Replay track unavailable", [
      "selected simulation has no usable track geometry"
    ]);
    return;
  }
}

function fitTrackPoints(points, width, height, margin) {
  const xs = points.map(point => Number(point[0])).filter(Number.isFinite);
  const ys = points.map(point => Number(point[1])).filter(Number.isFinite);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const sourceWidth = Math.max(0.001, maxX - minX);
  const sourceHeight = Math.max(0.001, maxY - minY);
  const scale = Math.min((width - margin * 2) / sourceWidth, (height - margin * 2) / sourceHeight);
  const drawWidth = sourceWidth * scale;
  const drawHeight = sourceHeight * scale;
  const offsetX = (width - drawWidth) / 2;
  const offsetY = (height - drawHeight) / 2;
  return points.map(([x, y]) => [
    offsetX + (Number(x) - minX) * scale,
    offsetY + (Number(y) - minY) * scale
  ]);
}

function fitTrackPointsInBox(points, boxX, boxY, boxWidth, boxHeight, margin) {
  return fitTrackPoints(points, boxWidth, boxHeight, margin).map(([x, y]) => [x + boxX, y + boxY]);
}

function trackOverlayPoints(points, bounds, audit) {
  const overlay = audit?.geometryOverlay || {};
  const transform = overlay.transform || {};
  const imageWidth = finiteNumber(overlay.image_width) || finiteNumber(transform.image_width);
  const imageHeight = finiteNumber(overlay.image_height) || finiteNumber(transform.image_height);
  const scaleX = finiteNumber(transform.scale_x);
  const scaleY = finiteNumber(transform.scale_y);
  const translateX = finiteNumber(transform.translate_x);
  const translateY = finiteNumber(transform.translate_y);
  if (!imageWidth || !imageHeight || scaleX == null || scaleY == null || translateX == null || translateY == null) {
    return [];
  }
  return points
    .map(([rawX, rawY]) => {
      let x = finiteNumber(rawX);
      let y = finiteNumber(rawY);
      if (x == null || y == null) {
        return null;
      }
      if (transform.swap_xy === true) {
        [x, y] = [y, x];
      }
      if (transform.flip_x === true) {
        x = 1 - x;
      }
      if (transform.flip_y === true) {
        y = 1 - y;
      }
      const imageX = x * scaleX + translateX;
      const imageY = y * scaleY + translateY;
      return [
        bounds.x + (imageX / imageWidth) * bounds.width,
        bounds.y + (imageY / imageHeight) * bounds.height
      ];
    })
    .filter(Boolean);
}

function drawReplayProgressRail(ctx, width, height, rows) {
  const frame = rowsAtReplayLap(rows).slice(0, 8);
  if (!frame.length) {
    return;
  }
  const left = 40;
  const right = width - 40;
  const y = height - 36;
  ctx.save();
  ctx.strokeStyle = "#2f384a";
  ctx.lineWidth = 12;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(left, y);
  ctx.lineTo(right, y);
  ctx.stroke();
  ctx.strokeStyle = "#45c4b0";
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.moveTo(left, y);
  ctx.lineTo(right, y);
  ctx.stroke();
  const leader = frame[0] || {};
  const leaderLapTime = Math.max(40, Number(leader.lap_time) || 90);
  const verticalOffsets = [-16, -8, 0, 8, 16, 24, -24, 32];
  frame.forEach((row, index) => {
    const gap = Math.max(0, Number(row.gap_to_leader) || 0);
    const progress = 1 - Math.min(0.96, gap / leaderLapTime);
    const x = Math.max(left + 8, Math.min(right - 8, left + (right - left) * progress - index * 8));
    const offsetY = y + verticalOffsets[index % verticalOffsets.length];
    const color = colors[row.driver_id] || "#f3f6fb";
    ctx.fillStyle = "rgba(16, 21, 31, 0.9)";
    ctx.beginPath();
    ctx.arc(x, offsetY, 10, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(x, offsetY, 7, 0, Math.PI * 2);
    ctx.stroke();
  });
  ctx.restore();
}

function drawReplayMarkers(ctx, width, height, event, scaledPoints = null, rows = null, audit = null) {
  const points = Array.isArray(event.track_map) ? event.track_map : [];
  const allRows = Array.isArray(rows) && rows.length ? rows : replayRows();
  const frame = rowsAtReplayLap(allRows).slice(0, 8);
  if ((!scaledPoints && points.length < 4) || !frame.length) {
    return;
  }
  const scaled = scaledPoints || points.map(([x, y]) => [x * width, y * height]);
  const leader = frame[0] || {};
  const leaderLapTime = Math.max(40, Number(leader.lap_time) || 90);
  const progressOffset = finiteNumber(audit?.geometryOverlay?.transform?.progress_offset) || 0;

  ctx.save();
  ctx.font = "700 12px system-ui";
  ctx.textBaseline = "middle";
  frame.forEach((row, index) => {
    const progress = replayMarkerProgress(row, allRows, leaderLapTime, progressOffset);
    const pointIndex = Math.max(0, Math.min(scaled.length - 1, Math.round(progress * (scaled.length - 1))));
    const [baseX, baseY] = scaled[pointIndex];
    const offsetAngle = (index / Math.max(1, frame.length)) * Math.PI * 2;
    const x = baseX + Math.cos(offsetAngle) * 9;
    const y = baseY + Math.sin(offsetAngle) * 9;
    const color = colors[row.driver_id] || "#f3f6fb";

    ctx.fillStyle = "rgba(16, 21, 31, 0.88)";
    ctx.beginPath();
    ctx.arc(x, y, 12, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(x, y, 9, 0, Math.PI * 2);
    ctx.stroke();
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(x, y, 4, 0, Math.PI * 2);
    ctx.fill();

    if (index === 0) {
      const label = `${row.position} ${driverNames[row.driver_id] || row.driver_id}`;
      const labelX = Math.min(width - 96, Math.max(12, x + 14));
      const labelY = Math.min(height - 18, Math.max(18, y - 10));
      ctx.fillStyle = "rgba(16, 21, 31, 0.82)";
      ctx.fillRect(labelX - 6, labelY - 11, ctx.measureText(label).width + 12, 22);
      ctx.fillStyle = color;
      ctx.fillText(label, labelX, labelY);
    }
  });

  ctx.fillStyle = "rgba(16, 21, 31, 0.86)";
  ctx.fillRect(16, 16, 124, 30);
  ctx.fillStyle = "#f3f6fb";
  ctx.fillText(`Replay lap ${state.replayLap || "-"}`, 28, 31);
  ctx.restore();
}

function replayMarkerProgress(row, rows, leaderLapTime, progressOffset = 0) {
  const bounds = replayLapBounds(rows);
  const minLap = bounds?.min ?? 1;
  const maxLap = bounds?.max ?? minLap;
  const lapCount = Math.max(1, maxLap - minLap + 1);
  const lap = finiteNumber(row.lap) ?? state.replayLap ?? minLap;
  const lapIndex = Math.min(lapCount - 1, Math.max(0, lap - minLap));
  const leaderProgress = lapIndex / lapCount;
  const gap = Math.max(0, finiteNumber(row.gap_to_leader) || 0);
  const gapProgress = Math.min(0.94, gap / Math.max(40, leaderLapTime || 90));
  return positiveModulo(leaderProgress - gapProgress + progressOffset, 1);
}

function positiveModulo(value, divisor) {
  return ((value % divisor) + divisor) % divisor;
}

function drawCanvasNotice(ctx, width, height, title, lines) {
  ctx.fillStyle = "#10151f";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#2f384a";
  ctx.lineWidth = 1;
  ctx.strokeRect(16, 16, width - 32, height - 32);
  ctx.fillStyle = "#f3f6fb";
  ctx.font = "600 18px system-ui";
  ctx.textAlign = "center";
  ctx.fillText(title, width / 2, height / 2 - 18);
  ctx.fillStyle = "#9aa6ba";
  ctx.font = "13px system-ui";
  lines.forEach((line, index) => {
    ctx.fillText(line, width / 2, height / 2 + 12 + index * 20);
  });
  ctx.textAlign = "start";
}

function path(ctx, scaled) {
  ctx.beginPath();
  scaled.forEach(([x, y], index) => {
    if (index === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
  });
}

function drawReplayChart(rows) {
  const canvas = document.getElementById("lapCanvas");
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#10151f";
  ctx.fillRect(0, 0, width, height);

  const usableRows = rows
    .filter(row => Number.isFinite(Number(row.position)) && Number.isFinite(Number(row.lap)))
    .map(row => ({ ...row, lap: Number(row.lap), position: Number(row.position) }));
  if (!usableRows.length) {
    drawCanvasNotice(ctx, width, height, "Simulation replay unavailable", replayUnavailableLines());
    return;
  }

  const drivers = [...new Set(usableRows.map(row => row.driver_id))].slice(0, 8);
  const minLap = Math.min(...usableRows.map(row => row.lap));
  const maxLap = Math.max(...usableRows.map(row => row.lap));
  const maxPosition = Math.max(3, Math.min(22, Math.max(...usableRows.map(row => row.position))));
  const activeLap = Math.min(maxLap, Math.max(minLap, Number(state.replayLap) || minLap));
  const left = 48;
  const right = width - 88;
  const top = 26;
  const bottom = height - 38;

  ctx.strokeStyle = "#2f384a";
  ctx.lineWidth = 1;
  for (let i = 0; i < 5; i += 1) {
    const y = top + (bottom - top) * (i / 4);
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
  }

  drivers.forEach(driverId => {
    const series = usableRows
      .filter(row => row.driver_id === driverId)
      .sort((a, b) => a.lap - b.lap);
    ctx.strokeStyle = colors[driverId] || "#ffffff";
    ctx.lineWidth = 3;
    ctx.beginPath();
    series.forEach((row, index) => {
      const x = left + (right - left) * ((row.lap - minLap) / Math.max(1, maxLap - minLap));
      const y = top + (bottom - top) * ((row.position - 1) / Math.max(1, maxPosition - 1));
      if (index === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    });
    ctx.stroke();

    series
      .filter(row => row.pit_stop)
      .forEach(row => {
        const x = left + (right - left) * ((row.lap - minLap) / Math.max(1, maxLap - minLap));
        const y = top + (bottom - top) * ((row.position - 1) / Math.max(1, maxPosition - 1));
        ctx.fillStyle = colors[driverId] || "#ffffff";
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, Math.PI * 2);
        ctx.fill();
      });

    const last = series[series.length - 1];
    if (last) {
      const x = right + 8;
      const y = top + (bottom - top) * ((last.position - 1) / Math.max(1, maxPosition - 1));
      ctx.fillStyle = colors[driverId] || "#ffffff";
      ctx.font = "12px system-ui";
      ctx.fillText(driverNames[driverId] || driverId, x, y + 4);
    }
  });

  const activeX = left + (right - left) * ((activeLap - minLap) / Math.max(1, maxLap - minLap));
  ctx.strokeStyle = "#f3f6fb";
  ctx.lineWidth = 1;
  ctx.setLineDash([5, 6]);
  ctx.beginPath();
  ctx.moveTo(activeX, top - 6);
  ctx.lineTo(activeX, bottom + 6);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = "#f3f6fb";
  ctx.font = "12px system-ui";
  ctx.fillText(`Lap ${activeLap}`, Math.min(activeX + 6, right - 46), top - 10);

  ctx.fillStyle = "#9aa6ba";
  ctx.font = "13px system-ui";
  ctx.fillText("P1", 16, top + 4);
  ctx.fillText(`P${maxPosition}`, 16, bottom + 4);
  ctx.fillText(`Lap ${minLap}`, left, height - 12);
  ctx.fillText(`Lap ${maxLap}`, right - 48, height - 12);
}

function renderStrategyTrace(rows) {
  if (!rows.length) {
    const detail = replayUnavailableLines().map(line => `<p>${escapeHtml(line)}</p>`).join("");
    document.getElementById("strategyTrace").innerHTML = detail;
    return;
  }
  const byDriver = new Map();
  rows.forEach(row => {
    if (!byDriver.has(row.driver_id)) {
      byDriver.set(row.driver_id, []);
    }
    byDriver.get(row.driver_id).push(row);
  });
  const cards = [...byDriver.entries()].slice(0, 6).map(([driverId, driverRows]) => {
    const first = driverRows[0] || {};
    const sortedRows = driverRows.slice().sort((a, b) => Number(a.lap) - Number(b.lap));
    const last = sortedRows[sortedRows.length - 1] || first;
    const positions = sortedRows
      .map(row => Number(row.position))
      .filter(position => Number.isFinite(position));
    const bestPosition = positions.length ? Math.min(...positions) : null;
    const replayPitLaps = sortedRows.filter(row => row.pit_stop).map(row => row.lap);
    const pitLaps = replayPitLaps.length ? replayPitLaps : first.pit_laps || [];
    const compounds = [...new Set(driverRows.map(row => row.compound).filter(Boolean))];
    const statuses = [...new Set(driverRows.map(row => row.track_status).filter(Boolean))];
    const pitText = pitLaps.length ? pitLaps.join(", ") : "none";
    const finalPosition = last.position ? `P${last.position}` : "n/a";
    const bestText = bestPosition ? `P${bestPosition}` : "n/a";
    const gridText = first.grid_position ? `P${first.grid_position}` : "n/a";
    return `
      <article class="strategy-card">
        <div>
          <h3>${driverNames[driverId] || driverId}</h3>
          <span class="pill">${first.planned_stops || 0} stop plan</span>
        </div>
        <p>Grid ${gridText} -> lap ${last.lap || "n/a"} ${finalPosition}</p>
        <p>Best ${bestText} | gap ${last.gap_to_leader == null ? "n/a" : `${Number(last.gap_to_leader).toFixed(1)}s`}</p>
        <p>Compounds ${compounds.join(" / ") || "n/a"}</p>
        <p>Pit laps ${pitText}</p>
        <p>Status ${statuses.join(" / ") || "green"}</p>
      </article>
    `;
  });
  document.getElementById("strategyTrace").innerHTML = cards.join("");
}

function renderProbabilityTable(rows) {
  const rankedRows = normalizeRaceProbabilities(Array.isArray(rows) ? rows : []);
  document.getElementById("probabilityTable").innerHTML = [
    `<div class="row probability-row header"><span>排名</span><span>车手</span><span>冠军</span><span>领奖台</span><span>积分区</span><span>期望积分</span></div>`,
    ...rankedRows.map(row => `
      <div class="row probability-row">
        <span>P${escapeHtml(row.expected_rank || "-")}</span>
        <span>${escapeHtml(driverNames[row.driver_id] || row.driver_id)}</span>
        <span>${pct(row.win)}</span>
        <span>${pct(row.podium)}</span>
        <span>${pct(row.points)}</span>
        <span>${finiteNumber(row.expected_points, 0).toFixed(2)}</span>
      </div>
    `)
  ].join("");
}

function renderSeasonForecast() {
  const season = state.season;
  if (!season) {
    return;
  }
  const baseSources = season.base_points_event_sources || {};
  const fastf1Points = baseSources.fastf1_points || 0;
  const samplingModel = season.event_sampling_model === "strategy_aware_race_time_sampler"
    ? "strategy sampler"
    : "diagnostic sampler";
  document.getElementById("seasonStatus").textContent =
    `${season.status} | ${samplingModel} | ${fastf1Points} actual pts | ${season.remaining_events_simulated} simulated`;
  const rows = (season.rows || []).slice(0, 8);
  document.getElementById("seasonTable").innerHTML = [
    `<div class="row header"><span>Driver</span><span>Base</span><span>Final</span><span>Title</span><span>Top 3</span></div>`,
    ...rows.map(row => `
      <div class="row">
        <span>${driverNames[row.driver_id] || row.driver_name || row.driver_id}</span>
        <span>${row.base_points.toFixed(0)}</span>
        <span>${row.expected_final_points.toFixed(1)}</span>
        <span>${pct(row.champion_probability)}</span>
        <span>${pct(row.top3_probability)}</span>
      </div>
    `)
  ].join("");
}

function renderOfficialStandings() {
  const report = state.officialStandings;
  if (!report) {
    return;
  }
  document.getElementById("officialStatus").textContent =
    `${report.roster_status} | ${report.driver_row_count} drivers | ${report.team_row_count} teams`;
  const summaryRows = [
    ["Can seed", report.can_seed_season_points ? "yes" : "no"],
    ["Matched", report.matched_driver_count || 0],
    ["Official gaps", (report.unmatched_official_drivers || []).length],
    ["Project gaps", (report.unmatched_project_drivers || []).length],
    ["Team mismatches", (report.team_mismatch_drivers || []).length],
    ["Captured", shortDate(report.source_captured_at)]
  ];
  document.getElementById("officialSummary").innerHTML = summaryRows
    .map(([label, value]) => `
      <div class="metric-card">
        <span>${label}</span>
        <strong>${escapeHtml(value)}</strong>
      </div>
    `)
    .join("");
  const unmatchedOfficial = report.unmatched_official_drivers || [];
  const unmatchedProject = report.unmatched_project_drivers || [];
  const mismatches = report.team_mismatch_drivers || [];
  const warnings = report.warnings || [];
  const topDrivers = (report.driver_rows || []).slice(0, 8);
  document.getElementById("officialList").innerHTML = [
    officialCard(
      "Official Point-Scoring Gaps",
      "missing in project roster",
      unmatchedOfficial.length ? unmatchedOfficial.join(" | ") : "none"
    ),
    officialCard(
      "Project Roster Gaps",
      "missing in official standings",
      unmatchedProject.length ? unmatchedProject.join(" | ") : "none"
    ),
    officialCard(
      "Team Assignment Drift",
      "local roster mismatch",
      mismatches.length ? mismatches.join(" | ") : "none"
    ),
    officialCard(
      "Warnings",
      "standings gate",
      warnings.length ? warnings.join(" | ") : "none"
    ),
    `<div class="table official-table">
      <div class="row header"><span>Pos</span><span>Driver</span><span>Team</span><span>Pts</span><span>Match</span></div>
      ${topDrivers.map(row => `
        <div class="row">
          <span>${row.position}</span>
          <span>${escapeHtml(row.driver_name)}</span>
          <span>${escapeHtml(row.team_name)}</span>
          <span>${Number(row.points).toFixed(0)}</span>
          <span>${escapeHtml(row.matched_driver_id || "unmatched")}</span>
        </div>
      `).join("")}
    </div>`
  ].join("");
}

function officialCard(title, label, body) {
  return `
    <article class="official-card">
      <div>
        <h3>${escapeHtml(title)}</h3>
        <span class="pill">${escapeHtml(label)}</span>
      </div>
      <p>${escapeHtml(body)}</p>
    </article>
  `;
}

function renderEdgeTable(rows) {
  document.getElementById("edgeTable").innerHTML = [
    `<div class="row header"><span>Outcome</span><span>Model</span><span>Market</span><span>Consv edge</span><span>Action</span></div>`,
    ...rows.slice(0, 8).map(row => {
      const conservativeProbability = row.conservative_model_probability ?? row.model_probability;
      const conservativeEdge = row.conservative_edge_after_cost ?? row.edge_after_cost;
      const risk = (row.risk_flags || []).includes("recommendation_downgraded_by_calibration")
        ? "downgraded"
        : row.risk_flags?.[0] || "";
      return `
        <div class="row">
          <span>${escapeHtml(outcomeLabel(row))}</span>
          <span>${pct(row.model_probability)} -> ${pct(conservativeProbability)}</span>
          <span>${pct(row.market_probability)}</span>
          <span class="${conservativeEdge >= 0 ? "edge-positive" : "edge-negative"}">${signedPct(conservativeEdge)}</span>
          <span>${row.recommendation}${risk ? ` (${risk})` : ""}</span>
        </div>
      `;
    })
  ].join("");
}

function outcomeLabel(row) {
  if (row.market_type === "constructor_double_podium") {
    return `${teamNames[row.outcome_id] || row.outcome_id} double podium`;
  }
  return driverNames[row.outcome_id] || row.outcome_id;
}

function renderAiJudgement(judgement) {
  const notes = judgement.risk_notes.length
    ? judgement.risk_notes.map(note => `<p>${escapeHtml(note)}</p>`).join("")
    : "<p>没有额外风险说明。</p>";
  document.getElementById("aiJudgement").innerHTML = `
    <span class="pill">${judgement.evidence_count} 条证据声明</span>
    <span class="pill">${judgement.strong_evidence_quality_count || 0} 条强来源</span>
    <span class="pill">${judgement.weak_evidence_quality_count || 0} 条弱/待复核</span>
    <span class="pill">${judgement.feature_adjustment_count || 0} 条结构化特征</span>
    <span class="pill">${judgement.positive_edge_count} 条正向市场差异</span>
    <p>${escapeHtml(judgement.summary || "")}</p>
    ${notes}
  `;
}

function renderResearchPlan() {
  const plan = state.researchPlan;
  if (!plan) {
    return;
  }
  const tasks = plan.source_tasks || [];
  const p0 = tasks.filter(task => task.priority === "P0").length;
  const p1 = tasks.filter(task => task.priority === "P1").length;
  const bands = plan.impact_bands || [];
  const gates = plan.quality_gates || [];
  document.getElementById("researchPlanStatus").textContent =
    `${plan.status} | ${tasks.length} source tasks`;
  const summaryRows = [
    ["P0 tasks", p0],
    ["P1 tasks", p1],
    ["Impact bands", bands.length],
    ["Quality gates", gates.length],
    ["Cutoff", shortDate(plan.knowledge_cutoff)],
    ["Evidence rows", (plan.existing_evidence || []).length]
  ];
  document.getElementById("researchPlanSummary").innerHTML = summaryRows
    .map(([label, value]) => `
      <div class="metric-card">
        <span>${label}</span>
        <strong>${escapeHtml(value)}</strong>
      </div>
    `)
    .join("");

  const taskCards = tasks.map(task => {
    const queries = (task.query_templates || []).slice(0, 2)
      .map(query => `<code>${escapeHtml(query)}</code>`)
      .join("");
    const accept = (task.acceptance_checks || [])[0] || "";
    const reject = (task.rejection_rules || [])[0] || "";
    const metrics = (task.model_metrics || []).join(" / ");
    return `
      <article class="research-plan-card ${task.priority === "P0" ? "priority-high" : ""}">
        <div>
          <h3>${escapeHtml(task.title)}</h3>
          <span class="pill">${escapeHtml(task.priority)} | ${escapeHtml(task.source_class)}</span>
        </div>
        <div>
          <p>${escapeHtml(metrics)}</p>
          <p>${escapeHtml(accept)}</p>
          <p>${escapeHtml(reject)}</p>
        </div>
        <div>${queries}</div>
      </article>
    `;
  });

  const bandCards = bands.map(band => {
    const range = band.signed_magnitude_range || [];
    return `
      <article class="research-plan-card band-card">
        <div>
          <h3>${escapeHtml(band.band)}</h3>
          <span class="pill">cap ${Number(band.confidence_cap || 0).toFixed(2)}</span>
        </div>
        <div>
          <p>${signedNumber(range[0] || 0)} to ${signedNumber(range[1] || 0)}</p>
          <p>${escapeHtml(band.use_when || "")}</p>
          <p>${escapeHtml(band.review_rule || "")}</p>
        </div>
      </article>
    `;
  });

  const gateCards = gates.map(gate => `
    <article class="research-plan-card gate-card">
      <div>
        <h3>Quality Gate</h3>
        <span class="pill">binding</span>
      </div>
      <p>${escapeHtml(gate)}</p>
    </article>
  `);

  document.getElementById("researchPlanList").innerHTML = [
    `<h3 class="readiness-section-title">Source Tasks</h3>`,
    ...taskCards,
    `<h3 class="readiness-section-title">Impact Rubric</h3>`,
    ...bandCards,
    `<h3 class="readiness-section-title">Quality Gates</h3>`,
    ...gateCards
  ].join("");
}

function renderSourceCandidates() {
  const report = state.sourceCandidates;
  const statusElement = document.getElementById("sourceCandidateStatus");
  const summaryElement = document.getElementById("sourceCandidateSummary");
  const listElement = document.getElementById("sourceCandidateList");
  if (!report) {
    statusElement.textContent = "No candidate audit loaded";
    summaryElement.innerHTML = "";
    listElement.innerHTML = "<p>No Codex source candidate audit for this event.</p>";
    return;
  }

  const rows = Array.isArray(report.rows) ? report.rows : [];
  const ready = Number(report.review_ready_count || 0);
  const blocked = Number(report.blocked_count || 0);
  const review = Number(report.warning_count || 0);
  statusElement.textContent = `${report.status || "unknown"} | ${ready} ready | ${blocked} blocked`;

  const summaryRows = [
    ["Candidates", report.candidate_count || 0],
    ["Ready", ready],
    ["Blocked", blocked],
    ["Review", review],
    ["Task links", Object.keys(report.task_link_counts || {}).length],
    ["Source", report.source || "live"]
  ];
  summaryElement.innerHTML = summaryRows
    .map(([label, value]) => `
      <div class="metric-card ${label === "Blocked" && blocked ? "metric-alert" : ""}">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(value)}</strong>
      </div>
    `)
    .join("");

  const statusCards = Object.entries(report.status_counts || {})
    .map(([status, count]) => `
      <article class="preflight-card ${status === "candidate_blocked" ? "blocking" : ""}">
        <div>
          <h3>${escapeHtml(status)}</h3>
          <span class="pill">${escapeHtml(count)} candidates</span>
        </div>
        <p>${candidateStatusText(status)}</p>
      </article>
    `);

  const candidateCards = rows.slice(0, 10).map(row => {
    const flags = (row.risk_flags || []).slice(0, 5)
      .map(flag => `<span class="pill">${escapeHtml(flag)}</span>`)
      .join("");
    const findings = (row.findings || []).slice(0, 3)
      .map(finding => `<p>${escapeHtml(finding.severity || "info")}: ${escapeHtml(finding.code || "finding")} - ${escapeHtml(finding.detail || "")}</p>`)
      .join("");
    const metrics = (row.model_metrics || []).join(" / ") || "metrics n/a";
    const targets = (row.target_hints || []).join(" / ") || "targets n/a";
    const routePreview = (row.route_preview || []).slice(0, 3)
      .map(preview => {
        const context = preview.context_multiplier == null ? "" : " | 赛道适配会影响该路由";
        const demand = preview.track_demand_component
          ? ` | 赛道需求：${factorLabel(preview.track_demand_component)}`
          : "";
        return `${factorLabel(preview.metric)} -> ${surfaceLabel(preview.model_surface || preview.route)}${context}${demand}`;
      })
      .join(" | ");
    const bandPreview = (row.impact_band_guidance || [])
      .map(band => band.band)
      .filter(Boolean)
      .join(" / ");
    const reliability = reliabilityBand(row.source_reliability);
    const relevance = relevanceBand(row.relevance_score);
    return `
      <article class="preflight-card ${row.status === "candidate_blocked" ? "blocking" : ""}">
        <div>
          <h3>${escapeHtml(row.candidate_id || "candidate")}</h3>
          <span class="pill">${escapeHtml(row.status || "status n/a")}</span>
          <span class="pill">${escapeHtml(row.source_class || "source n/a")}</span>
        </div>
        <p>${escapeHtml(row.source || row.title || "source")} | 来源等级：${escapeHtml(reliability)}</p>
        <p>${escapeHtml(metrics)} | ${escapeHtml(targets)} | 相关性：${escapeHtml(relevance)}</p>
        <p>${escapeHtml(routePreview || "route preview n/a")}</p>
        <p>影响幅度需要等来源内容被抽取、审计和归一化后再确定。</p>
        <p>${escapeHtml(row.cutoff_status || "cutoff n/a")} | ${escapeHtml(row.task_link_status || "task link n/a")}</p>
        <p>task ${escapeHtml(row.task_id || "unlinked")} | event ${escapeHtml(row.event_id || report.event_id || "n/a")}</p>
        ${row.url ? `<code>${escapeHtml(row.url)}</code>` : ""}
        <div class="preflight-flags">${flags || "<span class=\"pill\">no flags</span>"}</div>
        ${findings}
        <p>${escapeHtml(row.next_action || "")}</p>
      </article>
    `;
  });

  const pathCards = [
    report.input_path ? `<article class="preflight-card"><h3>Candidate Input</h3><code>${escapeHtml(report.input_path)}</code></article>` : "",
    report.report_path ? `<article class="preflight-card"><h3>Candidate Report</h3><code>${escapeHtml(report.report_path)}</code></article>` : ""
  ].filter(Boolean);

  listElement.innerHTML = [
    `<h3 class="readiness-section-title">Status Counts</h3>`,
    ...(statusCards.length ? statusCards : ["<p>No source candidates supplied yet.</p>"]),
    `<h3 class="readiness-section-title">Candidate Rows</h3>`,
    ...(candidateCards.length ? candidateCards : ["<p>Fill source_candidates.json with Codex search/open results, then rerun the audit.</p>"]),
    `<h3 class="readiness-section-title">Artifacts</h3>`,
    ...(pathCards.length ? pathCards : ["<p>No source-candidate artifacts found.</p>"])
  ].join("");
}

function candidateStatusText(status) {
  if (status === "candidate_ready_for_claim_review") {
    return "Eligible for source inspection and claim drafting after review.";
  }
  if (status === "candidate_needs_review") {
    return "Needs manual or Codex follow-up before it can become a source-backed claim.";
  }
  if (status === "candidate_blocked") {
    return "Blocked candidate; fix the issue or discard it before drafting claims.";
  }
  return "No audited candidate rows yet.";
}

function renderResearchPreflight() {
  const preflight = state.researchPreflight;
  const statusElement = document.getElementById("researchPreflightStatus");
  const summaryElement = document.getElementById("researchPreflightSummary");
  const listElement = document.getElementById("researchPreflightList");
  if (!preflight) {
    statusElement.textContent = "No preflight loaded";
    summaryElement.innerHTML = "";
    listElement.innerHTML = "<p>No research packet preflight data for this event.</p>";
    return;
  }

  const findings = Array.isArray(preflight.findings) ? preflight.findings : [];
  const claims = Array.isArray(preflight.claims) ? preflight.claims : [];
  const candidateAudit = preflight.source_candidate_audit || {};
  const blocking = Number(preflight.blocking_issue_count || 0);
  const warnings = Number(preflight.warning_count || 0);
  const passed = preflight.archive_precheck_can_archive === true;
  statusElement.textContent = `${preflight.status || "unknown"} | ${passed ? "archive precheck passed" : "archive precheck blocked"}`;

  const summaryRows = [
    ["Claims", `${preflight.valid_claim_count || 0}/${preflight.claim_count || 0}`],
    ["Sources", preflight.source_count || 0],
    ["Candidate Match", `${candidateAudit.matched_source_count || 0}/${preflight.source_count || 0}`],
    ["Blocking", blocking],
    ["Warnings", warnings],
    ["Update gate", preflight.valid_claim_count ? "reviewed" : "missing"],
    ["Source", preflight.source || "live"]
  ];
  summaryElement.innerHTML = summaryRows
    .map(([label, value]) => `
      <div class="metric-card ${label === "Blocking" && blocking ? "metric-alert" : ""}">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(value)}</strong>
      </div>
    `)
    .join("");

  const routeCounts = preflight.factor_route_counts || {};
  const routeCards = Object.entries(routeCounts)
    .map(([route, count]) => `
      <article class="preflight-card">
        <div>
          <h3>${escapeHtml(route)}</h3>
          <span class="pill">${escapeHtml(count)} claims</span>
        </div>
        <p>Simulator route preview before archive.</p>
      </article>
    `);

  const candidateAuditCard = `
    <article class="preflight-card ${Number(candidateAudit.unmatched_source_count || 0) || Number(candidateAudit.not_ready_source_count || 0) || Number(candidateAudit.blocked_candidate_source_count || 0) ? "blocking" : ""}">
      <div>
        <h3>Source Candidate Audit</h3>
        <span class="pill">${escapeHtml(candidateAudit.status || "not checked")}</span>
      </div>
      <p>${escapeHtml(candidateAudit.source || "n/a")} | candidates ${escapeHtml(candidateAudit.candidate_count || 0)}</p>
      <p>matched ${escapeHtml(candidateAudit.matched_source_count || 0)} | missing ${escapeHtml(candidateAudit.unmatched_source_count || 0)} | not ready ${escapeHtml(candidateAudit.not_ready_source_count || 0)} | blocked ${escapeHtml(candidateAudit.blocked_candidate_source_count || 0)}</p>
      ${candidateAudit.report_path ? `<code>${escapeHtml(candidateAudit.report_path)}</code>` : ""}
    </article>
  `;

  const findingCards = findings.slice(0, 8).map(finding => `
    <article class="preflight-card ${finding.severity === "error" ? "blocking" : ""}">
      <div>
        <h3>${escapeHtml(finding.code || "finding")}</h3>
        <span class="pill">${escapeHtml(finding.severity || "info")}</span>
      </div>
      <p>${escapeHtml(finding.detail || "")}</p>
      ${finding.claim_id ? `<p>claim ${escapeHtml(finding.claim_id)}</p>` : ""}
    </article>
  `);

  const claimCards = claims.slice(0, 8).map(row => {
    const flags = (row.risk_flags || []).slice(0, 3)
      .map(flag => `<span class="pill">${escapeHtml(flag)}</span>`)
      .join("");
    const contractCodes = row.factor_contract_codes || [];
    const contract = contractCodes.length ? contractCodes.join(" | ") : "contract ok";
    const contractBlocking = contractCodes.some(code => [
      "factor_contract_target_mismatch",
      "factor_contract_claim_type_mismatch",
      "factor_contract_missing_technical_mechanism",
      "factor_contract_missing_track_context"
    ].includes(code));
    const demand = row.track_demand_component
      ? `${row.track_demand_component}`
      : "demand n/a";
    return `
      <article class="preflight-card claim-row ${row.route_status === "unsupported_metric" || contractBlocking ? "blocking" : ""}">
        <div>
          <h3>${escapeHtml(row.claim_id)}</h3>
          <span class="pill">${escapeHtml(row.metric)} -> ${escapeHtml(row.route || "n/a")}</span>
        </div>
        <p>${escapeHtml(row.quality_status || "quality n/a")} | conflict ${escapeHtml(row.conflict_status || "n/a")}</p>
        <p>${escapeHtml(contract)}</p>
        <p>更新方向 ${escapeHtml(row.direction || "n/a")} | 赛道需求 ${escapeHtml(demand)} | ${escapeHtml(row.source_status || "source n/a")}</p>
        <div class="preflight-flags">${flags}</div>
      </article>
    `;
  });

  listElement.innerHTML = [
    `<h3 class="readiness-section-title">Route Preview</h3>`,
    ...(routeCards.length ? routeCards : ["<p>No routed claim preview yet.</p>"]),
    `<h3 class="readiness-section-title">Source Candidate Gate</h3>`,
    candidateAuditCard,
    `<h3 class="readiness-section-title">Findings</h3>`,
    ...(findingCards.length ? findingCards : ["<p>No preflight findings.</p>"]),
    `<h3 class="readiness-section-title">Claim Rows</h3>`,
    ...(claimCards.length ? claimCards : ["<p>No valid claim rows.</p>"])
  ].join("");
}

function renderEvidenceQuality(rows) {
  document.getElementById("evidenceQualityList").innerHTML = rows.length
    ? rows.slice(0, 10).map(row => {
        const flags = (row.risk_flags || [])
          .slice(0, 4)
          .map(flag => `<span class="pill">${escapeHtml(reasonLabel(flag))}</span>`)
          .join("");
        return `
          <article class="quality-card ${row.quality_status === "strong" ? "quality-strong" : ""}">
            <div>
              <h3>${escapeHtml(row.claim_id)}</h3>
              <span class="pill">${escapeHtml(qualityStatusLabel(row.quality_status))}</span>
              <span class="pill">${escapeHtml(impactLevelLabel(row.impact_level))}</span>
            </div>
            <p>来源时效：${escapeHtml(sourceStatusLabel(row.source_status))}</p>
            <p>独立佐证：${escapeHtml(triangulationLabel(row.triangulation_status))}</p>
            <p>冲突检查：${escapeHtml(conflictLabel(row.conflict_status))}</p>
            <p>更新权限由来源、时效、机制、独立佐证和冲突检查共同决定；种子场景来源会被阻断入模。</p>
            <div class="quality-flags">${flags || "<span class=\"pill\">没有风险标签</span>"}</div>
          </article>
        `;
      }).join("")
    : "<p>当前分站没有 Codex 证据质量审计。</p>";
}

function renderEvidence(rows) {
  const sortedRows = rows.slice().sort((a, b) => Number(isSeedClaim(a)) - Number(isSeedClaim(b)));
  document.getElementById("evidenceList").innerHTML = sortedRows.length
    ? sortedRows.map(row => {
        const seed = isSeedClaim(row);
        const evidenceText = row.evidence_text_zh || row.evidence_text || "该声明缺少证据文本。";
        const reasoningText = row.reasoning_zh || row.reasoning || "该声明缺少机制说明。";
        const sourceText = sourceNameLabel(row.source || "未知来源");
        const sourceUrlText = row.source_url ? "有来源链接" : "无 URL";
        return `
        <article class="evidence-card">
          <h3>${escapeHtml(targetDisplay(row.target_type, row.target_id))} | ${escapeHtml(factorLabel(row.metric))}</h3>
          <span class="pill">${escapeHtml(directionLabel(row.direction))} | ${seed ? "开发占位，已阻断入模" : "可追溯证据声明"}</span>
          <p>${escapeHtml(evidenceText)}</p>
          <p>${escapeHtml(reasoningText)}</p>
          <p>来源：${escapeHtml(sourceText)} | ${escapeHtml(sourceUrlText)}</p>
        </article>
      `;
      }).join("")
    : "<p>当前分站还没有 Codex 证据声明。</p>";
}

function renderEvidenceImpact(report) {
  const sidecar = state.impactTraceSidecar || null;
  const sidecarTraces = Array.isArray(sidecar?.traces) ? sidecar.traces : [];
  const packetTraces = Array.isArray(report?.prediction_impact_trace) ? report.prediction_impact_trace : [];
  const traces = sidecarTraces.length ? sidecarTraces : packetTraces;
  const rows = traces.slice().sort((a, b) => tracePriority(b) - tracePriority(a));
  const coverage = sidecar?.coverage || {};
  const page = sidecar?.pagination || {};
  const formalTrace = sidecar?.formal_readiness || {};
  const sidecarSummary = sidecar
    ? `
      <article class="impact-card">
        <div>
          <h3>完整影响追踪缓存</h3>
          <span class="pill">${escapeHtml(sidecar.trace_generation?.comparison_status || "cached")}</span>
          <span class="pill">${escapeHtml(formalTrace.formal_ready ? "正式解释已就绪" : formalTrace.status || "正式解释未就绪")}</span>
        </div>
        <p>${escapeHtml(sidecar.trace_generation?.status_zh || "已读取缓存 sidecar。")}</p>
        <p>${escapeHtml(formalTrace.status_zh || "正式解释就绪状态未记录。")}</p>
        <p>覆盖 ${escapeHtml(coverage.impact_trace_covered_claim_count || 0)} / ${escapeHtml(coverage.impact_trace_claim_count || 0)} 条来源化更新；当前页 ${escapeHtml(page.returned_trace_count || rows.length)} / ${escapeHtml(page.filtered_trace_count || rows.length)} 条。</p>
        <p>${escapeHtml(formalTrace.recommended_action_zh || "")}</p>
      </article>
    `
    : `
      <article class="impact-card">
        <div>
          <h3>完整影响追踪缓存未生成</h3>
          <span class="pill">主包快速样本</span>
        </div>
        <p>当前只展示预测主包内嵌的少量 trace；完整“原始来源 -> 信息分析 -> 状态更新 -> 模拟路由 -> 预测变化”需要先生成 sidecar。</p>
      </article>
    `;
  document.getElementById("evidenceImpactList").innerHTML = rows.length
    ? [
        sidecarSummary,
        ...rows.slice(0, 12).map(trace => {
        const changed = (trace.changed_factors || [])
          .slice(0, 3)
          .map(factor => `${targetDisplay(factor.target_type, factor.target_id)} ${factorLabel(factor.factor)} ${directionLabel(factor.direction)}`)
          .join("；");
        const points = (trace.expected_points_delta || [])
          .slice(0, 4)
          .map(row => predictionDeltaText(row))
          .join("；");
        const ranks = (trace.rank_delta || [])
          .slice(0, 4)
          .map(row => rankDeltaText(row))
          .join("；");
        const chain = (trace.source_to_prediction_chain || [])
          .slice(0, 5)
          .map(stage => `<p><strong>${escapeHtml(stage.stage || "")}</strong>：${escapeHtml(stage.text_zh || "")}</p>`)
          .join("");
        return `
          <article class="impact-card">
            <div>
              <h3>${escapeHtml(traceTypeLabel(trace.trace_type))}</h3>
              <span class="pill">${escapeHtml(magnitudeLabel(trace.probability_delta_bucket))}</span>
              <span class="pill">${escapeHtml(impactStatusLabel(trace.impact_status))}</span>
              ${trace.claim_id ? `<span class="pill">${escapeHtml(shortHash(trace.claim_id))}</span>` : ""}
            </div>
            <p>${escapeHtml(changed || "整体状态更新对比")}</p>
            <p>${escapeHtml(points || ranks || "本次同种子对比没有显著改变所展示车手。")}</p>
            <p>${escapeHtml(trace.interpretation_zh || "预测影响记录已生成。")}</p>
            <div class="trace-chain">${chain || ""}</div>
          </article>
        `;
      })
      ].join("")
    : `${sidecarSummary}<p>当前预测还没有可展示的预测影响追踪。</p>`;
}

function renderTechnicalFactorTrace(report) {
  const rows = Array.isArray(report?.state_update_ledger) ? report.state_update_ledger : [];
  const beliefState = report?.belief_state || {};
  const sources = new Map((beliefState.raw_sources || []).map(row => [row.source_id, row]));
  const selectedRows = rows
    .slice()
    .sort((a, b) => Math.abs(Number(b.delta) || 0) - Math.abs(Number(a.delta) || 0))
    .slice(0, 18);

  document.getElementById("technicalTraceStatus").textContent =
    rows.length ? `${rows.length} 条状态更新` : "没有状态更新";
  document.getElementById("technicalTraceList").innerHTML = selectedRows.length
    ? selectedRows.map(update => {
        const source = sources.get(update.source_id) || {};
        const reasons = (update.quality_reasons || [])
          .slice(0, 3)
          .map(reason => `<span class="pill">${escapeHtml(reasonLabel(reason))}</span>`)
          .join("");
        const surfaces = (update.affected_model_surfaces || [])
          .slice(0, 3)
          .map(surface => `<span class="pill">${escapeHtml(surfaceLabel(surface))}</span>`)
          .join("");
        return `
          <article class="technical-trace-card ${update.direction === "negative" ? "negative-factor" : ""}">
            <div class="technical-route">
              <h3>${escapeHtml(targetDisplay(update.target_type, update.target_id))}</h3>
              <span class="pill">${escapeHtml(factorLabel(update.factor))}</span>
              <span class="route-arrow">-></span>
              <span class="pill">${escapeHtml(directionLabel(update.direction))}</span>
              <span class="route-arrow">-></span>
              <span class="pill">${escapeHtml(permissionLabel(update.update_permission))}</span>
            </div>
            <div class="technical-score">
              <span>状态</span>
              <strong>${escapeHtml(bucketLabel(update.old_value_bucket))} -> ${escapeHtml(bucketLabel(update.new_value_bucket))}</strong>
              <span>${escapeHtml(magnitudeLabel(update.magnitude_bucket))}</span>
            </div>
            <div class="technical-copy">
              <p>来源：${escapeHtml(source.publisher || source.source_type || "未知来源")} | ${escapeHtml(source.title || update.claim_id || "无标题")}</p>
              <p>${escapeHtml(update.mechanism || "没有机制说明。")}</p>
              <div class="factor-meta">
                ${reasons || "<span>质量理由未展开</span>"}
                ${surfaces || "<span>模型表面未标注</span>"}
              </div>
            </div>
          </article>
        `;
      }).join("")
    : "<p>当前预测还没有状态更新账本。</p>";
}

function technicalAffectedText(outcome) {
  const driver = driverNames[outcome.driver_id] || outcome.driver_id;
  const win = outcome.win_delta == null ? "n/a" : signedPct(outcome.win_delta);
  const podium = outcome.podium_delta == null ? "n/a" : signedPct(outcome.podium_delta);
  const points = outcome.expected_points_delta == null
    ? "n/a"
    : signedNumber(outcome.expected_points_delta);
  return `
    <span>
      <strong>${escapeHtml(driver)}</strong>
      win ${escapeHtml(win)} | podium ${escapeHtml(podium)} | pts ${escapeHtml(points)}
    </span>
  `;
}

function claimSignedImpact(claim) {
  const sign = claim.direction === "positive" ? 1 : claim.direction === "negative" ? -1 : 0;
  return sign * Number(claim.magnitude || 0) * Number(claim.confidence || 0) * Math.max(0, 1 - Number(claim.uncertainty || 0));
}

function metricLabel(metric) {
  return String(metric || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, char => char.toUpperCase());
}

function metricRoute(metric) {
  if (metric === "tyre_deg") {
    return "tyre degradation";
  }
  if (metric === "strategy") {
    return "pit strategy";
  }
  if (metric === "wet_skill") {
    return "weather branch";
  }
  if (metric === "reliability") {
    return "DNF risk";
  }
  if (metric === "launch_performance") {
    return "start launch";
  }
  return "track-weighted pace";
}

function renderFeatures(rows) {
  const top = rows
    .slice()
    .sort((a, b) => Math.abs(b.value * b.confidence) - Math.abs(a.value * a.confidence))
    .slice(0, 12);
  document.getElementById("featureList").innerHTML = top.length
    ? top.map(row => `
        <article class="evidence-card">
          <h3>${targetDisplay(row.target_type, row.target_id)} | ${factorLabel(row.metric)}</h3>
          <span class="pill">${directionLabel(row.value >= 0 ? "positive" : "negative")} | ${magnitudeLabel(featureMagnitudeBucket(row))}</span>
          <p>${escapeHtml(row.explanation_zh || row.explanation || "该特征缺少中文机制说明，需要补充来源解释。")}</p>
          <p>来源：${escapeHtml(row.source || "未记录来源")}</p>
        </article>
      `).join("")
    : "<p>当前分站还没有可展示的结构化数据特征。</p>";
}

function renderChronologicalReplay() {
  const report = state.chronological;
  if (!report) {
    return;
  }
  const scope = report.replay_scope || {};
  const metrics = report.diagnostic_metrics || {};
  const readiness = report.readiness_summary || {};
  const calibration = report.calibration_summary || {};
  document.getElementById("chronologicalStatus").textContent =
    `${report.status} | formal ready: ${report.formal_edge_ready ? "yes" : "no"}`;
  const hitRate = metrics.top_pick_hit_rate == null ? "n/a" : pct(metrics.top_pick_hit_rate);
  const summaryRows = [
    ["Due", scope.due_events || 0],
    ["Replayed", scope.replayed_events || 0],
    ["Hit rate", hitRate],
    ["Market rows", metrics.events_with_market_snapshots || 0],
    ["Weak evidence", metrics.events_with_weak_evidence_quality || 0],
    ["Blockers", readiness.blocking_action_count || 0],
    ["Scored", calibration.scored_events || 0],
    ["Market scored", calibration.market_scored_events || 0]
  ];
  document.getElementById("chronologicalSummary").innerHTML = summaryRows
    .map(([label, value]) => `
      <div class="metric-card">
        <span>${label}</span>
        <strong>${escapeHtml(value)}</strong>
      </div>
    `)
    .join("");

  const actions = report.next_actions || [];
  const timeline = (report.timeline || []).filter(row => row.status === "replayed").slice(0, 8);
  const rootCauses = report.root_causes || [];
  const topCause = rootCauses[0];
  const cards = [];
  if (topCause) {
    cards.push(`
      <article class="chronological-card blocks-formal">
        <div>
          <h3>${escapeHtml(topCause.code)}</h3>
          <span class="pill">${escapeHtml(topCause.severity)} | ${topCause.count || 0} events</span>
        </div>
        <p>${escapeHtml(topCause.diagnosis || "")}</p>
        <p>${escapeHtml(topCause.improvement || "")}</p>
      </article>
    `);
  }
  if (actions.length) {
    cards.push(`
      <article class="chronological-card">
        <div>
          <h3>Next Actions</h3>
          <span class="pill">${actions.length} priorities</span>
        </div>
        <div>
          ${actions.slice(0, 4).map(action => `<p>${escapeHtml(action)}</p>`).join("")}
        </div>
      </article>
    `);
  }
  if (timeline.length) {
    cards.push(`
      <article class="chronological-card">
        <div>
          <h3>Scored Timeline</h3>
          <span class="pill">${timeline.length} shown</span>
        </div>
        <div class="chronological-mini-table">
          ${timeline.map(row => `
            <div>
              <span>${row.racing_sequence_number || row.round_number}</span>
              <strong>${escapeHtml(row.event_name)}</strong>
              <span>${row.hit ? "hit" : "miss"} | ${escapeHtml(row.actual_winner || "")}</span>
            </div>
          `).join("")}
        </div>
      </article>
    `);
  }
  document.getElementById("chronologicalList").innerHTML = cards.join("");
}

function renderReplayAnalysis() {
  const analysis = state.analysis;
  if (!analysis) {
    return;
  }
  const metrics = analysis.diagnostic_metrics || {};
  document.getElementById("analysisStatus").textContent =
    `${analysis.status} | formal ready: ${analysis.formal_backtest_ready ? "yes" : "no"}`;
  const hitRate = metrics.top_pick_hit_rate == null ? "n/a" : pct(metrics.top_pick_hit_rate);
  const quality = metrics.input_quality_breakdown || {};
  const verifiedProfiles = quality.generated_verified?.events || 0;
  const partialProfiles = quality.generated_with_partial_verified_profile?.events || 0;
  const placeholderProfiles = quality.generated_with_placeholder_profile?.events || 0;
  const summaryRows = [
    ["Due", analysis.replay_coverage.due_events],
    ["Replayed", analysis.replay_coverage.replayed_events],
    ["Hit rate", hitRate],
    ["Seed inputs", quality.seed_with_fastf1_result?.events || 0],
    ["Verified profiles", verifiedProfiles],
    ["Partial profiles", partialProfiles],
    ["Placeholder profiles", placeholderProfiles],
    ["Need research", metrics.events_needing_codex_research],
    ["Evidence", metrics.events_with_evidence],
    ["Evidence impact", metrics.events_with_evidence_impact || 0],
    ["Retro snaps", metrics.events_with_retrospective_source_snapshots || 0],
    ["Archive snaps", metrics.events_with_archive_backed_source_snapshots || 0],
    ["Market snaps", metrics.events_with_market_snapshots],
    ["Late markets", metrics.events_with_market_snapshots_after_cutoff || 0]
  ];
  document.getElementById("analysisSummary").innerHTML = summaryRows
    .map(([label, value]) => `
      <div class="metric-card">
        <span>${label}</span>
        <strong>${value}</strong>
      </div>
    `)
    .join("");

  renderRootCauses(analysis.root_causes || []);
  const issues = (analysis.issues || []).slice(0, 5);
  document.getElementById("issueList").innerHTML = issues.length
    ? issues.map(issue => `
        <article class="issue-card">
          <div>
            <h3>${issue.code}</h3>
            <span class="pill">${issue.severity} | ${issue.count} events</span>
          </div>
          <p>${issue.impact}</p>
          <p>${issue.recommendation}</p>
        </article>
      `).join("")
    : "<p>No replay analysis issues detected.</p>";
  renderReplayTimeline(analysis.event_diagnostics || []);
  renderSourceAudit(analysis.event_diagnostics || []);
  renderMarketAudit(analysis.event_diagnostics || []);
}

function renderMvpGate() {
  const report = state.mvpGate;
  if (!report) {
    return;
  }
  const summary = report.summary || {};
  document.getElementById("mvpGateStatus").textContent =
    `${report.status} | MVP ready: ${report.mvp_delivery_ready ? "yes" : "no"}`;
  const summaryRows = [
    ["Diagnostic", report.diagnostic_mvp_operational ? "yes" : "no"],
    ["MVP ready", report.mvp_delivery_ready ? "yes" : "no"],
    ["Formal edge", report.formal_edge_ready ? "yes" : "no"],
    ["MVP blockers", summary.mvp_blockers || 0],
    ["Formal blockers", summary.formal_edge_blockers || 0],
    ["Source", report.source || "disk"]
  ];
  document.getElementById("mvpGateSummary").innerHTML = summaryRows
    .map(([label, value]) => `
      <div class="metric-card">
        <span>${label}</span>
        <strong>${escapeHtml(value)}</strong>
      </div>
    `)
    .join("");

  const requirements = report.requirements || [];
  document.getElementById("mvpGateList").innerHTML = requirements.map(row => {
    const classes = [
      "mvp-gate-card",
      row.blocks_mvp_delivery ? "blocks-mvp" : "",
      row.blocks_formal_edge ? "blocks-formal" : ""
    ].filter(Boolean).join(" ");
    return `
      <article class="${classes}">
        <div>
          <h3>${escapeHtml(row.title)}</h3>
          <span class="pill">${escapeHtml(row.status)}</span>
          <p>MVP ${row.blocks_mvp_delivery ? "blocked" : "clear"} | formal ${row.blocks_formal_edge ? "blocked" : "clear"}</p>
        </div>
        <div>
          ${(row.evidence || []).slice(0, 4).map(item => `<p>${escapeHtml(item)}</p>`).join("")}
        </div>
        <div>
          ${((row.gaps || []).length ? row.gaps : ["no gate gaps"]).slice(0, 4).map(item => `<p>${escapeHtml(item)}</p>`).join("")}
          ${((row.next_actions || [])[0]) ? `<code>${escapeHtml(row.next_actions[0])}</code>` : ""}
        </div>
      </article>
    `;
  }).join("");
}

function renderFormalReadiness() {
  const readiness = state.readiness;
  if (!readiness) {
    return;
  }
  document.getElementById("readinessStatus").textContent =
    `${readiness.status} | formal ready: ${readiness.formal_backtest_ready ? "yes" : "no"}`;
  const counts = readiness.action_category_counts || {};
  const summaryRows = [
    ["Blocking", readiness.blocking_action_count || 0],
    ["Warnings", readiness.warning_action_count || 0],
    ["Market", counts.market_snapshot_required || 0],
    ["Late markets", counts.after_cutoff_market_replacement || 0],
    ["Sources", counts.source_archive_required || 0],
    ["Calibration", counts.model_calibration_review || 0]
  ];
  document.getElementById("readinessSummary").innerHTML = summaryRows
    .map(([label, value]) => `
      <div class="metric-card">
        <span>${label}</span>
        <strong>${value}</strong>
      </div>
    `)
    .join("");
  const workstreams = (readiness.workstreams || []).slice(0, 8);
  const rows = (readiness.events || []).filter(row => (row.actions || []).length);
  const cards = [];
  if (workstreams.length) {
    cards.push(`<h3 class="readiness-section-title">Workstreams</h3>`);
    cards.push(...workstreams.map(workstream => {
      const command = (workstream.command_templates || [])[0] || "";
      const criterion = (workstream.success_criteria || [])[0] || "";
      const eventCount = (workstream.event_ids || []).length;
      return `
        <article class="readiness-card workstream-card ${workstream.blocks_formal_claim ? "blocks-formal" : ""}">
          <div>
            <h3>${escapeHtml(workstream.title)}</h3>
            <span class="pill">P${workstream.priority} | ${escapeHtml(workstream.category)}</span>
          </div>
          <div>
            <p>${eventCount} events | ${escapeHtml(workstream.severity)}</p>
            <p>${escapeHtml(criterion)}</p>
          </div>
          <div>
            <p>Blocks ${workstream.blocking_action_count || 0}</p>
            <p>Warnings ${workstream.warning_action_count || 0}</p>
          </div>
          ${command ? `<code>${escapeHtml(command)}</code>` : ""}
        </article>
      `;
    }));
  }
  if (rows.length) {
    cards.push(`<h3 class="readiness-section-title">Event Intake</h3>`);
    cards.push(...rows.slice(0, 10).map(row => {
        const primary = (row.actions || [])[0] || {};
        const command = (primary.command_templates || [])[0] || "";
        return `
          <article class="readiness-card ${row.blocking_action_count ? "blocks-formal" : ""}">
            <div>
              <h3>${escapeHtml(row.event_name)}</h3>
              <span class="pill">${escapeHtml(row.status)}</span>
            </div>
            <div>
              <p>${escapeHtml(primary.category || "ready")}</p>
              <p>${escapeHtml(primary.summary || "")}</p>
            </div>
            <div>
              <p>Blocks ${row.blocking_action_count || 0}</p>
              <p>Required ${shortDate(primary.required_by)}</p>
            </div>
            ${command ? `<code>${escapeHtml(command)}</code>` : ""}
          </article>
        `;
    }));
  }
  document.getElementById("readinessList").innerHTML = cards.length
    ? cards.join("")
    : "<p>All replay rows have the current formal input checks satisfied.</p>";
}

function renderReadinessIntake() {
  const intake = state.intake;
  if (!intake) {
    return;
  }
  document.getElementById("intakeStatus").textContent =
    `${intake.readiness_status} | ${intake.action_count || 0} queued actions`;
  const summaryRows = [
    ["Blocking", intake.blocking_action_count || 0],
    ["Warnings", intake.warning_action_count || 0],
    ["Workstreams", intake.workstream_count || 0],
    ["Preview", intake.action_preview_count || 0],
    ["Ready", intake.formal_backtest_ready ? "yes" : "no"],
    ["Source", intake.source || "disk"]
  ];
  document.getElementById("intakeSummary").innerHTML = summaryRows
    .map(([label, value]) => `
      <div class="metric-card">
        <span>${label}</span>
        <strong>${escapeHtml(value)}</strong>
      </div>
    `)
    .join("");

  const files = intake.files || {};
  const workstreamCards = (intake.workstreams || []).map(workstream => {
    const jsonl = files[`${workstream.workstream_id}_jsonl`] || "";
    const csv = files[`${workstream.workstream_id}_csv`] || "";
    const events = (workstream.event_ids || []).slice(0, 5).join(", ");
    return `
      <article class="intake-card ${workstream.blocks_formal_claim ? "blocks-formal" : ""}">
        <div>
          <h3>${escapeHtml(workstream.title)}</h3>
          <span class="pill">P${workstream.priority} | ${escapeHtml(workstream.workstream_id)}</span>
        </div>
        <div>
          <p>${workstream.blocking_action_count || 0} blocking | ${workstream.warning_action_count || 0} warning</p>
          <p>${escapeHtml(events || "no events")}</p>
        </div>
        <div>
          <code>${escapeHtml(jsonl)}</code>
          <code>${escapeHtml(csv)}</code>
        </div>
      </article>
    `;
  });
  const previewCards = (intake.action_preview || []).map(action => {
    const codes = [
      ...(Array.isArray(action.blocker_codes) ? action.blocker_codes : []),
      ...(Array.isArray(action.warning_codes) ? action.warning_codes : [])
    ];
    const codePills = codes.slice(0, 5)
      .map(code => `<span class="pill">${escapeHtml(code)}</span>`)
      .join("");
    const missing = Array.isArray(action.minimum_missing_requirements)
      ? action.minimum_missing_requirements.slice(0, 2).join(" | ")
      : "";
    return `
      <article class="intake-card ${action.blocks_formal_claim ? "blocks-formal" : ""}">
        <div>
          <h3>${escapeHtml(action.queue_id)}</h3>
          <span class="pill">${escapeHtml(action.severity)} | ${escapeHtml(action.status)}</span>
          ${action.next_action_category ? `<span class="pill">${escapeHtml(action.next_action_category)}</span>` : ""}
        </div>
        <div>
          ${codePills ? `<div class="packet-flags">${codePills}</div>` : ""}
          <p>${escapeHtml(action.event_name)} | ${escapeHtml(action.category)}</p>
          <p>${escapeHtml(action.summary)}</p>
          <p>${escapeHtml(missing || action.acceptance_check)}</p>
        </div>
        <div>
          <p>Required ${shortDate(action.required_by)}</p>
          <code>${escapeHtml((action.command_templates || [])[0] || "")}</code>
        </div>
      </article>
    `;
  });
  document.getElementById("intakeList").innerHTML = [
    `<h3 class="readiness-section-title">Queue Files</h3>`,
    ...workstreamCards,
    `<h3 class="readiness-section-title">Action Preview</h3>`,
    ...previewCards
  ].join("");
}

function renderMarketReadiness() {
  const report = state.marketReadiness;
  if (!report) {
    return;
  }
  const blockingUnresolved = report.blocking_unresolved_event_count ?? report.unresolved_event_count ?? 0;
  const warningOnlyUnresolved = report.warning_only_unresolved_event_count || 0;
  document.getElementById("marketReadinessStatus").textContent =
    `${report.status} | ${blockingUnresolved} blocking | ${warningOnlyUnresolved} warning-only`;
  const summaryRows = [
    ["Actions", report.action_count || 0],
    ["Events", report.event_count || 0],
    ["Blocking Events", report.blocking_event_count || 0],
    ["Warning-only", report.warning_only_event_count || 0],
    ["All Unresolved", report.unresolved_event_count || 0],
    ["Queries", report.query_count || 0],
    ["Results", report.total_search_results || 0],
    ["Definitions", report.events_with_definitions || 0],
    ["Blocker code types", Object.keys(report.blocker_code_counts || {}).length],
    ["Action categories", Object.keys(report.next_action_category_counts || {}).length],
    ["Source", report.source || "disk"]
  ];
  document.getElementById("marketReadinessSummary").innerHTML = summaryRows
    .map(([label, value]) => `
      <div class="metric-card">
        <span>${label}</span>
        <strong>${escapeHtml(value)}</strong>
      </div>
    `)
    .join("");

  const issueCounts = report.search_report?.issue_counts || {};
  const issueSummary = Object.entries(issueCounts)
    .map(([code, count]) => `${code}: ${count}`)
    .join(" | ");
  const blockerSummary = Object.entries(report.blocker_code_counts || {})
    .map(([code, count]) => `${code}: ${count}`)
    .join(" | ");
  const warningSummary = Object.entries(report.warning_code_counts || {})
    .map(([code, count]) => `${code}: ${count}`)
    .join(" | ");
  const actionSummary = Object.entries(report.next_action_category_counts || {})
    .map(([code, count]) => `${code}: ${count}`)
    .join(" | ");
  const rows = report.rows || [];
  document.getElementById("marketReadinessList").innerHTML = [
    issueSummary
      ? `<article class="market-readiness-card ${blockingUnresolved ? "blocks-formal" : "warning-only"}">
          <div>
            <h3>Normalization Gate</h3>
            <span class="pill">${escapeHtml(report.status)}</span>
          </div>
          <p>${escapeHtml(issueSummary)}</p>
          <p>${escapeHtml(blockerSummary || "no blocker codes")}</p>
          <p>${escapeHtml(warningSummary || "no warning codes")}</p>
          <p>${escapeHtml(actionSummary || "no action categories")}</p>
          <p>${escapeHtml(blockingUnresolved)} blocking rows | ${escapeHtml(warningOnlyUnresolved)} warning-only rows</p>
        </article>`
      : "",
    ...rows.map(row => {
      const issues = safeJson(row.issue_counts_json);
      const examples = safeJson(row.issue_examples_json);
      const alternativeCounts = safeJson(row.alternative_market_counts_json);
      const alternativeTypes = safeJson(row.alternative_market_types_json);
      const alternativeExamples = safeJson(row.alternative_market_examples_json);
      const blockerCodes = safeJson(row.blocker_codes_json);
      const warningCodes = safeJson(row.warning_codes_json);
      const missingRequirements = safeJson(row.minimum_missing_requirements_json);
      const issueText = Object.entries(issues)
        .map(([code, count]) => `${code}: ${count}`)
        .join(" | ");
      const alternativeText = Object.entries(alternativeCounts)
        .map(([code, count]) => `${code}: ${count}`)
        .join(" | ");
      const alternativeTypeText = Object.entries(alternativeTypes)
        .map(([code, count]) => `${code}: ${count}`)
        .join(" | ");
      const blocks = Boolean(row.blocks_formal_claim);
      const warningOnly = !blocks && Boolean(row.warning_only);
      const example = Array.isArray(examples) && examples.length ? examples[0] : null;
      const alternativeExample = Array.isArray(alternativeExamples) && alternativeExamples.length ? alternativeExamples[0] : null;
      const codePills = [...(Array.isArray(blockerCodes) ? blockerCodes : []), ...(Array.isArray(warningCodes) ? warningCodes : [])]
        .slice(0, 5)
        .map(code => `<span class="pill">${escapeHtml(code)}</span>`)
        .join("");
      const missingText = Array.isArray(missingRequirements)
        ? missingRequirements.slice(0, 2).join(" | ")
        : "";
      return `
        <article class="market-readiness-card ${blocks ? "blocks-formal" : warningOnly ? "warning-only" : ""}">
          <div>
            <h3>${escapeHtml(row.event_name || row.event_id)}</h3>
            <span class="pill">${escapeHtml(blocks ? "blocks formal" : warningOnly ? "warning only" : "review")} | ${escapeHtml(row.status)}</span>
            <span class="pill">${escapeHtml(row.next_action_category || "manual_market_review")}</span>
          </div>
          <div>
            ${codePills ? `<div class="packet-flags">${codePills}</div>` : ""}
            <p>${row.search_result_count || 0} results | ${row.unique_market_count || 0} unique markets</p>
            <p>${row.snapshot_count || 0} snapshots | ${row.definition_count || 0} definitions</p>
            <p>${row.blocking_action_count || 0} blocking actions | ${row.warning_action_count || 0} warnings</p>
            <p>${escapeHtml(issueText || "no normalization issues")}</p>
            ${alternativeText ? `<p>${escapeHtml(alternativeText)}</p>` : ""}
            ${alternativeTypeText ? `<p>${escapeHtml(row.alternative_definition_count || 0)} alternative definitions | ${escapeHtml(alternativeTypeText)}</p>` : ""}
            <p>${escapeHtml(row.review_summary || "")}</p>
            ${missingText ? `<p>${escapeHtml(missingText)}</p>` : ""}
            ${example ? `<p>${escapeHtml(example.code)}: ${escapeHtml(example.question)}</p>` : ""}
            ${alternativeExample ? `<p>${escapeHtml(alternativeExample.market_family)}: ${escapeHtml(alternativeExample.model_requirement)}</p>` : ""}
          </div>
          <div>
            <p>${escapeHtml(row.categories || "")}</p>
            <p>Required ${escapeHtml(row.required_by || "n/a")}</p>
            <p>${escapeHtml(row.top_issue_code || "no top issue")}</p>
            <p>${escapeHtml(row.next_action || "")}</p>
            <code>${escapeHtml(row.first_query || "")}</code>
          </div>
        </article>
      `;
    })
  ].join("");
}

function renderSourceReadiness() {
  const report = state.sourceReadiness;
  if (!report) {
    return;
  }
  document.getElementById("sourceReadinessStatus").textContent =
    `${report.status} | ${report.remaining_source_count || 0} unresolved`;
  const summaryRows = [
    ["Sources", report.source_count || 0],
    ["Archive proof", report.archive_candidate_count || 0],
    ["Updated", report.sources_updated || 0],
    ["Remaining", report.remaining_source_count || 0],
    ["Archive candidates", report.remaining_candidate_count || 0],
    ["Replacement candidates", report.replacement_candidate_count || 0],
    ["Cutoff-valid replacements", report.cutoff_valid_replacement_count || 0],
    ["Need archive proof", report.replacement_archive_proof_required_count || 0],
    ["Need content review", report.replacement_content_review_required_count || 0],
    ["Blocker code types", Object.keys(report.replacement_blocker_code_counts || {}).length],
    ["Action categories", Object.keys(report.replacement_next_action_category_counts || {}).length],
    ["Source", report.source || "disk"]
  ];
  document.getElementById("sourceReadinessSummary").innerHTML = summaryRows
    .map(([label, value]) => `
      <div class="metric-card">
        <span>${label}</span>
        <strong>${escapeHtml(value)}</strong>
      </div>
    `)
    .join("");

  const statusText = Object.entries(report.status_counts || {})
    .map(([status, count]) => `${status}: ${count}`)
    .join(" | ");
  const remainingText = Object.entries(report.remaining_status_counts || {})
    .map(([status, count]) => `${status}: ${count}`)
    .join(" | ");
  const replacementText = Object.entries(report.replacement_status_counts || {})
    .map(([status, count]) => `${status}: ${count}`)
    .join(" | ");
  const replacementEventText = Object.entries(report.replacement_event_status_counts || {})
    .map(([status, count]) => `${status}: ${count}`)
    .join(" | ");
  const replacementBlockerText = Object.entries(report.replacement_blocker_code_counts || {})
    .map(([status, count]) => `${status}: ${count}`)
    .join(" | ");
  const replacementActionText = Object.entries(report.replacement_next_action_category_counts || {})
    .map(([status, count]) => `${status}: ${count}`)
    .join(" | ");
  const rows = report.rows || [];
  const replacementRows = report.replacement_rows || [];
  document.getElementById("sourceReadinessList").innerHTML = [
    `<article class="source-readiness-card ${report.remaining_source_count ? "blocks-formal" : ""}">
      <div>
        <h3>Archive Discovery</h3>
        <span class="pill">${escapeHtml(report.status)}</span>
      </div>
      <div>
        <p>${escapeHtml(statusText || "no discovery counts")}</p>
        <p>${escapeHtml(remainingText || "no remaining blockers")}</p>
      </div>
      <div>
        <code>${escapeHtml(report.report_path || "")}</code>
        <code>${escapeHtml(report.full_report_path || "")}</code>
      </div>
    </article>`,
    report.replacement_report_path
      ? `<article class="source-readiness-card ${report.cutoff_valid_replacement_count ? "" : "blocks-formal"}">
        <div>
          <h3>Replacement Candidates</h3>
          <span class="pill">${escapeHtml(report.replacement_status || "not generated")}</span>
        </div>
        <div>
          <p>${escapeHtml(replacementText || "no replacement candidates")}</p>
          <p>${escapeHtml(replacementEventText || "no event-level replacement status")}</p>
          <p>${escapeHtml(replacementBlockerText || "no blocker codes")}</p>
          <p>${escapeHtml(replacementActionText || "no action categories")}</p>
          <p>${escapeHtml(report.cutoff_valid_replacement_count || 0)} cutoff-valid of ${escapeHtml(report.replacement_candidate_count || 0)} candidates</p>
          <p>${escapeHtml(report.replacement_archive_proof_required_count || 0)} need archive proof | ${escapeHtml(report.replacement_content_review_required_count || 0)} need content review</p>
        </div>
        <div>
          <code>${escapeHtml(report.replacement_report_path || "")}</code>
        </div>
      </article>`
      : "",
    ...replacementRows.slice(0, 6).map(row => {
      const missing = Array.isArray(row.missing_terms) ? row.missing_terms.slice(0, 4).join(", ") : "";
      const found = Array.isArray(row.found_terms) ? row.found_terms.slice(0, 4).join(", ") : "";
      const commands = Array.isArray(row.command_templates) ? row.command_templates : [];
      const blockerCodes = Array.isArray(row.blocker_codes) ? row.blocker_codes : [];
      const blockerPills = blockerCodes.length
        ? blockerCodes.slice(0, 5).map(code => `<span class="pill">${escapeHtml(code)}</span>`).join("")
        : "<span class=\"pill\">ready</span>";
      const requirements = Array.isArray(row.minimum_missing_requirements)
        ? row.minimum_missing_requirements.slice(0, 2)
        : [];
      return `
        <article class="source-readiness-card ${row.formal_replacement_ready ? "" : "blocks-formal"}">
          <div>
            <h3>${escapeHtml(row.event_name || eventTitle(row.event_id))}</h3>
            <span class="pill">${escapeHtml(row.status)}</span>
            <span class="pill">${escapeHtml(row.next_action_category || "manual_review_candidate")}</span>
            <p>${escapeHtml(row.source_class || "source")} | ${escapeHtml(row.evidence_type || "candidate")}</p>
          </div>
          <div>
            <div class="packet-flags">${blockerPills}</div>
            <p>${escapeHtml(row.review_summary || "")}</p>
            <p>${escapeHtml(row.next_action || "")}</p>
            <code>${escapeHtml(row.url || "")}</code>
          </div>
          <div>
            <p>Current ${escapeHtml(row.current_check_status || "n/a")}</p>
            <p>Archive ${escapeHtml(row.archive_check_status || "n/a")}</p>
            <p>${requirements.length ? escapeHtml(requirements.join(" | ")) : "No missing requirements"}</p>
            <p>${missing ? `Missing ${escapeHtml(missing)}` : `Found ${escapeHtml(found || "not checked")}`}</p>
            <code>${escapeHtml(commands[1] || commands[0] || "")}</code>
          </div>
        </article>
      `;
    }),
    ...rows.map(row => {
      const criteria = Array.isArray(row.acceptance_criteria) ? row.acceptance_criteria.slice(0, 3) : [];
      const classes = Array.isArray(row.recommended_source_classes) ? row.recommended_source_classes.join(", ") : "";
      const claimIds = Array.isArray(row.used_in_claim_ids) ? row.used_in_claim_ids.join(", ") : "";
      return `
        <article class="source-readiness-card blocks-formal">
          <div>
            <h3>${escapeHtml(row.event_name || eventTitle(row.event_id))}</h3>
            <span class="pill">${escapeHtml(row.status)}</span>
            <p>${escapeHtml(row.source_class || "source")} ${classes ? `| ${escapeHtml(classes)}` : ""}</p>
          </div>
          <div>
            <p>${escapeHtml(row.review_summary || "No cutoff-valid archive candidate found by availability + CDX recheck.")}</p>
            <p>${escapeHtml(row.next_action || "")}</p>
            <code>${escapeHtml(row.url || "")}</code>
          </div>
          <div>
            <p>Cutoff ${shortDate(row.knowledge_cutoff)}</p>
            <p>Captured ${shortDate(row.captured_at)}</p>
            <p>${escapeHtml(claimIds || row.event_id)}</p>
            ${criteria.map(item => `<p>${escapeHtml(item)}</p>`).join("")}
            <code>${escapeHtml(row.replacement_query || "")}</code>
          </div>
        </article>
      `;
    })
  ].join("");
}

function renderImprovementPlan() {
  const report = state.improvement;
  if (!report) {
    return;
  }
  document.getElementById("improvementStatus").textContent =
    `${report.status} | ${report.blocking_workstream_count || 0} blockers`;
  const summaryRows = [
    ["Formal ready", report.formal_edge_ready ? "yes" : "no"],
    ["Blocking", report.blocking_workstream_count || 0],
    ["Diagnostic", report.diagnostic_workstream_count || 0],
    ["Top priority", report.top_priority || "none"],
    ["Source", report.source || "disk"],
    ["Cutoff", shortDate(report.as_of)]
  ];
  document.getElementById("improvementSummary").innerHTML = summaryRows
    .map(([label, value]) => `
      <div class="metric-card">
        <span>${label}</span>
        <strong>${escapeHtml(value)}</strong>
      </div>
    `)
    .join("");

  const workstreams = report.workstreams || [];
  document.getElementById("improvementList").innerHTML = workstreams.map(workstream => {
    const evidence = (workstream.current_evidence || []).slice(0, 3).join(" ");
    const acceptance = (workstream.acceptance_checks || [])[0] || "";
    const command = (workstream.command_templates || [])[0] || "";
    return `
      <article class="improvement-card ${workstream.blocks_formal_claim ? "blocks-formal" : ""}">
        <div>
          <h3>P${workstream.priority} ${escapeHtml(workstream.title)}</h3>
          <span class="pill">${escapeHtml(workstream.status)}</span>
        </div>
        <div>
          <p>${escapeHtml(workstream.why)}</p>
          <p>${escapeHtml(evidence)}</p>
          <p>${escapeHtml(acceptance)}</p>
        </div>
        <div>
          <p>${workstream.blocks_formal_claim ? "Blocks formal edge" : "Diagnostic follow-up"}</p>
          <code>${escapeHtml(command)}</code>
        </div>
      </article>
    `;
  }).join("");
}

function renderCalibrationReport() {
  const report = state.calibration;
  if (!report) {
    return;
  }
  const summary = report.summary || {};
  document.getElementById("calibrationStatus").textContent =
    `${report.status} | scored ${report.scored_events} | market ${report.market_scored_events}`;
  const summaryRows = [
    ["Hit rate", summary.top_pick_hit_rate == null ? "n/a" : pct(summary.top_pick_hit_rate)],
    ["Avg top p", summary.mean_top_pick_probability == null ? "n/a" : pct(summary.mean_top_pick_probability)],
    ["Avg actual p", summary.mean_actual_winner_probability == null ? "n/a" : pct(summary.mean_actual_winner_probability)],
    ["Brier", summary.mean_winner_brier_score == null ? "n/a" : Number(summary.mean_winner_brier_score).toFixed(3)],
    ["Log loss", summary.mean_actual_log_loss == null ? "n/a" : Number(summary.mean_actual_log_loss).toFixed(3)],
    ["Cal gap", summary.weighted_top_pick_calibration_gap == null ? "n/a" : signedPct(summary.weighted_top_pick_calibration_gap)]
  ];
  document.getElementById("calibrationSummary").innerHTML = summaryRows
    .map(([label, value]) => `
      <div class="metric-card">
        <span>${label}</span>
        <strong>${value}</strong>
      </div>
    `)
    .join("");
  const bins = report.bins || [];
  document.getElementById("calibrationBins").innerHTML = [
    `<div class="row header"><span>Confidence</span><span>Count</span><span>Avg p</span><span>Hit</span><span>Gap</span></div>`,
    ...bins.map(row => `
      <div class="row">
        <span>${pct(row.lower_bound)}-${pct(row.upper_bound)}</span>
        <span>${row.count}</span>
        <span>${row.average_confidence == null ? "n/a" : pct(row.average_confidence)}</span>
        <span>${row.hit_rate == null ? "n/a" : pct(row.hit_rate)}</span>
        <span>${row.calibration_error == null ? "n/a" : signedPct(row.calibration_error)}</span>
      </div>
    `)
  ].join("");
}

function renderModelErrorReview() {
  const report = state.modelErrorReview;
  if (!report) {
    return;
  }
  const events = (report.events || []).filter(row => !row.hit);
  const summary = report.summary || {};
  document.getElementById("modelErrorStatus").textContent =
    `${report.status} | misses ${report.missed_events || 0}/${report.reviewed_events || 0}`;
  const summaryRows = [
    ["Hit rate", summary.top_pick_hit_rate == null ? "n/a" : pct(summary.top_pick_hit_rate)],
    ["Actual top 3", `${report.actual_winners_ranked_top3 || 0}/${report.reviewed_events || 0}`],
    ["Miss p gap", summary.mean_probability_gap_on_misses == null ? "n/a" : signedPct(summary.mean_probability_gap_on_misses)],
    ["Miss count", report.missed_events || events.length || 0],
    ["Source", report.source || "disk"]
  ];
  document.getElementById("modelErrorSummary").innerHTML = summaryRows
    .map(([label, value]) => `
      <div class="metric-card">
        <span>${label}</span>
        <strong>${escapeHtml(value)}</strong>
      </div>
    `)
    .join("");

  const findings = report.findings || [];
  document.getElementById("modelErrorList").innerHTML = [
    `<article class="model-error-card">
      <div>
        <h3>Replay Pattern</h3>
        <span class="pill">${escapeHtml(report.status)}</span>
      </div>
      <div>
        ${(findings.length ? findings : ["No diagnostic findings available."])
          .map(item => `<p>${escapeHtml(item)}</p>`)
          .join("")}
      </div>
      <div>
        <p>${escapeHtml((report.warnings || []).join(", ") || "no warnings")}</p>
        <code>${escapeHtml(JSON.stringify(report.issue_counts || {}, null, 2))}</code>
      </div>
    </article>`,
    ...events.map(row => {
      const candidates = row.candidate_drivers || [];
      const topCandidates = candidates.slice(0, 3).map(candidate => {
        const name = driverNames[candidate.driver_id] || candidate.driver_id;
        return `${name} win ${pct(candidate.win_probability)}`;
      });
      return `
        <article class="model-error-card diagnostic-miss">
          <div>
            <h3>${escapeHtml(row.event_name)}</h3>
            <span class="pill">${escapeHtml(row.diagnosis_codes.join(", "))}</span>
            <p>${escapeHtml(driverNames[row.top_pick] || row.top_pick)} -> ${escapeHtml(driverNames[row.actual_winner] || row.actual_winner)}</p>
          </div>
          <div>
            <p>${escapeHtml(row.review_summary)}</p>
            <p>${escapeHtml(row.next_action)}</p>
            ${topCandidates.map(item => `<p>${escapeHtml(item)}</p>`).join("")}
          </div>
          <div>
            <p>Actual rank ${row.actual_winner_rank}</p>
            <p>Top p ${pct(row.top_pick_probability)} | actual ${pct(row.actual_winner_probability)}</p>
          </div>
        </article>
      `;
    })
  ].join("");
}

function renderPostEventReview() {
  const report = state.postEventReview;
  if (!report) {
    return;
  }
  const statusElement = document.getElementById("postEventReviewStatus");
  const summaryElement = document.getElementById("postEventReviewSummary");
  const listElement = document.getElementById("postEventReviewList");
  if (report.error) {
    statusElement.textContent = `${report.status || "unavailable"} | ${report.event_id || ""}`;
    summaryElement.innerHTML = `
      <div class="metric-card">
        <span>Result</span>
        <strong>Unavailable</strong>
      </div>
    `;
    listElement.innerHTML = `
      <article class="model-error-card">
        <div>
          <h3>No post-event review</h3>
          <span class="pill">${escapeHtml(report.status || "unavailable")}</span>
        </div>
        <div>
          <p>${escapeHtml(report.error)}</p>
        </div>
      </article>
    `;
    return;
  }
  statusElement.textContent =
    `${report.status} | ${report.winner_hit ? "winner hit" : "winner missed"} | ${report.event_name}`;
  const summaryRows = [
    ["Predicted P1", driverNames[report.predicted_winner] || report.predicted_winner || "n/a"],
    ["Actual winner", driverNames[report.actual_winner] || report.actual_winner || "n/a"],
    ["Winner rank", report.actual_winner_predicted_rank == null ? "n/a" : `P${report.actual_winner_predicted_rank}`],
    ["Winner p", report.actual_winner_win_probability == null ? "n/a" : pct(report.actual_winner_win_probability)],
    ["Podium overlap", report.podium_overlap_rate == null ? "n/a" : pct(report.podium_overlap_rate)],
    ["Points overlap", report.points_overlap_rate == null ? "n/a" : pct(report.points_overlap_rate)]
  ];
  summaryElement.innerHTML = summaryRows
    .map(([label, value]) => `
      <div class="metric-card">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(value)}</strong>
      </div>
    `)
    .join("");
  const rows = report.top10_actual_position_summary || [];
  listElement.innerHTML = [
    `<article class="model-error-card ${report.winner_hit ? "" : "diagnostic-miss"}">
      <div>
        <h3>${escapeHtml(report.event_name || "Post-event review")}</h3>
        <span class="pill">${escapeHtml(report.prediction_status || "diagnostic_only")}</span>
        <p>${escapeHtml(report.summary_zh || "")}</p>
      </div>
      <div>
        <p>Run ${escapeHtml(shortHash(report.prediction_run_id || ""))}</p>
        <p>Result ${escapeHtml(report.result_source || "unknown")} | after cutoff: ${report.result_captured_after_prediction_cutoff ? "yes" : "no"}</p>
        <p>${escapeHtml((report.warnings || []).join(", "))}</p>
      </div>
    </article>`,
    ...rows.map(row => `
      <article class="model-error-card">
        <div>
          <h3>P${escapeHtml(row.predicted_rank)} ${escapeHtml(driverNames[row.driver_id] || row.driver_id)}</h3>
          <span class="pill">Actual ${row.actual_position == null ? "n/a" : `P${row.actual_position}`}</span>
        </div>
        <div>
          <p>Win ${pct(row.win_probability || 0)} | expected points ${Number(row.expected_points || 0).toFixed(2)}</p>
        </div>
      </article>
    `)
  ].join("");
}

function renderSimulatorCalibration() {
  const report = state.simulatorCalibration;
  if (!report) {
    return;
  }
  document.getElementById("simulatorCalibrationStatus").textContent =
    `${report.status} | candidates ${report.candidate_count || 0} | review ${report.recommended_config_id || "n/a"}`;
  const candidates = report.candidates || [];
  const selected = candidates.find(row => row.selected_for_review) || candidates[0] || {};
  const selectedSummary = selected.summary || {};
  const selectedDelta = selected.delta_vs_baseline || {};
  const summaryRows = [
    ["Recommended", selected.config_id || report.recommended_config_id || "n/a"],
    ["Score", selected.composite_score == null ? "n/a" : Number(selected.composite_score).toFixed(3)],
    ["Actual p", selectedSummary.mean_actual_winner_probability == null ? "n/a" : pct(selectedSummary.mean_actual_winner_probability)],
    ["Log loss", selectedSummary.mean_actual_log_loss == null ? "n/a" : Number(selectedSummary.mean_actual_log_loss).toFixed(3)],
    ["Delta loss", selectedDelta.mean_actual_log_loss == null ? "n/a" : signedNumber(selectedDelta.mean_actual_log_loss)],
    ["Formal", report.formal_simulator_claim_ready ? "yes" : "no"]
  ];
  document.getElementById("simulatorCalibrationSummary").innerHTML = summaryRows
    .map(([label, value]) => `
      <div class="metric-card">
        <span>${label}</span>
        <strong>${escapeHtml(value)}</strong>
      </div>
    `)
    .join("");

  const warnings = report.warnings || [];
  document.getElementById("simulatorCalibrationList").innerHTML = [
    `<article class="simulator-calibration-card blocks-formal">
      <div>
        <h3>Calibration Boundary</h3>
        <span class="pill">diagnostic scoring</span>
      </div>
      <div>
        <p>Candidate ranking is diagnostic only; it uses the current replay inputs and is not a held-out simulator ablation.</p>
        <p>${escapeHtml(report.scoring_method || "lower composite score ranks first")}</p>
        <p>${escapeHtml(warnings.slice(0, 4).join(", ") || "no warnings")}</p>
      </div>
      <div>
        <p>Iterations ${escapeHtml(report.iterations || "n/a")}</p>
        <p>Baseline ${escapeHtml(report.baseline_config_id || "n/a")}</p>
      </div>
    </article>`,
    ...candidates.slice(0, 6).map(candidate => {
      const summary = candidate.summary || {};
      const delta = candidate.delta_vs_baseline || {};
      return `
        <article class="simulator-calibration-card ${candidate.selected_for_review ? "selected" : ""}">
          <div>
            <h3>#${candidate.rank} ${escapeHtml(candidate.config_id)}</h3>
            <span class="pill">${candidate.selected_for_review ? "review candidate" : "candidate"}</span>
          </div>
          <div>
            <p>${escapeHtml(candidate.description || "")}</p>
            <p>Hit ${summary.top_pick_hit_rate == null ? "n/a" : pct(summary.top_pick_hit_rate)} | actual ${summary.mean_actual_winner_probability == null ? "n/a" : pct(summary.mean_actual_winner_probability)}</p>
            <p>Brier ${summary.mean_winner_brier_score == null ? "n/a" : Number(summary.mean_winner_brier_score).toFixed(3)} | log loss ${summary.mean_actual_log_loss == null ? "n/a" : Number(summary.mean_actual_log_loss).toFixed(3)}</p>
          </div>
          <div>
            <p>Score ${candidate.composite_score == null ? "n/a" : Number(candidate.composite_score).toFixed(3)}</p>
            <p>Delta loss ${delta.mean_actual_log_loss == null ? "n/a" : signedNumber(delta.mean_actual_log_loss)}</p>
            <p>Scored ${candidate.scored_events || 0} | market ${candidate.market_scored_events || 0}</p>
          </div>
        </article>
      `;
    })
  ].join("");
}

function renderReplayFreeze() {
  const report = state.freeze;
  if (!report) {
    return;
  }
  const hash = report.manifest_payload_sha256 || "";
  const groups = report.artifact_groups || [];
  const groupsById = Object.fromEntries(groups.map(group => [group.group_id, group]));
  const flags = report.integrity_flags || [];
  document.getElementById("freezeStatus").textContent =
    `${report.status} | ${hash ? hash.slice(0, 12) : "no hash"}`;
  const summaryRows = [
    ["Source files", groupsById.source_code?.file_count || 0],
    ["Input files", groupsById.input_data?.file_count || 0],
    ["Reports", groupsById.diagnostic_reports?.file_count || 0],
    ["Flags", flags.length],
    ["Ready", report.status === "formal_ready_freeze" ? "yes" : "no"],
    ["Hash", hash ? hash.slice(0, 8) : "n/a"]
  ];
  document.getElementById("freezeSummary").innerHTML = summaryRows
    .map(([label, value]) => `
      <div class="metric-card">
        <span>${label}</span>
        <strong>${escapeHtml(value)}</strong>
      </div>
    `)
    .join("");
  const groupCards = groups.map(group => `
    <article class="freeze-card">
      <div>
        <h3>${escapeHtml(group.title)}</h3>
        <span class="pill">${escapeHtml(group.group_id)}</span>
      </div>
      <div>
        <p>${group.file_count || 0} files | ${formatBytes(group.total_bytes || 0)}</p>
        <code>${escapeHtml(group.content_sha256 || "")}</code>
      </div>
    </article>
  `);
  const flagCards = flags.length
    ? flags.map(flag => `
        <article class="freeze-card blocks-formal">
          <div>
            <h3>${escapeHtml(flag)}</h3>
            <span class="pill">integrity flag</span>
          </div>
          <p>${escapeHtml(freezeFlagText(flag))}</p>
        </article>
      `)
    : [`
        <article class="freeze-card">
          <div>
            <h3>No Integrity Flags</h3>
            <span class="pill">freeze clean</span>
          </div>
          <p>The current manifest has no reproducibility or formal-readiness flags.</p>
        </article>
      `];
  document.getElementById("freezeList").innerHTML = [
    `<h3 class="readiness-section-title">Artifact Fingerprints</h3>`,
    ...groupCards,
    `<h3 class="readiness-section-title">Integrity Flags</h3>`,
    ...flagCards
  ].join("");
}

function renderRootCauses(rows) {
  document.getElementById("rootCauseList").innerHTML = rows.length
    ? rows.slice(0, 5).map(cause => `
        <article class="root-cause-card ${cause.blocks_formal_claim ? "blocks-formal" : ""}">
          <div class="root-cause-head">
            <h3>${cause.code}</h3>
            <span class="pill">${cause.severity} | ${cause.count} events</span>
          </div>
          <p>${cause.diagnosis}</p>
          <p>${cause.evidence}</p>
          <p>${cause.improvement}</p>
        </article>
      `).join("")
    : "";
}

function renderReplayTimeline(rows) {
  const dueRows = rows.filter(row => row.status !== "not_due");
  const visibleRows = dueRows.length ? dueRows : rows.slice(0, 12);
  document.getElementById("replayTimeline").innerHTML = visibleRows.length
    ? visibleRows.map(row => {
        const statusClass = statusTone(row);
        const raceSeq = row.racing_sequence_number == null ? "-" : row.racing_sequence_number;
        const pick = row.top_pick ? driverNames[row.top_pick] || row.top_pick : "-";
        const actual = row.actual_winner ? driverNames[row.actual_winner] || row.actual_winner : "-";
        const hit = row.hit == null ? "-" : row.hit ? "hit" : "miss";
        const actualProbability = row.actual_winner_probability == null ? "-" : pct(row.actual_winner_probability);
        const issueTags = (row.issue_codes || []).slice(0, 3);
        const sequenceShift = (row.warnings || []).find(warning => warning.startsWith("round_sequence_shift_"));
        const marketState = marketStateLabel(row);
        const sourceState = sourceStateLabel(row);
        const impactState = evidenceImpactLabel(row);
        return `
          <article class="timeline-card ${statusClass}">
            <div class="timeline-index">
              <strong>R${row.round_number}</strong>
              <span>Seq ${raceSeq}</span>
            </div>
            <div class="timeline-main">
              <div class="timeline-heading">
                <h3>${row.event_name}</h3>
                <span class="pill">${row.status}</span>
              </div>
              <div class="timeline-facts">
                <span>Input ${row.event_input_quality || row.prediction_input_source || "n/a"}</span>
                <span>Pick ${pick}</span>
                <span>Actual ${actual}</span>
                <span>${hit} ${actualProbability}</span>
              </div>
              ${sequenceShift ? `<p class="timeline-note">${formatSequenceShift(sequenceShift)}</p>` : ""}
            </div>
            <div class="timeline-health">
              <span class="health-chip">${sourceState}</span>
              <span class="health-chip">${impactState}</span>
              <span class="health-chip">${marketState}</span>
              ${issueTags.map(code => `<span class="health-chip issue">${code}</span>`).join("")}
            </div>
          </article>
        `;
      }).join("")
    : "";
}

function statusTone(row) {
  if (row.status === "cancelled") {
    return "status-muted";
  }
  if (row.hit === true) {
    return "status-good";
  }
  if (row.hit === false) {
    return "status-bad";
  }
  return "status-open";
}

function marketStateLabel(row) {
  if ((row.market_snapshot_count || 0) > 0) {
    return `${row.market_snapshot_count} market`;
  }
  if ((row.market_snapshot_after_cutoff_count || 0) > 0) {
    return `${row.market_snapshot_after_cutoff_count} late market`;
  }
  if (row.missing_market_snapshot_detail) {
    return "market missing";
  }
  return "no market need";
}

function sourceStateLabel(row) {
  if ((row.retrospective_source_snapshot_count || 0) > 0) {
    return `${row.retrospective_source_snapshot_count} retro source`;
  }
  if ((row.archive_backed_source_snapshot_count || 0) > 0) {
    return `${row.archive_backed_source_snapshot_count} archived source`;
  }
  if ((row.source_snapshot_count || 0) > 0) {
    return `${row.source_snapshot_count} source`;
  }
  return row.status === "cancelled" ? "source n/a" : "source missing";
}

function evidenceImpactLabel(row) {
  if ((row.evidence_impact_count || 0) > 0) {
    const delta = row.max_evidence_win_delta == null ? "" : ` ${signedPct(row.max_evidence_win_delta)}`;
    return `${row.evidence_impact_count} impact${delta}`;
  }
  return row.status === "replayed" ? "impact missing" : "impact n/a";
}

function formatSequenceShift(warning) {
  const match = warning.match(/openf1=(\d+)_fastf1=(\d+)_cancelled_before=(\d+)/);
  if (!match) {
    return warning;
  }
  return `Calendar round ${match[1]} maps to race sequence ${match[2]} after ${match[3]} cancelled events.`;
}

function renderSourceAudit(rows) {
  const details = [];
  rows.forEach(row => {
    (row.retrospective_source_details || []).forEach(detail => {
      details.push({ eventName: row.event_name, detail });
    });
    (row.archive_backed_source_details || []).forEach(detail => {
      details.push({ eventName: row.event_name, detail });
    });
  });
  document.getElementById("sourceAuditList").innerHTML = details.length
    ? details.slice(0, 8).map(({ eventName, detail }) => {
        const status = detail.archive_status || "source";
        const archive = detail.archived_at || "no cutoff archive";
        const title = detail.title || detail.source || detail.url || "Source";
        return `
          <article class="source-card">
            <div>
              <h3>${eventName}</h3>
              <span class="pill">${status}</span>
            </div>
            <div>
              <p>${title}</p>
              <a href="${detail.url}" target="_blank" rel="noreferrer">source link</a>
            </div>
            <div>
              <p>Published ${shortDate(detail.published_at)}</p>
              <p>Captured ${shortDate(detail.captured_at)}</p>
              <p>Archive ${shortDate(archive)}</p>
            </div>
          </article>
        `;
      }).join("")
    : "";
}

function renderMarketAudit(rows) {
  const details = [];
  rows.forEach(row => {
    if (row.missing_market_snapshot_detail) {
      details.push({ eventName: row.event_name, detail: row.missing_market_snapshot_detail, kind: "missing" });
    }
    (row.market_snapshot_after_cutoff_details || []).forEach(detail => {
      details.push({ eventName: row.event_name, detail, kind: "late" });
    });
    (row.market_snapshot_details || []).forEach(detail => {
      details.push({ eventName: row.event_name, detail, kind: "valid" });
    });
  });
  document.getElementById("marketAuditList").innerHTML = details.length
    ? details.slice(0, 10).map(({ eventName, detail, kind }) => {
        const status = detail.status || kind;
        const captured = detail.captured_at || "";
        const cutoff = detail.required_at_or_before || detail.knowledge_cutoff || "";
        const prices = (detail.top_prices || [])
          .slice(0, 3)
          .map(item => `${driverNames[item.outcome_id] || item.outcome_id} ${(item.price * 100).toFixed(0)}%`)
          .join(" | ");
        const note = kind === "missing"
          ? `Needs ${detail.market_type || "winner"} snapshot by ${shortDate(cutoff)}`
          : `${detail.market_id || "market"} ${prices}`;
        return `
          <article class="source-card">
            <div>
              <h3>${eventName}</h3>
              <span class="pill">${status}</span>
            </div>
            <div>
              <p>${note}</p>
              <p>${detail.recommendation || ""}</p>
            </div>
            <div>
              <p>Cutoff ${shortDate(cutoff)}</p>
              <p>Captured ${shortDate(captured)}</p>
              <p>${detail.source || ""}</p>
            </div>
          </article>
        `;
      }).join("")
    : "";
}

function tracePriority(trace) {
  if (trace.trace_type === "isolated_same_seed_leave_one_information") {
    return 300 + impactBucketScore(trace.probability_delta_bucket);
  }
  if (trace.trace_type === "same_seed_before_after") {
    return 200 + impactBucketScore(trace.probability_delta_bucket);
  }
  return 100 + impactBucketScore(trace.probability_delta_bucket);
}

function impactBucketScore(bucket) {
  const scores = {
    large: 4,
    medium: 3,
    small: 2,
    very_small: 1,
    tiny: 1,
    not_isolated_yet: 0
  };
  return scores[String(bucket)] || 0;
}

function traceTypeLabel(type) {
  const labels = {
    same_seed_before_after: "完整状态同种子对比",
    isolated_same_seed_leave_one_information: "单条信息隔离重跑",
    isolated_same_seed_leave_source_group: "同源信息组隔离重跑",
    state_update_route: "状态更新路由"
  };
  return labels[String(type)] || String(type || "预测影响");
}

function impactStatusLabel(status) {
  const labels = {
    material_prediction_change: "显著改变预测",
    small_prediction_change: "小幅改变预测",
    no_material_prediction_change: "没有显著改变",
    pending_isolated_rerun: "等待隔离重跑"
  };
  return labels[String(status)] || String(status || "影响状态未知");
}

function anomalyStatusLabel(status) {
  const labels = {
    requires_model_review: "需要优先复核",
    review_recommended: "建议复核",
    no_major_anomaly_detected: "未发现主要异常"
  };
  return labels[String(status)] || String(status || "异常状态未知");
}

function severityLabel(severity) {
  const labels = {
    high: "高优先级",
    medium: "中优先级",
    low: "低优先级"
  };
  return labels[String(severity)] || String(severity || "优先级未知");
}

function anomalyCodeLabel(code) {
  const labels = {
    source_backed_negative_not_reflected: "负向来源未充分反映",
    source_backed_positive_under_ranked: "正向来源可能被压低",
    recent_form_not_reflected: "近期走势未反映",
    teammate_order_conflict: "队友顺序张力",
    impact_trace_incomplete_for_material_updates: "单条影响追踪不足"
  };
  return labels[String(code)] || String(code || "异常类型");
}

function traceStatusLabel(status) {
  const labels = {
    isolated_impact_available: "已有同种子影响证据",
    state_route_only: "仅有状态路由证据"
  };
  return labels[String(status)] || String(status || "影响追踪状态未知");
}

function targetDisplay(targetType, targetId) {
  if (targetType === "driver") {
    return driverNames[targetId] || targetId || "车手";
  }
  if (targetType === "team") {
    return teamNames[targetId] || targetId || "车队";
  }
  if (targetType === "event") {
    return "本场比赛";
  }
  return targetId || "对象";
}

function factorLabel(factor) {
  const labels = {
    overall_pace: "赛车整体速度",
    race_pace: "正赛速度",
    qualifying_pace: "排位速度",
    qualifying_ceiling: "排位上限",
    race_execution: "正赛执行",
    power_unit: "动力单元",
    energy_recovery: "能量回收/部署",
    straight_line_speed: "直道速度",
    drag_efficiency: "气动效率",
    traction: "低速牵引",
    low_speed_traction: "低速牵引",
    tyre_deg: "轮胎衰退",
    tyre_management: "保胎能力",
    wet_skill: "湿地能力",
    reliability: "可靠性",
    strategy_quality: "策略质量",
    strategy: "策略质量",
    upgrade_delta: "升级效果",
    upgrade_effect: "升级效果",
    first_lap_gain: "起步首圈",
    launch_performance: "起步表现",
    wet_probability: "湿地概率",
    safety_car_probability: "安全车概率"
  };
  return labels[String(factor)] || metricLabel(factor);
}

function directionLabel(direction) {
  const labels = {
    positive: "正向",
    negative: "负向",
    neutral: "中性"
  };
  return labels[String(direction)] || String(direction || "方向未知");
}

function bucketLabel(bucket) {
  const labels = {
    strong_positive: "明显偏强",
    positive: "偏强",
    slight_positive: "略强",
    neutral: "中性",
    slight_negative: "略弱",
    negative: "偏弱",
    strong_negative: "明显偏弱"
  };
  return labels[String(bucket)] || magnitudeLabel(bucket);
}

function magnitudeLabel(bucket) {
  const labels = {
    large: "大幅",
    medium: "中等",
    small: "小幅",
    very_small: "很小",
    tiny: "很小",
    none: "无明显变化",
    high: "高",
    moderate: "中等",
    low: "低",
    not_isolated_yet: "尚未单条重跑"
  };
  return labels[String(bucket)] || String(bucket || "幅度未知");
}

function featureMagnitudeBucket(row) {
  const value = Math.abs(Number(row?.value || 0) * Number(row?.confidence || 0));
  if (value >= 0.12) {
    return "large";
  }
  if (value >= 0.06) {
    return "medium";
  }
  if (value >= 0.02) {
    return "small";
  }
  if (value > 0) {
    return "very_small";
  }
  return "none";
}

function isSeedClaim(row) {
  return String(row?.source_url || "").startsWith("seed://");
}

function qualityStatusLabel(status) {
  const labels = {
    strong: "来源强，可正常更新",
    usable_diagnostic: "诊断可用",
    weak_diagnostic: "弱诊断",
    review_required: "需要复核",
    medium: "诊断可用"
  };
  return labels[String(status)] || String(status || "质量未知");
}

function impactLevelLabel(level) {
  const labels = {
    material: "影响较大",
    moderate: "中等影响",
    small: "小影响",
    none: "未观察到影响",
    not_modeled: "尚未建模"
  };
  return labels[String(level)] || magnitudeLabel(level);
}

function questionTypeLabel(type) {
  const labels = {
    rank_explanation: "排名解释",
    driver_comparison: "车手对比",
    group_zero_podium: "零领奖台组解释",
    driver_explanation: "车手解释",
    general_explanation: "整体解释"
  };
  return labels[String(type)] || String(type || "解释");
}

function traceRelevanceLabel(scope) {
  const labels = {
    direct_target: "直接作用于所问对象",
    event_context: "本场比赛环境影响",
    global_baseline: "整体状态基线对比",
    indirect_competition: "竞争格局间接影响，不是直接证据"
  };
  return labels[String(scope)] || String(scope || "相关性未标注");
}

function sourceStatusLabel(status) {
  const labels = {
    within_cutoff: "在知识截止前可用",
    source_log_missing: "缺少来源日志，不能作为正式证据",
    unknown_published_at: "发布时间不清，需要复核",
    source_after_cutoff: "来源晚于知识截止，已阻断",
    claim_after_cutoff: "声明晚于知识截止，已阻断",
    snapshot_after_cutoff: "快照晚于知识截止，只能诊断"
  };
  return labels[String(status)] || String(status || "来源时效未知");
}

function sourceNameLabel(source) {
  const labels = {
    "Open-Meteo forecast API": "Open-Meteo 天气预报接口",
    "FastF1": "FastF1 结构化数据",
    "F1 official standings": "F1 官方积分榜"
  };
  return labels[String(source)] || String(source || "未知来源");
}

function triangulationLabel(status) {
  const labels = {
    corroborated_independent_sources: "多个独立来源互相支持",
    limited_corroboration: "佐证有限",
    same_source_repetition: "同源重复，不能当作独立佐证",
    single_source: "单一来源，需要谨慎",
    single_source_claim: "单一来源，需要谨慎",
    seed_or_test_only: "仅 seed/test 场景，不能作为正式证据",
    unlinked_source: "来源未正确链接到 claim"
  };
  return labels[String(status)] || String(status || "佐证状态未知");
}

function conflictLabel(status) {
  const labels = {
    no_conflict: "未发现相反声明",
    limited_conflict: "存在轻微冲突",
    material_conflict: "存在重要冲突，需要复核",
    seed_or_test_conflict: "冲突只来自 seed/test 场景"
  };
  return labels[String(status)] || String(status || "冲突状态未知");
}

function reliabilityBand(value) {
  const score = Number(value);
  if (!Number.isFinite(score)) {
    return "未记录";
  }
  if (score >= 0.82) {
    return "高";
  }
  if (score >= 0.65) {
    return "中";
  }
  if (score > 0) {
    return "低";
  }
  return "未记录";
}

function relevanceBand(value) {
  const score = Number(value);
  if (!Number.isFinite(score)) {
    return "未记录";
  }
  if (score >= 0.78) {
    return "高度相关";
  }
  if (score >= 0.55) {
    return "相关";
  }
  if (score > 0) {
    return "弱相关";
  }
  return "未记录";
}

function permissionLabel(permission) {
  const labels = {
    blocked: "不允许更新",
    weak_update: "弱更新",
    normal_update: "正常更新",
    strong_update: "强更新"
  };
  return labels[String(permission)] || String(permission || "权限未知");
}

function reasonLabel(reason) {
  const labels = {
    source_backed_timing_data: "计时数据来源",
    specific_event_observation: "本场观测",
    structured_recent_results: "近期结构化成绩",
    source_backed_points_or_classification: "积分/排名来源",
    recent_window_structured_feature: "近期窗口特征",
    low_confidence_context_feature: "低置信背景特征",
    unscored_codex_claim: "待质量评分",
    claim_requires_review: "声明需要复核",
    single_source_claim: "单一来源",
    seed_scenario_source: "种子场景来源，已阻断入模",
    source_log_missing: "缺少来源日志",
    seed_only_triangulation: "仅 seed/test 佐证",
    claim_not_linked_to_source_record: "声明未链接到来源记录",
    claim_after_cutoff: "声明晚于知识截止",
    source_after_cutoff: "来源晚于知识截止",
    snapshot_after_cutoff: "快照晚于知识截止"
  };
  return labels[String(reason)] || String(reason || "质量理由");
}

function surfaceLabel(surface) {
  const labels = {
    race_pace_score: "正赛速度",
    qualifying_grid_sampler: "排位/发车位",
    stint_degradation: "轮胎衰退",
    strategy_plan: "策略计划",
    pit_strategy: "进站策略",
    safety_car_window: "安全车窗口",
    dnf_sampler: "退赛采样",
    wet_race_branch: "湿地分支"
  };
  return labels[String(surface)] || String(surface || "模型表面");
}

function predictionDeltaText(row) {
  const driver = driverNames[row.driver_id] || row.driver_id || "车手";
  const delta = Number(row.expected_points_delta);
  const direction = delta > 0.03 ? "完整预测更高" : delta < -0.03 ? "完整预测更低" : "接近不变";
  return `${driver} ${direction} ${pointsDeltaBucket(delta)}`;
}

function rankDeltaText(row) {
  const driver = driverNames[row.driver_id] || row.driver_id || "车手";
  const delta = Number(row.expected_rank_delta);
  if (!Number.isFinite(delta) || delta === 0) {
    return `${driver} 排名接近不变`;
  }
  return `${driver} ${delta < 0 ? "排名改善" : "排名下降"} ${Math.abs(delta)} 位`;
}

function pointsDeltaBucket(delta) {
  const value = Math.abs(Number(delta) || 0);
  if (value >= 2) {
    return "大幅";
  }
  if (value >= 0.6) {
    return "中等";
  }
  if (value >= 0.1) {
    return "小幅";
  }
  return "很小";
}

function shortHash(value) {
  if (!value) {
    return "n/a";
  }
  const text = String(value);
  return text.length > 18 ? `${text.slice(0, 15)}...` : text;
}

function pct(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${(number * 100).toFixed(1)}%` : "n/a";
}

function signedPct(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "n/a";
  }
  const sign = number >= 0 ? "+" : "";
  return `${sign}${(number * 100).toFixed(1)}pp`;
}

function signedNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "n/a";
  }
  const sign = number >= 0 ? "+" : "";
  return `${sign}${number.toFixed(3)}`;
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes >= 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  if (bytes >= 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${bytes} B`;
}

function eventTitle(eventId) {
  const event = state.events.find(item => item.event_id === eventId);
  return event ? event.name : eventId;
}

function safeJson(value) {
  if (!value) {
    return {};
  }
  if (typeof value === "object") {
    return value;
  }
  try {
    return JSON.parse(value);
  } catch {
    return {};
  }
}

function freezeFlagText(flag) {
  if (flag === "formal_edge_claim_not_ready") {
    return "The current replay is still diagnostic because formal readiness has unresolved blockers.";
  }
  if (flag === "probability_calibration_diagnostic_only") {
    return "Calibration output is not strong enough to support formal probability or edge claims.";
  }
  if (String(flag).startsWith("readiness_blockers:")) {
    return "Formal readiness still has blocking input actions that must be resolved first.";
  }
  if (String(flag).startsWith("missing_report:")) {
    return "A required replay report was missing when this manifest was built.";
  }
  return "Review this reproducibility flag before treating the replay as formal evidence.";
}

function shortDate(value) {
  if (!value) {
    return "n/a";
  }
  return String(value).replace("T", " ").replace("+00:00", "Z").slice(0, 19);
}

init().catch(error => {
  document.body.innerHTML = `<pre>${error.stack || error}</pre>`;
});
