# Development Process

## Overview

TraffinAI is a web-based smart traffic management system for a 4-lane intersection.

The application allows a user to:

1. Upload 4 lane videos
2. Draw one ROI polygon per lane
3. Start live vehicle detection
4. Run a traffic-signal controller based on weighted lane pressure
5. Trigger emergency vehicle preemption
6. Review live counts, signal state, lane analytics, logs, and runtime config

The project is built as a single FastAPI application with a plain HTML/CSS/JavaScript frontend and a multiprocessing backend for video processing.

---

## Current Tech Stack

### Backend

- `FastAPI` for REST APIs
- `python-socketio` for real-time UI updates
- `OpenCV` for video decoding and frame extraction
- `Ultralytics YOLO` for inference
- Python `multiprocessing` for lane workers and inference process

### Frontend

- Plain `HTML`
- Plain `CSS`
- Plain `JavaScript`
- No build step
- No React
- No npm dependency chain

---

## Project Goals

The current implementation is focused on:

- clear separation between upload, ROI, and monitoring flow
- CPU-safe inference orchestration
- fairer signal allocation using pressure score plus waiting time
- emergency override support
- a dashboard-style monitoring experience for operators
- runtime tuning through a Config tab

---

## Folder Structure

```text
TraffinAI/
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── inference_server.py
│   ├── worker.py
│   ├── signal_controller.py
│   ├── model_loader.py
│   ├── requirements.txt
│   └── models/
│       ├── model1.pt
│       └── model2.pt
├── frontend/
│   ├── index.html
│   ├── css/
│   │   └── style.css
│   └── js/
│       ├── app.js
│       ├── upload.js
│       ├── roi.js
│       └── detection.js
├── uploads/
├── roi_data/
├── data/
├── README.md
├── PROJECT.md
└── DEVELOPMENT_PROCESS.md
```

---

## How The System Works

## 1. Upload Flow

The user uploads 4 videos, one per lane.

Backend behavior:

- validates file type
- saves the uploaded video in `uploads/`
- extracts the first frame using OpenCV
- stores the extracted frame in `uploads/frames/`

Frontend behavior:

- shows preview thumbnails
- stores uploaded file metadata in client state
- moves to ROI page once all 4 lanes are ready

Relevant files:

- [backend/main.py](d:/4-2%20Projects/TraffinAI/backend/main.py)
- [frontend/js/upload.js](d:/4-2%20Projects/TraffinAI/frontend/js/upload.js)

---

## 2. ROI Drawing Flow

The user draws one polygon region per lane. Only vehicles inside this region should contribute to detection and scoring.

Backend behavior:

- accepts ROI polygons as normalized coordinates
- stores them in `roi_data/roi_<lane>.json`

Frontend behavior:

- overlays a canvas on each first-frame image
- records clicks as normalized `0..1` coordinates
- clamps values before submission to avoid invalid coordinates

Relevant files:

- [backend/main.py](d:/4-2%20Projects/TraffinAI/backend/main.py)
- [frontend/js/roi.js](d:/4-2%20Projects/TraffinAI/frontend/js/roi.js)

---

## 3. Detection Runtime

Once detection starts, the backend launches:

- 1 inference process
- 4 lane worker processes
- 1 signal controller async loop
- 1 WebSocket broadcast loop

### Lane worker responsibilities

Each lane worker:

- opens its assigned video
- loops the video when it ends
- skips frames based on `FRAME_SKIP`
- applies the lane ROI mask
- sends masked frames to the inference process
- receives merged detections back
- counts classes
- emits detection payloads to the UI
- raises emergency alerts when needed

Relevant file:

- [backend/worker.py](d:/4-2%20Projects/TraffinAI/backend/worker.py)

### Inference process responsibilities

The inference process:

- loads both YOLO models
- runs Model 1 for general vehicle classes
- runs Model 2 for `auto_rickshaw` and `emergency_vehicle`
- merges detections
- applies NMS
- routes results back to the correct lane

Important design detail:

- Model 1 is restricted to vehicle-only class IDs
- inference is centralized to avoid multi-process model contention on CPU

Relevant files:

