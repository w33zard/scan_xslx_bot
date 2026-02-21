# -*- coding: utf-8 -*-
"""
A. Ingest — приём и нормализация входных данных
"""
import os
import tempfile
from pathlib import Path
from typing import Iterator

import numpy as np
from PIL import Image

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


MAX_FILE_MB = int(os.environ.get("MAX_FILE_MB", "20"))
MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024


class IngestError(Exception):
    """Ошибка при приёме файла"""
    pass


def _is_image(path: str) -> bool:
    ext = Path(path).suffix.lower()
    return ext in (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp")


def _load_image(path: str) -> np.ndarray:
    """Загрузить изображение в numpy array (BGR для OpenCV)"""
    if not HAS_CV2:
        pil = Image.open(path).convert("RGB")
        arr = np.array(pil)
        return arr[:, :, ::-1].copy()
    img = cv2.imread(path)
    if img is None:
        pil = Image.open(path).convert("RGB")
        arr = np.array(pil)
        return arr[:, :, ::-1].copy()
    return img


def normalize_to_images(input_path: str, temp_dir: str | None = None) -> list[tuple[str, str]]:
    """
    Нормализовать вход в список изображений.
    Возвращает список (path, mime_type).
    Поддержка: JPG, PNG, BMP, TIFF, PDF (страницы как изображения).
    """
    path = Path(input_path)
    if not path.exists():
        raise IngestError(f"Файл не найден: {input_path}")

    stat = path.stat()
    if stat.st_size > MAX_FILE_BYTES:
        raise IngestError(f"Файл слишком большой ({stat.st_size / 1024 / 1024:.1f} MB, макс {MAX_FILE_MB} MB)")

    temp = temp_dir or tempfile.mkdtemp()
    result: list[tuple[str, str]] = []

    if _is_image(str(path)):
        result.append((str(path), "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"))
        return result

    if path.suffix.lower() == ".pdf":
        try:
            import pdf2image
            pages = pdf2image.convert_from_path(str(path), dpi=150)
            for i, page in enumerate(pages):
                out = Path(temp) / f"page_{i}.png"
                page.save(str(out), "PNG")
                result.append((str(out), "image/png"))
        except ImportError:
            raise IngestError("PDF не поддерживается: установите pdf2image и poppler")
        if not result:
            raise IngestError("Не удалось извлечь страницы из PDF")
        return result

    raise IngestError(f"Неподдерживаемый формат: {path.suffix}")


def get_image_array(path: str) -> np.ndarray:
    """Получить numpy array изображения для обработки"""
    return _load_image(path)
