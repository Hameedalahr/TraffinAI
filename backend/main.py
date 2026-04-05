import asyncio
import contextlib
import json
import multiprocessing as mp
import time
import uuid
from pathlib import Path
from typing import Any

import aiofiles
import cv2
import socketio
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import config
from backend.inference_server import inference_server
from backend.signal_controller import build_signal_payload, signal_controller_loop
from backend.worker import lane_worker


class ROIEntry(BaseModel):
    lane_id: int
    polygon: list[list[float]] = Field(default_factory=list)


class ROIPayload(BaseModel):
    rois: list[ROIEntry]


def default_lane_summary() -> dict[str, Any]:
    return {
        "green_count": 0,
        "total_vehicles_passed": 0,
        "emergency_count": 0,
        "class_totals": {
            "car": 0,
            "truck": 0,
            "bus": 0,
            "auto_rickshaw": 0,
            "motorcycle": 0,
            "bicycle": 0,
            "emergency_vehicle": 0,
        },
        "last_green_at": None,
    }


def ensure_directories() -> None:
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    config.ROI_DIR.mkdir(parents=True, exist_ok=True)
    config.FRAMES_DIR.mkdir(parents=True, exist_ok=True)


def create_app_state() -> dict[str, Any]:
    return {
        "running": False,
        "video_paths": {},
        "video_urls": {},
        "frame_paths": {},
        "frame_sizes": {},
        "roi_data": {},
        "workers": [],
        "inference_proc": None,
        "counts": {lane_id: {} for lane_id in range(config.LANE_COUNT)},
        "scores": {lane_id: 0.0 for lane_id in range(config.LANE_COUNT)},
        "green_times": {lane_id: config.G_MIN for lane_id in range(config.LANE_COUNT)},
        "waiting_times": {lane_id: 0 for lane_id in range(config.LANE_COUNT)},
        "priority_scores": {lane_id: 0.0 for lane_id in range(config.LANE_COUNT)},
        "wait_started_at": {lane_id: 0.0 for lane_id in range(config.LANE_COUNT)},
        "last_green_lane": None,
        "lane_summaries": {lane_id: default_lane_summary() for lane_id in range(config.LANE_COUNT)},
        "history": [],
        "last_count_snapshots": {lane_id: {} for lane_id in range(config.LANE_COUNT)},
        "signal_states": ["red"] * config.LANE_COUNT,
        "active_lane": 0,
        "remaining_seconds": 0,
        "emergency_active": False,
        "emergency_lane": None,
        "count_queues": [],
        "infer_input_queue": None,
        "infer_output_queues": [],
        "ws_queue": None,
        "emergency_event": None,
        "emergency_lane_id": None,
        "emergency_seen_at": None,
        "stop_event": None,
        "signal_task": None,
        "ws_task": None,
    }


app_state = create_app_state()
ensure_directories()

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
fastapi_app = FastAPI(title="Smart Traffic Management System")
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@fastapi_app.on_event("startup")
async def on_startup() -> None:
    ensure_directories()


@fastapi_app.on_event("shutdown")
async def on_shutdown() -> None:
    await stop_runtime()


@sio.event
async def connect(sid, environ, auth):
    await sio.emit("signal_update", build_signal_payload(app_state), to=sid)


@sio.on("request_status")
async def request_status(sid, data):
    await sio.emit("signal_update", build_signal_payload(app_state), to=sid)


def validate_lane_id(lane_id: int) -> None:
    if lane_id < 0 or lane_id >= config.LANE_COUNT:
        raise HTTPException(status_code=400, detail="lane_id must be between 0 and 3")


def get_frame_path(lane_id: int) -> Path:
    path = app_state["frame_paths"].get(lane_id)
    if not path:
        raise HTTPException(status_code=404, detail="Frame not found for lane")
    return Path(path)


def save_first_frame(video_path: Path, lane_id: int) -> tuple[Path, int, int]:
    capture = cv2.VideoCapture(str(video_path))
    success, frame = capture.read()
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
    capture.release()

    if not success:
        raise HTTPException(status_code=400, detail="Unable to read uploaded video")

    frame_path = config.FRAMES_DIR / f"frame_{lane_id}.jpg"
    cv2.imwrite(str(frame_path), frame)
    return frame_path, width, height


