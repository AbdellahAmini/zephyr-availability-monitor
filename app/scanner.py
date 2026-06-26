import asyncio
from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import CITIES, Settings
from app.dedupe import is_new_result, mark_seen
from app.models import AvailabilityResult
from app.telegram_client import TelegramClient
from app.zephyr_client import ZephyrClient


MOROCCO_TZ = ZoneInfo("Africa/Casablanca")


def morocco_today() -> date:
    return datetime.now(MOROCCO_TZ).date()


def generate_searches(
    today: date,
    scan_days: int,
    stay_lengths: list[int],
):
    for offset in range(scan_days):
        checkin = today + timedelta(days=offset)

        for nights in stay_lengths:
            checkout = checkin + timedelta(days=nights)

            for city in CITIES:
                yield {
                    "city": city,
                    "checkin": checkin,
                    "checkout": checkout,
                    "nights": nights,
                }


async def run_scan(settings: Settings, seen: dict) -> dict:
    zephyr = ZephyrClient(
        adherent_number=settings.adherent_number,
        max_concurrency=settings.max_concurrency,
    )

    telegram = TelegramClient(
        bot_token=settings.telegram_bot_token,
        chat_ids=settings.telegram_chat_ids,
        dry_run=settings.dry_run,
    )

    summary = {
        "checks_attempted": 0,
        "available_results": 0,
        "new_alerts_sent": 0,
        "errors": 0,
    }

    searches = list(
        generate_searches(
            today=morocco_today(),
            scan_days=settings.scan_days,
            stay_lengths=settings.stay_lengths_nights,
        )
    )

    for search in searches:
        summary["checks_attempted"] += 1

        try:
            result = await zephyr.check_availability(
                city=search["city"],
                checkin=search["checkin"],
                checkout=search["checkout"],
                nights=search["nights"],
            )
        except Exception as exc:
            summary["errors"] += 1
            print(f"Check failed: {search} error={exc}")
            continue

        if not result.available:
            continue

        summary["available_results"] += 1

        if is_new_result(result, seen):
            await telegram.send_alert(result, settings.adherent_number)
            mark_seen(result, seen)
            summary["new_alerts_sent"] += 1
        else:
            mark_seen(result, seen)

    return summary