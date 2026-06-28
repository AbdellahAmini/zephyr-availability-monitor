import asyncio
import sys
import html
import json
import os
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from app.browser_booking_client import BrowserBookingClient
from app.config import CITIES, mask_adherent
from app.telegram_client import TelegramClient


MOROCCO_TZ = ZoneInfo("Africa/Casablanca")


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def bool_env(name: str, default: bool = False) -> bool:
    raw = env(name, str(default)).lower()
    return raw in {"1", "true", "yes", "on"}


def int_env(name: str, default: int) -> int:
    try:
        return int(env(name, str(default)))
    except Exception:
        return default


def parse_date(value: str | None) -> date | None:
    value = (value or "").strip()

    if not value:
        return None

    return datetime.fromisoformat(value).date()


def parse_int_list(value: str, default: list[int]) -> list[int]:
    value = (value or "").strip()

    if not value:
        return default

    result = []

    for item in value.replace(";", ",").split(","):
        item = item.strip()

        if not item:
            continue

        result.append(int(item))

    return result or default


def city_matches(city, token: str) -> bool:
    token = token.strip().lower()

    if not token:
        return False

    return (
        city.key.lower() == token
        or city.name.lower() == token
        or city.name.lower().replace("zephyr ", "") == token
    )


def select_cities() -> list:
    raw = env("MANUAL_CITIES") or env("CITY_FILTER")

    if not raw:
        return list(CITIES)

    tokens = [item.strip().lower() for item in raw.replace(";", ",").split(",") if item.strip()]
    selected = [city for city in CITIES if any(city_matches(city, token) for token in tokens)]

    if not selected:
        valid = ", ".join(city.key for city in CITIES)
        raise RuntimeError(f"MANUAL_CITIES={raw!r} matched no cities. Valid: {valid}")

    return selected


def build_date_ranges() -> tuple[list[dict], dict]:
    today = datetime.now(MOROCCO_TZ).date()

    start_raw = env("MANUAL_START_DATE") or env("SEARCH_START_DATE") or env("START_DATE")
    end_raw = env("MANUAL_END_DATE") or env("SEARCH_END_DATE") or env("END_DATE")

    manual_period = bool(start_raw or end_raw)

    start = parse_date(start_raw) or today

    if end_raw:
        end = parse_date(end_raw)
    else:
        scan_days = int_env("SCAN_DAYS", 90)
        end = start + timedelta(days=max(scan_days - 1, 0))

    if not end:
        raise RuntimeError("Could not determine search end date")

    if end < start:
        raise RuntimeError(f"End date {end} is before start date {start}")

    nights = parse_int_list(
        env("MANUAL_STAY_LENGTHS_NIGHTS") or env("STAY_LENGTHS_NIGHTS"),
        [3, 4],
    )

    keep_checkout_inside = bool_env("MANUAL_KEEP_CHECKOUT_WITHIN_PERIOD", True)

    ranges = []
    cursor = start

    while cursor <= end:
        for night_count in nights:
            checkout = cursor + timedelta(days=night_count)

            if manual_period and keep_checkout_inside and checkout > end:
                continue

            ranges.append(
                {
                    "checkin": cursor,
                    "checkout": checkout,
                    "nights": night_count,
                }
            )

        cursor += timedelta(days=1)

    if manual_period:
        cap_raw = env("MANUAL_MAX_DATE_CHECKS_PER_CITY")
        cap = int(cap_raw) if cap_raw else None
    else:
        cap = int_env("BOOKING_MAX_DATE_CHECKS_PER_CITY", 4)

    if cap and cap > 0:
        ranges = ranges[:cap]

    if not ranges:
        raise RuntimeError(
            "No date ranges generated. Your period may be shorter than the requested nights. "
            "Example: start=2026-08-29 end=2026-09-05 nights=3,4"
        )

    params = {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "manual_period": manual_period,
        "stay_lengths_nights": nights,
        "keep_checkout_inside_period": keep_checkout_inside,
        "ranges_per_city": len(ranges),
        "cap_used": cap,
    }

    return ranges, params


def option_passes_extra_filters(option: dict) -> bool:
    text = " ".join(
        str(option.get(key) or "")
        for key in ["room_type", "label", "description", "price"]
    ).lower()

    room_filter = env("ROOM_TEXT_FILTER").lower()

    if room_filter and room_filter not in text:
        return False

    min_remaining_raw = env("MIN_REMAINING")

    if min_remaining_raw:
        try:
            min_remaining = int(min_remaining_raw)
            remaining = option.get("remaining")

            if remaining is None or int(remaining) < min_remaining:
                return False
        except Exception:
            return False

    breakfast_filter = env("BREAKFAST_FILTER", "any").lower()
    has_breakfast = (
        "petit déjeuner inclus" in text
        or "petit dejeuner inclus" in text
        or "breakfast included" in text
    )

    if breakfast_filter in {"with", "included", "yes"} and not has_breakfast:
        return False

    if breakfast_filter in {"without", "no", "excluded"} and has_breakfast:
        return False

    return True


