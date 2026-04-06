window.AppState = {
  currentPage: 1,
  uploadedFiles: [null, null, null, null],
  fileIds: [null, null, null, null],
  frameUrls: [null, null, null, null],
  videoUrls: [null, null, null, null],
  frameSizes: [
    { width: 0, height: 0 },
    { width: 0, height: 0 },
    { width: 0, height: 0 },
    { width: 0, height: 0 },
  ],
  roiPolygons: [[], [], [], []],
  roiClosed: [false, false, false, false],
  socket: null,
  signalStates: ["red", "red", "red", "red"],
  scores: [0, 0, 0, 0],
  greenTimes: [10, 10, 10, 10],
  waitingTimes: [0, 0, 0, 0],
  priorityScores: [0, 0, 0, 0],
  counts: [{}, {}, {}, {}],
  laneSummaries: [],
  history: [],
  selectedHistoryWindow: 10,
  runtimeConfig: null,
  activeLane: -1,
  remainingSeconds: 0,
  emergencyActive: false,
};

window.navigateTo = function navigateTo(page) {
  document.querySelectorAll(".page").forEach((section) => {
    section.classList.add("hidden");
  });
  document.getElementById(`page-${page}`).classList.remove("hidden");
  window.AppState.currentPage = page;

  if (page === 2 && typeof window.renderRoiPage === "function") {
    window.renderRoiPage();
  }
  if (page === 3 && typeof window.initDetectionPage === "function") {
    window.initDetectionPage();
  }
};

window.showError = function showError(message) {
  window.alert(message);
};

window.fetchJson = async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = "Request failed";
    try {
      const errorBody = await response.json();
      detail = errorBody.detail || JSON.stringify(errorBody);
    } catch (error) {
      detail = `${response.status} ${response.statusText}`;
    }
    throw new Error(detail);
  }
  return response.json();
};
