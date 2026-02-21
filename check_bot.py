#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quick check: imports and pipeline"""
import sys
import tempfile
from pathlib import Path

def main():
    print("1. Imports...")
    try:
        from passport_ocr.pipeline import process_passport
        from passport_ocr.schemas import PassportResult
        from bot.config import TELEGRAM_BOT_TOKEN, ADMIN_IDS
        from bot.handlers import handle_document, handle_photo, cmd_ocr_raw, process_ready
        print("   OK")
    except Exception as e:
        print(f"   FAIL: {e}")
        return 1

    print("2. Pipeline on empty image...")
    try:
        from PIL import Image
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            Image.new("RGB", (50, 50), "white").save(f.name)
            r = process_passport(f.name, do_preprocess=False)
        Path(f.name).unlink(missing_ok=True)
        assert r.doc_type == "passport_rf_internal"
        print("   OK")
    except Exception as e:
        print(f"   FAIL: {e}")
        return 1

    print("3. Config...")
    print(f"   TOKEN: {'set' if TELEGRAM_BOT_TOKEN else 'NOT SET'}")
    print(f"   ADMIN_IDS: {ADMIN_IDS}")

    print("\nAll checks OK.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