def normalize_polygon(entry: ROIEntry) -> list[list[float]]:
    if len(entry.polygon) < 3:
        return [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]

    normalized = []
    epsilon = 1e-6
    for point in entry.polygon:
        if len(point) != 2:
            raise HTTPException(status_code=400, detail=f"Invalid polygon point for lane {entry.lane_id}")
        x, y = point
        if not (-epsilon) <= x <= (1.0 + epsilon) or not (-epsilon) <= y <= (1.0 + epsilon):
            raise HTTPException(status_code=400, detail=f"ROI coordinates must be normalized for lane {entry.lane_id}")
        normalized.append([min(1.0, max(0.0, float(x))), min(1.0, max(0.0, float(y)))])
    return normalized


def append_history(event_type: str, lane_id: int, message: str, details: dict[str, Any] | None = None) -> None:
    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": time.time(),
        "lane_id": lane_id,
        "event_type": event_type,
        "message": message,
        "details": details or {},
    }
    app_state["history"].append(entry)
    app_state["history"] = app_state["history"][-300:]


def get_lane_summaries() -> list[dict[str, Any]]:
    return [
        {
            "lane_id": lane_id,
            **app_state["lane_summaries"].get(lane_id, default_lane_summary()),
        }
        for lane_id in range(config.LANE_COUNT)
    ]


def update_vehicle_history(lane_id: int, counts: dict[str, int]) -> bool:
    previous = app_state["last_count_snapshots"].get(lane_id, {})
    summary = app_state["lane_summaries"][lane_id]
    positive_delta_total = 0
    delta_counts: dict[str, int] = {}

    for class_name, count in counts.items():
        delta = max(0, count - previous.get(class_name, 0))
        if delta > 0:
            delta_counts[class_name] = delta
            positive_delta_total += delta
            summary["class_totals"][class_name] = summary["class_totals"].get(class_name, 0) + delta

    if positive_delta_total > 0:
        summary["total_vehicles_passed"] += positive_delta_total
        append_history(
            "vehicle_flow",
            lane_id,
            f"Lane {lane_id + 1} observed {positive_delta_total} additional vehicles",
            {"delta_counts": delta_counts, "total_vehicles_passed": summary["total_vehicles_passed"]},
        )

    app_state["last_count_snapshots"][lane_id] = dict(counts)
    return positive_delta_total > 0


async def ws_broadcast_loop() -> None:
    while app_state["running"] and app_state["ws_queue"] is not None:
        try:
            payload = await asyncio.to_thread(app_state["ws_queue"].get, True, 0.2)
        except Exception:
            await asyncio.sleep(0.05)
            continue

        event_name = payload.get("event")
        if event_name == "detection_frame":
            changed = update_vehicle_history(payload["lane_id"], payload.get("counts", {}))
            if changed:
                await sio.emit(
                    "history_update",
                    {
                        "history": app_state["history"][-200:],
                        "lane_summaries": get_lane_summaries(),
                    },
                )
        elif event_name == "emergency_alert":
            lane_id = payload["lane_id"]
            app_state["lane_summaries"][lane_id]["emergency_count"] += 1
            append_history(
                "emergency",
                lane_id,
                f"Emergency vehicle detected on Lane {lane_id + 1}",
                {
                    "vehicle_class": payload.get("vehicle_class"),
                    "confidence": payload.get("confidence"),
                },
            )
            await sio.emit(
                "history_update",
                {
                    "history": app_state["history"][-200:],
                    "lane_summaries": get_lane_summaries(),
                },
            )

        payload = dict(payload)
        event_name = payload.pop("event", None)
        if event_name:
            await sio.emit(event_name, payload)


def join_processes(processes: list[mp.Process]) -> None:
    for process in processes:
        if process.is_alive():
            process.join(timeout=1)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)


async def stop_runtime() -> None:
    if not app_state["running"] and not app_state["workers"] and app_state["inference_proc"] is None:
        return

    preserved_state = {
        "video_paths": dict(app_state["video_paths"]),
        "video_urls": dict(app_state["video_urls"]),
        "frame_paths": dict(app_state["frame_paths"]),
        "frame_sizes": dict(app_state["frame_sizes"]),
        "roi_data": dict(app_state["roi_data"]),
    }
    app_state["running"] = False

    stop_event = app_state.get("stop_event")
    if stop_event is not None:
        stop_event.set()

    infer_input_queue = app_state.get("infer_input_queue")
    if infer_input_queue is not None:
        with contextlib.suppress(Exception):
            infer_input_queue.put_nowait(None)

    for task_key in ("signal_task", "ws_task"):
        task = app_state.get(task_key)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    join_processes(app_state.get("workers", []))
    inference_proc = app_state.get("inference_proc")
    if inference_proc is not None:
        join_processes([inference_proc])

    app_state.update(create_app_state())
    app_state.update(preserved_state)


