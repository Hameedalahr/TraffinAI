import queue
from typing import Any

from backend import config
from backend.model_loader import load_yolo_model


def extract_boxes(result: Any, class_map: dict[int, str], source: str) -> list[dict[str, Any]]:
    boxes: list[dict[str, Any]] = []
    names = getattr(result, "names", {})
    if result.boxes is None:
        return boxes

    xyxy = result.boxes.xyxy.tolist()
    confs = result.boxes.conf.tolist()
    classes = result.boxes.cls.tolist()

    for coords, confidence, cls_idx in zip(xyxy, confs, classes):
        class_id = int(cls_idx)
        class_name = class_map.get(class_id) or names.get(class_id)
        if not class_name:
            continue

        x1, y1, x2, y2 = coords
        boxes.append(
            {
                "x1": float(x1),
                "y1": float(y1),
                "x2": float(x2),
                "y2": float(y2),
                "class_name": str(class_name),
                "confidence": float(confidence),
                "model": source,
            }
        )

    return boxes


def compute_iou(box_a: dict[str, Any], box_b: dict[str, Any]) -> float:
    x_left = max(box_a["x1"], box_b["x1"])
    y_top = max(box_a["y1"], box_b["y1"])
    x_right = min(box_a["x2"], box_b["x2"])
    y_bottom = min(box_a["y2"], box_b["y2"])

    if x_right <= x_left or y_bottom <= y_top:
        return 0.0

    inter_area = (x_right - x_left) * (y_bottom - y_top)
    area_a = (box_a["x2"] - box_a["x1"]) * (box_a["y2"] - box_a["y1"])
    area_b = (box_b["x2"] - box_b["x1"]) * (box_b["y2"] - box_b["y1"])
    union_area = max(area_a + area_b - inter_area, 1e-6)
    return inter_area / union_area


def nms_filter(boxes: list[dict[str, Any]], iou_threshold: float) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for box in sorted(boxes, key=lambda item: item["confidence"], reverse=True):
        duplicate = any(
            kept["class_name"] == box["class_name"] and compute_iou(kept, box) >= iou_threshold
            for kept in filtered
        )
        if not duplicate:
            filtered.append(box)
    return filtered


def merge_detections(result1: Any, result2: Any) -> list[dict[str, Any]]:
    boxes = []
    boxes.extend(extract_boxes(result1, config.MODEL1_CLASSES, "model1"))
    boxes.extend(extract_boxes(result2, config.MODEL2_CLASSES, "model2"))
    return nms_filter(boxes, config.IOU_NMS_THRESH)


def inference_server(input_queue, output_queues, stop_event) -> None:
    model1 = load_yolo_model(config.MODEL1_PATH)
    model2 = load_yolo_model(config.MODEL2_PATH)

    while not stop_event.is_set():
        try:
            first_item = input_queue.get(timeout=0.2)
        except queue.Empty:
            continue

        if first_item is None:
            break

        batch = [first_item]
        while len(batch) < config.INFER_BATCH_SIZE:
            try:
                next_item = input_queue.get_nowait()
            except queue.Empty:
                break
            if next_item is None:
                stop_event.set()
                break
            batch.append(next_item)

        frames = [item["frame"] for item in batch]
        lane_ids = [item["lane_id"] for item in batch]
        frame_sizes = [item["frame_size"] for item in batch]

        results1 = model1(
            frames,
            verbose=False,
            conf=config.CONFIDENCE_THRESH,
            device=config.DEVICE,
            classes=config.MODEL1_CLASS_IDS,
        )
        results2 = model2(
            frames,
            verbose=False,
            conf=config.CONFIDENCE_THRESH,
            device=config.DEVICE,
            classes=config.MODEL2_CLASS_IDS,
        )

        for lane_id, frame_size, result1, result2 in zip(lane_ids, frame_sizes, results1, results2):
            output_queues[lane_id].put(
                {
                    "lane_id": lane_id,
                    "frame_width": frame_size[0],
                    "frame_height": frame_size[1],
                    "boxes": merge_detections(result1, result2),
                }
            )
