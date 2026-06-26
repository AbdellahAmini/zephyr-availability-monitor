from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


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