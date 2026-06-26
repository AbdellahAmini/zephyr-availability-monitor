import html

import httpx

from app.config import mask_adherent
from app.models import AvailabilityResult


class TelegramClient:
    def __init__(self, bot_token: str, chat_ids: list[str], dry_run: bool = False):
        self.bot_token = bot_token
        self.chat_ids = chat_ids
        self.dry_run = dry_run

    async def send_message(self, text: str) -> None:
        if self.dry_run:
            print("[DRY_RUN] Telegram message:")
            print(text)
            return

        async with httpx.AsyncClient(timeout=20) as client:
            for chat_id in self.chat_ids:
                try:
                    response = await client.post(
                        f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": text,
                            "parse_mode": "HTML",
                            "disable_web_page_preview": False,
                        },
                    )
                    response.raise_for_status()
                except Exception as exc:
                    print(f"Telegram send failed for chat_id={chat_id}: {exc}")

    async def send_alert(self, result: AvailabilityResult, adherent_number: str) -> None:
        booking_line = (
            f"\n\nBook now:\n{html.escape(result.booking_url)}"
            if result.booking_url
            else ""
        )

        text = f"""🚨 <b>Zephyr availability found</b>

City: {html.escape(result.city_name)}
Stay: {result.nights} nights
Check-in: {result.checkin.isoformat()}
Check-out: {result.checkout.isoformat()}
Room: {html.escape(result.room_type or "Unknown")}
Price: {html.escape(result.price or "Unknown")}
Adherent: {html.escape(mask_adherent(adherent_number))}
Found at: {html.escape(result.found_at.astimezone().strftime("%Y-%m-%d %H:%M"))}{booking_line}
"""
        await self.send_message(text)

    async def send_scan_summary(self, summary: dict) -> None:
        text = f"""✅ <b>Zephyr scan finished</b>

Checks attempted: {summary.get("checks_attempted", 0)}
Available results: {summary.get("available_results", 0)}
New alerts sent: {summary.get("new_alerts_sent", 0)}
Errors: {summary.get("errors", 0)}
"""
        await self.send_message(text)