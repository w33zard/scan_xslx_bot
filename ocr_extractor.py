"""
Извлечение данных из сканов паспортов с помощью OCR
"""
import re
import tempfile
from pathlib import Path
from typing import Optional

import cv2
import pytesseract
from PIL import Image


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
    # Увеличение контраста без бинаризации (OTSU может затереть текст)
    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    # Масштабирование для мелкого текста
    scale = 2
    gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return gray


def extract_text_from_image(image_path: str) -> str:
    """Извлечь текст из изображения паспорта"""
    try:
        img = cv2.imread(image_path)
        if img is None:
            return ""

        # Варианты: предобработка и исходник (иногда лучше работает)
        variants = [preprocess_image(image_path), cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)]

        for lang in ["rus+eng", "rus", "eng"]:
            for img_use in variants:
                if img_use is None:
                    continue
                for psm in [6, 3]:
                    try:
                        config = f"--psm {psm} -c preserve_interword_spaces=1"
                        text = pytesseract.image_to_string(img_use, lang=lang, config=config)
                        if text and len(text.strip()) > 20:
                            return text
                    except Exception:
                        continue
        last_img = next((v for v in variants if v is not None), cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        for lang in ["rus+eng", "rus"]:
            try:
                t = pytesseract.image_to_string(last_img, lang=lang, config="--psm 6")
                if t:
                    return t
            except Exception:
                continue
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

    # Серия и номер - особый случай, ищем первое совпадение формата ХХ ХХ ХХХХХХ
    series_match = re.search(r"(\d{2})\s*(\d{2})\s*(\d{6})", full_text)
    if series_match:
        data["Серия и номер паспорта"] = f"{series_match.group(1)} {series_match.group(2)} {series_match.group(3)}"

    # Дата рождения - DD.MM.YYYY
    dob_matches = re.findall(r"\b(\d{2}\.\d{2}\.\d{4})\b", full_text)
    if dob_matches:
        data["Дата рождения"] = dob_matches[0]
        if len(dob_matches) > 1:
            data["Дата выдачи"] = dob_matches[1]

    # ФИО - обычно в начале, три слова подряд с заглавной буквы
    fio_match = re.search(
        r"([А-ЯЁ][а-яё]+)\s+([А-ЯЁ][а-яё]+)\s+([А-ЯЁ][а-яё]+)",
        full_text,
    )
    if fio_match:
        data["Фамилия"] = fio_match.group(1)
        data["Имя"] = fio_match.group(2)
        data["Отчество"] = fio_match.group(3)

    # ИНН — только 12 цифр (физлицо), не путать с серией паспорта (10 цифр)
    inn_match = re.search(r"\b(\d{12})\b", full_text)
    if inn_match:
        data["ИНН"] = inn_match.group(1)

    # Кем выдан - ищем после "выдан" или код подразделения
    issued_match = re.search(
        r"(?:кем выдан|выдан|Кем выдан)\s*[:]?\s*([А-Яа-яЁё0-9\s,.\-]+?)(?=\d{3}-\d{3}|\n\n|$)",
        full_text,
        re.IGNORECASE | re.DOTALL,
    )
    if issued_match:
        data["Кем выдан"] = issued_match.group(1).strip()[:200]

    # Место рождения
    birth_place_match = re.search(
        r"(?:место рождения|Место рождения)\s*[:]?\s*([А-Яа-яЁё0-9\s,.\-]+?)(?=\d{2}\.\d{2}\.\d{4}|\n\n|серия|паспорт)",
        full_text,
        re.IGNORECASE | re.DOTALL,
    )
    if birth_place_match:
        data["Место рождения"] = birth_place_match.group(1).strip()[:150]

    # Адрес - часто в конце
    addr_match = re.search(
        r"(?:адрес|место жительства|Адрес)\s*[:]?\s*([А-Яа-яЁё0-9\s,.\-/]+?)(?=\n\n|$)",
        full_text,
        re.IGNORECASE | re.DOTALL,
    )
    if addr_match:
        data["Адрес регистрации"] = addr_match.group(1).strip()[:200]

    return data


def process_passport_image(image_path: str, index: int = 1) -> dict:
    """
    Обработать одно изображение паспорта и вернуть данные для Excel
    """
    ocr_text = extract_text_from_image(image_path)
    data = parse_passport_data(ocr_text)
    data_with_num = {"№ п/п": str(index), **data}
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
