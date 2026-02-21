# -*- coding: utf-8 -*-
"""Тесты валидации"""
import pytest
from passport_ocr.schemas import PassportResult, FieldValue, empty_fields
from passport_ocr.validate import validate_result


def test_valid_series_number():
    fields = empty_fields()
    fields["passport_series"] = FieldValue(value="1234", confidence=0.9)
    fields["passport_number"] = FieldValue(value="567890", confidence=0.9)
    r = PassportResult(fields=fields)
    r = validate_result(r)
    assert r.checks.series_number_valid is True
    assert len(r.errors) == 0


def test_invalid_series():
    fields = empty_fields()
    fields["passport_series"] = FieldValue(value="12", confidence=0.9)
    r = PassportResult(fields=fields)
    r = validate_result(r)
    assert r.checks.series_number_valid is False


def test_authority_code_format():
    fields = empty_fields()
    fields["authority_code"] = FieldValue(value="292-000", confidence=0.9)
    r = PassportResult(fields=fields)
    r = validate_result(r)
    assert r.checks.authority_code_valid is True


def test_authority_code_invalid():
    fields = empty_fields()
    fields["authority_code"] = FieldValue(value="292000", confidence=0.9)
    r = PassportResult(fields=fields)
    r = validate_result(r)
    assert r.checks.authority_code_valid is False
