(function () {
  const allowedExtensions = [".mp4", ".avi", ".mov", ".mkv"];
  const grid = document.getElementById("upload-grid");
  const nextButton = document.getElementById("upload-next-btn");

  function buildUploadCards() {
    grid.innerHTML = "";

    for (let laneIndex = 0; laneIndex < 4; laneIndex += 1) {
      const card = document.createElement("article");
      card.className = "lane-card";
      card.innerHTML = `
        <div class="lane-header">
          <div>
            <h3 class="lane-title">Lane ${laneIndex + 1}</h3>
            <p class="lane-status" id="upload-status-${laneIndex}">Waiting for file</p>
          </div>
        </div>
        <div class="upload-preview">
          <img id="upload-preview-${laneIndex}" alt="Lane ${laneIndex + 1} preview" />
        </div>
        <div class="upload-meta">
          <span class="file-name" id="upload-file-name-${laneIndex}">No file selected</span>
          <label class="file-input-label" for="file-input-${laneIndex}">Choose video</label>
          <input id="file-input-${laneIndex}" class="file-input" type="file" accept=".mp4,.avi,.mov,.mkv,video/*" />
        </div>
      `;
      grid.appendChild(card);

      card.querySelector(`#file-input-${laneIndex}`).addEventListener("change", (event) => {
        const [file] = event.target.files || [];
        if (file) {
          handleFileSelect(laneIndex, file);
        }
      });
    }
  }

  function checkAllSelected() {
    const ready = window.AppState.uploadedFiles.every(Boolean);
    nextButton.disabled = !ready;
  }

  function isValidFile(file) {
    const lower = file.name.toLowerCase();
    return allowedExtensions.some((ext) => lower.endsWith(ext));
  }

  function createVideoThumbnail(file, laneIndex) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(file);
      const video = document.createElement("video");
      video.preload = "metadata";
      video.src = url;
      video.muted = true;
      video.playsInline = true;

      video.addEventListener("loadeddata", () => {
        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const context = canvas.getContext("2d");
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        document.getElementById(`upload-preview-${laneIndex}`).src = canvas.toDataURL("image/jpeg");
        URL.revokeObjectURL(url);
        resolve();
      });

      video.addEventListener("error", () => {
        URL.revokeObjectURL(url);
        reject(new Error("Could not preview the selected video"));
      });
    });
  }

  async function handleFileSelect(laneIndex, file) {
    if (!isValidFile(file)) {
      window.showError("Please choose an MP4, AVI, MOV, or MKV video.");
      return;
    }

    window.AppState.uploadedFiles[laneIndex] = file;
    document.getElementById(`upload-file-name-${laneIndex}`).textContent = file.name;
    document.getElementById(`upload-status-${laneIndex}`).textContent = "Preview ready";

    try {
      await createVideoThumbnail(file, laneIndex);
    } catch (error) {
      window.showError(error.message);
    }

    checkAllSelected();
  }

  async function uploadAllFiles() {
    for (let laneIndex = 0; laneIndex < 4; laneIndex += 1) {
      const formData = new FormData();
      formData.append("video", window.AppState.uploadedFiles[laneIndex]);
      formData.append("lane_id", laneIndex);

      const result = await window.fetchJson("/api/upload", {
        method: "POST",
        body: formData,
      });

      window.AppState.fileIds[laneIndex] = result.file_id;
      window.AppState.frameUrls[laneIndex] = result.frame_url;
      window.AppState.videoUrls[laneIndex] = result.video_url;
      window.AppState.frameSizes[laneIndex] = {
        width: result.width,
        height: result.height,
      };
      document.getElementById(`upload-status-${laneIndex}`).textContent = "Uploaded";
    }
  }

  nextButton.addEventListener("click", async () => {
    nextButton.disabled = true;
    nextButton.textContent = "Uploading...";
    try {
      await uploadAllFiles();
      window.navigateTo(2);
    } catch (error) {
      window.showError(error.message);
      nextButton.disabled = false;
      nextButton.textContent = "Next: Draw Regions";
      return;
    }
    nextButton.textContent = "Next: Draw Regions";
    nextButton.disabled = false;
  });

  buildUploadCards();
})();