def model_to_dict(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")

    if hasattr(value, "dict"):
        return value.dict()

    return value


def parse_dt(value: str):
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def month_label(value: str) -> str:
    dt = parse_dt(value)

    if not dt:
        return "Unknown month"

    return dt.strftime("%B %Y")


def day_label(value: str) -> str:
    dt = parse_dt(value)

    if not dt:
        return str(value)

    return dt.strftime("%d %b")


def build_telegram_messages(options: list[dict], params: dict, states: dict) -> list[str]:
    use_colors = bool_env("TELEGRAM_USE_COLOR_EMOJIS", True)

    if use_colors:
        tag_date = "🟩 DATE"
        tag_price = "🟨 PRICE"
        tag_details = "🟦 DETAILS"
        tag_city = "🏨"
        tag_bed = "🛏️"
        tag_link = "🔗"
    else:
        tag_date = "[DATE]"
        tag_price = "[PRICE]"
        tag_details = "[DETAILS]"
        tag_city = "[CITY]"
        tag_bed = "[ROOM]"
        tag_link = "[LINK]"

    max_price = env("MAX_PRICE_PER_NIGHT_MAD", "350")
    title = f"Zephyr manual search summary <= {max_price} MAD/night"

    if not options:
        state_lines = "\n".join(f"- {html.escape(str(k))}: {v}" for k, v in sorted(states.items()))

        text = f"""<b>{html.escape(title)}</b>

No matching availability found.

Search:
- Period: {html.escape(params["start_date"])} -> {html.escape(params["end_date"])}
- Nights: {html.escape(",".join(map(str, params["stay_lengths_nights"])))}
- Ranges per city: {params["ranges_per_city"]}

States:
{state_lines or "- none"}
"""
        return [text]

    grouped = defaultdict(list)

    for option in options:
        city = str(option.get("city_name") or option.get("city_key") or "Unknown city")
        month = month_label(option.get("checkin"))
        grouped[(city, month)].append(option)

    lines = [
        f"<b>{html.escape(title)}</b>",
        "",
        f"Found: <b>{len(options)}</b> matching option(s)",
        f"Period: <code>{html.escape(params['start_date'])} -> {html.escape(params['end_date'])}</code>",
        f"Nights: <code>{html.escape(','.join(map(str, params['stay_lengths_nights'])))}</code>",
    ]

    def sort_key(option):
        return (
            str(option.get("city_name") or ""),
            str(option.get("checkin") or ""),
            int(option.get("nights") or 0),
            float(option.get("price_per_night_mad") or 999999),
            str(option.get("room_type") or option.get("label") or ""),
        )

    for (city, month), city_options in sorted(grouped.items()):
        lines.append("")
        lines.append("--------------------------------------------------")
        lines.append(f"{tag_city} <b>{html.escape(city)}</b>")
        lines.append(f"<b>{html.escape(month)}</b>")

        by_range = defaultdict(list)

        for option in sorted(city_options, key=sort_key):
            checkin = str(option.get("checkin") or "")
            checkout = str(option.get("checkout") or "")
            nights = str(option.get("nights") or "")
            by_range[(checkin, checkout, nights)].append(option)

        for (checkin, checkout, nights), range_options in sorted(by_range.items()):
            lines.append("")
            lines.append(
                f"{tag_date}: <b>{html.escape(day_label(checkin))} -> {html.escape(day_label(checkout))}</b> "
                f"({html.escape(nights)} nights)"
            )
            lines.append(f"<code>{html.escape(checkin)} -> {html.escape(checkout)}</code>")

            for option in range_options:
                room = str(option.get("room_type") or option.get("label") or "Available booking")
                price = str(option.get("price") or "Unknown price")
                nightly = option.get("price_per_night_mad")
                remaining = option.get("remaining")
                desc = str(option.get("description") or "")
                url = str(option.get("booking_url") or option.get("source_url") or "")

                price_line = price

                if nightly:
                    try:
                        price_line += f" ({float(nightly):.0f} MAD/night)"
                    except Exception:
                        pass

                if remaining not in {None, ""}:
                    price_line += f" | {remaining} remaining"

                lines.append("")
                lines.append(f"{tag_bed} <b>{html.escape(room)}</b>")
                lines.append(f"{tag_price}: <b>{html.escape(price_line)}</b>")

                if desc:
                    lines.append(f"{tag_details}: {html.escape(desc)}")

                if url:
                    lines.append(f"{tag_link}: {html.escape(url)}")

    messages = []
    current = []

    for line in lines:
        candidate = "\n".join(current + [line])

        if len(candidate) > 3500 and current:
            messages.append("\n".join(current))
            current = [
                f"<b>{html.escape(title)}</b>",
                "<i>continued...</i>",
                "",
                line,
            ]
        else:
            current.append(line)

    if current:
        messages.append("\n".join(current))

    return messages


async def main():
    load_dotenv()

    os.environ.setdefault("PRICE_FILTER_PRICE_IS_TOTAL_STAY", "false")

    scan_id = datetime.now(MOROCCO_TZ).isoformat()
    scan_started_at = datetime.now(MOROCCO_TZ)

    cities = select_cities()
    date_ranges, params = build_date_ranges()

    os.environ["MAX_PRICE_PER_NIGHT_MAD"] = env("MAX_PRICE_PER_NIGHT_MAD", "350")

    adherent_number = env("ADHERENT_NUMBER")
    bot_token = env("TELEGRAM_BOT_TOKEN")
    chat_ids = [item.strip() for item in env("TELEGRAM_CHAT_IDS").replace(";", ",").split(",") if item.strip()]

    if not adherent_number:
        raise RuntimeError("ADHERENT_NUMBER is missing")

    print("Zephyr manual search started", flush=True)
    print(f"Adherent: {mask_adherent(adherent_number)}", flush=True)
    print(f"Cities: {', '.join(city.name for city in cities)}", flush=True)
    print(f"Period: {params['start_date']} -> {params['end_date']}", flush=True)
    print(f"Nights: {params['stay_lengths_nights']}", flush=True)
    print(f"Ranges per city: {params['ranges_per_city']}", flush=True)
    print(f"Max price/night: {env('MAX_PRICE_PER_NIGHT_MAD', '350')} MAD", flush=True)

    client = BrowserBookingClient(
        headless=bool_env("HEADLESS_BROWSER", True),
        wait_seconds=int_env("BOOKING_WAIT_SECONDS", 60),
        hold_browser_open_seconds=int_env("BOOKING_HOLD_BROWSER_OPEN_SECONDS", 0),
    )

    telegram = TelegramClient(
        bot_token=bot_token,
        chat_ids=chat_ids,
        dry_run=bool_env("DRY_RUN", False),
    )

    snapshots = []
    all_options = []

    for city_index, city in enumerate(cities, start=1):
        print("", flush=True)
        print(f"[{city_index}/{len(cities)}] {city.name}: checking {len(date_ranges)} range(s)", flush=True)

        city_snapshots = await client.scan_city_ranges(
            scan_id=scan_id,
            scan_started_at=scan_started_at,
            city=city,
            adherent_number=adherent_number,
            date_ranges=date_ranges,
        )

        snapshots.extend(city_snapshots)

        city_options_count = 0

        for snapshot in city_snapshots:
            for option in getattr(snapshot, "availability_options", []) or []:
                if option_passes_extra_filters(option):
                    all_options.append(option)
                    city_options_count += 1

        print(f"[{city.name}] done. Matching options: {city_options_count}", flush=True)

    states = Counter(getattr(snapshot, "state", "UNKNOWN") for snapshot in snapshots)

    summary = {
        "scan_id": scan_id,
        "manual_search": True,
        "parameters": {
            **params,
            "cities": [city.key for city in cities],
            "max_price_per_night_mad": env("MAX_PRICE_PER_NIGHT_MAD", "350"),
            "room_text_filter": env("ROOM_TEXT_FILTER"),
            "min_remaining": env("MIN_REMAINING"),
            "breakfast_filter": env("BREAKFAST_FILTER", "any"),
        },
        "snapshots_checked": len(snapshots),
        "states": dict(states),
        "availability_options_count": len(all_options),
        "availability_options": all_options,
        "snapshots": [model_to_dict(snapshot) for snapshot in snapshots],
    }

    Path("data").mkdir(exist_ok=True)
    Path("data/manual_latest_scan_results.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    messages = build_telegram_messages(all_options, params, dict(states))

    for message in messages:
        await telegram.send_message(message)

    print("", flush=True)
    print("Zephyr manual search finished", flush=True)
    print(json.dumps(
        {
            "snapshots_checked": len(snapshots),
            "states": dict(states),
            "availability_options_count": len(all_options),
            "telegram_messages_sent": len(messages),
            "results_file": "data/manual_latest_scan_results.json",
        },
        ensure_ascii=False,
        indent=2,
    ), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
