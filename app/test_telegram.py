import asyncio
from dotenv import load_dotenv

from app.config import load_settings
from app.telegram_client import TelegramClient


async def main():
    load_dotenv()
    settings = load_settings()

    telegram = TelegramClient(
        bot_token=settings.telegram_bot_token,
        chat_ids=settings.telegram_chat_ids,
        dry_run=settings.dry_run,
    )

    await telegram.send_message("✅ Zephyr monitor Telegram test message received.")


if __name__ == "__main__":
    asyncio.run(main())