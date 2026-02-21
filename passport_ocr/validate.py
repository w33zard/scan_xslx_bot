# -*- coding: utf-8 -*-
"""
F. Validation — проверки форматов, разумности, checksums
"""
from datetime import datetime
import re
from typing import Optional

from passport_ocr.schemas import PassportResult, Checks


def _parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s.strip()[:10], fmt)
        except ValueError:
            continue
    return None


def _validate_dates(result: PassportResult) -> tuple[bool, list[str]]:
    errors = []
    today = datetime.now().date()
    ok = True

    for key, label in [("birth_date", "Дата рождения"), ("issue_date", "Дата выдачи")]:
        val = result.fields.get(key)
        if not val or not getattr(val, "value", None):
            continue
        v = val.value
        dt = _parse_date(v)
        if not dt:
            errors.append(f"{label}: неверный формат '{v}'")
            ok = False
            continue
        d = dt.date()
        if d > today:
            errors.append(f"{label}: дата в будущем ({v})")
            ok = False
        if key == "birth_date":
            age = (today - d).days / 365.25
            if age < 0 or age > 120:
                errors.append(f"{label}: неверный возраст ({age:.0f} лет)")
                ok = False

    return ok, errors


def _validate_series_number(result: PassportResult) -> tuple[bool, list[str]]:
    errors = []
    ser = result.fields.get("passport_series")
    num = result.fields.get("passport_number")
    s_val = getattr(ser, "value", None) if ser else None
    n_val = getattr(num, "value", None) if num else None

    if not s_val and not n_val:
        return True, []

    if s_val and not re.match(r"^\d{4}$", re.sub(r"\D", "", s_val)):
        errors.append("Серия паспорта: должна быть 4 цифры")
        return False, errors
    if n_val and not re.match(r"^\d{6}$", re.sub(r"\D", "", n_val)):
        errors.append("Номер паспорта: должен быть 6 цифр")
        return False, errors

    return True, errors


def _validate_authority_code(result: PassportResult) -> tuple[bool, list[str]]:
    val = result.fields.get("authority_code")
    v = getattr(val, "value", None) if val else None
    if not v:
        return True, []
    if not re.match(r"^\d{3}-\d{3}$", v.strip()):
        return False, ["Код подразделения: формат NNN-NNN"]
    return True, []


def validate_result(result: PassportResult) -> PassportResult:
    """Применить все проверки, обновить checks и errors"""
    all_errors = []
    checks = Checks()

    dates_ok, err1 = _validate_dates(result)
    checks.date_formats_ok = dates_ok
    all_errors.extend(err1)

    series_ok, err2 = _validate_series_number(result)
    checks.series_number_valid = series_ok
    all_errors.extend(err2)

    auth_ok, err3 = _validate_authority_code(result)
    checks.authority_code_valid = auth_ok
    all_errors.extend(err3)

    result.checks = checks
    result.errors = all_errors
    return result
