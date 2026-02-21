# -*- coding: utf-8 -*-
"""EasyOCR engine (fallback)"""
from passport_ocr.ocr_engines.base import OCREngine, OCRResult

try:
    import easyocr
    import numpy as np
    HAS_EASYOCR = True
except ImportError:
    HAS_EASYOCR = False

_reader = None


def _get_reader():
    global _reader
    if _reader is None and HAS_EASYOCR:
        _reader = easyocr.Reader(["ru", "en"], gpu=False, verbose=False)
    return _reader


class EasyOCREngine(OCREngine):
    """EasyOCR (fallback)"""

    @property
    def name(self) -> str:
        return "easyocr"

    def recognize(self, image, lang: str = "ru") -> OCRResult:
        if not HAS_EASYOCR:
            return OCRResult(text="", confidence=0, engine=self.name)
        try:
            reader = _get_reader()
            if reader is None:
                return OCRResult(text="", confidence=0, engine=self.name)
            results = reader.readtext(image)
            lines = []
            total_conf = 0
            n = 0
            for (_, text, conf) in results:
                if text and conf > 0.1:
                    lines.append(text)
                    total_conf += conf
                    n += 1
            text = "\n".join(lines) if lines else ""
            avg_conf = total_conf / n if n else 0.5
            return OCRResult(text=text, confidence=min(1.0, avg_conf), engine=self.name)
        except Exception:
            return OCRResult(text="", confidence=0, engine=self.name)
