from dataclasses import dataclass
import os


@dataclass(frozen=True)
class City:
    key: str
    name: str
    base_url: str


CITIES = [
    City("ifrane", "Zephyr Ifrane", "https://zephyrifrane.ma"),
    City("targa", "Zephyr Targa", "https://zephyrtarga.ma"),
    City("mazagan", "Zephyr Mazagan", "https://zephyrmazagan.ma"),
    City("agadir", "Zephyr Agadir", "https://zephyragadir.ma"),
    City("martil", "Zephyr Martil", "https://zephyrmartil.ma"),
    City("saidia", "Zephyr Saïdia", "https://zephyrsaidia.ma"),
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
        adherent_number=os.environ["ADHERENT_NUMBER"],
        telegram_bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
        telegram_chat_ids=chat_ids,
        scan_days=int(os.environ.get("SCAN_DAYS", "90")),
        stay_lengths_nights=stay_lengths,
        max_concurrency=int(os.environ.get("MAX_CONCURRENCY", "4")),
        dry_run=os.environ.get("DRY_RUN", "false").lower() == "true",
    )


def mask_adherent(number: str) -> str:
    if not number:
        return "missing"
    return f"****{number[-4:]}"