# -*- coding: utf-8 -*-
"""Плагинные OCR-движки"""
import os

from passport_ocr.ocr_engines.base import OCREngine, OCRResult
from passport_ocr.ocr_engines.tesseract_engine import TesseractEngine
from passport_ocr.ocr_engines.yandex_engine import YandexEngine

try:
    from passport_ocr.ocr_engines.easyocr_engine import EasyOCREngine
    HAS_EASYOCR = True
except ImportError:
    HAS_EASYOCR = False


def get_engine(name: str | None = None) -> OCREngine:
    """Получить OCR-движок по имени. name: paddle|tesseract|easyocr|yandex"""
    engine = (name or os.environ.get("OCR_ENGINE", "tesseract")).lower()
    if engine == "yandex" and os.environ.get("YANDEX_VISION_API_KEY"):
        return YandexEngine()
    if engine == "easyocr" and HAS_EASYOCR:
        return EasyOCREngine()
    if engine == "paddle":
        try:
            from passport_ocr.ocr_engines.paddle_engine import PaddleEngine
            return PaddleEngine()
        except ImportError:
            pass
    return TesseractEngine()