def require_ready_to_start() -> None:
    if len(app_state["video_paths"]) != config.LANE_COUNT:
        raise HTTPException(status_code=400, detail="Upload all four videos before starting detection")
    if len(app_state["roi_data"]) != config.LANE_COUNT:
        raise HTTPException(status_code=400, detail="Save ROI polygons for all four lanes before starting detection")


@fastapi_app.post("/api/upload")
async def upload_video(video: UploadFile = File(...), lane_id: int = Form(...)):
    validate_lane_id(lane_id)

    suffix = Path(video.filename or "").suffix.lower()
    if suffix not in config.ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported video type")

    file_id = str(uuid.uuid4())
    output_path = config.UPLOAD_DIR / f"{lane_id}_{file_id}{suffix}"

    async with aiofiles.open(output_path, "wb") as out_file:
        while chunk := await video.read(1024 * 1024):
            await out_file.write(chunk)

    frame_path, width, height = save_first_frame(output_path, lane_id)

    app_state["video_paths"][lane_id] = str(output_path)
    app_state["video_urls"][lane_id] = f"/uploads/{output_path.name}"
    app_state["frame_paths"][lane_id] = str(frame_path)
    app_state["frame_sizes"][lane_id] = {"width": width, "height": height}

    return {
        "file_id": file_id,
        "frame_url": f"/api/frame/{lane_id}",
        "video_url": app_state["video_urls"][lane_id],
        "width": width,
        "height": height,
    }


@fastapi_app.get("/api/frame/{lane_id}")
async def get_frame(lane_id: int):
    validate_lane_id(lane_id)
    frame_path = get_frame_path(lane_id)
    if not frame_path.exists():
        raise HTTPException(status_code=404, detail="Frame file missing")
    return FileResponse(frame_path, media_type="image/jpeg")


@fastapi_app.post("/api/roi")
async def save_roi(payload: ROIPayload):
    if len(payload.rois) != config.LANE_COUNT:
        raise HTTPException(status_code=400, detail="ROI payload must contain exactly four lanes")

    seen_lanes = set()
    for entry in payload.rois:
        validate_lane_id(entry.lane_id)
        if entry.lane_id in seen_lanes:
            raise HTTPException(status_code=400, detail="Duplicate lane_id in ROI payload")
        seen_lanes.add(entry.lane_id)

        normalized = normalize_polygon(entry)
        roi_path = config.ROI_DIR / f"roi_{entry.lane_id}.json"
        roi_path.write_text(json.dumps({"lane_id": entry.lane_id, "polygon": normalized}, indent=2), encoding="utf-8")
        app_state["roi_data"][entry.lane_id] = normalized

    return {"status": "ok"}


