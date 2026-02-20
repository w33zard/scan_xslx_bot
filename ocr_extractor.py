"""
Извлечение данных из сканов паспортов с помощью OCR
Поддержка: Yandex Vision API (приоритет) и Tesseract (fallback)
"""
import base64
import os
import re
from pathlib import Path
from typing import Optional

import cv2
import pytesseract


# Колонки для Excel (как в целевом формате)
EXCEL_COLUMNS = [
    "№ п/п",
    "Фамилия",
    "Имя",
    "Отчество",
    "Дата рождения",
    "Место рождения",
    "Серия и номер паспорта",
    "Дата выдачи",
    "Кем выдан",
    "ИНН",
    "Адрес регистрации",
    "Примечания",
]


def preprocess_image(image_path: str) -> "cv2.Mat":
    """Предобработка изображения для улучшения OCR"""
    img = cv2.imread(image_path)
    if img is None:
        return None

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # Обрезка краёв — убираем рамки/водяные знаки, оставляем центральную часть
    h, w = gray.shape
    margin = min(h, w) // 15
    gray = gray[margin : h - margin, margin : w - margin]
    # Лёгкое шумоподавление (сильное размывает текст)
    gray = cv2.fastNlMeansDenoising(gray, None, 5, 7, 21)
    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    # Масштабирование для мелкого текста
    scale = 2
    gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return gray


def _crop_center(img, frac=0.85):
    """Обрезать по центру, убрать края"""
    h, w = img.shape[:2]
    nh, nw = int(h * frac), int(w * frac)
    y0, x0 = (h - nh) // 2, (w - nw) // 2
    return img[y0 : y0 + nh, x0 : x0 + nw]


