import queue
import time
from collections import Counter
from typing import Any

import cv2
import numpy as np

from backend import config


def build_roi_mask(polygon_normalized: list[list[float]], frame_w: int, frame_h: int) -> np.ndarray:
    if len(polygon_normalized) < 3:
        return np.full((frame_h, frame_w), 255, dtype=np.uint8)

    pts = np.array(
        [[int(x * frame_w), int(y * frame_h)] for x, y in polygon_normalized],
        dtype=np.int32,
    )
    mask = np.zeros((frame_h, frame_w), dtype=np.uint8)
    cv2.fillPoly(mask, [pts], 255)
    return mask


def apply_roi_mask(frame: np.ndarray, mask: np.ndarray) -> np.ndarray:
    return cv2.bitwise_and(frame, frame, mask=mask)


def count_by_class(boxes: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter(box["class_name"] for box in boxes)
    return dict(counter)


def compute_score(counts: dict[str, int]) -> float:
    score = 0.0
    for class_name, count in counts.items():
        weight = config.VEHICLE_WEIGHTS.get(class_name)
        if weight is not None:
            score += count * weight
    return round(score, 2)


def has_emergency_vehicle(boxes: list[dict[str, Any]]) -> bool:
    return any(box["class_name"] in config.EMERGENCY_CLASSES for box in boxes)


def get_emergency_box(boxes: list[dict[str, Any]]) -> dict[str, Any] | None:
    emergency_boxes = [box for box in boxes if box["class_name"] in config.EMERGENCY_CLASSES]
    if not emergency_boxes:
        return None
    return max(emergency_boxes, key=lambda item: item["confidence"])


def lane_worker(
    lane_id: int,
    video_path: str,
    roi_polygon: list[list[float]],
    infer_input_queue,
    infer_output_queue,
    count_queue,
    ws_queue,
    emergency_event,
    emergency_lane_id,
    emergency_seen_at,
    stop_event,
) -> None:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        ws_queue.put(
            {
                "event": "worker_error",
                "lane_id": lane_id,
                "message": f"Unable to open video for lane {lane_id + 1}.",
                "timestamp": time.time(),
            }
        )
        return

    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
    roi_mask = build_roi_mask(roi_polygon, frame_width, frame_height)
    frame_counter = 0

    while not stop_event.is_set():
        ret, frame = cap.read()
        if not ret:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            continue

        frame_counter += 1
        if frame_counter % config.FRAME_SKIP != 0:
            continue

        masked_frame = apply_roi_mask(frame, roi_mask)
        infer_input_queue.put(
            {
                "lane_id": lane_id,
                "frame": masked_frame,
                "frame_size": (frame_width, frame_height),
            }
        )

        try:
            result = infer_output_queue.get(timeout=config.INFER_OUTPUT_TIMEOUT)
        except queue.Empty:
            time.sleep(config.WORKER_LOOP_SLEEP)
            continue

        boxes = result["boxes"]
        counts = count_by_class(boxes)
        score = compute_score(counts)
        count_queue.put((lane_id, counts))

        ws_queue.put(
            {
                "event": "detection_frame",
                "lane_id": lane_id,
                "timestamp": time.time(),
                "frame_width": frame_width,
                "frame_height": frame_height,
                "boxes": boxes,
                "counts": counts,
                "score": score,
            }
        )

        emergency_box = get_emergency_box(boxes)
        if emergency_box is not None:
            emergency_event.set()
            with emergency_lane_id.get_lock():
                emergency_lane_id.value = lane_id
            with emergency_seen_at.get_lock():
                emergency_seen_at.value = time.time()
            ws_queue.put(
                {
                    "event": "emergency_alert",
                    "lane_id": lane_id,
                    "vehicle_class": emergency_box["class_name"],
                    "confidence": emergency_box["confidence"],
                    "timestamp": time.time(),
                }
            )

    cap.release()
