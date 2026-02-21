# -*- coding: utf-8 -*-
"""
E. Parsing — выделение полей из OCR-текста с устойчивостью к ошибкам (0/О, 1/I)
"""
import re
from typing import Optional

from passport_ocr.schemas import FieldValue

LABELS = {"фамилия", "имя", "отчество", "почество"}


def _fix_ocr_char(c: str) -> str:
    """Коррекция типичных OCR-ошибок: О→0 в цифрах, 1→I в буквах"""
    return c


def _value_near_label(lines: list, label: str, skip_values: set, min_conf: float = 0.7) -> tuple[str, float]:
    """Значение рядом с меткой. Возвращает (value, confidence)."""
    for i, ln in enumerate(lines):
        low = ln.lower()
        if label not in low:
            continue
        if label == "имя" and "отчество" in low:
            continue
        for idx in (i - 1, i + 1, i - 2, i + 2):
            if 0 <= idx < len(lines):
                words = re.findall(r"[А-ЯЁа-яё\-]+", lines[idx])
                for w in words:
                    w = w.strip()
                    if 2 <= len(w) <= 50 and w.isalpha() and w.lower() not in LABELS:
                        if w.upper() not in {s.upper() for s in skip_values}:
                            return w, min_conf
    return "", 0.0


def _extract_fio(lines: list, full: str, full_norm: str) -> tuple[FieldValue, FieldValue, FieldValue]:
    fam, cf = _value_near_label(lines, "фамилия", set())
    im, ci = _value_near_label(lines, "имя", {fam} if fam else set())
    otch, co = _value_near_label(lines, "отчество", {fam, im} if fam or im else set())

    if not fam or not im:
        w = r"[А-ЯЁа-яё][А-ЯЁа-яё\-]{1,}"
        for txt in (full_norm, full):
            for m in re.finditer(rf"({w})\s+({w})\s+({w})", txt):
                a, b, c = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
                if (c.lower().endswith(("вич", "вна", "ова", "ич"))
                    and a.lower() not in LABELS and b.lower() not in LABELS):
                    if not fam:
                        fam, cf = a, 0.75
                    if not im:
                        im, ci = b, 0.75
                    if not otch:
                        otch, co = c, 0.75
                    break

    return (
        FieldValue(value=fam or None, confidence=cf, source="ocr"),
        FieldValue(value=im or None, confidence=ci, source="ocr"),
        FieldValue(value=otch or None, confidence=co, source="ocr"),
    )


def _extract_gender(full: str) -> FieldValue:
    m = re.search(r"(?:пол|пол\s*)[:\s]*(муж|жен|м\.?|ж\.?|male|female)", full, re.I)
    if m:
        v = m.group(1).lower()
        if v.startswith("муж") or v.startswith("м") or v == "male":
            return FieldValue(value="M", confidence=0.9, source="ocr")
        if v.startswith("жен") or v.startswith("ж") or v == "female":
            return FieldValue(value="F", confidence=0.9, source="ocr")
    return FieldValue(value=None, confidence=0, source="ocr")


def _norm_date_to_iso(s: str) -> Optional[str]:
    """DD.MM.YYYY или DD-MM-YYYY -> YYYY-MM-DD"""
    if not s:
        return None
    s = s.strip()
    m = re.match(r"(\d{1,2})[.\-](\d{1,2})[.\-](\d{4})", s)
    if m:
        d, mo, y = m.group(1).zfill(2), m.group(2).zfill(2), m.group(3)
        return f"{y}-{mo}-{d}"
    return None


