# -*- coding: utf-8 -*-
"""
C. Page classification — определение типа страницы (main_spread / registration)
"""
import re


MAIN_KEYWORDS = [
    "фамилия", "имя", "отчество", "пол", "дата рождения", "место рождения",
    "паспорт выдан", "дата выдачи", "код подразделения", "личная подпись",
]
REGISTRATION_KEYWORDS = [
    "место жительства", "зарегистрирован", "адрес", "улица", "дом", "квартира",
    "семейное положение", "дети", "сведения о ранее выданном",
]


def classify_page(ocr_text: str) -> str:
    """
    Определить тип страницы по ключевым словам в OCR-тексте.
    Возвращает: "main_spread" | "registration" | "unknown"
    """
    if not ocr_text or not ocr_text.strip():
        return "unknown"

    text_lower = ocr_text.lower().replace("\n", " ")
    main_score = sum(1 for kw in MAIN_KEYWORDS if kw in text_lower)
    reg_score = sum(1 for kw in REGISTRATION_KEYWORDS if kw in text_lower)

    if main_score >= 3 or (main_score >= 2 and reg_score < 2):
        return "main_spread"
    if reg_score >= 2 or "зарегистрирован" in text_lower:
        return "registration"
    if main_score >= 1:
        return "main_spread"
    return "unknown"
