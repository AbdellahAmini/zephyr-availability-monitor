from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class AvailabilityResult(BaseModel):
    available: bool
    city_key: str
    city_name: str
    checkin: date
    checkout: date
    nights: int
    room_type: Optional[str] = None
    price: Optional[str] = None
    booking_url: Optional[str] = None
    raw_status: Optional[str] = None
    found_at: datetime

    def unique_key(self) -> str:
        return "|".join(
            [
                self.city_key,
                self.checkin.isoformat(),
                self.checkout.isoformat(),
                str(self.nights),
                self.room_type or "unknown-room",
                self.price or "unknown-price",
            ]
        )


class SnapshotRecord(BaseModel):
    scan_id: str
    scan_started_at: datetime
    source_url: str
    final_url: Optional[str] = None
    city_key: str
    city_name: str
    user_type: Optional[str] = None
    page_type: str
    state: str
    http_status_if_available: Optional[int] = None
    visible_message: str
    queue_position: Optional[str] = None
    queue_estimated_time: Optional[str] = None
    verification_interval_seconds: Optional[int] = None
    checkin: Optional[date] = None
    checkout: Optional[date] = None
    nights: Optional[int] = None
    room_type: Optional[str] = None
    price: Optional[str] = None
    booking_url: Optional[str] = None
    raw_hash: str
    parser_version: str = "visible-html-v2"

    booking_options: list[dict[str, Any]] = Field(default_factory=list)
    availability_options: list[dict[str, Any]] = Field(default_factory=list)

    def status_key(self) -> str:
        return f"{self.city_key}|{self.page_type}|{self.user_type or 'none'}"