def _extract_dates(full: str) -> tuple[FieldValue, FieldValue]:
    birth_val, birth_conf = None, 0.0
    issue_val, issue_conf = None, 0.0

    for label, key in [("рождения", "birth"), ("выдачи", "issue")]:
        m = re.search(
            rf"(?:дата\s+{label}|{label})[:\s]*(\d{{1,2}}[.\-]\d{{1,2}}[.\-]\d{{4}})",
            full, re.I
        )
        if m:
            val = _norm_date_to_iso(m.group(1))
            if key == "birth":
                birth_val, birth_conf = val, 0.85
            else:
                issue_val, issue_conf = val, 0.85

    if not birth_val or not issue_val:
        dates = re.findall(r"\b(\d{1,2}[.\-]\d{1,2}[.\-]\d{4})\b", full)
        if dates:
            by_year = [
                (d, int(d.split(".")[-1] if "." in d else d.split("-")[-1]))
                for d in dates
            ]
            by_year.sort(key=lambda x: x[1])
            if not birth_val and by_year:
                birth_val = _norm_date_to_iso(by_year[0][0])
                birth_conf = 0.7
            if not issue_val and len(by_year) > 1:
                issue_val = _norm_date_to_iso(by_year[-1][0])
                issue_conf = 0.7

    return (
        FieldValue(value=birth_val, confidence=birth_conf, source="ocr"),
        FieldValue(value=issue_val, confidence=issue_conf, source="ocr"),
    )


def _extract_series_number(full: str, full_norm: str) -> tuple[FieldValue, FieldValue]:
    def ok(s1, s2, num):
        if not (s1 and s2 and num and len(num) == 6):
            return False
        if (s1 + s2).startswith(("19", "20")):
            return False
        return True

    candidates = []
    for txt in (full_norm, full):
        for m in re.finditer(r"\b(\d{2})[\s\-]?(\d{2})[\s\-]?(\d{6})\b", txt):
            if ok(m.group(1), m.group(2), m.group(3)):
                candidates.append((m.start(), m.group(1), m.group(2), m.group(3)))
        for m in re.finditer(r"\b(\d{4})[\s\-]?(\d{6})\b", txt):
            s, num = m.group(1), m.group(2)
            if s.startswith(("19", "20")):
                continue
            if ok(s[:2], s[2:], num):
                candidates.append((m.start(), s[:2], s[2:], num))

    if not candidates:
        digits = re.sub(r"\D", "", full)
        for i in range(len(digits) - 9):
            s1, s2, num = digits[i:i+2], digits[i+2:i+4], digits[i+4:i+10]
            if ok(s1, s2, num):
                candidates.append((i, s1, s2, num))
                break

    if not candidates:
        return FieldValue(value=None, confidence=0, source="ocr"), FieldValue(value=None, confidence=0, source="ocr")

    date_pat = re.compile(r"\d{1,2}[.\-]\d{1,2}[.\-]\d{4}")
    best = None
    best_dist = 999
    for pos, s1, s2, num in candidates:
        end = pos + 12
        m = date_pat.search(full, end)
        dist = m.start() - end if m else 999
        if dist < best_dist:
            best_dist = dist
            best = (s1 + s2, num)

    if best:
        return (
            FieldValue(value=best[0], confidence=0.85, source="ocr"),
            FieldValue(value=best[1], confidence=0.85, source="ocr"),
        )
    s1, s2, num = candidates[0][1], candidates[0][2], candidates[0][3]
    return (
        FieldValue(value=s1 + s2, confidence=0.8, source="ocr"),
        FieldValue(value=num, confidence=0.8, source="ocr"),
    )


def _extract_authority_code(full: str) -> FieldValue:
    m = re.search(r"\b(\d{3}-\d{3})\b", full)
    if m:
        return FieldValue(value=m.group(1), confidence=0.9, source="ocr")
    return FieldValue(value=None, confidence=0, source="ocr")


def _extract_issue_place(full: str) -> FieldValue:
    code = re.search(r"\b(\d{3}-\d{3})\b", full)
    subdiv = code.group(1) if code else ""
    issued = re.search(
        r"(?:паспорт\s+выдан|кем\s+выдан|выдан)\s*[:\s]*([А-Яа-яЁё0-9№\s,.\-/]+?)(?=дата\s+выдачи|код|$)",
        full, re.I | re.DOTALL
    )
    if issued:
        val = re.sub(r"\s+", " ", issued.group(1).strip())[:500]
        if subdiv and subdiv not in val:
            val = (val + " " + subdiv).strip()
        return FieldValue(value=val, confidence=0.8, source="ocr")
    if subdiv:
        return FieldValue(value=subdiv, confidence=0.6, source="ocr")
    return FieldValue(value=None, confidence=0, source="ocr")


