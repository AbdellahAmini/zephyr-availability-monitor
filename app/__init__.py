import argparse
import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv
from playwright.async_api import async_playwright, Request, Response, WebSocket


BOOKING_URLS = {
    "martil": "https://booking.zephyr.ma/martil/s/a/",
    "agadir": "https://booking.zephyr.ma/agadir/s/a/",
    "ifrane": "https://booking.zephyr.ma/ifrane/s/a/",
    "targa": "https://booking.zephyr.ma/targa/s/a/",
    "mazagan": "https://booking.zephyr.ma/mazagan/s/a/",
    "saidia": "https://booking.zephyr.ma/saidia/s/a/",
}


DEBUG_DIR = Path("debug/booking_discovery")
DEBUG_DIR.mkdir(parents=True, exist_ok=True)


TARGET_DOMAINS = {
    "booking.zephyr.ma",
    "tools-v2.zephyr.ma",
}


STATIC_EXTENSIONS = (
    ".css",
    ".js",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".svg",
    ".woff",
    ".woff2",
    ".ttf",
    ".ico",
)


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


def is_target_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()

    if host not in TARGET_DOMAINS:
        return False

    if path.endswith(STATIC_EXTENSIONS):
        return False

    return True


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


async def discover_booking(city: str, wait_seconds: int, headed: bool) -> None:
    url = BOOKING_URLS[city]

    output_dir = DEBUG_DIR / city
    output_dir.mkdir(parents=True, exist_ok=True)

    network_events: list[dict[str, Any]] = []
    websocket_events: list[dict[str, Any]] = []
    page_events: list[dict[str, Any]] = []

    print(f"Booking discovery target: {city}")
    print(f"Opening: {url}")
    print(f"Wait seconds: {wait_seconds}")
    print(f"Output folder: {output_dir}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not headed)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 1100},
            locale="fr-FR",
            timezone_id="Africa/Casablanca",
        )

        page = await context.new_page()

        def capture_request(request: Request) -> None:
            if not is_target_url(request.url):
                return

            network_events.append(
                {
                    "event": "request",
                    "timestamp": datetime.now().isoformat(),
                    "method": request.method,
                    "url": request.url,
                    "resource_type": request.resource_type,
                    "headers": sanitize_headers(request.headers),
                    "post_data": redact_text(request.post_data),
                }
            )

        async def capture_response(response: Response) -> None:
            if not is_target_url(response.url):
                return

            try:
                request = response.request
                content_type = response.headers.get("content-type", "")

                entry: dict[str, Any] = {
                    "event": "response",
                    "timestamp": datetime.now().isoformat(),
                    "status": response.status,
                    "url": response.url,
                    "request_method": request.method,
                    "content_type": content_type,
                    "headers": sanitize_headers(response.headers),
                }

                if is_text_response(content_type):
                    try:
                        body = await response.text()
                        body = redact_text(body) or ""

                        if len(body) > 40000:
                            body = body[:40000] + "\n\n<TRUNCATED>"

                        entry["body_preview"] = body
                    except Exception as exc:
                        entry["body_preview_error"] = str(exc)

                network_events.append(entry)

            except Exception as exc:
                network_events.append(
                    {
                        "event": "response_capture_error",
                        "timestamp": datetime.now().isoformat(),
                        "url": response.url,
                        "error": str(exc),
                    }
                )

        def capture_websocket(ws: WebSocket) -> None:
            websocket_events.append(
                {
                    "event": "websocket_opened",
                    "timestamp": datetime.now().isoformat(),
                    "url": ws.url,
                }
            )

            ws.on(
                "framesent",
                lambda payload: websocket_events.append(
                    {
                        "event": "websocket_framesent",
                        "timestamp": datetime.now().isoformat(),
                        "url": ws.url,
                        "payload": redact_text(str(payload)),
                    }
                ),
            )

            ws.on(
                "framereceived",
                lambda payload: websocket_events.append(
                    {
                        "event": "websocket_framereceived",
                        "timestamp": datetime.now().isoformat(),
                        "url": ws.url,
                        "payload": redact_text(str(payload)),
                    }
                ),
            )

        page.on("request", capture_request)
        page.on("response", lambda response: asyncio.create_task(capture_response(response)))
        page.on("websocket", capture_websocket)

        page.on(
            "framenavigated",
            lambda frame: page_events.append(
                {
                    "event": "framenavigated",
                    "timestamp": datetime.now().isoformat(),
                    "url": frame.url,
                }
            ),
        )

        await page.goto(url, wait_until="domcontentloaded", timeout=60000)

        await page.screenshot(
            path=output_dir / "initial.png",
            full_page=True,
        )

        initial_html = await page.content()
        (output_dir / "initial.html").write_text(
            redact_text(initial_html) or "",
            encoding="utf-8",
        )

        print()
        print("Page loaded. Waiting naturally. Do not refresh the page.")
        print("If the queue advances, interact manually only with the normal visible form.")
        print()

        for elapsed in range(0, wait_seconds, 20):
            await page.wait_for_timeout(20_000)

            try:
                visible_text = await page.locator("body").inner_text(timeout=5000)
                visible_text = redact_text(visible_text) or ""
                visible_text = visible_text[:2000]

                page_events.append(
                    {
                        "event": "visible_text_snapshot",
                        "timestamp": datetime.now().isoformat(),
                        "elapsed_seconds": elapsed + 20,
                        "text": visible_text,
                    }
                )

                print(f"[{elapsed + 20}s] Visible page text:")
                print(visible_text[:500].replace("\n", " | "))
                print()

            except Exception as exc:
                page_events.append(
                    {
                        "event": "visible_text_error",
                        "timestamp": datetime.now().isoformat(),
                        "elapsed_seconds": elapsed + 20,
                        "error": str(exc),
                    }
                )

        await page.screenshot(
            path=output_dir / "final.png",
            full_page=True,
        )

        final_html = await page.content()
        (output_dir / "final.html").write_text(
            redact_text(final_html) or "",
            encoding="utf-8",
        )

        await context.close()
        await browser.close()

    (output_dir / "network.json").write_text(
        json.dumps(network_events, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    (output_dir / "websockets.json").write_text(
        json.dumps(websocket_events, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    (output_dir / "page_events.json").write_text(
        json.dumps(page_events, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print()
    print("Booking discovery complete.")
    print(f"Network: {output_dir / 'network.json'}")
    print(f"WebSockets: {output_dir / 'websockets.json'}")
    print(f"Page events: {output_dir / 'page_events.json'}")
    print(f"Screenshots: {output_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--city",
        choices=sorted(BOOKING_URLS.keys()),
        default="martil",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=180,
    )
    parser.add_argument(
        "--headed",
        action="store_true",
    )
    return parser.parse_args()


async def main() -> None:
    load_dotenv()
    args = parse_args()

    await discover_booking(
        city=args.city,
        wait_seconds=args.wait_seconds,
        headed=args.headed,
    )


if __name__ == "__main__":
    asyncio.run(main())