# -*- coding: utf-8 -*-
"""Yandex Vision API OCR engine"""
import base64
import os
import re
from pathlib import Path

from passport_ocr.ocr_engines.base import OCREngine, OCRResult

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


def _yandex_recognize_file(path: str) -> str:
    api_key = os.environ.get("YANDEX_VISION_API_KEY")
    if not api_key:
        return ""
    try:
        import requests

        def _collect(obj, out: list):
            if isinstance(obj, str) and len(obj) > 2 and re.search(r"[А-Яа-яЁё0-9]", obj):
                out.append(obj.strip())
            elif isinstance(obj, dict):
                for v in obj.values():
                    _collect(v, out)
            elif isinstance(obj, list):
                for v in obj:
                    _collect(v, out)

        content = None
        if path.lower().endswith((".jpg", ".jpeg", ".png")):
            with open(path, "rb") as f:
                raw = f.read()
            if len(raw) < 900_000:
                content = base64.b64encode(raw).decode("utf-8")

        if not content and HAS_CV2:
            img = cv2.imread(path)
            if img is not None:
                _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if len(buf) < 900_000:
                    content = base64.b64encode(buf.tobytes()).decode("utf-8")

        if not content:
            return ""

        url = "https://vision.api.cloud.yandex.net/vision/v1/batchAnalyze"
        headers = {"Authorization": f"Api-Key {api_key}", "Content-Type": "application/json"}
        body = {
            "analyze_specs": [{
                "content": content,
                "features": [{"type": "TEXT_DETECTION", "text_detection_config": {"language_codes": ["ru", "en"]}}]
            }]
        }
        r = requests.post(url, json=body, headers=headers, timeout=60)
        r.raise_for_status()
        data = r.json()

        for res in (data.get("results") or []):
            for item in (res.get("results") or res.get("result") or []):
                td = item.get("textDetection") or item.get("textAnnotation") or {}
                ft = (td.get("fullText") or "").strip()
                if ft:
                    return ft
                for page in td.get("pages", []):
                    for block in page.get("blocks", []):
                        for line in block.get("lines", []):
                            lt = line.get("text") or " ".join(str(w.get("text", "")) for w in line.get("words", []))
                            if lt:
                                return lt
        fallback = []
        _collect(data, fallback)
        return "\n".join(fallback[:200]) if fallback else ""
    except Exception:
        return ""


class YandexEngine(OCREngine):
    """Yandex Vision API — лучше для паспортов РФ (требует API key)"""

    @property
    def name(self) -> str:
        return "yandex"

    def recognize(self, image, lang: str = "ru") -> OCRResult:
        if not os.environ.get("YANDEX_VISION_API_KEY"):
            return OCRResult(text="", confidence=0, engine=self.name)
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            try:
                if HAS_CV2:
                    cv2.imwrite(f.name, image)
                else:
                    from PIL import Image
                    Image.fromarray(image[:, :, ::-1]).save(f.name, "JPEG")
                text = _yandex_recognize_file(f.name)
                return OCRResult(text=text or "", confidence=0.85 if text else 0, engine=self.name)
            finally:
                try:
                    os.unlink(f.name)
                except Exception:
                    pass

    def recognize_file(self, path: str, lang: str = "ru") -> OCRResult:
        text = _yandex_recognize_file(path)
        return OCRResult(text=text or "", confidence=0.85 if text else 0, engine=self.name)
