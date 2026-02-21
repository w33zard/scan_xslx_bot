# -*- coding: utf-8 -*-
"""Тесты парсера полей"""
import pytest
from passport_ocr.parse import parse_ocr_to_fields


def test_series_number():
    text = "Фамилия ИВАНОВ Имя ПЕТР Отчество СИДОРОВИЧ 12 34 567890 03.04.1987"
    fields = parse_ocr_to_fields(text)
    assert fields["passport_series"].value == "1234"
    assert fields["passport_number"].value == "567890"


def test_series_number_with_spaces():
    text = "40 08 595794"
    fields = parse_ocr_to_fields(text)
    assert fields["passport_series"].value == "4008"
    assert fields["passport_number"].value == "595794"


def test_authority_code():
    text = "Код подразделения 292-000"
    fields = parse_ocr_to_fields(text)
    assert fields["authority_code"].value == "292-000"


def test_dates():
    text = "Дата рождения 03.04.1987 Дата выдачи 17.12.2004"
    fields = parse_ocr_to_fields(text)
    assert fields["birth_date"].value == "1987-04-03"
    assert fields["issue_date"].value == "2004-12-17"


def test_fio_by_labels():
    text = """Фамилия
ЦИЦАР
Имя
ФЕДОР
Отчество
МИХАЙЛОВИЧ"""
    fields = parse_ocr_to_fields(text)
    assert fields["surname"].value == "ЦИЦАР"
    assert fields["name"].value == "ФЕДОР"
    assert fields["patronymic"].value == "МИХАЙЛОВИЧ"


def test_ocr_error_avoidance():
    text = "Фамилия ФЕДОР Имя Выдан Отчество ТП"
    fields = parse_ocr_to_fields(text)
    assert fields["name"].value != "Выдан"
    assert fields["patronymic"].value != "ТП"


def test_empty():
    fields = parse_ocr_to_fields("")
    assert fields["surname"].value is None
    assert fields["passport_series"].value is None
