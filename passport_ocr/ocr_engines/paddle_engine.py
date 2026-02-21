# -*- coding: utf-8 -*-
"""PaddleOCR engine (опционально, требуется paddlepaddle)"""
from passport_ocr.ocr_engines.base import OCREngine, OCRResult

try:
    from paddleocr import PaddleOCR
    import numpy as np
    HAS_PADDLE = True
except ImportError:
    HAS_PADDLE = False

_paddle = None


def _get_paddle():
    global _paddle
    if _paddle is None and HAS_PADDLE:
        _paddle = PaddleOCR(use_angle_cls=True, lang="ru", show_log=False)
    return _paddle


class PaddleEngine(OCREngine):
    """PaddleOCR — хорошее качество для русского"""

    @property
    def name(self) -> str:
        return "paddle"

    def recognize(self, image, lang: str = "ru") -> OCRResult:
        if not HAS_PADDLE:
            return OCRResult(text="", confidence=0, engine=self.name)
        try:
            ocr = _get_paddle()
            if ocr is None:
                return OCRResult(text="", confidence=0, engine=self.name)
            result = ocr.ocr(image, cls=True)
            if not result or not result[0]:
                return OCRResult(text="", confidence=0, engine=self.name)
            lines = []
            total_conf = 0
            n = 0
            for line in result[0]:
                if line and len(line) >= 2:
                    text = line[1][0] if isinstance(line[1], (list, tuple)) else str(line[1])
                    conf = line[1][1] if isinstance(line[1], (list, tuple)) and len(line[1]) > 1 else 0.8
                    if text:
                        lines.append(text)
                        total_conf += conf
                        n += 1
            text = "\n".join(lines) if lines else ""
            avg = total_conf / n if n else 0.5
            return OCRResult(text=text, confidence=min(1.0, avg), engine=self.name)
        except Exception:
            return OCRResult(text="", confidence=0, engine=self.name)
