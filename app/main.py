import asyncio

from dotenv import load_dotenv

from app.config import load_settings, mask_adherent
from app.dedupe import load_seen, save_seen
from app.scanner import run_scan


async def async_main() -> None:
    load_dotenv()

    settings = load_settings()

    print("Zephyr scan started")
    print(f"Adherent: {mask_adherent(settings.adherent_number)}")
    print(f"Scan days: {settings.scan_days}")
    print(f"Stay lengths: {settings.stay_lengths_nights}")
    print(f"Dry run: {settings.dry_run}")

    seen = load_seen()
    summary = await run_scan(settings, seen)
    save_seen(seen)

    print("Zephyr scan finished")
    print(summary)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()