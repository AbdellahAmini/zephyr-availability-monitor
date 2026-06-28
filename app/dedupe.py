import json
from datetime import datetime
from pathlib import Path

from app.models import AvailabilityResult, SnapshotRecord

SEEN_PATH = Path("data/seen.json")


def load_seen() -> dict:
    if not SEEN_PATH.exists():
        return {
            "availability": {},
            "status": {},
        }

    try:
        data = json.loads(SEEN_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = {}

    data.setdefault("availability", {})
    data.setdefault("status", {})
    return data


def save_seen(seen: dict) -> None:
    SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEEN_PATH.write_text(
        json.dumps(seen, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def is_new_result(result: AvailabilityResult, seen: dict) -> bool:
    return result.unique_key() not in seen.setdefault("availability", {})


def mark_seen(result: AvailabilityResult, seen: dict) -> None:
    key = result.unique_key()
    now = datetime.now().astimezone().isoformat()

    availability = seen.setdefault("availability", {})

    if key not in availability:
        availability[key] = {
            "first_seen": now,
            "last_seen": now,
            "alert_count": 1,
        }
    else:
        availability[key]["last_seen"] = now


def get_previous_status(snapshot: SnapshotRecord, seen: dict) -> dict | None:
    return seen.setdefault("status", {}).get(snapshot.status_key())


def should_alert_status_change(
    snapshot: SnapshotRecord,
    seen: dict,
    alert_on_first_status: bool = False,
) -> bool:
    previous = get_previous_status(snapshot, seen)

    if previous is None:
        return alert_on_first_status

    return previous.get("state") != snapshot.state


def mark_status_seen(snapshot: SnapshotRecord, seen: dict) -> None:
    now = datetime.now().astimezone().isoformat()
    status = seen.setdefault("status", {})
    key = snapshot.status_key()

    previous = status.get(key)

    status[key] = {
        "state": snapshot.state,
        "visible_message": snapshot.visible_message[:500],
        "raw_hash": snapshot.raw_hash,
        "source_url": snapshot.source_url,
        "city_key": snapshot.city_key,
        "city_name": snapshot.city_name,
        "page_type": snapshot.page_type,
        "user_type": snapshot.user_type,
        "first_seen": previous.get("first_seen") if previous else now,
        "last_seen": now,
        "change_count": (previous.get("change_count", 0) + 1) if previous and previous.get("state") != snapshot.state else (previous.get("change_count", 0) if previous else 0),
    }
