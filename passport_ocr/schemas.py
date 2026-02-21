# -*- coding: utf-8 -*-
"""
Схемы результата извлечения данных паспорта РФ
"""
from typing import Optional
from pydantic import BaseModel, Field


class FieldValue(BaseModel):
    """Поле с confidence и source"""
    value: Optional[str] = None
    confidence: float = Field(ge=0, le=1, default=0.0)
    source: str = "ocr"


class Checks(BaseModel):
    """Проверки валидности"""
    date_formats_ok: bool = True
    series_number_valid: bool = True
    authority_code_valid: bool = True
    mrz_checksum_ok: Optional[bool] = None


class DebugInfo(BaseModel):
    """Отладочная информация (без PII)"""
    pipeline_version: str = "v1"
    timings_ms: dict = Field(default_factory=dict)
    ocr_engine: str = ""
    preprocess: dict = Field(default_factory=dict)


def empty_fields() -> dict:
    """Пустые поля результата"""
    return {
        "surname": FieldValue(),
        "name": FieldValue(),
        "patronymic": FieldValue(),
        "gender": FieldValue(value=None),
        "birth_date": FieldValue(value=None),
        "birth_place": FieldValue(value=None),
        "passport_series": FieldValue(value=None),
        "passport_number": FieldValue(value=None),
        "issue_date": FieldValue(value=None),
        "issue_place": FieldValue(value=None),
        "authority_code": FieldValue(value=None),
        "registration_address": FieldValue(value=None),
        "mrz": FieldValue(value=None, source="mrz"),
    }


class PassportResult(BaseModel):
    """Единый результат извлечения паспорта"""
    doc_type: str = "passport_rf_internal"
    page_type: str = "unknown"
    fields: dict = Field(default_factory=empty_fields)
    checks: Checks = Field(default_factory=Checks)
    errors: list[str] = Field(default_factory=list)
    debug: DebugInfo = Field(default_factory=DebugInfo)

    def to_dict(self) -> dict:
        d = self.model_dump()
        # Преобразуем FieldValue в dict для JSON
        for k, v in d.get("fields", {}).items():
            if isinstance(v, dict) and "value" in v:
                continue
        return d
