import os
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class City:
    key: str
    name: str
    hotel_site: str
    booking_adherent_url: str
    booking_public_url: str


CITIES = [
    City("martil", "Zephyr Martil", "https://zephyrmartil.ma/", "https://booking.zephyr.ma/martil/s/a/", "https://booking.zephyr.ma/martil/s/n/"),
    City("agadir", "Zephyr Agadir", "https://zephyragadir.ma/", "https://booking.zephyr.ma/agadir/s/a/", "https://booking.zephyr.ma/agadir/s/n/"),
    City("ifrane", "Zephyr Ifrane", "https://zephyrifrane.ma/", "https://booking.zephyr.ma/ifrane/s/a/", "https://booking.zephyr.ma/ifrane/s/n/"),
    City("targa", "Zephyr Targa", "https://zephyrtarga.ma/", "https://booking.zephyr.ma/targa/s/a/", "https://booking.zephyr.ma/targa/s/n/"),
    City("mazagan", "Zephyr Mazagan", "https://zephyrmazagan.ma/", "https://booking.zephyr.ma/mazagan/s/a/", "https://booking.zephyr.ma/mazagan/s/n/"),
    City("saidia", "Zephyr Saïdia", "https://zephyrsaidia.ma/", "https://booking.zephyr.ma/saidia/s/a/", "https://booking.zephyr.ma/saidia/s/n/"),
]


PUBLIC_PAGES = [
    {
        "key": "zephyr_home",
        "name": "Zephyr Homepage",
        "url": "https://zephyr.ma/",
        "page_type": "public_home",
    },
    {
        "key": "zephyr_reservations",
        "name": "Zephyr Reservations",
        "url": "https://zephyr.ma/reservations/",
        "page_type": "public_reservation",
    },
]


@dataclass(frozen=True)
class Settings:
    adherent_number: str
    telegram_bot_token: str
    telegram_chat_ids: list[str]

    scan_days: int
    stay_lengths_nights: list[int]
    max_concurrency: int
    dry_run: bool

    alert_status_changes: bool
    alert_on_first_status: bool
    send_scan_summary: bool

    enable_public_page_monitor: bool
    enable_hotel_page_monitor: bool
    enable_queue_monitor: bool

    enable_browser_booking_scan: bool
    headless_browser: bool
    booking_wait_seconds: int
    booking_hold_browser_open_seconds: int
    booking_max_date_checks_per_city: int

    http_timeout_seconds: float


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_settings() -> Settings:
    chat_ids = [
        value.strip()
        for value in os.environ.get("TELEGRAM_CHAT_IDS", "").split(",")
        if value.strip()
    ]

    stay_lengths = [
        int(value.strip())
        for value in os.environ.get("STAY_LENGTHS_NIGHTS", "3,4").split(",")
        if value.strip()
    ]

    return Settings(
        adherent_number=os.environ.get("ADHERENT_NUMBER", ""),
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_ids=chat_ids,

        scan_days=int(os.environ.get("SCAN_DAYS", "90")),
        stay_lengths_nights=stay_lengths,
        max_concurrency=int(os.environ.get("MAX_CONCURRENCY", "1")),
        dry_run=env_bool("DRY_RUN", False),

        alert_status_changes=env_bool("ALERT_STATUS_CHANGES", True),
        alert_on_first_status=env_bool("ALERT_ON_FIRST_STATUS", False),
        send_scan_summary=env_bool("SEND_SCAN_SUMMARY", False),

        enable_public_page_monitor=env_bool("ENABLE_PUBLIC_PAGE_MONITOR", False),
        enable_hotel_page_monitor=env_bool("ENABLE_HOTEL_PAGE_MONITOR", False),
        enable_queue_monitor=env_bool("ENABLE_QUEUE_MONITOR", True),

        enable_browser_booking_scan=env_bool("ENABLE_BROWSER_BOOKING_SCAN", True),
        headless_browser=env_bool("HEADLESS_BROWSER", True),
        booking_wait_seconds=int(os.environ.get("BOOKING_WAIT_SECONDS", "60")),
        booking_hold_browser_open_seconds=int(os.environ.get("BOOKING_HOLD_BROWSER_OPEN_SECONDS", "0")),
        booking_max_date_checks_per_city=int(os.environ.get("BOOKING_MAX_DATE_CHECKS_PER_CITY", "1")),

        http_timeout_seconds=float(os.environ.get("HTTP_TIMEOUT_SECONDS", "30")),
    )


def mask_adherent(number: str) -> str:
    if not number:
        return "missing"
    return f"****{number[-4:]}"

@dataclass(frozen=True)
class TestDateRange:
    checkin: date
    checkout: date

    @property
    def nights(self) -> int:
        return (self.checkout - self.checkin).days


def parse_test_date_ranges() -> list[TestDateRange]:
    raw = os.getenv("BOOKING_TEST_DATE_RANGES", "").strip()

    if not raw:
        return []

    ranges: list[TestDateRange] = []

    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue

        try:
            checkin_raw, checkout_raw = item.split(":", 1)

            checkin = datetime.strptime(checkin_raw.strip(), "%Y-%m-%d").date()
            checkout = datetime.strptime(checkout_raw.strip(), "%Y-%m-%d").date()

            if checkout <= checkin:
                raise ValueError("checkout must be after checkin")

            ranges.append(TestDateRange(checkin=checkin, checkout=checkout))

        except Exception as exc:
            raise ValueError(
                f"Invalid BOOKING_TEST_DATE_RANGES item: {item}. "
                f"Expected format: YYYY-MM-DD:YYYY-MM-DD"
            ) from exc

    return ranges

def _apply_city_filter_for_local_tests() -> None:
    global CITIES

    raw = os.getenv("CITY_FILTER", os.getenv("TEST_CITY", "")).strip().lower()

    if not raw:
        return

    allowed = {
        item.strip().lower()
        for item in raw.split(",")
        if item.strip()
    }

    filtered = [
        city
        for city in CITIES
        if city.key.lower() in allowed
        or city.name.lower().replace("zephyr ", "") in allowed
    ]

    if not filtered:
        valid = ", ".join(city.key for city in CITIES)
        raise RuntimeError(
            f"CITY_FILTER={raw!r} matched no cities. Valid city keys: {valid}"
        )

    CITIES = filtered


_apply_city_filter_for_local_tests()

