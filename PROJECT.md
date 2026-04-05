# Smart Traffic Management System with Emergency Vehicle Prioritization

### Complete Project Specification for Agent Build

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [System Architecture](#2-system-architecture)
3. [Technology Stack](#3-technology-stack)
4. [Project Structure](#4-project-structure)
5. [Page 1 — Video Upload](#5-page-1--video-upload)
6. [Page 2 — Region of Interest Drawing](#6-page-2--region-of-interest-drawing)
7. [Page 3 — Live Detection & Signal Control](#7-page-3--live-detection--signal-control)
8. [Mathematical Model](#8-mathematical-model)
9. [Detection Pipeline](#9-detection-pipeline)
10. [Backend API Specification](#10-backend-api-specification)
11. [WebSocket Protocol](#11-websocket-protocol)
12. [Database / State Management](#12-database--state-management)
13. [Signal Controller Logic](#13-signal-controller-logic)
14. [Emergency Vehicle Handling](#14-emergency-vehicle-handling)
15. [Frontend Component Specification](#15-frontend-component-specification)
16. [Environment & Configuration](#16-environment--configuration)
17. [Setup & Run Instructions](#17-setup--run-instructions)
18. [Key Constraints & Rules](#18-key-constraints--rules)

---

## 1. Project Overview

Build a web-based AI smart traffic management system that:

- Accepts **4 simultaneous video inputs** representing 4 road lanes at an intersection
- Runs **two YOLO-based detection models** on each video stream
- Lets the user **draw custom detection regions** (ROI) on each lane's video frame
- Displays a **live 2×2 detection grid** with bounding boxes rendered on canvas overlays
- Shows a **traffic light indicator** (red/yellow/green) beside each video block
- Uses a **mathematical formula** to compute weighted lane pressure, allocate green signal time, and sequence the lights
- Implements **emergency vehicle preemption** — any detected emergency vehicle instantly overrides the normal cycle and forces that lane green

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                        Browser                          │
│  Page 1: Upload  →  Page 2: ROI Draw  →  Page 3: Live  │
│  WebSocket client receives: boxes + signal states       │
└────────────────────────┬────────────────────────────────┘
                         │ WebSocket (JSON frames)
┌────────────────────────▼────────────────────────────────┐
│                   FastAPI Backend                        │
│                                                         │
│  ┌─────────────┐   ┌──────────────────────────────┐    │
│  │  REST API   │   │      Signal Controller        │    │
│  │  /upload    │   │  Reads count queues           │    │
│  │  /roi       │   │  Runs weighting formula       │    │
│  │  /start     │   │  Emits signal states via WS   │    │
│  └─────────────┘   └──────────────────────────────┘    │
│                                                         │
│  ┌────────────────────────────────────────────────┐     │
│  │           4 Worker Processes (multiprocessing) │     │
│  │   Worker 1 │ Worker 2 │ Worker 3 │ Worker 4    │     │
│  │   Each: decode frame → ROI crop → detect       │     │
│  │           → count → push to queue              │     │
│  └───────────────────┬────────────────────────────┘     │
│                      │ frame batches                     │
│  ┌───────────────────▼────────────────────────────┐     │
│  │         Inference Server (CPU, sequential)       │     │
│  │   Model 1 (general vehicles) + Model 2         │     │
│  │   (auto-rickshaw + emergency vehicles)          │     │
│  └────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────┘
```

### Key Architectural Decisions

- **Separate inference server** — both models run on CPU in a dedicated process; a single inference queue ensures workers never call models concurrently, avoiding GIL contention and memory spikes.
- **Worker per lane** — each lane's video is decoded and processed in an independent `multiprocessing.Process`, ensuring one slow lane never blocks another.
- **Frame skipping** — process every 3rd–5th frame (~10–15 fps effective) for detection; signal timing updates on a 2–5 second cycle, so 30fps detection is unnecessary.
- **WebSocket push** — bounding box coordinates and signal states are pushed to the browser; the browser draws boxes on a `<canvas>` overlay over the `<video>` element. Full annotated video is never re-encoded and streamed.
- **Emergency fast path** — a shared `multiprocessing.Event` is set by any worker the moment an emergency vehicle is detected; the signal controller checks this flag at the top of every cycle before the weighting formula runs.

---

## 3. Technology Stack

### Backend

| Component           | Technology                                 |
| ------------------- | ------------------------------------------ |
| Web framework       | FastAPI (Python)                           |
| WebSocket server    | `python-socketio` with `uvicorn`           |
| Video decoding      | OpenCV (`cv2`)                             |
| Detection models    | Ultralytics YOLOv8                         |
| Parallel processing | `multiprocessing` (Python stdlib)          |
| Inference device    | CPU (`torch`, no CUDA required)            |
| Data serialization  | `msgpack` for frame data, JSON for signals |

### Frontend

| Component            | Technology                                  |
| -------------------- | ------------------------------------------- |
| Framework            | Vanilla JS + HTML5 (no build step required) |
| Video display        | HTML5 `<video>` element                     |
| Bounding box overlay | HTML5 `<canvas>`                            |
| ROI drawing          | Canvas mouse events                         |
| Real-time comms      | Socket.IO client                            |
| Styling              | CSS (no external framework required)        |

### Models

| Model   | Purpose                   | Classes                              |
| ------- | ------------------------- | ------------------------------------ |
| Model 1 | General vehicle detection | Car, truck, bus, motorcycle, bicycle |
| Model 2 | Specialized detection     | Auto-rickshaw, emergency vehicle     |

---

## 4. Project Structure

```
smart_traffic/
│
├── backend/
│   ├── main.py                  # FastAPI app, WebSocket server, REST endpoints
│   ├── inference_server.py      # Sequential CPU inference process
│   ├── worker.py                # Per-lane worker process
│   ├── signal_controller.py     # Signal timing formula + state machine
│   ├── models/
│   │   ├── model1.pt            # Pre-trained general vehicle model (user provides)
│   │   └── model2.pt            # Custom auto-rickshaw + emergency model (user provides)
│   ├── config.py                # All tunable parameters
│   └── requirements.txt
│
├── frontend/
│   ├── index.html               # Single-page app shell (3 pages as sections)
│   ├── css/
│   │   └── style.css
│   └── js/
│       ├── app.js               # Page routing + shared state
│       ├── upload.js            # Page 1 logic
│       ├── roi.js               # Page 2 ROI drawing logic
│       └── detection.js         # Page 3 detection display + signal UI
│
├── uploads/                     # Temporary video file storage
├── roi_data/                    # Saved ROI polygon JSON files
└── README.md
```

---

## 5. Page 1 — Video Upload

### Purpose

Allow the user to upload exactly 4 video files, one per lane. Each upload slot is labeled Lane 1 through Lane 4.

### UI Layout

```
┌─────────────────────────────────────────────────────────┐
│          Smart Traffic Management System                 │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐                    │
│  │   Lane 1     │  │   Lane 2     │                    │
│  │  [ Upload ]  │  │  [ Upload ]  │                    │
│  │  filename.mp4│  │  filename.mp4│                    │
│  └──────────────┘  └──────────────┘                    │
│  ┌──────────────┐  ┌──────────────┐                    │
│  │   Lane 3     │  │   Lane 4     │                    │
│  │  [ Upload ]  │  │  [ Upload ]  │                    │
│  └──────────────┘  └──────────────┘                    │
│                                                         │
│              [ Next → Draw Regions ]                    │
└─────────────────────────────────────────────────────────┘
```

### Behavior

- Each slot accepts `.mp4`, `.avi`, `.mov`, `.mkv` files.
- On file select, show the filename and a green checkmark.
- Show a thumbnail preview of the first frame (extracted via canvas after loading the video element briefly).
- The "Next" button is **disabled** until all 4 slots have a file.
- On "Next" click:
  - POST each file to `POST /api/upload` with `lane_id` (0–3).
  - On success, navigate to Page 2.

### API Call (from upload.js)

```javascript
const formData = new FormData();
formData.append("video", file);
formData.append("lane_id", laneIndex);

const response = await fetch("/api/upload", {
  method: "POST",
  body: formData,
});
const { file_id } = await response.json();
// Store file_id per lane in app state
```

### Backend Endpoint: `POST /api/upload`

```python
@app.post("/api/upload")
async def upload_video(video: UploadFile, lane_id: int = Form(...)):
    # Validate lane_id is 0-3
    # Save to uploads/{lane_id}_{uuid}.mp4
    # Extract first frame with OpenCV
    # Save first frame as uploads/frame_{lane_id}.jpg
    # Return { "file_id": str, "frame_url": str }
```

---

## 6. Page 2 — Region of Interest Drawing

### Purpose

For each of the 4 lanes, show the first frame of that video and let the user draw a polygon to define the detection zone. Only vehicles inside this polygon will be counted.

### UI Layout

```
┌─────────────────────────────────────────────────────────┐
│  Draw Detection Regions                                  │
│  Click to add polygon points. Double-click to close.    │
│                                                         │
│  ┌───────────────────────┐  ┌───────────────────────┐  │
│  │  Lane 1               │  │  Lane 2               │  │
│  │  [first frame image]  │  │  [first frame image]  │  │
│  │  <canvas overlay>     │  │  <canvas overlay>     │  │
│  │  [ Clear ]            │  │  [ Clear ]            │  │
│  └───────────────────────┘  └───────────────────────┘  │
│  ┌───────────────────────┐  ┌───────────────────────┐  │
│  │  Lane 3               │  │  Lane 4               │  │
│  │  [first frame image]  │  │  [first frame image]  │  │
│  │  <canvas overlay>     │  │  <canvas overlay>     │  │
│  │  [ Clear ]            │  │  [ Clear ]            │  │
│  └───────────────────────┘  └───────────────────────┘  │
│                                                         │
│         [ Back ]         [ Start Detection → ]          │
└─────────────────────────────────────────────────────────┘
```

### ROI Drawing Behavior (roi.js)

- Each lane frame is rendered as an `<img>` tag.
- A transparent `<canvas>` is absolutely overlaid on top.
- **Click** on the canvas to add a polygon vertex. Draw a small circle at each vertex.
- Draw lines between consecutive vertices as the user clicks.
- **Double-click** to close the polygon (connect last point to first point). Fill with semi-transparent blue overlay.
- **Clear button** resets the polygon for that lane.
- Polygons are stored as normalized coordinates (0.0–1.0 relative to frame width/height) so they work regardless of display size.
- If the user leaves a polygon unclosed (fewer than 3 points), treat the **entire frame** as the ROI for that lane.
- On "Start Detection":
  - POST all 4 ROI polygons to `POST /api/roi`.
  - Navigate to Page 3.

### ROI Data Format

```json
{
  "rois": [
    {
      "lane_id": 0,
      "polygon": [
        [0.1, 0.2],
        [0.9, 0.2],
        [0.9, 0.9],
        [0.1, 0.9]
      ]
    },
    {
      "lane_id": 1,
      "polygon": [
        [0.0, 0.0],
        [1.0, 0.0],
        [1.0, 1.0],
        [0.0, 1.0]
      ]
    }
  ]
}
```

### Backend Endpoint: `POST /api/roi`

```python
@app.post("/api/roi")
async def save_roi(data: ROIPayload):
    # Validate each polygon has >= 3 points
    # Save to roi_data/roi_{lane_id}.json
    # Convert normalized coords to pixel coords using stored frame dimensions
    # Return { "status": "ok" }
```

---

## 7. Page 3 — Live Detection & Signal Control

### Purpose

Display 4 live video streams in a 2×2 grid with bounding boxes drawn in real time. Each block has a traffic light indicator. The system runs the detection pipeline and signal algorithm continuously.

### UI Layout

```
┌─────────────────────────────────────────────────────────┐
│  Smart Traffic — Live View                              │
│                                                         │
│  ┌──────────────────────┐  ┌──────────────────────┐    │
│  │  Lane 1              │  │  Lane 2              │    │
│  │  ┌────────────────┐  │  │  ┌────────────────┐  │    │
│  │  │  <video>       │  │  │  │  <video>       │  │    │
│  │  │  <canvas>      │  │  │  │  <canvas>      │  │    │
│  │  └────────────────┘  │  │  └────────────────┘  │    │
│  │  Score: 24.5         │  │  Score: 41.0         │    │
│  │  Green: 28s          │  │  Green: 48s          │    │
│  │   [●] RED            │  │   [●] GREEN          │    │
│  └──────────────────────┘  └──────────────────────┘    │
│  ┌──────────────────────┐  ┌──────────────────────┐    │
│  │  Lane 3              │  │  Lane 4              │    │
│  │  ...                 │  │  ...                 │    │
│  │   [●] RED            │  │   [●] RED            │    │
│  └──────────────────────┘  └──────────────────────┘    │
│                                                         │
│  Cycle: Lane 2 active — 48s remaining                  │
│  Next: Lane 4 (score 33.0)                             │
└─────────────────────────────────────────────────────────┘
```

### Traffic Light Component

Each video block has a traffic light beside (or below) it containing three circles:

- **Red circle** — lit when this lane is waiting
- **Yellow circle** — lit for 3 seconds during transition between cycles
- **Green circle** — lit when this lane has the active green signal

Only one lane can have a green light at any time (except during emergency override).

### Canvas Overlay Behavior (detection.js)

The browser receives bounding box data via WebSocket. On each frame event:

1. Clear the canvas.
2. For each detected box:
   - Draw a rectangle with color based on class (see color map below).
   - Draw a label above the box with class name and confidence.
3. Do not re-encode or stream video frames — only box coordinates are sent over the network.

#### Bounding Box Color Map

| Class             | Color            |
| ----------------- | ---------------- |
| Emergency vehicle | Red `#E24B4A`    |
| Truck / bus       | Orange `#BA7517` |
| Car / SUV         | Blue `#378ADD`   |
| Auto-rickshaw     | Teal `#1D9E75`   |
| Motorcycle / bike | Purple `#7F77DD` |

### Backend Endpoint: `POST /api/start`

Called when the user navigates to Page 3. Starts all 4 worker processes and the inference server.

```python
@app.post("/api/start")
async def start_detection():
    # Load ROI data from roi_data/
    # Load video file paths from uploads/
    # Start inference server process
    # Start 4 worker processes
    # Start signal controller loop
    # Return { "status": "running" }
```

### Backend Endpoint: `POST /api/stop`

```python
@app.post("/api/stop")
async def stop_detection():
    # Terminate all worker processes
    # Terminate inference server
    # Stop signal controller loop
    # Return { "status": "stopped" }
```

---

## 8. Mathematical Model

### 8.1 Vehicle Class Weights

Each detected vehicle class is assigned a weight `w_j` representing its contribution to lane pressure (congestion cost):

| Class                | Weight `w_j`      | Model Source |
| -------------------- | ----------------- | ------------ |
| Emergency vehicle    | ∞ (hard override) | Model 2      |
| Truck / bus          | 3.0               | Model 1      |
| Car / SUV            | 1.5               | Model 1      |
| Auto-rickshaw        | 1.2               | Model 2      |
| Motorcycle / bicycle | 0.5               | Model 1      |

These weights encode real-world space consumption and delay contribution. They are configurable in `config.py`.

### 8.2 Lane Pressure Score

For each lane `i` (i = 1, 2, 3, 4), the **pressure score** `S_i` is:

```
S_i = Σ_j ( count_{i,j} × w_j )
```

Where:

- `count_{i,j}` = number of vehicles of class `j` detected inside the ROI of lane `i`
- `w_j` = weight of vehicle class `j`

### 8.3 Green Time Allocation

Given:

- `S_i` = pressure score of lane `i`
- `G_total` = total cycle budget in seconds (default: 120s, configurable)
- `G_min` = minimum guaranteed green time per lane in seconds (default: 10s, configurable)
- `N` = number of lanes (4)

The **allocated green time** `G_i` for lane `i` is:

```
G_i = G_min + ( S_i / Σ_k S_k ) × ( G_total − N × G_min )
```

This formula guarantees:

- Every lane receives at least `G_min` seconds (prevents starvation).
- The remaining budget `(G_total − N × G_min)` is distributed proportionally by lane pressure.
- `Σ G_i = G_total` (budget is fully allocated).

**Edge case:** If all `S_i = 0` (no vehicles detected), distribute time equally: `G_i = G_total / N` for all lanes.

### 8.4 Lane Selection (Active Lane)

The lane that goes green next is always the lane with the highest current pressure score:

```
Active_lane = argmax_i( S_i )
```

After the active lane's green time `G_i` expires, the next lane is selected from the remaining lanes using the same `argmax` rule on their current scores (re-evaluated at transition time).

### 8.5 Emergency Vehicle Override

If Model 2 detects an emergency vehicle in any lane `e`, the normal cycle is immediately suspended:

```
if emergency_detected(lane_e):
    suspend_normal_cycle()
    set_green(lane_e)
    G_emergency = 30s  (configurable)
    hold_for(G_emergency)
    resume_normal_cycle()
```

During the emergency period:

- All other lanes are set to red.
- The yellow transition (3s) is skipped — the switch is instantaneous.
- After `G_emergency` seconds, if the emergency vehicle is no longer detected, resume normal cycle from the beginning.
- If the emergency vehicle is still detected, extend by another `G_emergency` seconds.

### 8.6 Yellow Transition

Between any two green phases, insert a 3-second yellow period:

```
cycle:
  set_green(active_lane) → hold G_i seconds
  set_yellow(active_lane) → hold 3 seconds
  select_next_lane → set_green(next_lane) → ...
```

### 8.7 Worked Example

Given:

- Lane 1: 2 trucks, 5 cars, 3 autos, 4 bikes
- Lane 2: 0 trucks, 8 cars, 6 autos, 2 bikes
- Lane 3: 3 trucks, 3 cars, 2 autos, 6 bikes
- Lane 4: 1 truck, 4 cars, 5 autos, 3 bikes

Scores:

```
S1 = 2×3.0 + 5×1.5 + 3×1.2 + 4×0.5 = 6.0 + 7.5 + 3.6 + 2.0 = 19.1
S2 = 0×3.0 + 8×1.5 + 6×1.2 + 2×0.5 = 0   + 12.0 + 7.2 + 1.0 = 20.2
S3 = 3×3.0 + 3×1.5 + 2×1.2 + 6×0.5 = 9.0 + 4.5 + 2.4 + 3.0  = 18.9
S4 = 1×3.0 + 4×1.5 + 5×1.2 + 3×0.5 = 3.0 + 6.0 + 6.0 + 1.5  = 16.5
```

Sum: `ΣS = 74.7`

With `G_total = 120`, `G_min = 10`, `N = 4`:

```
Budget left = 120 − 4×10 = 80s

G1 = 10 + (19.1/74.7) × 80 = 10 + 20.5 = 30.5s → round to 31s
G2 = 10 + (20.2/74.7) × 80 = 10 + 21.6 = 31.6s → round to 32s
G3 = 10 + (18.9/74.7) × 80 = 10 + 20.2 = 30.2s → round to 30s
G4 = 10 + (16.5/74.7) × 80 = 10 + 17.7 = 27.7s → round to 28s

Active lane = Lane 2 (highest score: 20.2)
```

---

## 9. Detection Pipeline

### 9.1 Inference Server (`inference_server.py`)

```python
# Pseudocode — implement fully
import torch
import multiprocessing as mp
from ultralytics import YOLO

def inference_server(input_queue, output_queue, model1_path, model2_path):
    """
    Runs on a dedicated process. Receives frame batches from workers,
    runs both models, returns merged detections.
    """
    model1 = YOLO(model1_path)
    model2 = YOLO(model2_path)
    # CPU inference — no .to('cuda') needed

    while True:
        batch = input_queue.get()  # list of (lane_id, frame_np)
        if batch is None:
            break

        frames = [item[1] for item in batch]
        lane_ids = [item[0] for item in batch]

        # Run Model 1 — general vehicle classes
        results1 = model1(frames, verbose=False)

        # Run Model 2 — auto-rickshaw + emergency
        results2 = model2(frames, verbose=False)

        # Merge results per lane
        for i, lane_id in enumerate(lane_ids):
            boxes = merge_detections(results1[i], results2[i])
            output_queue.put((lane_id, boxes))
```

### 9.2 Worker Process (`worker.py`)

```python
# Pseudocode — implement fully
import cv2
import numpy as np
import multiprocessing as mp

def worker(lane_id, video_path, roi_polygon, infer_input_q, infer_output_q,
           count_queue, emergency_event, ws_queue, frame_skip=4):
    """
    Runs on a dedicated process. Decodes video, crops to ROI,
    sends frames to inference server, receives detections, updates counts.
    """
    cap = cv2.VideoCapture(video_path)
    roi_mask = build_roi_mask(roi_polygon, frame_width, frame_height)
    frame_counter = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # Loop video
            continue

        frame_counter += 1
        if frame_counter % frame_skip != 0:
            continue

        # Apply ROI mask
        masked_frame = apply_roi_mask(frame, roi_mask)

        # Send to inference server
        infer_input_q.put((lane_id, masked_frame))

        # Receive detections (blocking with timeout)
        try:
            received_lane_id, boxes = infer_output_q.get(timeout=0.5)
        except:
            continue

        # Count vehicles by class
        counts = count_by_class(boxes)

        # Check for emergency vehicle
        if has_emergency_vehicle(boxes):
            emergency_event.set()
            emergency_event.lane_id = lane_id  # track which lane

        # Push counts to signal controller
        count_queue.put((lane_id, counts))

        # Push box data to WebSocket queue for browser
        ws_queue.put({
            'lane_id': lane_id,
            'boxes': serialize_boxes(boxes),
            'timestamp': time.time()
        })
```

### 9.3 ROI Mask Application

The ROI polygon drawn in Page 2 is stored as normalized (0.0–1.0) coordinates. When the worker loads it, convert to pixel coordinates and create a NumPy mask:

```python
def build_roi_mask(polygon_normalized, frame_w, frame_h):
    """Returns a binary mask (uint8) same size as frame."""
    pts = np.array([
        [int(x * frame_w), int(y * frame_h)]
        for x, y in polygon_normalized
    ], dtype=np.int32)

    mask = np.zeros((frame_h, frame_w), dtype=np.uint8)
    cv2.fillPoly(mask, [pts], 255)
    return mask

def apply_roi_mask(frame, mask):
    """Zero out pixels outside the ROI."""
    return cv2.bitwise_and(frame, frame, mask=mask)
```

### 9.4 Detection Merging

Both models may detect overlapping boxes. Apply Non-Maximum Suppression (NMS) after merging:

```python
def merge_detections(result1, result2):
    """
    Merge boxes from both models, run NMS at IoU threshold 0.5.
    Preserve class labels and model source.
    Returns list of dicts: {x1, y1, x2, y2, class_name, confidence, model}
    """
    boxes = []
    boxes += extract_boxes(result1, source='model1')
    boxes += extract_boxes(result2, source='model2')
    return nms_filter(boxes, iou_threshold=0.5)
```

### 9.5 Class Name Mapping

```python
# Model 1 — standard COCO class indices for vehicles
MODEL1_CLASSES = {
    2:  'car',
    3:  'motorcycle',
    5:  'bus',
    7:  'truck',
    1:  'bicycle',
}

# Model 2 — custom trained classes
MODEL2_CLASSES = {
    0: 'auto_rickshaw',
    1: 'emergency_vehicle',
}

# Unified weight map used by signal controller
VEHICLE_WEIGHTS = {
    'truck':             3.0,
    'bus':               3.0,
    'car':               1.5,
    'auto_rickshaw':     1.2,
    'motorcycle':        0.5,
    'bicycle':           0.5,
    'emergency_vehicle': None,  # triggers override, not scored
}

EMERGENCY_CLASSES = {'emergency_vehicle'}
```

---

## 10. Backend API Specification

### REST Endpoints

#### `POST /api/upload`

Upload a video file for one lane.

Request: `multipart/form-data`

- `video` (file) — video file
- `lane_id` (int, 0–3) — which lane

Response:

```json
{
  "file_id": "uuid-string",
  "frame_url": "/api/frame/0",
  "width": 1280,
  "height": 720
}
```

Errors: `400` if `lane_id` out of range or file type unsupported.

---

#### `GET /api/frame/{lane_id}`

Return the first frame image (JPEG) for the given lane. Used by Page 2 for ROI drawing.

Response: `image/jpeg`

---

#### `POST /api/roi`

Save ROI polygons for all 4 lanes.

Request body:

```json
{
  "rois": [
    {
      "lane_id": 0,
      "polygon": [
        [0.1, 0.2],
        [0.9, 0.2],
        [0.9, 0.9],
        [0.1, 0.9]
      ]
    },
    {
      "lane_id": 1,
      "polygon": [
        [0.0, 0.0],
        [1.0, 0.0],
        [1.0, 1.0],
        [0.0, 1.0]
      ]
    },
    {
      "lane_id": 2,
      "polygon": [
        [0.1, 0.1],
        [0.8, 0.1],
        [0.8, 0.8],
        [0.1, 0.8]
      ]
    },
    {
      "lane_id": 3,
      "polygon": [
        [0.2, 0.2],
        [0.7, 0.2],
        [0.7, 0.7],
        [0.2, 0.7]
      ]
    }
  ]
}
```

Response: `{ "status": "ok" }`

---

#### `POST /api/start`

Start detection workers and signal controller.

Response:

```json
{
  "status": "running",
  "lanes": [0, 1, 2, 3]
}
```

Error: `409` if already running.

---

#### `POST /api/stop`

Stop all workers and signal controller.

Response: `{ "status": "stopped" }`

---

#### `GET /api/status`

Get current system status.

Response:

```json
{
  "running": true,
  "active_lane": 2,
  "signal_states": ["red", "red", "green", "red"],
  "scores": [19.1, 20.2, 18.9, 16.5],
  "green_times": [31, 32, 30, 28],
  "remaining_seconds": 21,
  "emergency_active": false,
  "emergency_lane": null
}
```

---

## 11. WebSocket Protocol

The WebSocket server uses Socket.IO. The frontend connects on page load of Page 3.

### Connection

```javascript
const socket = io("http://localhost:8000");

socket.on("connect", () => {
  console.log("Connected to traffic server");
});
```

### Events: Server → Client

#### `detection_frame`

Emitted every time a worker produces new detections for a lane.

```json
{
  "event": "detection_frame",
  "lane_id": 2,
  "timestamp": 1712345678.123,
  "frame_width": 1280,
  "frame_height": 720,
  "boxes": [
    {
      "x1": 120,
      "y1": 80,
      "x2": 340,
      "y2": 200,
      "class_name": "car",
      "confidence": 0.91,
      "model": "model1"
    },
    {
      "x1": 400,
      "y1": 100,
      "x2": 560,
      "y2": 220,
      "class_name": "auto_rickshaw",
      "confidence": 0.87,
      "model": "model2"
    }
  ],
  "counts": {
    "car": 3,
    "truck": 1,
    "auto_rickshaw": 2,
    "motorcycle": 4
  },
  "score": 20.2
}
```

#### `signal_update`

Emitted whenever the signal state changes (lane switch, emergency override, yellow transition).

```json
{
  "event": "signal_update",
  "signal_states": ["red", "red", "green", "red"],
  "active_lane": 2,
  "remaining_seconds": 28,
  "scores": [19.1, 20.2, 18.9, 16.5],
  "green_times": [31, 32, 30, 28],
  "emergency_active": false,
  "emergency_lane": null,
  "timestamp": 1712345678.5
}
```

#### `emergency_alert`

Emitted immediately when an emergency vehicle is detected.

```json
{
  "event": "emergency_alert",
  "lane_id": 1,
  "vehicle_class": "emergency_vehicle",
  "confidence": 0.94,
  "timestamp": 1712345680.0
}
```

#### `timer_tick`

Emitted every second to update the countdown display.

```json
{
  "event": "timer_tick",
  "active_lane": 2,
  "remaining_seconds": 27,
  "emergency_active": false
}
```

### Events: Client → Server

#### `request_status`

Client can request a full status snapshot at any time.

```json
{ "event": "request_status" }
```

---

## 12. Database / State Management

No persistent database is required. All state is held in memory during a session.

### Backend State (in `main.py`)

```python
app_state = {
    "running": False,
    "video_paths": {},        # lane_id -> file path
    "roi_data": {},           # lane_id -> polygon (normalized)
    "workers": [],            # list of Process objects
    "inference_proc": None,   # Process object
    "counts": {0:{}, 1:{}, 2:{}, 3:{}},  # latest counts per lane
    "scores": {0:0.0, 1:0.0, 2:0.0, 3:0.0},
    "signal_states": ["red","red","red","red"],
    "active_lane": 0,
    "emergency_active": False,
    "emergency_lane": None,
}
```

### Shared IPC Structures

```python
from multiprocessing import Queue, Event, Value

# One queue per worker → signal controller (counts)
count_queues = [Queue() for _ in range(4)]

# One queue per worker → WebSocket pusher (detection frames)
ws_queue = Queue()

# Emergency flag — any worker can set this
emergency_event = Event()
emergency_lane_id = Value('i', -1)  # shared int, -1 = none

# Inference server queues
infer_input_queue = Queue(maxsize=20)   # workers → inference server
infer_output_queue = Queue(maxsize=20)  # inference server → workers
```

---

## 13. Signal Controller Logic

The signal controller runs in the main asyncio event loop as a background task.

```python
# signal_controller.py — full implementation pseudocode

import asyncio

async def signal_controller_loop(app_state, count_queues, emergency_event,
                                 emergency_lane_id, socketio, config):
    """
    Main signal timing loop. Runs forever until stopped.
    """
    G_TOTAL = config.G_TOTAL          # default 120
    G_MIN   = config.G_MIN            # default 10
    G_EMERG = config.G_EMERGENCY      # default 30
    YELLOW  = config.YELLOW_DURATION  # default 3
    N       = 4

    while app_state['running']:

        # --- Step 1: Drain count queues, update scores ---
        drain_count_queues(count_queues, app_state)

        # --- Step 2: Check emergency override ---
        if emergency_event.is_set():
            lane = emergency_lane_id.value
            await run_emergency_phase(lane, G_EMERG, socketio, app_state,
                                      emergency_event, emergency_lane_id)
            continue

        # --- Step 3: Compute scores and green times ---
        scores = compute_scores(app_state['counts'])
        green_times = compute_green_times(scores, G_TOTAL, G_MIN, N)
        active_lane = max(range(N), key=lambda i: scores[i])

        # --- Step 4: Update state and emit signal_update ---
        app_state['scores'] = scores
        app_state['green_times'] = green_times
        app_state['active_lane'] = active_lane

        states = ['red'] * N
        states[active_lane] = 'green'
        app_state['signal_states'] = states

        await socketio.emit('signal_update', build_signal_payload(app_state))

        # --- Step 5: Count down green time, emitting timer_tick each second ---
        duration = green_times[active_lane]
        for remaining in range(duration, 0, -1):
            if emergency_event.is_set():
                break
            drain_count_queues(count_queues, app_state)
            await socketio.emit('timer_tick', {
                'active_lane': active_lane,
                'remaining_seconds': remaining,
                'emergency_active': False
            })
            await asyncio.sleep(1)

        # --- Step 6: Yellow transition ---
        if not emergency_event.is_set():
            states[active_lane] = 'yellow'
            app_state['signal_states'] = states
            await socketio.emit('signal_update', build_signal_payload(app_state))
            await asyncio.sleep(YELLOW)


async def run_emergency_phase(lane, duration, socketio, app_state,
                               emergency_event, emergency_lane_id):
    states = ['red'] * 4
    states[lane] = 'green'
    app_state['signal_states'] = states
    app_state['emergency_active'] = True
    app_state['emergency_lane'] = lane

    await socketio.emit('signal_update', build_signal_payload(app_state))

    for remaining in range(duration, 0, -1):
        await socketio.emit('timer_tick', {
            'active_lane': lane,
            'remaining_seconds': remaining,
            'emergency_active': True
        })
        await asyncio.sleep(1)

    emergency_event.clear()
    emergency_lane_id.value = -1
    app_state['emergency_active'] = False
    app_state['emergency_lane'] = None
```

### Helper Functions

```python
def compute_scores(counts):
    """
    counts: dict of {lane_id: {class_name: count}}
    Returns: dict of {lane_id: float}
    """
    scores = {}
    for lane_id, class_counts in counts.items():
        s = 0.0
        for class_name, count in class_counts.items():
            w = VEHICLE_WEIGHTS.get(class_name)
            if w is not None:  # skip emergency classes for scoring
                s += count * w
        scores[lane_id] = s
    return scores


def compute_green_times(scores, G_total, G_min, N):
    """
    Returns dict of {lane_id: int (seconds)}
    """
    total_score = sum(scores.values())
    budget = G_total - N * G_min
    green_times = {}

    for lane_id, s in scores.items():
        if total_score > 0:
            g = G_min + (s / total_score) * budget
        else:
            g = G_total / N
        green_times[lane_id] = round(g)

    return green_times
```

---

## 14. Emergency Vehicle Handling

### Detection (in worker.py)

```python
def has_emergency_vehicle(boxes):
    return any(b['class_name'] in EMERGENCY_CLASSES for b in boxes)

# In the worker loop, after receiving detections:
if has_emergency_vehicle(boxes):
    emergency_event.set()
    with emergency_lane_id.get_lock():
        emergency_lane_id.value = lane_id
    await socketio.emit('emergency_alert', {
        'lane_id': lane_id,
        'vehicle_class': get_emergency_class(boxes),
        'confidence': get_max_confidence(boxes),
        'timestamp': time.time()
    })
```

### Signal Response

1. `emergency_event.is_set()` returns `True`.
2. Signal controller interrupts current cycle (exits the countdown loop early).
3. All lanes immediately set to red.
4. Emergency lane set to green, no yellow transition.
5. Hold for `G_EMERGENCY` seconds (default 30s).
6. Check again: if still detected, hold another `G_EMERGENCY` seconds.
7. When no longer detected, clear the event and resume normal cycle from scratch (recompute scores).

### Frontend Alert (detection.js)

```javascript
socket.on("emergency_alert", (data) => {
  showEmergencyBanner(data.lane_id, data.vehicle_class);
  // Flash red border on the relevant lane block
  document
    .getElementById(`lane-block-${data.lane_id}`)
    .classList.add("emergency-flash");
  setTimeout(() => {
    document
      .getElementById(`lane-block-${data.lane_id}`)
      .classList.remove("emergency-flash");
  }, 5000);
});
```

---

## 15. Frontend Component Specification

### app.js — Shared State and Routing

```javascript
const AppState = {
  currentPage: 1,
  uploadedFiles: [null, null, null, null], // File objects
  fileIds: [null, null, null, null], // returned by /api/upload
  roiPolygons: [[], [], [], []], // normalized polygon points
  socket: null,
  signalStates: ["red", "red", "red", "red"],
  scores: [0, 0, 0, 0],
  activeLane: -1,
};

function navigateTo(page) {
  // Hide all pages, show selected one
  document.querySelectorAll(".page").forEach((p) => (p.style.display = "none"));
  document.getElementById(`page-${page}`).style.display = "block";
  AppState.currentPage = page;
}
```

### upload.js — Page 1

Key functions:

- `handleFileSelect(laneIndex, file)` — validate, preview, store
- `uploadAllFiles()` — POST each file to `/api/upload`, store `file_id`
- `checkAllUploaded()` — enable/disable Next button

### roi.js — Page 2

Key functions:

- `initCanvas(laneIndex)` — set up canvas on top of first frame image
- `handleCanvasClick(laneIndex, e)` — add vertex, redraw
- `handleCanvasDoubleClick(laneIndex, e)` — close polygon
- `clearROI(laneIndex)` — reset polygon
- `drawPolygon(laneIndex)` — redraw all vertices and edges
- `normalizePolygon(polygon, canvasW, canvasH)` — convert to 0.0–1.0
- `saveAndProceed()` — POST to `/api/roi`, navigate to Page 3

### detection.js — Page 3

Key functions:

- `initDetectionPage()` — connect socket, POST `/api/start`, set up canvases
- `onDetectionFrame(data)` — draw bounding boxes on the correct canvas
- `onSignalUpdate(data)` — update all 4 traffic light displays
- `onTimerTick(data)` — update countdown display
- `onEmergencyAlert(data)` — show emergency banner
- `drawBoundingBoxes(canvas, boxes, frameW, frameH)` — scale coords to canvas size
- `updateTrafficLight(laneIndex, state)` — set red/yellow/green circle styles

### Traffic Light HTML Structure (per lane)

```html
<div class="lane-block" id="lane-block-0">
  <div class="lane-header">
    <span class="lane-label">Lane 1</span>
    <div class="traffic-light">
      <div class="light red" id="light-0-red"></div>
      <div class="light yellow" id="light-0-yellow"></div>
      <div class="light green" id="light-0-green"></div>
    </div>
  </div>
  <div class="video-container">
    <video id="video-0" autoplay muted loop></video>
    <canvas id="canvas-0"></canvas>
  </div>
  <div class="lane-stats">
    <span class="score-label">Score: <span id="score-0">0.0</span></span>
    <span class="time-label">Green: <span id="green-time-0">—</span></span>
  </div>
</div>
```

### Traffic Light CSS

```css
.traffic-light {
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: #1a1a1a;
  padding: 6px;
  border-radius: 8px;
}

.light {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  opacity: 0.2; /* dim = off */
  transition:
    opacity 0.3s,
    box-shadow 0.3s;
}

.light.red {
  background: #e24b4a;
}
.light.yellow {
  background: #ef9f27;
}
.light.green {
  background: #639922;
}

.light.active {
  opacity: 1;
}

.emergency-flash {
  animation: flash-border 0.5s ease-in-out infinite alternate;
}

@keyframes flash-border {
  from {
    border: 2px solid transparent;
  }
  to {
    border: 2px solid #e24b4a;
  }
}
```

### Updating a Traffic Light (detection.js)

```javascript
function updateTrafficLight(laneIndex, state) {
  // 'state' is one of: 'red', 'yellow', 'green'
  ["red", "yellow", "green"].forEach((color) => {
    const el = document.getElementById(`light-${laneIndex}-${color}`);
    el.classList.toggle("active", color === state);
  });
}
```

---

## 16. Environment & Configuration

### `backend/config.py`

```python
# Signal timing
G_TOTAL          = 120   # Total cycle budget in seconds
G_MIN            = 10    # Minimum green time per lane in seconds
G_EMERGENCY      = 30    # Emergency vehicle green hold in seconds
YELLOW_DURATION  = 3     # Yellow transition time in seconds

# Detection
FRAME_SKIP       = 4     # Process every Nth frame (1 = every frame)
CONFIDENCE_THRESH = 0.5  # Minimum detection confidence
IOU_NMS_THRESH   = 0.5   # NMS IoU threshold for merging boxes

# Models
MODEL1_PATH = "backend/models/model1.pt"
MODEL2_PATH = "backend/models/model2.pt"
DEVICE      = "cpu"      # CPU inference — no GPU required

# Server
HOST = "0.0.0.0"
PORT = 8000

# File storage
UPLOAD_DIR = "uploads/"
ROI_DIR    = "roi_data/"

# Vehicle weights (tunable)
VEHICLE_WEIGHTS = {
    'truck':          3.0,
    'bus':            3.0,
    'car':            1.5,
    'auto_rickshaw':  1.2,
    'motorcycle':     0.5,
    'bicycle':        0.5,
}

EMERGENCY_CLASSES = {'emergency_vehicle'}
```

### `backend/requirements.txt`

```
fastapi==0.110.0
uvicorn[standard]==0.29.0
python-socketio==5.11.2
python-multipart==0.0.9
opencv-python==4.9.0.80
ultralytics==8.1.0
torch>=2.0.0
torchvision>=0.15.0
numpy==1.26.4
msgpack==1.0.8
Pillow==10.2.0
aiofiles==23.2.1
```

---

## 17. Setup & Run Instructions

### Prerequisites

- Python 3.10+
- Node.js not required (vanilla JS)
- CPU inference — no GPU or CUDA required
- Sufficient RAM (8GB+ recommended for running both models simultaneously)

### Installation

```bash
# Clone / create project
cd smart_traffic

# Create virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# Install dependencies
pip install -r backend/requirements.txt

# Create required directories
mkdir -p uploads roi_data
```

### Running the Server

```bash
cd smart_traffic
source venv/bin/activate
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### Opening the App

Open `http://localhost:8000` in a browser. The FastAPI server serves the `frontend/` directory as static files.

Add this to `main.py`:

```python
from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
```

---

## 18. Key Constraints & Rules

The agent must follow these rules without deviation:

1. **Never stream annotated video frames** over WebSocket. Only bounding box coordinates and signal state JSON are pushed. Bounding boxes are drawn by the browser on a `<canvas>` overlay.

2. **Only one lane can be green at a time** in normal mode. Emergency override may suspend this briefly but must restore it after `G_EMERGENCY` seconds.

3. **Frame skipping is mandatory.** Do not process every frame. Default `FRAME_SKIP = 4` (process every 4th frame, ~7–10 fps effective on CPU). On CPU, YOLOv8n is recommended over larger variants to keep inference under ~200ms per frame. Signal timing updates on a second-level cycle — per-frame detection is unnecessary and will saturate the CPU.

4. **The inference server must be a separate process** from workers. Workers send frames to it via a queue; they do not call the YOLO models directly. This ensures both models are called sequentially on CPU without concurrent memory spikes.

5. **ROI mask is applied before inference.** Workers must zero out pixels outside the user-drawn polygon before sending the frame to the inference server. This prevents vehicles in adjacent lanes from being counted.

6. **Emergency override bypasses the weighting formula entirely.** It does not add a very high weight to the score — it is a hard interrupt that preempts the entire cycle.

7. **Both Model 1 and Model 2 run on every processed frame.** Their detections are merged (NMS applied). Model 2 is the only source of emergency vehicle and auto-rickshaw classes.

8. **The `G_min` floor must always be respected.** `G_i >= G_min` for every lane at all times in normal mode.

9. **Video files loop.** When a video reaches the end (`cap.read()` returns `False`), reset with `cap.set(cv2.CAP_PROP_POS_FRAMES, 0)`.

10. **All configurable parameters live in `config.py`** only. They must not be hardcoded in logic files.

11. **The frontend is plain HTML/CSS/JS** — no React, no build step, no npm. Socket.IO client is loaded from CDN: `https://cdn.jsdelivr.net/npm/socket.io-client@4/dist/socket.io.min.js`

12. **The yellow transition (3s) always occurs between green phases** in normal mode. It is skipped only on emergency override activation.

---

_End of specification._
