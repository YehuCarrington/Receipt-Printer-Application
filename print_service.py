# print_service.py
import os, json, time
from collections import deque
from flask import Flask, request, abort
from dotenv import load_dotenv

from print_cli import print_ticket

# ---------- config ----------
load_dotenv()  # optional .env
SHARED_SECRET = os.getenv("PRINT_SECRET", "change-me")
DEDUP_TTL_SEC = 600
QUEUE_DIR = os.path.join(os.path.expanduser("~"), ".ticket_print", "queue")
os.makedirs(QUEUE_DIR, exist_ok=True)

# ---------- app ----------
app = Flask(__name__)
_recent = deque(maxlen=300)  # (ticket_id, ts)

def already_printed(tid: str) -> bool:
    now = time.time()
    while _recent and now - _recent[0][1] > DEDUP_TTL_SEC:
        _recent.popleft()
    return any(k == tid for k, _ in _recent)

def mark_printed(tid: str):
    _recent.append((tid, time.time()))

def enqueue(payload: dict):
    ts = int(time.time())
    path = os.path.join(QUEUE_DIR, f"{payload.get('id','unknown')}_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)

@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Print-Secret"
    return resp

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/print_ticket")
def print_ticket_endpoint():
    # auth
    if SHARED_SECRET and request.headers.get("X-Print-Secret") != SHARED_SECRET:
        abort(401, "Missing or bad X-Print-Secret")

    payload = request.get_json(silent=True) or {}
    for k in ("id", "title"):
        if not payload.get(k):
            abort(400, f"Missing required field: {k}")

    tid = str(payload["id"])

    # de-dupe for 10 minutes
    if already_printed(tid):
        return {"ok": True, "deduped": True}

    try:
        print_ticket(payload)
        mark_printed(tid)
        return {"ok": True, "printed": True}
    except Exception as e:
        enqueue(payload)
        abort(503, f"Printer unavailable. Queued for retry. {e}")

if __name__ == "__main__":
    
    app.run(host="127.0.0.1", port=5055)