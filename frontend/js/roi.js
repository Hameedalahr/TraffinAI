(function () {
  const grid = document.getElementById("roi-grid");
  const backButton = document.getElementById("roi-back-btn");
  const startButton = document.getElementById("roi-start-btn");

  function clamp01(value) {
    return Math.min(1, Math.max(0, value));
  }

  function sanitizePolygon(points) {
    return points
      .filter((point) => Array.isArray(point) && point.length === 2)
      .map(([x, y]) => [clamp01(Number(x) || 0), clamp01(Number(y) || 0)]);
  }

  function getDefaultPolygon() {
    return [
      [0, 0],
      [1, 0],
      [1, 1],
      [0, 1],
    ];
  }

  function drawPolygon(laneIndex) {
    const canvas = document.getElementById(`roi-canvas-${laneIndex}`);
    const image = document.getElementById(`roi-image-${laneIndex}`);
    if (!canvas || !image || !image.complete) {
      return;
    }

    const context = canvas.getContext("2d");
    canvas.width = image.clientWidth;
    canvas.height = image.clientHeight;
    context.clearRect(0, 0, canvas.width, canvas.height);

    const points = window.AppState.roiPolygons[laneIndex];
    if (!points.length) {
      return;
    }

    context.lineWidth = 2;
    context.strokeStyle = "#1f6d5a";
    context.fillStyle = "rgba(55, 138, 221, 0.22)";
    context.beginPath();
    context.moveTo(points[0][0] * canvas.width, points[0][1] * canvas.height);

    points.slice(1).forEach((point) => {
      context.lineTo(point[0] * canvas.width, point[1] * canvas.height);
    });

    if (window.AppState.roiClosed[laneIndex] && points.length >= 3) {
      context.closePath();
      context.fill();
    }
    context.stroke();

    points.forEach((point) => {
      context.beginPath();
      context.arc(point[0] * canvas.width, point[1] * canvas.height, 4, 0, Math.PI * 2);
      context.fillStyle = "#1f6d5a";
      context.fill();
    });
  }

  function addCanvasHandlers(laneIndex) {
    const canvas = document.getElementById(`roi-canvas-${laneIndex}`);
    const image = document.getElementById(`roi-image-${laneIndex}`);

    canvas.addEventListener("click", (event) => {
      if (window.AppState.roiClosed[laneIndex]) {
        return;
      }

      const rect = canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) {
        return;
      }

      const x = clamp01((event.clientX - rect.left) / rect.width);
      const y = clamp01((event.clientY - rect.top) / rect.height);
      window.AppState.roiPolygons[laneIndex].push([x, y]);
      drawPolygon(laneIndex);
    });

    canvas.addEventListener("dblclick", (event) => {
      event.preventDefault();
      if (window.AppState.roiPolygons[laneIndex].length >= 3) {
        window.AppState.roiClosed[laneIndex] = true;
        drawPolygon(laneIndex);
      }
    });

    image.addEventListener("load", () => drawPolygon(laneIndex));
    window.addEventListener("resize", () => drawPolygon(laneIndex));
  }

  window.renderRoiPage = function renderRoiPage() {
    grid.innerHTML = "";

    for (let laneIndex = 0; laneIndex < 4; laneIndex += 1) {
      const card = document.createElement("article");
      card.className = "lane-card";
      card.innerHTML = `
        <div class="lane-header">
          <div>
            <h3 class="lane-title">Lane ${laneIndex + 1}</h3>
            <p class="lane-status">Use the whole frame if you leave the polygon open.</p>
          </div>
          <button class="secondary-btn" id="roi-clear-${laneIndex}">Clear</button>
        </div>
        <div class="frame-wrap">
          <img id="roi-image-${laneIndex}" src="${window.AppState.frameUrls[laneIndex]}" alt="Lane ${laneIndex + 1} frame" />
          <canvas id="roi-canvas-${laneIndex}" class="overlay-canvas"></canvas>
        </div>
        <p class="instructions">Click to add points. Double-click to close the region.</p>
      `;
      grid.appendChild(card);
      addCanvasHandlers(laneIndex);

      document.getElementById(`roi-clear-${laneIndex}`).addEventListener("click", () => {
        window.AppState.roiPolygons[laneIndex] = [];
        window.AppState.roiClosed[laneIndex] = false;
        drawPolygon(laneIndex);
      });

      drawPolygon(laneIndex);
    }
  };

  backButton.addEventListener("click", () => {
    window.navigateTo(1);
  });

  startButton.addEventListener("click", async () => {
    startButton.disabled = true;
    startButton.textContent = "Saving...";

    const rois = Array.from({ length: 4 }, (_, laneIndex) => ({
      lane_id: laneIndex,
      polygon:
        window.AppState.roiClosed[laneIndex] && window.AppState.roiPolygons[laneIndex].length >= 3
          ? sanitizePolygon(window.AppState.roiPolygons[laneIndex])
          : getDefaultPolygon(),
    }));

    try {
      await window.fetchJson("/api/roi", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rois }),
      });

      window.AppState.roiPolygons = rois.map((entry) => entry.polygon);
      window.AppState.roiClosed = [true, true, true, true];
      window.navigateTo(3);
    } catch (error) {
      window.showError(error.message);
    } finally {
      startButton.disabled = false;
      startButton.textContent = "Start Detection";
    }
  });
})();
