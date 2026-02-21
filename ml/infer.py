#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Инференс обученных моделей (заглушка).
После обучения OCR/NER — загрузить модели и использовать в pipeline.
"""
import sys
from pathlib import Path

# Добавить корень проекта в path
sys.path.insert(0, str(Path(__file__).parent.parent))


def load_ocr_model(model_path: str):
    """Загрузить обученную OCR-модель"""
    # TODO: после train_ocr.py — реализовать загрузку
    raise NotImplementedError("Обученная модель пока не подключена")


def load_ner_model(model_path: str):
    """Загрузить обученную NER-модель"""
    # TODO: после train_ner.py — реализовать загрузку
    raise NotImplementedError("Обученная модель пока не подключена")


if __name__ == "__main__":
    print("ml/infer.py — заглушка. После обучения подключите модели.")
