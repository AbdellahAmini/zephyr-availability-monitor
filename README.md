# Zephyr Availability Monitor

Private Zephyr availability search tool for Moroccan Zephyr resorts.

The project can be used in two ways:

1. Local/manual CLI search using tools/manual_scan.py
2. Web UI search using a React app deployed to Vercel

The web UI does not store your Zephyr adherent number or Telegram bot token. It only triggers a GitHub Actions workflow. GitHub Actions runs the Playwright scanner and sends the grouped result to Telegram.

## What it checks

The scanner uses the official visible Zephyr adherent booking forms:

- Zephyr Martil
- Zephyr Agadir
- Zephyr Ifrane
- Zephyr Targa
- Zephyr Mazagan
- Zephyr Saïdia

It does not bypass queues, CAPTCHA, payment, or final reservation steps. It only checks availability and sends Telegram summaries.

## Required secrets

Keep these out of Git.

In your local .env:

ADHERENT_NUMBER=your_adherent_number
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_IDS=chat_id_1,chat_id_2
DRY_RUN=false
PRICE_FILTER_PRICE_IS_TOTAL_STAY=false

In GitHub repository secrets:

ADHERENT_NUMBER
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_IDS

Go to:

GitHub repository → Settings → Secrets and variables → Actions → New repository secret
