# -*- coding: utf-8 -*-
"""Tesseract OCR engine"""
from passport_ocr.ocr_engines.base import OCREngine, OCRResult

try:
    import pytesseract
    import cv2
    import numpy as np
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False


class TesseractEngine(OCREngine):
    """Tesseract OCR (tesseract + rus)"""

    @property
    def name(self) -> str:
        return "tesseract"

    def recognize(self, image, lang: str = "ru") -> OCRResult:
        if not HAS_TESSERACT:
            return OCRResult(text="", confidence=0, engine=self.name)
        try:
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray = image
            gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            lang = "rus+eng" if lang == "ru" else "eng"
            text = pytesseract.image_to_string(gray, lang=lang, config="--psm 6")
            data = pytesseract.image_to_data(gray, lang=lang, output_type=pytesseract.Output.DICT)
            confs = [int(c) for c in data.get("conf", []) if c != "-1"]
            conf = sum(confs) / len(confs) / 100.0 if confs else 0.5
            return OCRResult(text=text or "", confidence=min(1.0, max(0, conf)), engine=self.name)
        except Exception:
            return OCRResult(text="", confidence=0, engine=self.name)
