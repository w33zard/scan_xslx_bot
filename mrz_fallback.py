# -*- coding: utf-8 -*-
"""
MRZ fallback — когда основной OCR не извлёк данные, пробуем MRZ (Machine Readable Zone).
MRZ в паспорте РФ — 2 строки по 44 символа внизу страницы, формат TD3.
"""
import re
from typing import Optional


def _normalize_mrz_line(s: str) -> str:
    """Очистка для MRZ: только A-Z, 0-9, <"""
    s = re.sub(r"[^A-Za-z0-9<]", "", s.upper())
    s = s.replace(" ", "<")
    return s


def _parse_td3_mrz(line1: str, line2: str) -> Optional[dict]:
    """
    Парсинг TD3 (паспорт). Возвращает dict для merge с parse_passport_data или None.
    line1: P<XXXsurname<<name<patronymic...
    line2: doc_number country birth sex expiry ...
    """
    if len(line1) < 30 or len(line2) < 30:
        return None
    if not line1.startswith("P<") and not line1.startswith("P "):
        return None

    out = {}
    try:
        country = line1[2:5]
        if country != "RUS" and country != "Rus":
            return None

        name_part = line1[5:].split("<<")
        if len(name_part) >= 1 and name_part[0]:
            surname = name_part[0].replace("<", " ").strip().title()
            out["Фамилия"] = surname
        if len(name_part) >= 2 and name_part[1]:
            names = name_part[1].replace("<", " ").strip().split()
            if len(names) >= 1:
                out["Имя"] = names[0].title()
            if len(names) >= 2:
                out["Отчество"] = " ".join(names[1:]).title()
            elif len(names) == 1 and "<" in name_part[1]:
                parts = name_part[1].split("<")
                out["Имя"] = (parts[0] or "").title()
                out["Отчество"] = (parts[1] or "").title() if len(parts) > 1 else ""

        doc_num = line2[:9].replace("<", "")
        num_clean = re.sub(r"\D", "", doc_num)
        if len(num_clean) >= 10:
            out["Серия и номер паспорта"] = f"{num_clean[:2]} {num_clean[2:4]} {num_clean[4:10]}"
        elif len(num_clean) >= 6 and not num_clean.startswith(("19", "20")):
            s1 = num_clean[:2] if len(num_clean) >= 2 else ""
            s2 = num_clean[2:4] if len(num_clean) >= 4 else ""
            out["Серия и номер паспорта"] = f"{s1} {s2} {num_clean[4:10]}".strip()

        birth = line2[13:19]
        if len(birth) == 6 and birth.isdigit():
            y, m, d = birth[0:2], birth[2:4], birth[4:6]
            yy = "19" + y if int(y) > 30 else "20" + y
            out["Дата рождения"] = f"{d}.{m}.{yy}"

        sex = line2[20:21] if len(line2) > 20 else ""
        if sex == "M":
            out["Пол"] = "M"
        elif sex == "F":
            out["Пол"] = "F"

    except Exception:
        return None
    return out if out else None


def extract_mrz_from_text(ocr_text: str) -> Optional[dict]:
    """
    Ищем в OCR-тексте 2 строки MRZ (TD3) и парсим.
    MRZ: строки длиной ~44 символа, символы A-Z, 0-9, <
    """
    if not ocr_text or len(ocr_text) < 50:
        return None
    candidates = []
    for ln in ocr_text.replace("\r", "\n").split("\n"):
        normalized = _normalize_mrz_line(ln)
        if 38 <= len(normalized) <= 55:
            candidates.append(normalized[:44] if len(normalized) > 44 else normalized.ljust(44, "<"))
    for i in range(len(candidates) - 1):
        ln1, ln2 = candidates[i], candidates[i + 1]
        if ln1.startswith("P<") and (ln2[0].isdigit() or ln2[0] in "<"):
            res = _parse_td3_mrz(ln1, ln2)
            if res:
                return res
    return None


def extract_mrz_from_image(image_path: str) -> Optional[dict]:
    """
    Вырезаем нижнюю часть изображения (там MRZ), OCR, парсим.
    """
    try:
        import cv2
        import pytesseract
    except ImportError:
        return None

    img = cv2.imread(image_path)
    if img is None:
        return None
    h, w = img.shape[:2]
    bottom = int(h * 0.2)
    roi = img[h - bottom :, :]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    binary = cv2.resize(binary, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    try:
        text = pytesseract.image_to_string(
            binary,
            config="--psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789< ",
        )
    except Exception:
        return None
    return extract_mrz_from_text(text)