def _extract_birth_place(full: str) -> FieldValue:
    m = re.search(
        r"(?:место\s+рождения|рождения)[:\s]*([А-Яа-яЁёA-Za-z\s,.\-]+?)(?=\d{1,2}[.\-]\d|$)",
        full, re.I | re.DOTALL
    )
    if m:
        val = re.sub(r"\s+", " ", m.group(1).strip())[:150]
        if val and not re.match(r"^\d", val):
            return FieldValue(value=val, confidence=0.85, source="ocr")
    m = re.search(r"ГОР\.\s*([А-Яа-яЁёA-Za-z\s\-]+?)(?=\d{1,2}\.\d|595|\n\n|$)", full)
    if m:
        return FieldValue(value=("гор. " + m.group(1).strip()).strip()[:150], confidence=0.7, source="ocr")
    return FieldValue(value=None, confidence=0, source="ocr")


def _extract_registration_address(full: str) -> FieldValue:
    m = re.search(
        r"(?:Зарегистрирован|зарегистрирован)\s*[:\s]*([А-Яа-яЁё0-9№\s,.\-/]+?)(?=Семейное|Дети|Кем выдан|Паспорт|\n\n|$)",
        full, re.I | re.DOTALL
    )
    if m:
        val = re.sub(r"\s+", " ", m.group(1).strip())
        if len(val) > 15:
            return FieldValue(value=val[:450], confidence=0.8, source="ocr")
    addr = []
    for label, pat in [
        ("г. ", r"(?:пункт|гор\.?|город)\s*[:\s]*([А-Яа-яЁё\-\s]+?)(?=\n|р-н|улица|дом|$)"),
        ("р-н ", r"р-н\s*[:\s]*([А-Яа-яЁё\-]+)"),
        ("", r"(?:улица|ул\.?)\s*[:\s]*([А-Яа-яЁё0-9\s\-]+?)(?=\n|дом|корп|кв|$)"),
        ("д. ", r"(?:дом|д\.)\s*[:\s]*(\d+[\s\-]*(?:корп\.?\s*[\-\d]*)?)"),
        ("кв. ", r"(?:кв\.?|квартира)\s*[:\s]*(\d+)"),
    ]:
        m = re.search(pat, full, re.I)
        if m:
            v = re.sub(r"\s+", " ", m.group(1).strip())
            if v:
                addr.append((label + v) if label else v)
    if addr:
        return FieldValue(value=", ".join(addr)[:450], confidence=0.7, source="ocr")
    return FieldValue(value=None, confidence=0, source="ocr")


def parse_ocr_to_fields(ocr_text: str) -> dict:
    """Извлечь все поля из OCR-текста в формате {field_name: FieldValue}"""
    from passport_ocr.schemas import empty_fields
    fields = empty_fields()

    if not ocr_text or not ocr_text.strip():
        return fields

    full = ocr_text.strip()
    full_norm = re.sub(r"\s+", " ", full)
    lines = [ln.strip() for ln in full.split("\n") if ln.strip()]

    fields["surname"], fields["name"], fields["patronymic"] = _extract_fio(lines, full, full_norm)
    fields["gender"] = _extract_gender(full)
    fields["birth_date"], fields["issue_date"] = _extract_dates(full)
    fields["birth_place"] = _extract_birth_place(full)
    fields["passport_series"], fields["passport_number"] = _extract_series_number(full, full_norm)
    fields["issue_place"] = _extract_issue_place(full)
    fields["authority_code"] = _extract_authority_code(full)
    fields["registration_address"] = _extract_registration_address(full)

    return fields
