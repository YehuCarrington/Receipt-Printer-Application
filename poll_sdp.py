# poll_sdp.py
import json, os, time, json, pathlib, requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

SDP_BASE       = os.getenv("SDP_BASE", "").rstrip("/")
AUTHTOKEN      = os.getenv("SDP_AUTHTOKEN", "").strip()
RAW_COOKIE     = os.getenv("SDP_COOKIE", "").strip()
PRINT_SECRET   = os.getenv("PRINT_SECRET", "change-me")
LOCAL_ENDPOINT = "http://127.0.0.1:5055/print_ticket"
ASSIGNEE_NAME = os.getenv("ASSIGNEE_NAME", "").strip()

STATE_PATH = pathlib.Path(".sdp_state.json")
POLL_SEC   = 60

def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"seen_ids": [], "last_seen_updated": None}

def save_state(state):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def make_session():
    if not SDP_BASE:
        raise SystemExit("Set SDP_BASE in .env")
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    if AUTHTOKEN:
        s.headers.update({"authtoken": AUTHTOKEN})
    elif RAW_COOKIE:
        s.headers.update({"Cookie": RAW_COOKIE})
    else:
        raise SystemExit("Provide either SDP_AUTHTOKEN or SDP_COOKIE in .env")
    return s

def map_request_to_payload(r):
    # r is one request object from SDP v3 API.
    return {
        "id": str(r.get("id", "")),
        "title": r.get("subject", "(no subject)"),
        "description": r.get("description", "") or "",
        "priority": (r.get("priority") or {}).get("name", ""),
        "assignee": (r.get("technician") or {}).get("name", "Yehu"),
        "created": r.get("created_time", ""),
        "url": f"{SDP_BASE}/requests/{r.get('id')}",
        "xp": 5,
    }

def fetch_recent_assigned(session, row_count=25):
    """
    Pull newest N, then filter to tickets assigned to ASSIGNEE_NAME (client-side).
    Later we can move this into search_criteria once we confirm your tenant's field names.
    """
    url = f"{API_BASE}/requests"
    list_info = {
        "row_count": row_count,
        "start_index": 1,
        "sort_field": "updated_time",
        "sort_order": "desc"
        # We can add search_criteria later, e.g.:
        # "search_criteria": {
        #   "field": "technician.name", "condition": "is", "values": [ASSIGNEE_NAME]
        # }
    }
    params = {"list_info": json.dumps(list_info)}
    r = session.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    items = data.get("requests", data if isinstance(data, list) else [])

    # Client-side filter to you (safe until we lock exact server-side filter syntax)
    if ASSIGNEE_NAME:
        items = [it for it in items if (it.get("technician") or {}).get("name") == ASSIGNEE_NAME]
    return items


def post_to_local(payload):
    requests.post(
        LOCAL_ENDPOINT,
        headers={"X-Print-Secret": PRINT_SECRET, "Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=10,
    )

def main():
    state = load_state()
    seen_ids = set(state.get("seen_ids", []))
    session = make_session()

    print("[poll] started; Ctrl+C to stop")
    while True:
        try:
            reqs = fetch_recent_assigned(session, limit=25)
            for r in reqs:
                payload = map_request_to_payload(r)
                tid = payload["id"]
                if not tid:
                    continue

                # dedupe by ID; if you prefer dedupe-by (id, updated_time), add that here
                if tid in seen_ids:
                    continue

                # fire to local printer API
                try:
                    post_to_local(payload)
                    print(f"[poll] printed {tid} - {payload['title'][:60]}")
                except Exception as e:
                    print(f"[poll] local post failed for {tid}: {e}")

                seen_ids.add(tid)

            # persist a small rolling window (don’t grow forever)
            if len(seen_ids) > 500:
                seen_ids = set(list(seen_ids)[-300:])
            save_state({"seen_ids": list(seen_ids), "last_seen_updated": datetime.now(timezone.utc).isoformat()})
        except requests.HTTPError as e:
            # Helpful for tuning tenant-specific params
            print("[poll] HTTP error:", e.response.status_code, e.response.text[:400])
        except Exception as e:
            print("[poll] error:", e)

        time.sleep(POLL_SEC)

if __name__ == "__main__":
    main()
