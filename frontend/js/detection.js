(function () {
  const detectionGrid = document.getElementById("detection-grid");
  const cycleSummary = document.getElementById("cycle-summary");
  const remainingTime = document.getElementById("remaining-time");
  const systemMode = document.getElementById("system-mode");
  const emergencyBanner = document.getElementById("emergency-banner");
  const stopButton = document.getElementById("stop-btn");
  const analyticsGrid = document.getElementById("analytics-grid");
  const monitorMain = document.getElementById("monitor-main");
  const laneSummaryList = document.getElementById("lane-summary-list");
  const historyList = document.getElementById("history-list");
  const selectedWindow = document.getElementById("selected-window");
  const logDrawer = document.getElementById("log-drawer");
  const toggleLogDrawer = document.getElementById("toggle-log-drawer");
  const closeLogDrawer = document.getElementById("close-log-drawer");
  const configForm = document.getElementById("config-form");
  const saveConfigButton = document.getElementById("save-config-btn");
  const configMessage = document.getElementById("config-message");
  let initialized = false;

  const classColors = {
    emergency_vehicle: "#E24B4A",
    truck: "#BA7517",
    bus: "#BA7517",
    car: "#378ADD",
    auto_rickshaw: "#1D9E75",
    motorcycle: "#7F77DD",
    bicycle: "#7F77DD",
  };
  const countClasses = ["car", "truck", "bus", "auto_rickshaw", "motorcycle", "bicycle", "emergency_vehicle"];
  const numericConfigFields = [
    ["G_TOTAL", "Total cycle budget (s)", "Signal math", "number", "Applied live"],
    ["G_MIN", "Minimum green per lane (s)", "Signal math", "number", "Applied live"],
    ["G_EMERGENCY", "Emergency green hold (s)", "Signal math", "number", "Applied live"],
    ["YELLOW_DURATION", "Yellow transition (s)", "Signal math", "number", "Applied live"],
    ["WAIT_TIME_WEIGHT", "Wait-time weight", "Fairness", "number", "Applied live"],
    ["FRAME_SKIP", "Frame skip", "Detection", "number", "Requires restart"],
    ["CONFIDENCE_THRESH", "Confidence threshold", "Detection", "number", "Requires restart"],
    ["IOU_NMS_THRESH", "NMS IoU threshold", "Detection", "number", "Requires restart"],
  ];
  const weightFields = [
    ["truck", "Truck weight"],
    ["bus", "Bus weight"],
    ["car", "Car weight"],
    ["auto_rickshaw", "Auto-rickshaw weight"],
    ["motorcycle", "Motorcycle weight"],
    ["bicycle", "Bicycle weight"],
  ];

  function formatClock(timestamp) {
    if (!timestamp) {
      return "Never";
    }
    return new Date(timestamp * 1000).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }

  function showConfigMessage(message, isError = false) {
    configMessage.textContent = message;
    configMessage.classList.remove("hidden", "error");
    if (isError) {
      configMessage.classList.add("error");
    }
  }

  function renderConfigForm(configData) {
    if (!configForm || !configData) {
      return;
    }
    window.AppState.runtimeConfig = configData;

    const fieldsHtml = numericConfigFields
      .map(
        ([key, label, group, type, note]) => `
          <label class="config-card">
            <span class="config-group">${group}</span>
            <span class="config-label">${label}</span>
            <input class="config-input" name="${key}" type="${type}" step="any" value="${configData[key]}" />
            <span class="config-note">${note}</span>
          </label>
        `,
      )
      .join("");

    const weightsHtml = weightFields
      .map(
        ([key, label]) => `
          <label class="config-card">
            <span class="config-group">Vehicle weights</span>
            <span class="config-label">${label}</span>
            <input class="config-input" name="weight_${key}" type="number" step="any" value="${configData.VEHICLE_WEIGHTS[key]}" />
            <span class="config-note">Applied live</span>
          </label>
        `,
      )
      .join("");

    configForm.innerHTML = `
      ${fieldsHtml}
      <label class="config-card config-card-toggle">
        <span class="config-group">Fairness</span>
        <span class="config-label">Block consecutive greens</span>
        <select class="config-input" name="BLOCK_CONSECUTIVE_GREEN">
          <option value="true" ${configData.BLOCK_CONSECUTIVE_GREEN ? "selected" : ""}>Enabled</option>
          <option value="false" ${!configData.BLOCK_CONSECUTIVE_GREEN ? "selected" : ""}>Disabled</option>
        </select>
        <span class="config-note">Applied live</span>
      </label>
      ${weightsHtml}
      <label class="config-card config-card-disabled">
        <span class="config-group">Reserved</span>
        <span class="config-label">Emergency vehicle weight</span>
        <input class="config-input" value="Hard override" disabled />
        <span class="config-note">Always excluded from score</span>
      </label>
    `;
  }

  async function loadRuntimeConfig() {
    const response = await window.fetchJson("/api/config");
    renderConfigForm(response.config);
  }

  function readConfigPayload() {
    const form = new FormData(configForm);
    return {
      G_TOTAL: Number(form.get("G_TOTAL")),
      G_MIN: Number(form.get("G_MIN")),
      G_EMERGENCY: Number(form.get("G_EMERGENCY")),
      YELLOW_DURATION: Number(form.get("YELLOW_DURATION")),
      WAIT_TIME_WEIGHT: Number(form.get("WAIT_TIME_WEIGHT")),
      BLOCK_CONSECUTIVE_GREEN: form.get("BLOCK_CONSECUTIVE_GREEN") === "true",
      FRAME_SKIP: Number(form.get("FRAME_SKIP")),
      CONFIDENCE_THRESH: Number(form.get("CONFIDENCE_THRESH")),
      IOU_NMS_THRESH: Number(form.get("IOU_NMS_THRESH")),
      VEHICLE_WEIGHTS: {
        truck: Number(form.get("weight_truck")),
        bus: Number(form.get("weight_bus")),
        car: Number(form.get("weight_car")),
        auto_rickshaw: Number(form.get("weight_auto_rickshaw")),
        motorcycle: Number(form.get("weight_motorcycle")),
        bicycle: Number(form.get("weight_bicycle")),
        emergency_vehicle: null,
      },
    };
  }

  function getFilteredHistory() {
    const minutes = window.AppState.selectedHistoryWindow;
    const cutoff = Date.now() - minutes * 60 * 1000;
    return (window.AppState.history || []).filter((item) => item.timestamp * 1000 >= cutoff);
  }

  function renderHistoryDrawer() {
    const filteredHistory = getFilteredHistory()
      .sort((a, b) => b.timestamp - a.timestamp)
      .slice(0, 80);

    selectedWindow.textContent = `Last ${window.AppState.selectedHistoryWindow} minutes`;

    laneSummaryList.innerHTML = (window.AppState.laneSummaries || [])
      .map((summary) => `
        <article class="lane-summary-card">
          <div class="lane-summary-header">
            <strong>Lane ${summary.lane_id + 1}</strong>
            <span class="time-stamp">Last green: ${formatClock(summary.last_green_at)}</span>
          </div>
          <div class="lane-summary-meta">
            <span class="meta-pill">Green cycles: ${summary.green_count}</span>
            <span class="meta-pill">Vehicles passed: ${summary.total_vehicles_passed}</span>
            <span class="meta-pill">Emergency alerts: ${summary.emergency_count}</span>
          </div>
        </article>
      `)
      .join("");

    historyList.innerHTML = filteredHistory.length
      ? filteredHistory
          .map((item) => `
            <article class="history-item">
              <div class="history-item-head">
                <strong>Lane ${item.lane_id + 1} · ${item.event_type.replaceAll("_", " ")}</strong>
                <span class="time-stamp">${formatClock(item.timestamp)}</span>
              </div>
              <p>${item.message}</p>
            </article>
          `)
          .join("")
      : `<article class="history-item"><p>No history in this time window yet.</p></article>`;
  }

  function renderAnalytics() {
    analyticsGrid.innerHTML = (window.AppState.laneSummaries || [])
      .map((summary) => {
        const classRows = countClasses
          .map((className) => {
            const label = className.replaceAll("_", " ");
            const value = summary.class_totals?.[className] || 0;
            return `<div class="analytics-row"><span>${label}</span><strong>${value}</strong></div>`;
          })
          .join("");

        return `
          <article class="analytics-card">
            <h4>Lane ${summary.lane_id + 1}</h4>
            <div class="analytics-list">
              <div class="analytics-row"><span>Green cycles</span><strong>${summary.green_count}</strong></div>
              <div class="analytics-row"><span>Total vehicles passed</span><strong>${summary.total_vehicles_passed}</strong></div>
              <div class="analytics-row"><span>Emergency detections</span><strong>${summary.emergency_count}</strong></div>
              <div class="analytics-row"><span>Last green</span><strong>${formatClock(summary.last_green_at)}</strong></div>
              ${classRows}
            </div>
          </article>
        `;
      })
      .join("");
  }

  function syncLogDrawerHeight() {
    if (!monitorMain || !logDrawer || window.innerWidth <= 900 || logDrawer.classList.contains("closed")) {
      if (logDrawer) {
        logDrawer.style.height = "";
      }
      return;
    }

    const mainHeight = monitorMain.getBoundingClientRect().height;
    if (mainHeight > 0) {
      logDrawer.style.height = `${Math.round(mainHeight)}px`;
    }
  }

  function hydrateHistory(data) {
    if (data.history) {
      window.AppState.history = data.history;
    }
    if (data.lane_summaries) {
      window.AppState.laneSummaries = data.lane_summaries;
    }
    renderHistoryDrawer();
    renderAnalytics();
    syncLogDrawerHeight();
    if (data.runtime_config) {
      renderConfigForm(data.runtime_config);
    }
  }

  function formatWait(seconds, laneIndex) {
    if (window.AppState.activeLane === laneIndex && !window.AppState.emergencyActive) {
      return "Active now";
    }
    if (window.AppState.activeLane === laneIndex && window.AppState.emergencyActive) {
      return "Emergency green";
    }
    return `${Math.max(0, Number(seconds) || 0)}s waited`;
  }

  function renderCounts(laneIndex, counts = {}) {
    const container = document.getElementById(`counts-${laneIndex}`);
    if (!container) {
      return;
    }

    container.innerHTML = countClasses
      .map((className) => {
        const value = counts[className] || 0;
        const label = className.replaceAll("_", " ");
        return `<span class="count-pill"><strong>${label}:</strong> ${value}</span>`;
      })
      .join("");
  }

  function buildDetectionCards() {
    detectionGrid.innerHTML = "";
    for (let laneIndex = 0; laneIndex < 4; laneIndex += 1) {
      const card = document.createElement("article");
      card.className = "lane-card";
      card.id = `lane-block-${laneIndex}`;
      card.innerHTML = `
        <div class="lane-header">
          <div>
            <h3 class="lane-title">Lane ${laneIndex + 1}</h3>
            <p class="lane-status">Live detections inside ROI</p>
          </div>
          <div class="traffic-light">
            <div class="light red" id="light-${laneIndex}-red"></div>
            <div class="light yellow" id="light-${laneIndex}-yellow"></div>
            <div class="light green" id="light-${laneIndex}-green"></div>
          </div>
        </div>
        <div class="video-container">
          <video id="video-${laneIndex}" autoplay muted loop playsinline src="${window.AppState.videoUrls[laneIndex] || ""}"></video>
          <canvas id="canvas-${laneIndex}" class="overlay-canvas"></canvas>
        </div>
        <div class="lane-stats">
          <span>Score: <strong id="score-${laneIndex}">0.0</strong></span>
          <span>Green: <strong id="green-time-${laneIndex}">10</strong>s</span>
          <span>Waited: <strong id="wait-time-${laneIndex}">0s waited</strong></span>
        </div>
        <div class="count-list" id="counts-${laneIndex}"></div>
      `;
      detectionGrid.appendChild(card);

      const video = document.getElementById(`video-${laneIndex}`);
      const canvas = document.getElementById(`canvas-${laneIndex}`);
      video.addEventListener("loadedmetadata", () => {
        canvas.width = video.clientWidth;
        canvas.height = video.clientHeight;
      });
      window.addEventListener("resize", () => {
        canvas.width = video.clientWidth;
        canvas.height = video.clientHeight;
      });
      renderCounts(laneIndex, {});
    }
  }

  function updateTrafficLight(laneIndex, state) {
    ["red", "yellow", "green"].forEach((color) => {
      const light = document.getElementById(`light-${laneIndex}-${color}`);
      if (light) {
        light.classList.toggle("active", color === state);
      }
    });
  }

  function drawBoundingBoxes(canvas, boxes, frameWidth, frameHeight) {
    if (!canvas) {
      return;
    }

    const context = canvas.getContext("2d");
    canvas.width = canvas.clientWidth;
    canvas.height = canvas.clientHeight;
    context.clearRect(0, 0, canvas.width, canvas.height);

    boxes.forEach((box) => {
      const color = classColors[box.class_name] || "#1f6d5a";
      const x = (box.x1 / frameWidth) * canvas.width;
      const y = (box.y1 / frameHeight) * canvas.height;
      const w = ((box.x2 - box.x1) / frameWidth) * canvas.width;
      const h = ((box.y2 - box.y1) / frameHeight) * canvas.height;

      context.strokeStyle = color;
      context.lineWidth = 2;
      context.strokeRect(x, y, w, h);

      const label = `${box.class_name} ${Math.round(box.confidence * 100)}%`;
      context.font = "12px Georgia";
      const textWidth = context.measureText(label).width + 10;
      context.fillStyle = color;
      context.fillRect(x, Math.max(0, y - 20), textWidth, 18);
      context.fillStyle = "#fff";
      context.fillText(label, x + 5, Math.max(12, y - 7));
    });
  }

  function applySignalUpdate(data) {
    window.AppState.signalStates = data.signal_states;
    window.AppState.activeLane = data.active_lane;
    window.AppState.remainingSeconds = data.remaining_seconds;
    window.AppState.scores = data.scores;
    window.AppState.greenTimes = data.green_times;
    window.AppState.waitingTimes = data.waiting_times || [0, 0, 0, 0];
    window.AppState.priorityScores = data.priority_scores || [0, 0, 0, 0];
    window.AppState.emergencyActive = data.emergency_active;
    hydrateHistory(data);

    data.signal_states.forEach((state, laneIndex) => updateTrafficLight(laneIndex, state));
    data.scores.forEach((score, laneIndex) => {
      document.getElementById(`score-${laneIndex}`).textContent = Number(score).toFixed(1);
    });
    data.green_times.forEach((seconds, laneIndex) => {
      document.getElementById(`green-time-${laneIndex}`).textContent = seconds;
    });
    window.AppState.waitingTimes.forEach((seconds, laneIndex) => {
      document.getElementById(`wait-time-${laneIndex}`).textContent = formatWait(seconds, laneIndex);
    });

    cycleSummary.textContent =
      data.active_lane >= 0 ? `Lane ${data.active_lane + 1} active` : "Waiting for signal data";
    remainingTime.textContent = `${data.remaining_seconds || 0}s`;
    systemMode.textContent = data.emergency_active ? "Emergency Override" : "Normal";
  }

  function onDetectionFrame(data) {
    const canvas = document.getElementById(`canvas-${data.lane_id}`);
    drawBoundingBoxes(canvas, data.boxes, data.frame_width, data.frame_height);
    document.getElementById(`score-${data.lane_id}`).textContent = Number(data.score).toFixed(1);
    window.AppState.counts[data.lane_id] = data.counts || {};
    renderCounts(data.lane_id, data.counts || {});
  }

  function onEmergencyAlert(data) {
    emergencyBanner.classList.remove("hidden");
    emergencyBanner.textContent = `Emergency vehicle detected on Lane ${data.lane_id + 1}. Signal preemption engaged.`;

    const laneBlock = document.getElementById(`lane-block-${data.lane_id}`);
    laneBlock.classList.add("emergency-flash");
    setTimeout(() => laneBlock.classList.remove("emergency-flash"), 5000);
    setTimeout(() => {
      if (!window.AppState.emergencyActive) {
        emergencyBanner.classList.add("hidden");
      }
    }, 6000);
  }

  function onWorkerError(data) {
    emergencyBanner.classList.remove("hidden");
    emergencyBanner.textContent = data.message || `Processing failed on Lane ${data.lane_id + 1}.`;
    systemMode.textContent = "Error";
  }

  async function startBackendDetection() {
    await window.fetchJson("/api/start", { method: "POST" });
    const status = await window.fetchJson("/api/status");
    applySignalUpdate({
      signal_states: status.signal_states,
      active_lane: status.active_lane,
      remaining_seconds: status.remaining_seconds,
      scores: status.scores,
      green_times: status.green_times,
      waiting_times: status.waiting_times,
      priority_scores: status.priority_scores,
      lane_summaries: status.lane_summaries,
      history: status.history,
      emergency_active: status.emergency_active,
    });
    (status.counts || []).forEach((counts, laneIndex) => {
      window.AppState.counts[laneIndex] = counts || {};
      renderCounts(laneIndex, counts || {});
    });
    status.video_urls.forEach((url, laneIndex) => {
      const video = document.getElementById(`video-${laneIndex}`);
      if (video && url) {
        video.src = url;
      }
    });
  }

  window.initDetectionPage = async function initDetectionPage() {
    if (!initialized) {
      buildDetectionCards();
      await loadRuntimeConfig();
      initialized = true;
      syncLogDrawerHeight();
    }

    try {
      await startBackendDetection();
    } catch (error) {
      if (String(error.message).includes("already running")) {
        const status = await window.fetchJson("/api/status");
        applySignalUpdate({
          signal_states: status.signal_states,
          active_lane: status.active_lane,
          remaining_seconds: status.remaining_seconds,
          scores: status.scores,
          green_times: status.green_times,
          waiting_times: status.waiting_times,
          priority_scores: status.priority_scores,
          lane_summaries: status.lane_summaries,
          history: status.history,
          emergency_active: status.emergency_active,
        });
        (status.counts || []).forEach((counts, laneIndex) => {
          window.AppState.counts[laneIndex] = counts || {};
          renderCounts(laneIndex, counts || {});
        });
      } else {
        window.showError(error.message);
      }
    }

    if (!window.AppState.socket) {
      window.AppState.socket = io(window.location.origin);
      window.AppState.socket.on("detection_frame", onDetectionFrame);
      window.AppState.socket.on("signal_update", applySignalUpdate);
      window.AppState.socket.on("history_update", hydrateHistory);
      window.AppState.socket.on("timer_tick", (data) => {
        remainingTime.textContent = `${data.remaining_seconds}s`;
        systemMode.textContent = data.emergency_active ? "Emergency Override" : "Normal";
        if (data.waiting_times) {
          window.AppState.waitingTimes = data.waiting_times;
          data.waiting_times.forEach((seconds, laneIndex) => {
            document.getElementById(`wait-time-${laneIndex}`).textContent = formatWait(seconds, laneIndex);
          });
        }
      });
      window.AppState.socket.on("emergency_alert", onEmergencyAlert);
      window.AppState.socket.on("worker_error", onWorkerError);
    } else {
      window.AppState.socket.emit("request_status", { event: "request_status" });
    }
  };

  document.querySelectorAll(".tab-btn").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((item) => item.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.add("hidden"));
      button.classList.add("active");
      document.getElementById(button.dataset.tab).classList.remove("hidden");
      setTimeout(syncLogDrawerHeight, 0);
    });
  });

  document.querySelectorAll(".filter-chip").forEach((button) => {
    button.addEventListener("click", () => {
      window.AppState.selectedHistoryWindow = Number(button.dataset.window);
      document.querySelectorAll(".filter-chip").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      renderHistoryDrawer();
      syncLogDrawerHeight();
    });
  });

  toggleLogDrawer.addEventListener("click", () => {
    logDrawer.classList.toggle("closed");
    toggleLogDrawer.textContent = logDrawer.classList.contains("closed") ? "Open Logs" : "Hide Logs";
    setTimeout(syncLogDrawerHeight, 0);
  });

  closeLogDrawer.addEventListener("click", () => {
    logDrawer.classList.add("closed");
    toggleLogDrawer.textContent = "Open Logs";
    syncLogDrawerHeight();
  });

  saveConfigButton.addEventListener("click", async () => {
    try {
      saveConfigButton.disabled = true;
      saveConfigButton.textContent = "Saving...";
      const payload = readConfigPayload();
      const response = await window.fetchJson("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      renderConfigForm(response.config);
      showConfigMessage(response.message || "Configuration updated.");
    } catch (error) {
      showConfigMessage(error.message, true);
    } finally {
      saveConfigButton.disabled = false;
      saveConfigButton.textContent = "Save Config";
    }
  });

  stopButton.addEventListener("click", async () => {
    try {
      await window.fetchJson("/api/stop", { method: "POST" });
      emergencyBanner.classList.add("hidden");
      cycleSummary.textContent = "System stopped";
      remainingTime.textContent = "0s";
      systemMode.textContent = "Stopped";
      window.AppState.signalStates = ["red", "red", "red", "red"];
      for (let laneIndex = 0; laneIndex < 4; laneIndex += 1) {
        updateTrafficLight(laneIndex, "red");
        const canvas = document.getElementById(`canvas-${laneIndex}`);
        if (canvas) {
          const context = canvas.getContext("2d");
          context.clearRect(0, 0, canvas.width, canvas.height);
        }
      }
    } catch (error) {
      window.showError(error.message);
    }
  });

  window.addEventListener("resize", () => {
    syncLogDrawerHeight();
  });
})();