def _yandex_vision_ocr(image_path: str) -> str:
    """OCR через Yandex Vision API — лучше для российских паспортов"""
    api_key = os.environ.get("YANDEX_VISION_API_KEY")
    if not api_key:
        return ""

    try:
        import requests
        import tempfile

        img = cv2.imread(image_path)
        if img is None:
            return ""

        # Yandex лимит ~1MB — уменьшаем, если больше
        h, w = img.shape[:2]
        max_side = 1600
        for q in [85, 75, 65]:
            scale = min(1.0, max_side / max(h, w))
            img_send = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else img
            _, buf = cv2.imencode(".jpg", img_send, [cv2.IMWRITE_JPEG_QUALITY, q])
            if len(buf) < 900_000:
                break
            max_side = int(max_side * 0.7)

        content = base64.b64encode(buf.tobytes()).decode("utf-8")

        url = "https://vision.api.cloud.yandex.net/vision/v1/batchAnalyze"
        headers = {"Authorization": f"Api-Key {api_key}", "Content-Type": "application/json"}
        body = {
            "analyze_specs": [{
                "content": content,
                "features": [{
                    "type": "TEXT_DETECTION",
                    "text_detection_config": {"language_codes": ["ru", "en"]}
                }]
            }]
        }
        r = requests.post(url, json=body, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()

        texts = []
        for res in data.get("results", []):
            for item in res.get("results", []):
                td = item.get("textDetection") or item.get("textAnnotation") or {}
                for page in td.get("pages", []):
                    for block in page.get("blocks", []):
                        for line in block.get("lines", []):
                            line_text = line.get("text") or " ".join(w.get("text", "") for w in line.get("words", []))
                            if line_text:
                                texts.append(line_text)
                full = td.get("fullText")
                if full:
                    texts.insert(0, full)
        return "\n".join(texts) if texts else ""
    except Exception as e:
        print(f"Yandex Vision error: {e}")
        return ""


def _is_garbage(text: str) -> bool:
    """Проверка: текст выглядит как мусор (в основном спецсимволы)"""
    if not text or len(text.strip()) < 10:
        return True
    letters = sum(1 for c in text if c.isalpha() or c in "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя")
    digits = sum(1 for c in text if c.isdigit())
    total = len([c for c in text if not c.isspace()])
    if total == 0:
        return True
    useful = (letters + digits) / total
    return useful < 0.25  # больше 75% мусора — отбрасываем

def extract_text_from_image(image_path: str) -> str:
    """Извлечь текст из изображения паспорта"""
    try:
        # Сначала Yandex Vision, если есть ключ
        text = _yandex_vision_ocr(image_path)
        if text and not _is_garbage(text):
            return text.strip()

        img = cv2.imread(image_path)
        if img is None:
            return ""

        gray_full = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray_crop = _crop_center(gray_full)
        preprocessed = preprocess_image(image_path)
        variants = [
            (preprocessed, "preprocessed"),
            (gray_crop, "cropped"),
            (gray_full, "full"),
        ]

        for img_use, _ in variants:
            if img_use is None:
                continue
            for psm in [11, 6, 4, 3]:  # 11=sparse text, лучше для паспортов
                for lang in ["rus+eng", "rus"]:
                    try:
                        config = f"--psm {psm} -c preserve_interword_spaces=1"
                        text = pytesseract.image_to_string(img_use, lang=lang, config=config)
                        if text and not _is_garbage(text):
                            return text.strip()
                    except Exception:
                        continue

        # Попытка через image_to_data — только слова с высокой уверенностью
        last_img = preprocessed if preprocessed is not None else gray_crop
        try:
            d = pytesseract.image_to_data(last_img, lang="rus+eng", output_type=pytesseract.Output.DICT)
            confs = d.get("conf", [])
            words = [
                str(d["text"][i]).strip() for i in range(len(d["text"]))
                if i < len(confs) and int(confs[i]) > 60 and str(d["text"][i]).strip()
            ]
            text = " ".join(words).strip() if words else ""
            if text and not _is_garbage(text):
                return text
        except Exception:
            pass
        return ""
    except Exception as e:
        print(f"OCR error for {image_path}: {e}")
        return ""


def parse_passport_data(ocr_text: str) -> dict:
    """
    Парсинг данных паспорта из OCR-текста.
    Поддерживает формат российского внутреннего паспорта.
    """
    data = {col: "" for col in EXCEL_COLUMNS[1:]}  # без № п/п

    lines = [line.strip() for line in ocr_text.split("\n") if line.strip()]

    # Паттерны для извлечения данных
    patterns = {
        "Фамилия": [
            r"(?:Фамилия|фамилия)\s*[:]?\s*([А-Яа-яЁё\s-]+)",
            r"^([А-Яа-яЁё]+)\s+[А-Яа-яЁё]+\s+[А-Яа-яЁё]+",  # первое слово в строке с ФИО
        ],
        "Имя": [
            r"(?:Имя|имя)\s*[:]?\s*([А-Яа-яЁё\s-]+)",
        ],
        "Отчество": [
            r"(?:Отчество|отчество)\s*[:]?\s*([А-Яа-яЁё\s-]+)",
        ],
        "Дата рождения": [
            r"(?:Дата рождения|дата рождения)\s*[:]?\s*(\d{2}\.\d{2}\.\d{4})",
            r"(\d{2}\.\d{2}\.\d{4})",
        ],
        "Место рождения": [
            r"(?:Место рождения|место рождения)\s*[:]?\s*(.+?)(?=\d{2}\.\d{2}|\n|$)",
        ],
        "Серия и номер паспорта": [
            r"(\d{2}\s?\d{2}\s?\d{6})",
            r"(\d{4}\s?\d{6})",
        ],
        "Дата выдачи": [
            r"(?:Дата выдачи|дата выдачи)\s*[:]?\s*(\d{2}\.\d{2}\.\d{4})",
        ],
        "Кем выдан": [
            r"(?:Кем выдан|кем выдан|выдан)\s*[:]?\s*(.+?)(?=\d{2}\.\d{2}|\n\n|Код|код|$)",
        ],
        "ИНН": [
            r"(?:ИНН|инн)\s*[:]?\s*(\d{10,12})",
            r"\b(\d{12})\b",
        ],
        "Адрес регистрации": [
            r"(?:Адрес|адрес|Место жительства|место жительства)\s*[:]?\s*(.+?)(?=\n\n|$)",
        ],
    }

    full_text = ocr_text

    # Серия и номер — XX XX XXXXXX, XXXX XXXXXX, XX-XX-XXXXXX
    series_match = re.search(r"\b(\d{2})[\s\-]?(\d{2})[\s\-]?(\d{6})\b", full_text)
    if not series_match:
        series_match = re.search(r"\b(\d{4})[\s\-]?(\d{6})\b", full_text)
        if series_match:
            s, n = series_match.group(1), series_match.group(2)
            data["Серия и номер паспорта"] = f"{s[:2]} {s[2:]} {n}"
    else:
        data["Серия и номер паспорта"] = f"{series_match.group(1)} {series_match.group(2)} {series_match.group(3)}"
    if not data["Серия и номер паспорта"]:
        # Fallback: 10 цифр подряд или с пробелами (серия 4 + номер 6)
        m = re.search(r"\b(\d{2})\s*(\d{2})\s*(\d{5,6})\b", full_text)
        if m:
            data["Серия и номер паспорта"] = f"{m.group(1)} {m.group(2)} {m.group(3)}"

    # Код подразделения XXX-XXX — можно добавить к "Кем выдан"
    code_match = re.search(r"\b(\d{3}-\d{3})\b", full_text)
    subdiv_code = code_match.group(1) if code_match else ""

    # Даты: "Дата рождения DD.MM.YYYY" и "Дата выдачи DD.MM.YYYY"
    dob_match = re.search(r"(?:дата\s+рождения|рождения)[:\s]*(\d{1,2}[.\-]\d{1,2}[.\-]\d{4})", full_text, re.I | re.DOTALL)
    if dob_match:
        data["Дата рождения"] = dob_match.group(1).replace("-", ".")
    vydacha_match = re.search(r"(?:дата\s+выдачи|выдачи)[:\s]*(\d{1,2}[.\-]\d{1,2}[.\-]\d{4})", full_text, re.I | re.DOTALL)
    if vydacha_match:
        data["Дата выдачи"] = vydacha_match.group(1).replace("-", ".")
    if not data["Дата рождения"] and not data["Дата выдачи"]:
        dob_matches = re.findall(r"\b(\d{1,2}[.\-]\d{1,2}[.\-]\d{4})\b", full_text)
        if dob_matches:
            data["Дата рождения"] = dob_matches[0].replace("-", ".")
            if len(dob_matches) > 1:
                data["Дата выдачи"] = dob_matches[1].replace("-", ".")

    # ФИО — после метки "Фамилия" или три слова кириллицей подряд
    fam_match = re.search(r"Фамилия\s*[.\s]+([А-ЯЁ][а-яё\-]+)", full_text, re.I)
    im_match = re.search(r"Имя\s*[.\s]+([А-ЯЁ][а-яё\-]+)", full_text, re.I)
    otch_match = re.search(r"(?:Отчество|ОТЧЕСТВО)\s*[.\s]+([А-ЯЁ][а-яё\-]+)", full_text, re.I)
    if fam_match:
        data["Фамилия"] = fam_match.group(1).strip()
    if im_match:
        data["Имя"] = im_match.group(1).strip()
    if otch_match:
        data["Отчество"] = otch_match.group(1).strip()
    # ФИО со следующей строки после метки
    for i, line in enumerate(lines):
        ln = line.lower()
        if "фамилия" in ln and i + 1 < len(lines) and not data["Фамилия"]:
            v = re.sub(r"[^\w\-]", "", lines[i + 1]).strip()
            if 2 <= len(v) <= 50 and all(c.isalpha() or c == "-" for c in v):
                data["Фамилия"] = v
        if ("имя" in ln and "отчество" not in ln) and i + 1 < len(lines) and not data["Имя"]:
            v = re.sub(r"[^\w\-]", "", lines[i + 1]).strip()
            if 2 <= len(v) <= 50 and all(c.isalpha() or c == "-" for c in v):
                data["Имя"] = v
        if "отчество" in ln and i + 1 < len(lines) and not data["Отчество"]:
            v = re.sub(r"[^\w\-]", "", lines[i + 1]).strip()
            if 2 <= len(v) <= 50 and all(c.isalpha() or c == "-" for c in v):
                data["Отчество"] = v
    if not data["Фамилия"] or not data["Имя"]:
        fio_match = re.search(
            r"([А-ЯЁ][а-яё]{2,})\s+([А-ЯЁ][а-яё]{2,})\s+([А-ЯЁ][а-яё]{2,})",
            full_text,
        )
        if fio_match and (not data["Фамилия"] or not data["Имя"]):
            data["Фамилия"] = data["Фамилия"] or fio_match.group(1)
            data["Имя"] = data["Имя"] or fio_match.group(2)
            data["Отчество"] = data["Отчество"] or fio_match.group(3)
        # Вариант: Имя Отчество (ФЕДОР МИХАЙЛОВИЧ) — ищем пару где второе похоже на отчество
        skip_words = {"животный", "личный", "код", "цицар", "граждан", "россий", "федера", "паспорт", "адрес", "санкт", "петербург", "отдела", "центральном"}
        if not data["Имя"] or not data["Отчество"]:
            for two_match in re.finditer(r"([А-ЯЁ][а-яё]{2,})\s+([А-ЯЁ][а-яё]{2,})", full_text):
                w1, w2 = two_match.group(1).lower(), two_match.group(2).lower()
                if w1 not in skip_words and w2 not in skip_words and len(w2) >= 4 and w2[-2:] in ("вич", "вна", "ова", "ев", "ин", "ич"):
                    data["Имя"] = data["Имя"] or two_match.group(1)
                    data["Отчество"] = data["Отчество"] or two_match.group(2)
                    break

    # ИНН — только 12 цифр (физлицо), не путать с серией паспорта (10 цифр)
    inn_match = re.search(r"\b(\d{12})\b", full_text)
    if inn_match:
        data["ИНН"] = inn_match.group(1)

    # Кем выдан — текст между "Паспорт выдан"/"выдан" и "Дата выдачи" или кодом XXX-XXX
    issued_match = re.search(
        r"(?:паспорт\s+выдан|кем\s+выдан|выдан)\s*[:\s]*([А-Яа-яЁё0-9№\s,.\-/]+?)(?=\d{3}-\d{3}|дата\s+выдачи|код\s+подразделения|$)",
        full_text,
        re.IGNORECASE | re.DOTALL,
    )
    if issued_match:
        data["Кем выдан"] = re.sub(r"\s+", " ", issued_match.group(1).strip())[:500]
        if subdiv_code and subdiv_code not in data["Кем выдан"]:
            data["Кем выдан"] = (data["Кем выдан"] + " " + subdiv_code).strip()
    elif subdiv_code:
        data["Кем выдан"] = subdiv_code

    # Место рождения — "ГОР. ЛЕНИНГРАД" или после "Место рождения"
    birth_place_match = re.search(
        r"(?:место рождения|Место рождения)[:\s]*([А-Яа-яЁёA-Za-z\s,.\-]+?)(?=\d{1,2}[.\-]\d|серия|паспорт|$)",
        full_text,
        re.IGNORECASE | re.DOTALL,
    )
    if birth_place_match:
        data["Место рождения"] = re.sub(r"\s+", " ", birth_place_match.group(1).strip())[:150]
    gor_match = re.search(r"ГОР\.\s*([А-Яа-яЁёA-Za-z\s\-]+?)(?=\d{1,2}\.\d|595|\n\n|$)", full_text)
    if gor_match and not data["Место рождения"]:
        data["Место рождения"] = ("гор. " + gor_match.group(1).strip()).strip()[:150]
    if data["Место рождения"] and re.match(r"^\d", data["Место рождения"]):
        data["Место рождения"] = ""

    # Адрес — "Место жительства", "Адрес регистрации", "Зарегистрирован", "прописка"
    addr_patterns = [
        r"(?:место\s+жительства|адрес\s+регистрации|зарегистрирован|прописка|адрес)\s*[:\s]*([А-Яа-яЁё0-9\s,.\-/]+?)(?=\n\n|$)",
        r"(?:жительства|проживания)\s*[:\s]*([А-Яа-яЁё0-9\s,.\-/]+?)(?=\n\n|серия|паспорт|$)",
    ]
    for pat in addr_patterns:
        addr_match = re.search(pat, full_text, re.IGNORECASE | re.DOTALL)
        if addr_match:
            val = re.sub(r"\s+", " ", addr_match.group(1).strip())[:300]
            if len(val) > 5 and not val.replace(" ", "").isdigit():
                data["Адрес регистрации"] = val
                break

    return data


def process_passport_image(image_path: str, index: int = 1) -> dict:
    """
    Обработать одно изображение паспорта и вернуть данные для Excel
    """
    ocr_text = extract_text_from_image(image_path)
    data = parse_passport_data(ocr_text)
    data_with_num = {"№ п/п": str(index), **data}
    # Если парсинг пустой, но OCR вернул осмысленный текст — кладём в Примечания
    if ocr_text and not any(data.values()) and not _is_garbage(ocr_text):
        data_with_num["Примечания"] = ocr_text.strip()[:500].replace("\n", " ")
    return data_with_num


def process_images_from_folder(folder_path: str) -> list[dict]:
    """
    Обработать все изображения в папке (включая вложенные)
    """
    folder = Path(folder_path)
    image_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
    image_files = sorted(
        [f for f in folder.rglob("*") if f.is_file() and f.suffix.lower() in image_extensions]
    )

    results = []
    for i, img_path in enumerate(image_files, start=1):
        row = process_passport_image(str(img_path), index=i)
        results.append(row)
    return results
