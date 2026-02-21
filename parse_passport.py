# -*- coding: utf-8 -*-
"""
Парсер паспорта РФ — по структуре документа.
Ищем значения ПО МЕТКАМ (Фамилия, Имя, Отчество), а не по паттернам в тексте.
"""
import re

EXCEL_COLUMNS = [
    "№ п/п", "Фамилия", "Имя", "Отчество", "Дата рождения", "Место рождения",
    "Серия и номер паспорта", "Дата выдачи", "Кем выдан", "ИНН",
    "Адрес регистрации", "Примечания",
]

# Только метки — не принимаем как значения
LABELS = {"фамилия", "имя", "отчество", "почество"}  # почество — OCR-ошибка "отчество"


def _value_near_label(lines: list, label: str, skip_values: set) -> str:
    """
    Значение рядом с меткой. В паспорте: на той же строке, ВЫШЕ или НИЖЕ.
    skip_values — уже найденные (Фамилия, Имя), чтобы не дублировать.
    """
    for i, ln in enumerate(lines):
        low = ln.lower()
        if label not in low:
            continue
        if label == "имя" and "отчество" in low:
            continue
        words = re.findall(r"[А-ЯЁа-яё\-]+", ln)
        for w in words:
            w = w.strip()
            if 2 <= len(w) <= 50 and w.isalpha() and w.lower() != label and w.lower() not in LABELS:
                if w.upper() not in {s.upper() for s in skip_values}:
                    return w
        for idx in (i - 1, i + 1, i - 2, i + 2):
            if 0 <= idx < len(lines):
                words = re.findall(r"[А-ЯЁа-яё\-]+", lines[idx])
                for w in words:
                    w = w.strip()
                    if 2 <= len(w) <= 50 and w.isalpha() and w.lower() not in LABELS:
                        if w.upper() not in {s.upper() for s in skip_values}:
                            return w
    return ""


def _extract_fio_by_structure(lines: list) -> tuple:
    """ФИО — по меткам. Каждое следующее не дублирует предыдущее."""
    fam = _value_near_label(lines, "фамилия", set())
    im = _value_near_label(lines, "имя", {fam} if fam else set())
    otch = _value_near_label(lines, "отчество", {fam, im} if fam or im else set())
    return fam, im, otch


def _extract_fio_triple(full: str, full_norm: str) -> tuple:
    """Fallback: тройка Фамилия Имя Отчество (3-е слово на -вич/-вна/-ова/-ич)."""
    w = r"[А-ЯЁа-яё][А-ЯЁа-яё\-]{1,}"
    for txt in (full_norm, full):
        for m in re.finditer(rf"({w})\s+({w})\s+({w})", txt):
            a, b, c = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
            if c.lower().endswith(("вич", "вна", "ова", "ич")) and a.lower() not in LABELS and b.lower() not in LABELS:
                return a, b, c
    return "", "", ""


def _extract_series(full: str, full_norm: str) -> str:
    """
    Серия — формат XX XX XXXXXX. Исключаем только явные даты (19xx, 20xx в серии).
    Предпочитаем серию рядом с датой (типичное место в паспорте).
    """
    def ok(s1, s2, num):
        if not (s1 and s2 and num and len(num) == 6):
            return False
        if (s1 + s2).startswith(("19", "20")):
            return False
        return True

    def fmt(s1, s2, num):
        return f"{s1} {s2} {num}"

    candidates = []
    for txt in (full_norm, full):
        for m in re.finditer(r"\b(\d{4})[\s\-]?(\d{6})\b", txt):
            s, num = m.group(1), m.group(2)
            if s.startswith(("19", "20")):
                continue
            if ok(s[:2], s[2:], num):
                candidates.append((m.start(), fmt(s[:2], s[2:], num)))
        for m in re.finditer(r"\b(\d{2})[\s\-]?(\d{2})[\s\-]?(\d{6})\b", txt):
            if ok(m.group(1), m.group(2), m.group(3)):
                candidates.append((m.start(), fmt(m.group(1), m.group(2), m.group(3))))
    if not candidates:
        digits = re.sub(r"\D", "", full)
        for i in range(len(digits) - 9):
            s1, s2, num = digits[i:i+2], digits[i+2:i+4], digits[i+4:i+10]
            if ok(s1, s2, num):
                return fmt(s1, s2, num)
        return ""
    # Предпочитаем серию, за которой сразу идёт дата (типичный блок в паспорте)
    date_pat = re.compile(r"\d{1,2}[.\-]\d{1,2}[.\-]\d{4}")
    best = None
    best_dist = 999
    for pos, val in candidates:
        end = pos + len(val)
        m = date_pat.search(full, end)
        if m and m.start() - end < best_dist:
            best_dist = m.start() - end
            best = val
    return best if best else candidates[0][1]


def _norm_date(s: str) -> str:
    parts = s.replace("-", ".").split(".")
    if len(parts) == 3:
        return f"{parts[0].zfill(2)}.{parts[1].zfill(2)}.{parts[2]}"
    return s


