import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

from app.config import load_settings, mask_adherent
from app.dedupe import load_seen, save_seen
from app.scanner import run_scan


async def async_main() -> None:
    load_dotenv()

    settings = load_settings()

    print("Zephyr production status monitor started")
    print(f"Adherent: {mask_adherent(settings.adherent_number)}")
    print(f"Dry run: {settings.dry_run}")
    print(f"Public page monitor: {settings.enable_public_page_monitor}")
    print(f"Hotel page monitor: {settings.enable_hotel_page_monitor}")
    print(f"Queue monitor: {settings.enable_queue_monitor}")
    print(f"Alert status changes: {settings.alert_status_changes}")
    print(f"Alert on first status: {settings.alert_on_first_status}")
    print()

    seen = load_seen()
    summary = await run_scan(settings, seen)

    Path("data").mkdir(exist_ok=True)
    Path("data/latest_scan_results.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if settings.dry_run:
        print("Dry run enabled: state was NOT saved to data/seen.json")
    else:
        save_seen(seen)

    Path("debug").mkdir(exist_ok=True)
    Path("debug/latest_summary.json").write_text(
        json.dumps(
            {
                key: value
                for key, value in summary.items()
                if key not in {"snapshots"}
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("Zephyr production status monitor finished")
    print(json.dumps(
        {
            key: value
            for key, value in summary.items()
            if key not in {"snapshots"}
        },
        ensure_ascii=False,
        indent=2,
    ))

    print()
    print("Full scan results written to: data/latest_scan_results.json")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
