import argparse
import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from playwright.async_api import async_playwright, Request, Response


CITY_URLS = {
    "central": "https://zephyr.ma/reservations/",
    "ifrane": "https://zephyrifrane.ma/reservations/",
    "targa": "https://zephyrtarga.ma/reservations/",
    "mazagan": "https://zephyrmazagan.ma/reservations/",
    "agadir": "https://zephyragadir.ma/reservations/",
    "martil": "https://zephyrmartil.ma/reservations/",
    "saidia": "https://zephyrsaidia.ma/reservations/",
}


DEBUG_DIR = Path("debug/zephyr_discovery")
DEBUG_DIR.mkdir(parents=True, exist_ok=True)


INTERESTING_KEYWORDS = [
    "tools-v2",
    "zephyr",
    "reservation",
    "reservations",
    "booking",
    "availability",
    "avail",
    "search",
    "dispon",
    "adherent",
    "api",
    "hotel",
    "room",
    "chambre",
    "tarif",
]


SENSITIVE_HEADER_NAMES = {
    "cookie",
    "authorization",
    "x-csrf-token",
    "x-xsrf-token",
    "set-cookie",
}


def redact_text(value: str | None) -> str | None:
    if value is None:
        return None

    redacted = value

    sensitive_values = [
        os.getenv("ADHERENT_NUMBER", ""),
        os.getenv("TELEGRAM_BOT_TOKEN", ""),
    ]

    for secret in sensitive_values:
        if secret:
            redacted = redacted.replace(secret, "<REDACTED_SECRET>")

    # Redact common numeric adherent-looking values.
    redacted = re.sub(
        r"(?i)(adherent|adhérent|numero|numéro|matricule|fm6)[^\n\r]{0,40}",
        lambda match: re.sub(r"\d{4,}", "<REDACTED_NUMBER>", match.group(0)),
        redacted,
    )

    # Redact long standalone numbers conservatively.
    redacted = re.sub(r"\b\d{7,}\b", "<REDACTED_NUMBER>", redacted)

    return redacted


def sanitize_headers(headers: dict[str, str]) -> dict[str, str]:
    clean = {}

    for key, value in headers.items():
        if key.lower() in SENSITIVE_HEADER_NAMES:
            clean[key] = "<REDACTED_HEADER>"
        else:
            clean[key] = redact_text(value) or ""

    return clean


def is_interesting_url(url: str) -> bool:
    lowered = url.lower()
    return any(keyword in lowered for keyword in INTERESTING_KEYWORDS)


def is_text_response(content_type: str) -> bool:
    lowered = content_type.lower()
    return any(
        item in lowered
        for item in [
            "application/json",
            "text/",
            "application/javascript",
            "application/x-www-form-urlencoded",
        ]
    )


async def discover(city: str, headed: bool, seconds_after_load: int) -> None:
    target_url = CITY_URLS[city]
    network_events: list[dict[str, Any]] = []

    print(f"Discovery target: {city}")
    print(f"Opening: {target_url}")
    print(f"Headed browser: {headed}")
    print(f"Output folder: {DEBUG_DIR}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not headed)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 1100},
            locale="fr-FR",
            timezone_id="Africa/Casablanca",
        )

        page = await context.new_page()

        def capture_request(request: Request) -> None:
            entry = {
                "event": "request",
                "timestamp": datetime.now().isoformat(),
                "method": request.method,
                "url": request.url,
                "interesting": is_interesting_url(request.url),
                "headers": sanitize_headers(request.headers),
                "post_data": redact_text(request.post_data),
                "resource_type": request.resource_type,
            }
            network_events.append(entry)

        async def capture_response(response: Response) -> None:
            try:
                request = response.request
                content_type = response.headers.get("content-type", "")

                entry: dict[str, Any] = {
                    "event": "response",
                    "timestamp": datetime.now().isoformat(),
                    "status": response.status,
                    "url": response.url,
                    "interesting": is_interesting_url(response.url),
                    "request_method": request.method,
                    "content_type": content_type,
                    "headers": sanitize_headers(response.headers),
                }

                if is_interesting_url(response.url) and is_text_response(content_type):
                    try:
                        body = await response.text()
                        body = redact_text(body) or ""

                        if len(body) > 30000:
                            body = body[:30000] + "\n\n<TRUNCATED>"

                        entry["body_preview"] = body
                    except Exception as exc:
                        entry["body_preview_error"] = str(exc)

                network_events.append(entry)

            except Exception as exc:
                network_events.append(
                    {
                        "event": "response_capture_error",
                        "timestamp": datetime.now().isoformat(),
                        "error": str(exc),
                    }
                )

        page.on("request", capture_request)
        page.on("response", lambda response: asyncio.create_task(capture_response(response)))

        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(seconds_after_load * 1000)

            await page.screenshot(
                path=DEBUG_DIR / f"{city}_initial_page.png",
                full_page=True,
            )

            html = await page.content()
            (DEBUG_DIR / f"{city}_initial_page.html").write_text(
                redact_text(html) or "",
                encoding="utf-8",
            )

            if headed:
                print()
                print("Browser is open.")
                print("Manually do the normal reservation steps:")
                print("1. Select destination if needed.")
                print("2. Enter the adherent number.")
                print("3. Select dates if the form allows it.")
                print("4. Click the normal reservation/search button.")
                print()
                await asyncio.to_thread(
                    input,
                    "After you finish the manual steps, press ENTER here to save the captured network traffic..."
                )

                await page.wait_for_timeout(3000)

                await page.screenshot(
                    path=DEBUG_DIR / f"{city}_after_manual_steps.png",
                    full_page=True,
                )

                final_html = await page.content()
                (DEBUG_DIR / f"{city}_after_manual_steps.html").write_text(
                    redact_text(final_html) or "",
                    encoding="utf-8",
                )

        finally:
            await page.wait_for_timeout(2000)
            await context.close()
            await browser.close()

    output_path = DEBUG_DIR / f"{city}_network.json"
    output_path.write_text(
        json.dumps(network_events, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    interesting = [
        item
        for item in network_events
        if item.get("interesting") is True
    ]

    summary_path = DEBUG_DIR / f"{city}_interesting_summary.json"
    summary_path.write_text(
        json.dumps(interesting, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print()
    print("Discovery complete.")
    print(f"Full network log: {output_path}")
    print(f"Interesting summary: {summary_path}")
    print(f"Screenshots saved in: {DEBUG_DIR}")
    print()
    print("Next: inspect the interesting summary for endpoint URLs, methods, payloads, and response bodies.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--city",
        choices=sorted(CITY_URLS.keys()),
        default="central",
        help="Which reservation page to inspect.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Open visible browser so you can manually interact with the reservation form.",
    )
    parser.add_argument(
        "--seconds-after-load",
        type=int,
        default=8,
        help="Seconds to wait after the page loads before saving initial state.",
    )
    return parser.parse_args()


async def main() -> None:
    load_dotenv()
    args = parse_args()
    await discover(
        city=args.city,
        headed=args.headed,
        seconds_after_load=args.seconds_after_load,
    )


if __name__ == "__main__":
    asyncio.run(main())