- [backend/inference_server.py](d:/4-2%20Projects/TraffinAI/backend/inference_server.py)
- [backend/model_loader.py](d:/4-2%20Projects/TraffinAI/backend/model_loader.py)

---

## 4. Signal Controller Logic

The signal controller is responsible for deciding:

- which lane gets green
- for how long
- when to insert yellow transitions
- when to switch into emergency mode

### Base Inputs

It uses:

- current vehicle counts per lane
- vehicle weights
- waiting time since last green
- fairness settings
- emergency state

### Current priority logic

The controller computes:

1. Raw traffic score per lane
2. Waiting time per lane
3. Priority score:

```text
priority_score = traffic_score + (waiting_time * WAIT_TIME_WEIGHT)
```

It then:

- blocks consecutive greens if `BLOCK_CONSECUTIVE_GREEN = True`
- chooses the next active lane using priority score
- allocates green time using proportional distribution

### Emergency logic

If an emergency vehicle is detected:

- normal cycle is interrupted
- emergency lane turns green immediately
- all other lanes turn red
- controller stays in emergency mode until the hold duration expires and the emergency signal goes stale

Relevant file:

- [backend/signal_controller.py](d:/4-2%20Projects/TraffinAI/backend/signal_controller.py)

---

## Frontend Structure

The frontend is organized into three functional stages.

## Page 1: Upload

- implemented in `upload.js`
- lane file selection
- local previews
- upload API calls

## Page 2: ROI

- implemented in `roi.js`
- polygon drawing
- normalized coordinate generation

## Page 3: Monitoring

- implemented in `detection.js`
- live video grid
- live detection boxes
- traffic lights
- waiting time display
- lane analytics
- operations log drawer
- runtime config tab

The root shell is in:

- [frontend/index.html](d:/4-2%20Projects/TraffinAI/frontend/index.html)

Styling is in:

- [frontend/css/style.css](d:/4-2%20Projects/TraffinAI/frontend/css/style.css)

---

## Page 3 Tabs

The monitoring page currently contains three tabs.

## 1. Live Grid

Shows:

- 4 lane video panels
- detection boxes
- score
- green allocation
- waited time
- per-class counts

## 2. Lane Analytics

Shows lane-wise summaries:

- green cycle count
- total vehicles passed
- emergency detections
- last green timestamp
- per-class totals

## 3. Config

Allows runtime tuning of important variables such as:

- `G_TOTAL`
- `G_MIN`
- `G_EMERGENCY`
- `YELLOW_DURATION`
- `WAIT_TIME_WEIGHT`
- `BLOCK_CONSECUTIVE_GREEN`
- `FRAME_SKIP`
- `CONFIDENCE_THRESH`
- `IOU_NMS_THRESH`
- `VEHICLE_WEIGHTS`

Important note:

- signal-model settings apply immediately
- detection-process settings affect new worker processes after restart

---

## Operations Drawer

The Operations drawer on Page 3 is the live history and summary panel.

It contains:

- lane summary cards
- recent event logs
- filter chips for:
  - under 10 min
  - under 20 min
  - under 30 min
  - under 40 min

It is designed to:

- match the height of the main monitoring block
- keep a fixed panel height
- scroll the inner history region when logs increase

---

## Runtime State

This project does not currently use a persistent database.

Most runtime state is held in memory in `app_state` inside:

- [backend/main.py](d:/4-2%20Projects/TraffinAI/backend/main.py)

This includes:

- uploaded video paths
- ROI polygons
- active process references
- counts
- scores
- signal states
- lane summaries
- event history
- runtime config snapshot

Persistence right now is limited to:

- uploaded videos
- saved ROI JSON files
- extracted frame images

---

## Configuration Model

There are two layers of configuration.

## 1. Static defaults

Defined in:

- [backend/config.py](d:/4-2%20Projects/TraffinAI/backend/config.py)

These are the startup defaults for:

- signal timing
- fairness
- detection thresholds
- model paths
- class mappings
- vehicle weights

## 2. Runtime overrides

Exposed through:

- `GET /api/config`
- `POST /api/config`

