# TraffinAI

Smart traffic management system with:

- 4-lane video upload flow
- ROI polygon drawing per lane
- YOLO-based live detection overlays
- Weighted green-time allocation
- Emergency vehicle preemption

## Run

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Open `http://localhost:8000`.
