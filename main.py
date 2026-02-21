#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Точка входа: Telegram-бот для извлечения данных из паспортов РФ.
Принимает изображение/файл → OCR → структурированный JSON + Excel.
"""
import asyncio
import logging
import os
import sys

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from bot.config import TELEGRAM_BOT_TOKEN, LOG_LEVEL
from bot.handlers import handle_document, handle_photo, cmd_ocr_raw, cmd_diagnose, process_ready


def setup_logging():
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def main():
    setup_logging()
    if not TELEGRAM_BOT_TOKEN:
        print("Установите TELEGRAM_BOT_TOKEN в .env")
        print("Получить токен: https://t.me/BotFather")
        sys.exit(1)

    from telegram import Update
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "👋 Бот для извлечения данных из паспортов РФ.\n\n"
            "📤 Отправьте фото/скан паспорта или ZIP с изображениями.\n"
            "📋 Получите JSON + Excel с полями: ФИО, даты, серия/номер, адрес и т.д.\n\n"
            "🔧 /diagnose — проверка OCR\n"
            "🔧 /ocr_raw — отладка (сырой OCR)\n"
            "📖 /start — это сообщение"
        )

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .drop_pending_updates(True)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("diagnose", cmd_diagnose))
    app.add_handler(CommandHandler("ocr_raw", cmd_ocr_raw))
    app.add_handler(CommandHandler("ready", process_ready))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    print("Бот запущен...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
