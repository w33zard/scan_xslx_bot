# -*- coding: utf-8 -*-
"""
Парсер паспорта РФ — простая логика с нуля.
ФИО: только тройка (Фамилия Имя Отчество), 3-е слово на -вич/-вна/-ова/-ич.
Серия: XX XX XXXXXX, не 77/87/19/20.
"""
import re

EXCEL_COLUMNS = [
    "№ п/п", "Фамилия", "Имя", "Отчество", "Дата рождения", "Место рождения",
    "Серия и номер паспорта", "Дата выдачи", "Кем выдан", "ИНН",
    "Адрес регистрации", "Примечания",
]

FIO_BAN = {
    "выдан", "тп", "паспорт", "отдел", "уфмс", "россии", "санкт", "петербург",
    "петербургу", "код", "подраздел", "гор", "пункт", "улица", "дом", "муж",
    "зарегистрирован", "рождения", "дата", "выдачи", "место", "федерация",
    "российская", "личный", "граждан", "номер", "серия", "квартира", "корп",
    "обл", "республик", "область", "район", "р-н", "фамилия", "имя", "отчество",
}


def parse_passport_data(ocr_text: str) -> dict:
    """Парсинг паспорта РФ. Только тройка ФИО + валидная серия."""
    data = {col: "" for col in EXCEL_COLUMNS[1:]}
    if not ocr_text or not ocr_text.strip():
        return data

    full = ocr_text.strip()
    full_norm = re.sub(r"\s+", " ", full)
    lines = [ln.strip() for ln in full.split("\n") if ln.strip()]

    # --- ФИО: тройка "X Y Z" где Z на -вич/-вна/-ова/-ич, все не в BAN ---
    def ok(w):
        w = (w or "").strip().lower()
        if not w or len(w) < 2 or not w.isalpha():
            return False
        if w in FIO_BAN:
            return False
        # Отсекаем слова, содержащие служебные подстроки (РОССИЙСКАЯФЕДЕРАЦИЯ, Паспортвыдан)
        if any(b in w for b in FIO_BAN):
            return False
        return True

    WORD = r"[А-ЯЁа-яё][А-ЯЁа-яё\-]{1,}"
    fam, im, otch = "", "", ""

    for txt in (full_norm, full):
        for m in re.finditer(rf"({WORD})\s+({WORD})\s+({WORD})", txt):
            a, b, c = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
            if not (ok(a) and ok(b) and ok(c)):
                continue
            if not c.lower().endswith(("вич", "вна", "ова", "ич")):
                continue
            fam, im, otch = a, b, c
            break
        if fam:
            break

    # Fallback: 3 подряд строки (последние 3 перед отчеством)
    if not fam and len(lines) >= 3:
        cand = []
        for ln in lines[:30]:
            w = re.sub(r"[^\w\-]", "", ln).strip()
            if 2 <= len(w) <= 50 and w.isalpha():
                if any(b in w.lower() for b in FIO_BAN) or w.lower() in FIO_BAN:
                    continue
                if cand and w.upper() == cand[-1].upper():
                    continue
                cand.append(w)
                if len(cand) >= 3 and cand[-1].lower().endswith(("вич", "вна", "ова", "ич")):
                    fam, im, otch = cand[-3], cand[-2], cand[-1]
                    break

    data["Фамилия"] = fam
    data["Имя"] = im
    data["Отчество"] = otch

    # --- Серия: XX XX XXXXXX, НЕ 77/87/19/20 ---
    def valid_series(s1, s2, num):
        if not (s1 and s2 and num and len(num) == 6):
            return False
        if num.startswith(("19", "20")):
            return False
        if s1 in ("77", "87", "19", "20") or s2 in ("77", "87"):
            return False
        return True

    series_val = ""
    for txt in (full_norm, full):
        m = re.search(r"\b(\d{4})[\s\-]?(\d{6})\b", txt)
        if m:
            s, num = m.group(1), m.group(2)
            if not s.startswith(("19", "20")) and valid_series(s[:2], s[2:], num):
                series_val = f"{s[:2]} {s[2:]} {num}"
                break
        m = re.search(r"\b(\d{2})[\s\-]?(\d{2})[\s\-]?(\d{6})\b", txt)
        if not series_val and m and valid_series(m.group(1), m.group(2), m.group(3)):
            series_val = f"{m.group(1)} {m.group(2)} {m.group(3)}"
            break
    if not series_val:
        digits = re.sub(r"\D", "", full)
        for i in range(len(digits) - 9):
            chunk = digits[i : i + 10]
            s1, s2, num = chunk[:2], chunk[2:4], chunk[4:]
            if valid_series(s1, s2, num):
                series_val = f"{s1} {s2} {num}"
                break
    data["Серия и номер паспорта"] = series_val

    # --- Даты ---
    birth_m = re.search(r"(?:рождения|дата\s+рождения)[:\s]*(\d{1,2}[.\-]\d{1,2}[.\-]\d{4})", full, re.I)
    issue_m = re.search(r"(?:выдачи|дата\s+выдачи)[:\s]*(\d{1,2}[.\-]\d{1,2}[.\-]\d{4})", full, re.I)
    if birth_m:
        data["Дата рождения"] = birth_m.group(1).replace("-", ".")
    if issue_m:
        data["Дата выдачи"] = issue_m.group(1).replace("-", ".")
    if not data["Дата рождения"] or not data["Дата выдачи"]:
        dates = re.findall(r"\b(\d{1,2}[.\-]\d{1,2}[.\-]\d{4})\b", full)
        if dates:
            # Раньше = рождение, позже = выдача
            parsed = [(d.replace("-", "."), int(d.split(".")[-1]) if "." in d else int(d.split("-")[-1])) for d in dates]
            parsed.sort(key=lambda x: x[1])
            if not data["Дата рождения"]:
                data["Дата рождения"] = parsed[0][0]
            if not data["Дата выдачи"] and len(parsed) > 1:
                data["Дата выдачи"] = parsed[-1][0]

    # --- Кем выдан ---
    code_m = re.search(r"\b(\d{3}-\d{3})\b", full)
    subdiv = code_m.group(1) if code_m else ""
    issued = re.search(
        r"(?:паспорт\s+выдан|кем\s+выдан|выдан)\s*[:\s]*([А-Яа-яЁё0-9№\s,.\-/]+?)(?=дата\s+выдачи|код|$)",
        full, re.I | re.DOTALL
    )
    if issued:
        data["Кем выдан"] = re.sub(r"\s+", " ", issued.group(1).strip())[:500]
        if subdiv and subdiv not in data["Кем выдан"]:
            data["Кем выдан"] = (data["Кем выдан"] + " " + subdiv).strip()
    elif subdiv:
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
    inn_m = re.search(r"\b(\d{12})\b", full)
    if inn_m:
        data["ИНН"] = inn_m.group(1)

    # --- Адрес ---
    reg = re.search(
        r"(?:Зарегистрирован|зарегистрирован)\s*[:\s]*([А-Яа-яЁё0-9№\s,.\-/]+?)(?=Семейное|Дети|Кем выдан|Паспорт|\n\n|$)",
        full, re.I | re.DOTALL
    )
    if reg:
        val = re.sub(r"\s+", " ", reg.group(1).strip())
        if len(val) > 15:
            data["Адрес регистрации"] = val[:450]
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

    return data