@fastapi_app.post("/api/start")
async def start_detection():
    if app_state["running"]:
        raise HTTPException(status_code=409, detail="Detection already running")

    require_ready_to_start()

    app_state["running"] = True
    app_state["counts"] = {lane_id: {} for lane_id in range(config.LANE_COUNT)}
    app_state["scores"] = {lane_id: 0.0 for lane_id in range(config.LANE_COUNT)}
    app_state["green_times"] = {lane_id: config.G_MIN for lane_id in range(config.LANE_COUNT)}
    app_state["waiting_times"] = {lane_id: 0 for lane_id in range(config.LANE_COUNT)}
    app_state["priority_scores"] = {lane_id: 0.0 for lane_id in range(config.LANE_COUNT)}
    start_ts = asyncio.get_running_loop().time()
    app_state["wait_started_at"] = {lane_id: start_ts for lane_id in range(config.LANE_COUNT)}
    app_state["last_green_lane"] = None
    app_state["lane_summaries"] = {lane_id: default_lane_summary() for lane_id in range(config.LANE_COUNT)}
    app_state["history"] = []
    app_state["last_count_snapshots"] = {lane_id: {} for lane_id in range(config.LANE_COUNT)}
    app_state["signal_states"] = ["red"] * config.LANE_COUNT
    app_state["active_lane"] = 0
    app_state["remaining_seconds"] = 0
    app_state["emergency_active"] = False
    app_state["emergency_lane"] = None

    ctx = mp.get_context("spawn")
    app_state["count_queues"] = [ctx.Queue() for _ in range(config.LANE_COUNT)]
    app_state["infer_input_queue"] = ctx.Queue(maxsize=config.INFER_QUEUE_SIZE)
    app_state["infer_output_queues"] = [ctx.Queue(maxsize=config.INFER_QUEUE_SIZE) for _ in range(config.LANE_COUNT)]
    app_state["ws_queue"] = ctx.Queue()
    app_state["emergency_event"] = ctx.Event()
    app_state["emergency_lane_id"] = ctx.Value("i", -1)
    app_state["emergency_seen_at"] = ctx.Value("d", 0.0)
    app_state["stop_event"] = ctx.Event()

    inference_proc = ctx.Process(
        target=inference_server,
        args=(
            app_state["infer_input_queue"],
            app_state["infer_output_queues"],
            app_state["stop_event"],
        ),
        daemon=True,
    )
    inference_proc.start()
    app_state["inference_proc"] = inference_proc

    workers = []
    for lane_id in range(config.LANE_COUNT):
        process = ctx.Process(
            target=lane_worker,
            args=(
                lane_id,
                app_state["video_paths"][lane_id],
                app_state["roi_data"][lane_id],
                app_state["infer_input_queue"],
                app_state["infer_output_queues"][lane_id],
                app_state["count_queues"][lane_id],
                app_state["ws_queue"],
                app_state["emergency_event"],
                app_state["emergency_lane_id"],
                app_state["emergency_seen_at"],
                app_state["stop_event"],
            ),
            daemon=True,
        )
        process.start()
        workers.append(process)

    app_state["workers"] = workers
    app_state["ws_task"] = asyncio.create_task(ws_broadcast_loop())
    app_state["signal_task"] = asyncio.create_task(
        signal_controller_loop(
            app_state,
            app_state["count_queues"],
            app_state["emergency_event"],
            app_state["emergency_lane_id"],
            app_state["emergency_seen_at"],
            sio,
        )
    )

    return {"status": "running", "lanes": list(range(config.LANE_COUNT))}


@fastapi_app.post("/api/stop")
async def stop_detection():
    await stop_runtime()
    return {"status": "stopped"}


@fastapi_app.get("/api/status")
async def get_status():
    return {
        "running": app_state["running"],
        "active_lane": app_state["active_lane"],
        "signal_states": app_state["signal_states"],
        "scores": [app_state["scores"].get(i, 0.0) for i in range(config.LANE_COUNT)],
        "green_times": [app_state["green_times"].get(i, config.G_MIN) for i in range(config.LANE_COUNT)],
        "waiting_times": [app_state["waiting_times"].get(i, 0) for i in range(config.LANE_COUNT)],
        "priority_scores": [app_state["priority_scores"].get(i, 0.0) for i in range(config.LANE_COUNT)],
        "remaining_seconds": app_state["remaining_seconds"],
        "emergency_active": app_state["emergency_active"],
        "emergency_lane": app_state["emergency_lane"],
        "counts": [app_state["counts"].get(i, {}) for i in range(config.LANE_COUNT)],
        "lane_summaries": get_lane_summaries(),
        "history": app_state["history"][-200:],
        "video_urls": [app_state["video_urls"].get(i) for i in range(config.LANE_COUNT)],
        "frame_urls": [f"/api/frame/{i}" if i in app_state["frame_paths"] else None for i in range(config.LANE_COUNT)],
    }


@fastapi_app.get("/api/health")
async def health():
    return JSONResponse({"status": "ok"})


fastapi_app.mount("/uploads", StaticFiles(directory=str(config.UPLOAD_DIR)), name="uploads")
fastapi_app.mount("/assets", StaticFiles(directory=str(config.BASE_DIR / "frontend")), name="assets")
fastapi_app.mount("/", StaticFiles(directory=str(config.BASE_DIR / "frontend"), html=True), name="frontend")

app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app)
