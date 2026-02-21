# -*- coding: utf-8 -*-
"""
Passport OCR pipeline — модульное извлечение данных из паспортов РФ
"""
from passport_ocr.schemas import PassportResult, FieldValue
from passport_ocr.pipeline import process_passport

__all__ = ["PassportResult", "FieldValue", "process_passport"]
