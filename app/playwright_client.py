import json
from pathlib import Path

from playwright.async_api import async_playwright


DEBUG_DIR = Path("debug")
DEBUG_DIR.mkdir(exist_ok=True)


async def discover_network(city_url: str) -> None:
    captured = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        page.on(
            "request",
            lambda request: captured.append(
                {
                    "type": "request",
                    "method": request.method,
                    "url": request.url,
                    "headers": sanitize_headers(request.headers),
                    "post_data": request.post_data,
                }
            ),
        )

        page.on(
            "response",
            lambda response: captured.append(
                {
                    "type": "response",
                    "status": response.status,
                    "url": response.url,
                }
            ),
        )

        await page.goto(city_url, wait_until="networkidle")
        await page.screenshot(path=DEBUG_DIR / "reservation_page.png", full_page=True)

        # Manual selectors must be added after observing the page.
        # Example future flow:
        # await page.fill("input[name='adherent']", adherent_number)
        # await page.click("text=Réserver maintenant")

        await browser.close()

    (DEBUG_DIR / "network.json").write_text(
        json.dumps(captured, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def sanitize_headers(headers: dict) -> dict:
    blocked = {"cookie", "authorization", "x-csrf-token"}
    return {
        key: ("<redacted>" if key.lower() in blocked else value)
        for key, value in headers.items()
    }