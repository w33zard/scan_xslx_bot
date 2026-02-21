# -*- coding: utf-8 -*-
"""Smoke-тест пайплайна"""
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image


def test_pipeline_empty_image():
    """Пайплайн на пустом/минимальном изображении не падает"""
    from passport_ocr.pipeline import process_passport

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        img = Image.new("RGB", (100, 100), color="white")
        img.save(f.name)
        path = f.name

    try:
        result = process_passport(path, do_preprocess=False)
        assert result is not None
        assert "doc_type" in result.model_dump()
        assert "fields" in result.model_dump()
        assert "errors" in result.model_dump()
    finally:
        Path(path).unlink(missing_ok=True)


def test_pipeline_with_text_image():
    """Пайплайн на изображении с текстом"""
    from passport_ocr.pipeline import process_passport

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        img = Image.new("RGB", (400, 200), color="white")
        from PIL import ImageDraw, ImageFont
        draw = ImageDraw.Draw(img)
        draw.text((20, 20), "Фамилия ИВАНОВ", fill="black")
        draw.text((20, 50), "Имя ПЕТР", fill="black")
        draw.text((20, 80), "40 08 595794", fill="black")
        img.save(f.name)
        path = f.name

    try:
        result = process_passport(path, do_preprocess=False)
        assert result is not None
        assert "doc_type" in result.model_dump()
        assert "fields" in result.model_dump()
    finally:
        Path(path).unlink(missing_ok=True)
