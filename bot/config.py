# -*- coding: utf-8 -*-
"""Конфигурация бота из .env"""
import os
from pathlib import Path


def load_dotenv():
    try:
        from dotenv import load_dotenv as _load
        _load()
    except ImportError:
        pass


load_dotenv()

# Bot
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]

# OCR
OCR_ENGINE = os.environ.get("OCR_ENGINE", "tesseract")
STORE_INPUT_IMAGES = os.environ.get("STORE_INPUT_IMAGES", "0") == "1"
TEMP_DIR = os.environ.get("TEMP_DIR") or None
MAX_FILE_MB = int(os.environ.get("MAX_FILE_MB", "20"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# Processing
PROCESS_TIMEOUT_SEC = int(os.environ.get("PROCESS_TIMEOUT_SEC", "90"))