def parse_passport_data(ocr_text: str) -> dict:
    """Парсинг по структуре: метки → соседние значения."""
    data = {col: "" for col in EXCEL_COLUMNS[1:]}
    if not ocr_text or not ocr_text.strip():
        return data

    full = ocr_text.strip()
    full_norm = re.sub(r"\s+", " ", full)
    lines = [ln.strip() for ln in full.split("\n") if ln.strip()]

    # --- ФИО: сначала по меткам (где искать) ---
    fam, im, otch = _extract_fio_by_structure(lines)
    if not fam or not im:
        fam, im, otch = _extract_fio_triple(full, full_norm)
    data["Фамилия"] = fam
    data["Имя"] = im
    data["Отчество"] = otch

    # --- Серия ---
    data["Серия и номер паспорта"] = _extract_series(full, full_norm)

    # --- Даты (по меткам) ---
    for label, key in [("рождения", "Дата рождения"), ("выдачи", "Дата выдачи")]:
        m = re.search(rf"(?:дата\s+{label}|{label})[:\s]*(\d{{1,2}}[.\-]\d{{1,2}}[.\-]\d{{4}})", full, re.I)
        if m:
            data[key] = _norm_date(m.group(1))
    if not data["Дата рождения"] or not data["Дата выдачи"]:
        dates = re.findall(r"\b(\d{1,2}[.\-]\d{1,2}[.\-]\d{4})\b", full)
        if dates:
            by_year = [(_norm_date(d), int(d.split(".")[-1] if "." in d else d.split("-")[-1])) for d in dates]
            by_year.sort(key=lambda x: x[1])
            if not data["Дата рождения"]:
                data["Дата рождения"] = by_year[0][0]
            if not data["Дата выдачи"] and len(by_year) > 1:
                data["Дата выдачи"] = by_year[-1][0]

    # --- Кем выдан ---
    code = re.search(r"\b(\d{3}-\d{3})\b", full)
    subdiv = code.group(1) if code else ""
    for pat in [
        r"(?:паспорт\s+выдан|кем\s+выдан|выдан)\s*[:\s]*([А-Яа-яЁё0-9№\s,.\-/]+?)(?=дата\s+выдачи|код\s+подразделения|\d{2}\.\d{2}\.\d{4}|$)",
        r"(ОТДЕЛОМ\s+УФМС\s+[А-Яа-яЁё0-9№\s,.\-/]+?)(?=\d{2}\.\d{2}\.\d{4}|МЕСТО|$)",
        r"(ОУФМС\s+[А-Яа-яЁё0-9№\s,.\-/]+?)(?=ЗАРЕГИСТРИРОВАН|МЕСТО|$)",
    ]:
        issued = re.search(pat, full, re.I | re.DOTALL)
        if issued:
            val = re.sub(r"\s+", " ", issued.group(1).strip())[:500]
            if len(val) > 10 and "УФМС" in val.upper() and "ул." not in val.lower():
                data["Кем выдан"] = val
                break
    if subdiv and subdiv not in (data["Кем выдан"] or ""):
        data["Кем выдан"] = ((data["Кем выдан"] or "") + " " + subdiv).strip()
    if not data["Кем выдан"] and subdiv:
        data["Кем выдан"] = subdiv

    # --- Место рождения ---
    bp = re.search(r"(?:место\s+рождения|рождения)[:\s]*([А-Яа-яЁёA-Za-z\s,.\-]+?)(?=\d{1,2}[.\-]\d|$)", full, re.I | re.DOTALL)
    if bp:
        data["Место рождения"] = re.sub(r"\s+", " ", bp.group(1).strip())[:150]
    gor = re.search(r"ГОР\.\s*([А-Яа-яЁёA-Za-z\s\-]+?)(?=\d{1,2}\.\d|595|\n\n|$)", full)
    if gor and not data["Место рождения"]:
        data["Место рождения"] = ("гор. " + gor.group(1).strip()).strip()[:150]
    if data["Место рождения"] and re.match(r"^\d", data["Место рождения"]):
        data["Место рождения"] = ""

    # --- ИНН ---
    inn = re.search(r"\b(\d{12})\b", full)
    if inn:
        data["ИНН"] = inn.group(1)

    # --- Адрес ---
    m_addr = re.search(r"(?:ул\.?|улица)\s+([А-Яа-яЁё\-]+).*?дом\s*[№]?\s*(\d+)(?:\s*корп\.?\s*(\d+))?(?:\s*кв\.?\s*(\d+))?", full, re.I | re.DOTALL)
    if m_addr:
        parts = [f"ул. {m_addr.group(1).strip()}", f"д. {m_addr.group(2)}"]
        if m_addr.group(3):
            parts.append(f"корп. {m_addr.group(3)}")
        if m_addr.group(4):
            parts.append(f"кв. {m_addr.group(4)}")
        data["Адрес регистрации"] = ", ".join(parts)[:450]
    if not data["Адрес регистрации"]:
        for pat in [
            r"(?:зарегистрирован|место\s+жительства)\s*[:\s]*([А-Яа-яЁё0-9№\s,.\-]+?)(?=подпись|семейное|дети|кем выдан|паспорт|\n\n|$)",
            r"(?:ул\.?|улица)\s*[:\s]*([А-Яа-яЁё0-9\s\-]+?)(?=дом|корп|кв|$|\n)",
        ]:
            reg = re.search(pat, full, re.I | re.DOTALL)
            if reg:
                val = re.sub(r"\s+", " ", reg.group(1).strip())
                if len(val) > 5 and not re.match(r"^\d+$", val) and "УФМС" not in val.upper():
                    data["Адрес регистрации"] = val[:450]
                    break
    if not data["Адрес регистрации"]:
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
            data["Адрес регистрации"] = ", ".join(addr)[:450]
        else:
            m = re.search(r"([А-Яа-яЁё\-]{4,}\s+(?:ул\.?|улица|пер\.)|(?:ул\.?|улица)\s+[А-Яа-яЁё\-]+).*?дом\s*[№]?\s*(\d+)(?:\s*корп\.?\s*(\d+))?(?:\s*кв\.?\s*(\d+))?", full, re.I | re.DOTALL)
            if m:
                data["Адрес регистрации"] = re.sub(r"\s+", " ", m.group(0).strip())[:450]

    return data
