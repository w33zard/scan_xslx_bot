# -*- coding: utf-8 -*-
"""
Базовый интерфейс OCR-движка
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class OCRResult:
    """Результат OCR"""
    text: str
    confidence: float = 0.0
    engine: str = ""


class OCREngine(ABC):
    """Абстрактный OCR-движок"""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def recognize(self, image: np.ndarray, lang: str = "ru") -> OCRResult:
        """Распознать текст на изображении"""
        pass

    def recognize_file(self, path: str, lang: str = "ru") -> OCRResult:
        """Распознать текст по пути к файлу"""
        import cv2
        img = cv2.imread(path)
        if img is None:
            from PIL import Image
            pil = Image.open(path).convert("RGB")
            img = np.array(pil)[:, :, ::-1].copy()
        return self.recognize(img, lang=lang)
