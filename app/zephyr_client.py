from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.config import City
from app.models import AvailabilityResult


MOROCCO_TZ = ZoneInfo("Africa/Casablanca")


class ZephyrClient:
    def __init__(self, adherent_number: str, max_concurrency: int = 4):
        self.adherent_number = adherent_number
        self.max_concurrency = max_concurrency

    async def check_availability(
        self,
        city: City,
        checkin: date,
        checkout: date,
        nights: int,
    ) -> AvailabilityResult:
        """
        Replace this after Playwright discovery.

        This method must:
        1. Call the real Zephyr availability endpoint.
        2. Pass city, checkin, checkout, and adherent number.
        3. Parse the response.
        4. Return AvailabilityResult.
        """
        return AvailabilityResult(
            available=False,
            city_key=city.key,
            city_name=city.name,
            checkin=checkin,
            checkout=checkout,
            nights=nights,
            raw_status="NOT_IMPLEMENTED",
            found_at=datetime.now(MOROCCO_TZ),
        )