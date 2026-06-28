import html

import httpx

from app.config import mask_adherent
from app.models import AvailabilityResult, SnapshotRecord


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

        if not self.bot_token or not self.chat_ids:
            print("Telegram is not configured. Skipping message.")
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
            f"\n\nBook manually:\n{html.escape(result.booking_url)}"
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
Found at: {html.escape(result.found_at.astimezone().strftime("%Y-%m-%d %H:%M Morocco time"))}{booking_line}
"""
        await self.send_message(text)

    async def send_status_change(
        self,
        snapshot: SnapshotRecord,
        old_state: str | None,
    ) -> None:
        text = f"""ℹ️ <b>Zephyr status changed</b>

City: {html.escape(snapshot.city_name)}
Page: {html.escape(snapshot.page_type)}
Old state: {html.escape(old_state or "none")}
New state: {html.escape(snapshot.state)}
Message: {html.escape(snapshot.visible_message[:700])}
Seen at: {html.escape(snapshot.scan_started_at.astimezone().strftime("%Y-%m-%d %H:%M Morocco time"))}

URL:
{html.escape(snapshot.source_url)}
"""
        await self.send_message(text)

    async def send_booking_form_open_alert(self, snapshot: SnapshotRecord) -> None:
        text = f"""🟢 <b>Zephyr booking form may be open</b>

City: {html.escape(snapshot.city_name)}
State: {html.escape(snapshot.state)}
Message: {html.escape(snapshot.visible_message[:700])}

Open manually:
{html.escape(snapshot.source_url)}
"""
        await self.send_message(text)

    async def send_booking_options_alert(self, snapshot: SnapshotRecord) -> None:
        from collections import defaultdict
        from datetime import datetime

        GREEN = "\U0001F7E2"
        BLUE = "\U0001F535"
        YELLOW = "\U0001F7E1"
        HOTEL = "\U0001F3E8"
        CAL = "\U0001F4C5"
        BED = "\U0001F6CF\U0000FE0F"
        MONEY = "\U0001F4B0"
        NOTE = "\U0001F4DD"

        options = list(snapshot.availability_options or [])

        if not options:
            text = f"""?? <b>Possible Zephyr booking options detected</b>

City: {html.escape(snapshot.city_name)}
State: {html.escape(snapshot.state)}

Confirm manually before booking:
{html.escape(snapshot.source_url)}
"""
            await self.send_message(text)
            return

        def clean(value, fallback=""):
            if value is None:
                return fallback
            value = str(value).strip()
            return value if value else fallback

        def parse_date(value):
            value = clean(value)
            try:
                return datetime.fromisoformat(value)
            except Exception:
                return None

        def month_label(value):
            dt = parse_date(value)
            return dt.strftime("%B %Y") if dt else "Unknown month"

        def day_label(value):
            dt = parse_date(value)
            return dt.strftime("%d %b") if dt else clean(value, "Unknown date")

        def sort_key(option):
            return (
                clean(option.get("city_name") or snapshot.city_name),
                clean(option.get("checkin") or snapshot.checkin),
                int(option.get("nights") or snapshot.nights or 0),
                clean(option.get("room_type") or option.get("label")),
                float(option.get("price_per_night_mad") or 999999),
            )

        options = sorted(options, key=sort_key)

        max_prices = []
        for option in options:
            try:
                max_prices.append(float(option.get("max_price_per_night_mad")))
            except Exception:
                pass

        max_price_text = ""
        if max_prices:
            max_price_text = f" ? {min(max_prices):.0f} MAD/night"

        grouped = defaultdict(list)

        for option in options:
            city = clean(option.get("city_name") or snapshot.city_name, "Unknown city")
            month = month_label(option.get("checkin") or snapshot.checkin)
            grouped[(city, month)].append(option)

        lines = [
            f"{GREEN} <b>Zephyr availability summary{html.escape(max_price_text)}</b>",
            "",
            f"Found: <b>{len(options)}</b> option(s)",
        ]

        for (city, month), group_options in grouped.items():
            lines.append("")
            lines.append(f"{HOTEL} <b>{html.escape(city)}</b>")
            lines.append(f"{CAL} <b>{html.escape(month)}</b>")

            by_range = defaultdict(list)

            for option in group_options:
                checkin = clean(option.get("checkin") or snapshot.checkin)
                checkout = clean(option.get("checkout") or snapshot.checkout)
                nights = clean(option.get("nights") or snapshot.nights)
                by_range[(checkin, checkout, nights)].append(option)

            for (checkin, checkout, nights), range_options in sorted(by_range.items()):
                date_range = f"{day_label(checkin)} -> {day_label(checkout)}"
                full_range = f"{checkin} -> {checkout}"

                lines.append("")
                lines.append(f"{GREEN} <b>{html.escape(date_range)}</b>  |  {html.escape(str(nights))} nights")
                lines.append(f"   <code>{html.escape(full_range)}</code>")

                for option in sorted(range_options, key=sort_key):
                    title = clean(
                        option.get("room_type")
                        or option.get("label")
                        or "Available booking"
                    )

                    price = clean(option.get("price"), "Unknown price")
                    nightly = option.get("price_per_night_mad")
                    remaining = option.get("remaining")
                    description = clean(option.get("description"))
                    url = clean(
                        option.get("booking_url")
                        or option.get("source_url")
                        or snapshot.source_url
                    )

                    price_line = price
                    if nightly:
                        try:
                            price_line += f" ({float(nightly):.0f} MAD/night)"
                        except Exception:
                            pass

                    remaining_line = ""
                    if remaining not in (None, ""):
                        remaining_line = f" | {remaining} remaining"

                    lines.append("")
                    lines.append(f"   {BED} <b>{html.escape(title)}</b>")
                    lines.append(f"   {YELLOW} {MONEY} <b>{html.escape(price_line)}</b>{html.escape(remaining_line)}")

                    if description:
                        lines.append(f"   {BLUE} {NOTE} {html.escape(description)}")

        # Telegram has a practical 4096-character message limit.
        # Split cleanly if a city has many options.
        messages = []
        current = []

        for line in lines:
            candidate = "\n".join(current + [line])

            if len(candidate) > 3500 and current:
                messages.append("\n".join(current))
                current = [
                    f"{GREEN} <b>Zephyr availability summary{html.escape(max_price_text)}</b>",
                    "<i>continued...</i>",
                    "",
                    line,
                ]
            else:
                current.append(line)

        if current:
            messages.append("\n".join(current))

        for message in messages:
            await self.send_message(message)


    async def send_scan_summary(self, summary: dict) -> None:
        states = summary.get("states", {})
        state_lines = "\n".join(
            f"- {html.escape(str(state))}: {count}"
            for state, count in sorted(states.items())
        )

        text = f"""✅ <b>Zephyr scan finished</b>

Snapshots checked: {summary.get("snapshots_checked", 0)}
Status alerts sent: {summary.get("status_alerts_sent", 0)}
Availability alerts sent: {summary.get("availability_alerts_sent", 0)}
Errors: {summary.get("errors", 0)}

Visible booking links found: {summary.get("booking_options_count", 0)}
Possible availability options found: {summary.get("availability_options_count", 0)}

States:
{state_lines or "- none"}
"""
        await self.send_message(text)
