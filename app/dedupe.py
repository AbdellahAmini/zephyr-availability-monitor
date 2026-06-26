import json
from datetime import datetime
from pathlib import Path

from app.models import AvailabilityResult

SEEN_PATH = Path("data/seen.json")


def load_seen() -> dict:
    if not SEEN_PATH.exists():
        return {}
    try:
        return json.loads(SEEN_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_seen(seen: dict) -> None:
    SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEEN_PATH.write_text(
        json.dumps(seen, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def is_new_result(result: AvailabilityResult, seen: dict) -> bool:
    return result.unique_key() not in seen


def mark_seen(result: AvailabilityResult, seen: dict) -> None:
    key = result.unique_key()
    now = datetime.now().astimezone().isoformat()

    if key not in seen:
        seen[key] = {
            "first_seen": now,
            "last_seen": now,
            "alert_count": 1,
        }
    else:
        seen[key]["last_seen"] = now