These let the UI modify live settings without editing Python files manually.

---

## API Summary

## Upload and ROI

- `POST /api/upload`
- `GET /api/frame/{lane_id}`
- `POST /api/roi`

## Runtime control

- `POST /api/start`
- `POST /api/stop`
- `GET /api/status`
- `GET /api/config`
- `POST /api/config`
- `GET /api/health`

## Socket events used by the UI

- `detection_frame`
- `signal_update`
- `timer_tick`
- `emergency_alert`
- `history_update`
- `worker_error`

---

## Development Setup

## Recommended Python Version

Use Python `3.12`.

Why:

- model/runtime compatibility is much smoother than Python 3.13+ for the pinned ecosystem
- older YOLO and NumPy combinations are less painful on 3.12

## Initial setup

```powershell
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r backend/requirements.txt
```

## Run locally

```powershell
.\venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Open:

```text
http://localhost:8000
```

---

## Suggested First-Time Test Flow

After cloning and starting the app:

1. Open the browser
2. Upload 4 lane videos
3. Draw ROI polygons
4. Start detection
5. Verify live boxes appear
6. Verify signal lights change
7. Verify operations drawer logs are updating
8. Open the Analytics tab
9. Open the Config tab and test a small value change

---

## Common Development Tasks

## Change signal math

Look at:

- [backend/signal_controller.py](d:/4-2%20Projects/TraffinAI/backend/signal_controller.py)
- [backend/config.py](d:/4-2%20Projects/TraffinAI/backend/config.py)

## Change detection class mapping

Look at:

- [backend/config.py](d:/4-2%20Projects/TraffinAI/backend/config.py)
- [backend/inference_server.py](d:/4-2%20Projects/TraffinAI/backend/inference_server.py)

## Change the dashboard UI

Look at:

- [frontend/index.html](d:/4-2%20Projects/TraffinAI/frontend/index.html)
- [frontend/css/style.css](d:/4-2%20Projects/TraffinAI/frontend/css/style.css)
- [frontend/js/detection.js](d:/4-2%20Projects/TraffinAI/frontend/js/detection.js)

## Change upload or ROI behavior

Look at:

- [frontend/js/upload.js](d:/4-2%20Projects/TraffinAI/frontend/js/upload.js)
- [frontend/js/roi.js](d:/4-2%20Projects/TraffinAI/frontend/js/roi.js)
- [backend/main.py](d:/4-2%20Projects/TraffinAI/backend/main.py)

---

## Known Design Decisions

These choices are intentional in the current implementation.

### Plain frontend

The UI uses plain JavaScript to keep the project simple to clone and run.

### No annotated frame streaming

Only metadata is sent over Socket.IO.

The browser draws:

- boxes
- labels
- traffic light state

This avoids expensive backend frame re-encoding.

### In-memory history

Lane history and summaries are session-based right now.

If the server restarts, history resets.

### Runtime config is not persisted yet

Config changes currently affect the running process only.

If persistence is needed later, a JSON-backed config store is the most natural next step.

---

## Debugging Notes

If detection looks idle:

- check whether the models loaded successfully
- confirm the worker processes started
- check browser console and server console for `worker_error`
- verify the ROI is not excluding the whole lane

If uploads fail:

- check supported file extensions
- check write permissions in `uploads/`

If ROI fails:

- ensure coordinates are normalized
- ensure at least 3 polygon points exist

If the UI looks stale:

- verify Socket.IO connection
- verify `signal_update` and `detection_frame` events are arriving

---

## Recommended Next Improvements

Good next steps for future contributors:

1. Persist runtime config to disk
2. Persist history logs to disk or database
3. Add export for analytics/logs
4. Add better per-lane throughput estimation
5. Add automated tests for signal-controller math
6. Add model health checks before detection start
7. Clean old uploads automatically

---

## Quick Mental Model For New Contributors

If you only remember one thing, remember this:

- `main.py` orchestrates the app
- `worker.py` reads lane videos
- `inference_server.py` runs the models
- `signal_controller.py` decides signals
- `detection.js` powers the live dashboard

That mental model is enough to start navigating the project productively.
