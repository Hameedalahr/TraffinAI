from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "backend"

# Signal timing
G_TOTAL = 120
G_MIN = 10
G_EMERGENCY = 30
YELLOW_DURATION = 3
WAIT_TIME_WEIGHT = 0.35
BLOCK_CONSECUTIVE_GREEN = True

# Detection
FRAME_SKIP = 4
CONFIDENCE_THRESH = 0.5
IOU_NMS_THRESH = 0.5
INFER_BATCH_SIZE = 4
INFER_QUEUE_SIZE = 20
INFER_OUTPUT_TIMEOUT = 2.0
WORKER_LOOP_SLEEP = 0.01
EMERGENCY_STALE_SECONDS = 3.0

# Models
MODEL1_PATH = str(BACKEND_DIR / "models" / "model1.pt")
MODEL2_PATH = str(BACKEND_DIR / "models" / "model2.pt")
DEVICE = "cpu"

# Server
HOST = "0.0.0.0"
PORT = 8000

# File storage
UPLOAD_DIR = BASE_DIR / "uploads"
ROI_DIR = BASE_DIR / "roi_data"
FRAMES_DIR = UPLOAD_DIR / "frames"
ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}
LANE_COUNT = 4

# Class mappings
MODEL1_CLASSES = {
    1: "bicycle",
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}
MODEL1_CLASS_IDS = sorted(MODEL1_CLASSES.keys())

MODEL2_CLASSES = {
    0: "auto_rickshaw",
    1: "emergency_vehicle",
}
MODEL2_CLASS_IDS = sorted(MODEL2_CLASSES.keys())

VEHICLE_WEIGHTS = {
    "truck": 3.0,
    "bus": 3.0,
    "car": 1.5,
    "auto_rickshaw": 1.2,
    "motorcycle": 0.5,
    "bicycle": 0.5,
    "emergency_vehicle": None,
}

EMERGENCY_CLASSES = {"emergency_vehicle"}
