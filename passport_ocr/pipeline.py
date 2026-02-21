# -*- coding: utf-8 -*-
"""
Главный пайплайн: Ingest → Preprocess → Classify → OCR → Parse → Validate → Output
"""
import logging
import time
from pathlib import Path
from typing import Optional

from passport_ocr.schemas import PassportResult, FieldValue, DebugInfo, empty_fields
from passport_ocr.ingest import get_image_array, IngestError
from passport_ocr.preprocess import preprocess_pipeline
from passport_ocr.classify import classify_page
from passport_ocr.ocr_engines import get_engine
from passport_ocr.parse import parse_ocr_to_fields
from passport_ocr.validate import validate_result
from passport_ocr.detect import extract_series_from_vertical

logger = logging.getLogger(__name__)


def _merge_field(best: FieldValue, candidate: FieldValue) -> FieldValue:
    """Выбрать поле с max confidence"""
    if not candidate or not getattr(candidate, "value", None):
        return best
    c_conf = getattr(candidate, "confidence", 0) or 0
    b_conf = getattr(best, "confidence", 0) or 0
    return candidate if c_conf > b_conf else best


def process_passport(
    image_path: str,
    ocr_engine_name: Optional[str] = None,
    do_preprocess: bool = True,
) -> PassportResult:
    """
    Обработать изображение паспорта и вернуть структурированный результат.
    Не логирует полный текст паспорта.
    """
    timings = {}
    t0 = time.perf_counter()
    result = PassportResult(page_type="unknown", fields=empty_fields())

    try:
        # Ingest
        img = get_image_array(image_path)
        if img is None or img.size == 0:
            result.errors.append("Не удалось загрузить изображение")
            result.debug = DebugInfo(timings_ms=timings, ocr_engine="")
            return result

        # Preprocess
        if do_preprocess:
            t1 = time.perf_counter()
            img, preprocess_info = preprocess_pipeline(img)
            timings["preprocess"] = round((time.perf_counter() - t1) * 1000, 1)
            result.debug.preprocess = preprocess_info
        else:
            preprocess_info = {}

        # OCR
        engine = get_engine(ocr_engine_name)
        t2 = time.perf_counter()
        ocr_result = engine.recognize(img)
        timings["ocr"] = round((time.perf_counter() - t2) * 1000, 1)
        result.debug.ocr_engine = engine.name

        ocr_text = ocr_result.text if ocr_result else ""
        if not ocr_text or len(ocr_text.strip()) < 5:
            # Fallback: ocr_extractor (Yandex Vision + Tesseract с разными ориентациями)
            try:
                from ocr_extractor import extract_text_from_image
                fallback_text = extract_text_from_image(image_path)
                if fallback_text and len(fallback_text.strip()) >= 5:
                    ocr_text = fallback_text
                    result.debug.ocr_engine = f"{result.debug.ocr_engine}+fallback"
                    result.errors.clear()
            except Exception:
                pass
        if not ocr_text or len(ocr_text.strip()) < 5:
            result.errors.append("Не удалось распознать текст (OCR пустой)")
            result.debug.timings_ms = timings
            return validate_result(result)

        # Classify
        result.page_type = classify_page(ocr_text)

        # Parse
        t3 = time.perf_counter()
        fields = parse_ocr_to_fields(ocr_text)
        timings["parse"] = round((time.perf_counter() - t3) * 1000, 1)

        # Vertical series (приоритет)
        vert = extract_series_from_vertical(image_path, img)
        if vert:
            s4, n6, conf = vert
            if s4 and n6:
                fields["passport_series"] = _merge_field(
                    fields["passport_series"],
                    FieldValue(value=s4, confidence=conf, source="ocr")
                )
                fields["passport_number"] = _merge_field(
                    fields["passport_number"],
                    FieldValue(value=n6, confidence=conf, source="ocr")
                )

        result.fields = fields

        # Validate
        result = validate_result(result)
        timings["total"] = round((time.perf_counter() - t0) * 1000, 1)
        result.debug.timings_ms = timings

        return result

    except IngestError as e:
        result.errors.append(str(e))
        result.debug.timings_ms = timings
        return result
    except Exception as e:
        logger.exception("Pipeline error (no PII in log)")
        result.errors.append(f"Ошибка обработки: {type(e).__name__}")
        result.debug.timings_ms = timings
        return result


def process_passport_from_bytes(
    image_bytes: bytes,
    temp_dir: Optional[str] = None,
    **kwargs
) -> PassportResult:
    """Обработать из bytes (например, из Telegram)"""
    import tempfile
    import os
    tmp = temp_dir or tempfile.gettempdir()
    path = Path(tmp) / f"passport_{id(image_bytes)}.jpg"
    try:
        path.write_bytes(image_bytes)
        return process_passport(str(path), **kwargs)
    finally:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
