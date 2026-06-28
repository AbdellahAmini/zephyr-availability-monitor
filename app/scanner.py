import sys
import asyncio
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.browser_booking_client import BrowserBookingClient
from app.config import CITIES, PUBLIC_PAGES, Settings
from app.dedupe import (
    get_previous_status,
    mark_status_seen,
    should_alert_status_change,
)
from app.telegram_client import TelegramClient
from app.zephyr_client import ZephyrClient

MOROCCO_TZ = ZoneInfo("Africa/Casablanca")


def morocco_now() -> datetime:
    return datetime.now(MOROCCO_TZ)


def morocco_today() -> date:
    return morocco_now().date()


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
    scan_started_at = morocco_now()
    scan_id = scan_started_at.isoformat()

    telegram = TelegramClient(
        bot_token=settings.telegram_bot_token,
        chat_ids=settings.telegram_chat_ids,
        dry_run=settings.dry_run,
    )

    summary = {
        "scan_id": scan_id,
        "snapshots_checked": 0,
        "status_alerts_sent": 0,
        "availability_alerts_sent": 0,
        "errors": 0,
        "states": {},
        "booking_options_count": 0,
        "availability_options_count": 0,
        "booking_options": [],
        "availability_options": [],
        "snapshots": [],
    }

    snapshots = []

    if settings.enable_browser_booking_scan:
        browser_client = BrowserBookingClient(
            headless=settings.headless_browser,
            wait_seconds=settings.booking_wait_seconds,
            hold_browser_open_seconds=settings.booking_hold_browser_open_seconds,
        )

        all_searches = list(
            generate_searches(
                today=morocco_today(),
                scan_days=settings.scan_days,
                stay_lengths=settings.stay_lengths_nights,
            )
        )

        for city in CITIES:
            city_date_ranges = []

            for search in all_searches:
                if search["city"].key != city.key:
                    continue

                city_date_ranges.append(
                    {
                        "checkin": search["checkin"],
                        "checkout": search["checkout"],
                        "nights": search["nights"],
                    }
                )

                if len(city_date_ranges) >= settings.booking_max_date_checks_per_city:
                    break

            city_snapshots = await browser_client.scan_city_ranges(
                scan_id=scan_id,
                scan_started_at=scan_started_at,
                city=city,
                adherent_number=settings.adherent_number,
                date_ranges=city_date_ranges,
            )

            snapshots.extend(city_snapshots)

            await asyncio.sleep(2.0)

    else:
        zephyr = ZephyrClient(timeout_seconds=settings.http_timeout_seconds)

        if settings.enable_public_page_monitor:
            for page in PUBLIC_PAGES:
                snapshots.append(
                    await zephyr.fetch_snapshot(
                        scan_id=scan_id,
                        scan_started_at=scan_started_at,
                        source_url=page["url"],
                        city_key=page["key"],
                        city_name=page["name"],
                        page_type=page["page_type"],
                        user_type=None,
                        booking_url=page["url"],
                    )
                )

        if settings.enable_hotel_page_monitor:
            for city in CITIES:
                snapshots.append(
                    await zephyr.fetch_snapshot(
                        scan_id=scan_id,
                        scan_started_at=scan_started_at,
                        source_url=city.hotel_site,
                        city_key=city.key,
                        city_name=city.name,
                        page_type="hotel_landing",
                        user_type=None,
                        booking_url=city.booking_adherent_url,
                    )
                )
                await asyncio.sleep(0.5)

        if settings.enable_queue_monitor:
            for city in CITIES:
                snapshots.append(
                    await zephyr.fetch_snapshot(
                        scan_id=scan_id,
                        scan_started_at=scan_started_at,
                        source_url=city.booking_adherent_url,
                        city_key=city.key,
                        city_name=city.name,
                        page_type="booking_queue",
                        user_type="adherent",
                        booking_url=city.booking_adherent_url,
                    )
                )
                await asyncio.sleep(1.0)

    for snapshot in snapshots:
        summary["snapshots_checked"] += 1
        summary["states"][snapshot.state] = summary["states"].get(snapshot.state, 0) + 1
        summary["booking_options"].extend(snapshot.booking_options)
        summary["availability_options"].extend(snapshot.availability_options)
        summary["snapshots"].append(snapshot.model_dump(mode="json"))

        previous = get_previous_status(snapshot, seen)
        old_state = previous.get("state") if previous else None

        if settings.alert_status_changes and should_alert_status_change(
            snapshot,
            seen,
            alert_on_first_status=settings.alert_on_first_status,
        ):
            await telegram.send_status_change(snapshot, old_state)
            summary["status_alerts_sent"] += 1

        if snapshot.state == "BOOKING_FORM_OPEN":
            await telegram.send_booking_form_open_alert(snapshot)
            summary["status_alerts_sent"] += 1

        if snapshot.availability_options:
            await telegram.send_booking_options_alert(snapshot)
            summary["availability_alerts_sent"] += 1

        if snapshot.state in {
            "RATE_LIMITED",
            "ADHERENT_INVALID",
            "PAYMENT_OR_FINAL_CONFIRMATION",
            "NETWORK_ERROR",
        }:
            summary["errors"] += 1

        mark_status_seen(snapshot, seen)

    summary["booking_options_count"] = len(summary["booking_options"])
    summary["availability_options_count"] = len(summary["availability_options"])

    if settings.send_scan_summary:
        await telegram.send_scan_summary(summary)

    return summary
