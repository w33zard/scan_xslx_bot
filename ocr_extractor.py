"""
Извлечение данных из сканов паспортов с помощью OCR
Поддержка: Yandex Vision API (приоритет) и Tesseract (fallback)
Параллельная обработка при наличии CPU/RAM — MAX_WORKERS в .env
"""
import base64
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import cv2
import pytesseract


# Параллелизм — больше CPU/RAM позволяют обрабатывать несколько папок одновременно
MAX_WORKERS = max(1, min(8, int(os.environ.get("MAX_WORKERS", "4"))))

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


def _extract_series_from_vertical_red(image_path: str) -> str:
    """
    Серия и номер паспорта — красные цифры справа на странице с ФИО, расположены вертикально.
    Сканы могут быть перевёрнуты (0°, 90°, 180°, 270°) — пробуем все 4 стороны.
    """
    img = cv2.imread(image_path)
    if img is None:
        return ""
    h, w = img.shape[:2]
    # Пробуем 4 ориентации — цифры могут быть у любой из сторон
    rots = [
        (img, "right"),   # 0° — правая сторона
        (cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE), "bottom"),
        (cv2.rotate(img, cv2.ROTATE_180), "left"),
        (cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE), "top"),
    ]

    def _try_ocr(roi_img, rotate=True, psm=6):
        try:
            img_use = cv2.rotate(roi_img, cv2.ROTATE_90_CLOCKWISE) if rotate else roi_img
            img_use = cv2.resize(img_use, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            text = pytesseract.image_to_string(img_use, config=f"--psm {psm} -c tessedit_char_whitelist=0123456789 ")
            digits = re.sub(r"\D", "", text)
            if len(digits) == 10:
                return f"{digits[:2]} {digits[2:4]} {digits[4:]}"
            for i in range(max(0, len(digits) - 9)):
                chunk = digits[i : i + 10]
                if chunk[:2] not in ("19", "20") and chunk[2:4] not in ("19", "20"):
                    return f"{chunk[:2]} {chunk[2:4]} {chunk[4:]}"
        except Exception:
            pass
        return ""

    def _process_roi(roi):
        if roi.size == 0:
            return ""
        b, g, r = cv2.split(roi)
        red_mask = (r.astype(float) > 80) & (r > g * 1.1) & (r > b * 1.1)
        mono = 255 - (red_mask.astype("uint8") * 255)
        _, binary1 = cv2.threshold(mono, 200, 255, cv2.THRESH_BINARY_INV)
        res = _try_ocr(binary1)
        if res:
            return res
        diff = cv2.subtract(r, cv2.maximum(g, b))
        _, binary2 = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
        res = _try_ocr(binary2)
        if res:
            return res
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        _, binary3 = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        res = _try_ocr(binary3)
        if res:
            return res
        res = _try_ocr(binary1, rotate=False, psm=5)
        if res:
            return res
        return _try_ocr(binary2)

    # ROI: правая и левая стороны (сканы могут быть зеркальными)
    for rot_img, _ in rots:
        rw = rot_img.shape[1]
        for frac in (0.70, 0.75, 0.80, 0.85):
            x0 = int(rw * frac)
            roi = rot_img[:, x0:].copy()
            if roi.size > 0:
                res = _process_roi(roi)
                if res:
                    return res
        for frac in (0.15, 0.20, 0.25):  # левая сторона (зеркальный скан)
            x1 = int(rw * frac)
            roi = rot_img[:, :x1].copy()
            if roi.size > 0:
                res = _process_roi(roi)
                if res:
                    return res

    # Fallback: digit-only OCR на всём изображении (все 4 ориентации)
    def _full_img_digits(im):
        try:
            g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
            g = cv2.resize(g, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            txt = pytesseract.image_to_string(g, config="--psm 6 -c tessedit_char_whitelist=0123456789 ")
            digits = re.sub(r"\D", "", txt)
            for i in range(len(digits) - 9):
                chunk = digits[i : i + 10]
                if chunk[:2] not in ("19", "20") and chunk[2:4] not in ("19", "20"):
                    return f"{chunk[:2]} {chunk[2:4]} {chunk[4:]}"
        except Exception:
            pass
        return ""

    for rot_img, _ in rots:
        res = _full_img_digits(rot_img)
        if res:
            return res
    return ""


def _yandex_vision_ocr(image_path: str) -> str:
    """OCR через Yandex Vision API — лучше для российских паспортов"""
    api_key = os.environ.get("YANDEX_VISION_API_KEY")
    if not api_key:
        return ""

    try:
        import requests

        def _extract_from_response(data) -> str:
            texts = []
            full_yt = ""
            results = data.get("results") or data.get("result") or []
            if not isinstance(results, list):
                results = [results] if results else []
            if not results and data.get("error"):
                return ""
            for res in results:
                if not isinstance(res, dict):
                    continue
                items = res.get("results")
                if items is None:
                    items = res.get("result") or []
                if not isinstance(items, list):
                    items = [items] if items else []
                if not items and ("textDetection" in res or "textAnnotation" in res):
                    items = [res]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    td = item.get("textDetection") or item.get("textAnnotation") or {}
                    if isinstance(td, str):
                        return td.strip()
                    ft = (td.get("fullText") or "").strip()
                    if ft:
                        full_yt = ft
                    for page in td.get("pages", []):
                        for block in page.get("blocks", []):
                            for line in block.get("lines", []):
                                lt = line.get("text")
                                if not lt and line.get("words"):
                                    lt = " ".join(str(w.get("text", "")) for w in line.get("words", []))
                                if lt and str(lt).strip():
                                    texts.append(str(lt).strip())
            lines_str = "\n".join(texts) if texts else ""
            out = (full_yt + "\n" + lines_str).strip() if full_yt and lines_str else (full_yt or lines_str)
            return out

        # Вариант 1: сырой файл (JPEG/PNG) — без перекодировки
        content = None
        path_lower = image_path.lower()
        if path_lower.endswith((".jpg", ".jpeg", ".png")):
            try:
                with open(image_path, "rb") as f:
                    raw = f.read()
                if len(raw) < 900_000:
                    content = base64.b64encode(raw).decode("utf-8")
            except Exception:
                pass

        if not content:
            img = cv2.imread(image_path)
            if img is None:
                return ""
            h, w = img.shape[:2]
            max_side = 1600
            for q in [90, 85, 75, 65]:
                scale = min(1.0, max_side / max(h, w))
                img_send = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else img
                _, buf = cv2.imencode(".jpg", img_send, [cv2.IMWRITE_JPEG_QUALITY, q])
                if len(buf) < 900_000:
                    content = base64.b64encode(buf.tobytes()).decode("utf-8")
                    break
                max_side = int(max_side * 0.8)

        if not content:
            return ""

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
        r = requests.post(url, json=body, headers=headers, timeout=60)
        r.raise_for_status()
        data = r.json()
        if os.environ.get("SAVE_YANDEX_RESPONSE"):
            import json
            import tempfile
            p = Path(tempfile.gettempdir()) / "yandex_response.json"
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[DEBUG] Yandex response saved to {p}")
        return _extract_from_response(data)
    except Exception as e:
        print(f"Yandex Vision error: {e}")
        return ""


def _is_garbage(text: str) -> bool:
    """Проверка: только явный мусор — принимаем всё, что может содержать данные"""
    if not text or len(text.strip()) < 3:
        return True
    if any(c.isalpha() or c.isdigit() for c in text):
        return False  # Есть буквы или цифры — не мусор
    return True

def _append_vertical_series(image_path: str, text: str) -> str:
    """Добавить серию/номер из правой вертикальной области (красные цифры)"""
    vert = _extract_series_from_vertical_red(image_path)
    if vert:
        return (text + "\n" + vert).strip() if text else vert
    return text or ""


def extract_text_from_image(image_path: str) -> str:
    """
    Извлечь текст из изображения паспорта.
    Сканы могут быть перевёрнуты (90°, 180°, 270°) — при fallback на Tesseract пробуем все ориентации.
    """
    try:
        text = ""
        # Сначала Yandex Vision, если есть ключ
        text = _yandex_vision_ocr(image_path)
        if text and os.environ.get("DEBUG_OCR"):
            debug_path = Path(image_path).with_suffix(".ocr.txt")
            try:
                debug_path.write_text(text, encoding="utf-8")
                print(f"[DEBUG_OCR] saved to {debug_path}")
            except Exception:
                print(f"[DEBUG_OCR] {image_path}:\n---\n{text[:500]}...\n---")
        if text:
            return _append_vertical_series(image_path, text.strip())

        img = cv2.imread(image_path)
        if img is None:
            return ""

        gray_full = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray_crop = _crop_center(gray_full)
        preprocessed = preprocess_image(image_path)
        # Сначала полное изображение — обрезка/предобработка может терять текст
        variants = [
            (gray_full, "full"),
            (gray_crop, "cropped"),
            (preprocessed, "preprocessed"),
        ]
        # Сканы могут быть перевёрнуты — добавляем повёрнутые варианты
        for rot in [cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE]:
            g = cv2.cvtColor(cv2.rotate(img, rot), cv2.COLOR_BGR2GRAY)
            variants.append((g, "rotated"))

        for img_use, _ in variants:
            if img_use is None:
                continue
            for psm in [11, 6, 4, 3]:  # 11=sparse text
                for lang in ["rus+eng", "rus"]:
                    try:
                        config = f"--psm {psm} -c preserve_interword_spaces=1"
                        text = pytesseract.image_to_string(img_use, lang=lang, config=config)
                        if text and text.strip():
                            return _append_vertical_series(image_path, text.strip())
                    except Exception:
                        continue

        # image_to_data — только высокий conf
        last_img = preprocessed if preprocessed is not None else gray_crop
        try:
            d = pytesseract.image_to_data(last_img, lang="rus+eng", output_type=pytesseract.Output.DICT)
            confs = d.get("conf", [])
            words = [
                str(d["text"][i]).strip() for i in range(len(d["text"]))
                if i < len(confs) and int(confs[i]) > 60 and str(d["text"][i]).strip()
            ]
            text = " ".join(words).strip() if words else ""
            if text:
                return _append_vertical_series(image_path, text)
        except Exception:
            pass
        return _append_vertical_series(image_path, "")
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
    # Нормализованный текст — цифры/слова могут быть разбиты переносами
    full_norm = re.sub(r"\s+", " ", full_text)

    # Серия и номер — XX XX XXXXXX (цифры могут быть разбиты переносами)
    for txt in (full_norm, full_text):
        series_match = re.search(r"\b(\d{2})[\s\-]?(\d{2})[\s\-]?(\d{6})\b", txt)
        if series_match:
            data["Серия и номер паспорта"] = f"{series_match.group(1)} {series_match.group(2)} {series_match.group(3)}"
            break
        series_match = re.search(r"\b(\d{4})[\s\-]?(\d{6})\b", txt)
        if series_match:
            s, n = series_match.group(1), series_match.group(2)
            if not s.startswith(("19", "20")):
                data["Серия и номер паспорта"] = f"{s[:2]} {s[2:]} {n}"
                break
    if not data["Серия и номер паспорта"]:
        # Любые 10 цифр подряд (не год) — OCR может вернуть без пробелов
        digits_only = re.sub(r"\D", "", full_text)
        for i in range(len(digits_only) - 9):
            chunk = digits_only[i : i + 10]
            if chunk[:2] not in ("19", "20") and chunk[2:4] not in ("19", "20"):
                data["Серия и номер паспорта"] = f"{chunk[:2]} {chunk[2:4]} {chunk[4:]}"
                break
    if not data["Серия и номер паспорта"]:
        for m in re.finditer(r"\b(\d{4})\b", full_text):
            f = m.group(1)
            if f.startswith(("19", "20")):
                continue
            rest = full_text[m.end():]
            six_m = re.search(r"\b(\d{6})\b", rest)
            if six_m:
                data["Серия и номер паспорта"] = f"{f[:2]} {f[2:]} {six_m.group(1)}"
                break
    if not data["Серия и номер паспорта"]:
        for pat in [
            r"\b(\d{2})\s*(\d{2})\s*(\d{5,6})\b",
            r"\b(\d{4})\s*(\d{6})\b",
            r"\b(\d{10})\b",
        ]:
            m = re.search(pat, full_text)
            if m:
                if len(m.groups()) == 3:
                    data["Серия и номер паспорта"] = f"{m.group(1)} {m.group(2)} {m.group(3)}"
                elif len(m.groups()) == 2:
                    s, n = m.group(1), m.group(2)
                    data["Серия и номер паспорта"] = f"{s[:2]} {s[2:]} {n}"
                else:
                    ten = m.group(1)
                    data["Серия и номер паспорта"] = f"{ten[:2]} {ten[2:4]} {ten[4:]}"
                break

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
    fam_match = re.search(r"Фамилия\s*[.:\s]+([А-ЯЁа-яё\-]+)", full_text, re.I)
    im_match = re.search(r"Имя\s*[.\s]+([А-ЯЁа-яё\-]+)", full_text, re.I)
    otch_match = re.search(r"(?:Отчество|ОТЧЕСТВО)\s*[.\s]+([А-ЯЁа-яё\-]+)", full_text, re.I)
    if fam_match:
        fam_val = fam_match.group(1).strip().split()[0]
        if len(fam_val) > 3 or not re.match(r"^[А-ЯЁ][А-ЯЁ]$", fam_val):
            data["Фамилия"] = fam_val
    if im_match:
        data["Имя"] = im_match.group(1).strip()
    if otch_match:
        data["Отчество"] = otch_match.group(1).strip()
    # ФИО — следующая или предыдущая строка после метки (Yandex читает блоками, порядок может отличаться)
    def _clean_word(s):
        return re.sub(r"[^\w\-]", "", s).strip()

    for i, line in enumerate(lines):
        ln = line.lower()
        # Ищем соседние строки (Yandex может выводить значение до или после метки)
        for field, key, min_len, extra_check in [
            ("фамилия", "Фамилия", 3, lambda v: not re.match(r"^[А-ЯЁ][А-ЯЁ]$", v)),
            ("имя", "Имя", 2, lambda v: True),
            ("отчество", "Отчество", 2, lambda v: len(v) >= 4 and v[-2:] in ("вич", "вна", "ова", "ич")),
        ]:
            if field not in ln or data[key]:
                continue
            if field == "имя" and "отчество" in ln:
                continue
            # Значение чаще всего НИЖЕ метки (i+1), реже выше (i-1)
            for idx in (i + 1, i + 2, i - 1, i - 2):
                if 0 <= idx < len(lines):
                    parts = [p for p in re.findall(r"[А-ЯЁа-яё\-]+", lines[idx]) if len(p) >= min_len]
                    if not parts:
                        continue
                    v = parts[-1] if (key == "Отчество" and len(parts) >= 2 and parts[-1].lower()[-2:] in ("вич", "вна", "ова", "ич")) else parts[0]
                    if min_len <= len(v) <= 50 and v.isalpha() and extra_check(v):
                        data[key] = v
                        break
    # ФИО — последний fallback: первая строка из 3 подряд кириллических слов (Фамилия Имя Отчество)
    _word = r"[А-ЯЁа-яё][А-ЯЁа-яё]{1,}"
    _skip = {"российская", "паспорт", "личный", "граждан", "код", "фамилия", "имя", "отчество", "дата", "место"}
    if not data["Фамилия"] or not data["Имя"]:
        best_fio = None
        for txt in (full_norm, full_text):
            for m in re.finditer(rf"({_word})\s+({_word})\s+({_word})", txt):
                w3, w1 = m.group(3).lower(), m.group(1).lower()
                if w3.endswith(("вич", "вна", "ич", "ова")) and w1 not in _skip:
                    best_fio = m
                    break
            if best_fio:
                break
        if not best_fio:
            for txt in (full_norm, full_text):
                best_fio = re.search(rf"({_word})\s+({_word})\s+({_word})", txt)
                if best_fio:
                    break
        if best_fio and (not data["Фамилия"] or not data["Имя"]):
            data["Фамилия"] = data["Фамилия"] or best_fio.group(1)
            data["Имя"] = data["Имя"] or best_fio.group(2)
            data["Отчество"] = data["Отчество"] or best_fio.group(3)
        # Имя Отчество — пара, где второе похоже на отчество
        # Fallback: 3 подряд строки = ФИО (ЦИЦАР, ФЕДОР, МИХАЙЛОВИЧ) — пропускаем дубликаты
        if (not data["Фамилия"] or not data["Имя"]) and len(lines) >= 3:
            cand = []
            for ln in lines[:25]:
                w = re.sub(r"[^\w\-]", "", ln).strip()
                if 2 <= len(w) <= 50 and w.isalpha() and w.lower() not in _skip and not re.match(r"^\d+$", w):
                    if cand and w.upper() == cand[-1].upper():
                        continue
                    cand.append(w)
                    if len(cand) >= 3 and cand[-1].lower()[-2:] in ("вич", "вна", "ова", "ич"):
                        data["Фамилия"] = data["Фамилия"] or cand[0]
                        data["Имя"] = data["Имя"] or cand[1]
                        data["Отчество"] = data["Отчество"] or cand[2]
                        break
        # Ультра-fallback: первые 3 уникальные строки с кириллицей = ФИО
        if (not data["Фамилия"] or not data["Имя"]) and len(lines) >= 3:
            seen = set()
            cand = []
            for ln in lines[:15]:
                w = re.sub(r"[^\w\-]", "", ln).strip()
                if 2 <= len(w) <= 40 and re.search(r"[А-Яа-яЁё]", w) and not w.isdigit() and w.lower() not in _skip:
                    wk = w.upper()
                    if wk not in seen:
                        seen.add(wk)
                        cand.append(w)
                    if len(cand) >= 3 and cand[-1].lower()[-2:] in ("вич", "вна", "ова", "ич"):
                        data["Фамилия"] = data["Фамилия"] or cand[0]
                        data["Имя"] = data["Имя"] or cand[1]
                        data["Отчество"] = data["Отчество"] or cand[2]
                        break
            if not data["Фамилия"] and len(cand) >= 3:
                data["Фамилия"] = cand[0]
                data["Имя"] = cand[1]
                data["Отчество"] = cand[2]
        skip_words = {"животный", "личный", "код", "граждан", "россий", "федера", "паспорт", "отдела"}
        if not data["Имя"] or not data["Отчество"]:
            for txt in (full_norm, full_text):
                for two_match in re.finditer(rf"({_word})\s+({_word})", txt):
                    w1, w2 = two_match.group(1).lower(), two_match.group(2).lower()
                    if w1 not in skip_words and w2 not in skip_words and len(w2) >= 4 and w2[-2:] in ("вич", "вна", "ова", "ев", "ин", "ич"):
                        data["Имя"] = data["Имя"] or two_match.group(1)
                        data["Отчество"] = data["Отчество"] or two_match.group(2)
                        break
                if data["Имя"] and data["Отчество"]:
                    break

    # ИНН — только 12 цифр (физлицо), не путать с серией паспорта (10 цифр)
    inn_match = re.search(r"\b(\d{12})\b", full_text)
    if inn_match:
        data["ИНН"] = inn_match.group(1)

    # Кем выдан — захватываем до "Дата выдачи" или конца
    issued_match = re.search(
        r"(?:паспорт\s+выдан|кем\s+выдан|выдан)\s*[:\s]*([А-Яа-яЁё0-9№\s,.\-/]+?)(?=дата\s+выдачи|код\s+подразделения|$)",
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

    # Адрес — приоритет: полный блок "Зарегистрирован ..." или сборка из полей
    addr_stop = r"(?:Семейное|Дети|Гражданство|Марки|Кем выдан|Паспорт выдан)"
    reg_full = re.search(
        r"(?:Зарегистрирован|зарегистрирован)\s*[:\s]*([А-Яа-яЁё0-9№\s,.\-/]+?)(?=" + addr_stop + r"|\n\n|$)",
        full_text,
        re.I | re.DOTALL,
    )
    if reg_full:
        val = re.sub(r"\s+", " ", reg_full.group(1).strip())
        if len(val) > 15:
            data["Адрес регистрации"] = val[:450]

    if not data["Адрес регистрации"]:
        addr_parts = []
        gor = re.search(r"(?:пункт|гор\.?|город|Гор\.)\s*[:\s]*([А-Яа-яЁё\-\s]+?)(?=\n|р-н|улица|ул\.|дом|д\.|$)", full_text, re.I)
        rn_before = re.search(r"([А-Яа-яЁё\-]{4,})\s+р-н", full_text)
        rn_after = re.search(r"р-н\s*[:\s]*([А-Яа-яЁё\-]+)", full_text, re.I)
        ul = re.search(r"(?:улица|ул\.?)\s*[:\s]*([А-Яа-яЁё0-9\s\-]+?)(?=\n|дом|д\.|корп|кв|$)", full_text, re.I)
        dom = re.search(r"(?:дом|д\.)\s*[:\s]*(\d+[\s\-]*(?:корп\.?\s*[\-\d]*)?)", full_text, re.I)
        kv = re.search(r"(?:кв\.?|квартира)\s*[:\s]*(\d+)", full_text, re.I)
        if gor:
            addr_parts.append("г. " + gor.group(1).strip())
        if rn_before:
            addr_parts.append("р-н " + rn_before.group(1).strip())
        elif rn_after:
            addr_parts.append("р-н " + rn_after.group(1).strip())
        if ul:
            addr_parts.append(ul.group(1).strip())
        if dom:
            d = re.sub(r"\s+", " ", dom.group(1).strip())
            addr_parts.append("д. " + d)
        if kv:
            addr_parts.append("кв. " + kv.group(1).strip())
        if addr_parts:
            data["Адрес регистрации"] = ", ".join(addr_parts)[:450]
    if not data["Адрес регистрации"]:
        for pat in [
            r"(?:место\s+жительства|адрес\s+регистрации)\s*[:\s]*([А-Яа-яЁё0-9\s,.\-/]+?)(?=\n\n|" + addr_stop + r"|$)",
            r"(?:гор\.|город)\s+([А-Яа-яЁё0-9\s,.\-/]+?)(?=р-н|улица|дом|$)",
        ]:
            m = re.search(pat, full_text, re.I | re.DOTALL)
            if m:
                val = re.sub(r"\s+", " ", m.group(1).strip())[:400]
                if len(val) > 8 and not val.replace(" ", "").replace(".", "").replace(",", "").isdigit():
                    data["Адрес регистрации"] = val
                    break

    return data


def process_passport_image(image_path: str, index: int = 1) -> dict:
    """
    Обработать одно изображение паспорта и вернуть данные для Excel
    """
    ocr_text = extract_text_from_image(image_path)
    data = parse_passport_data(ocr_text)
    if not data["Серия и номер паспорта"]:
        data["Серия и номер паспорта"] = _extract_series_from_vertical_red(image_path)
    # При пустых ключевых полях — сохраняем последний OCR для отладки
    if (not data["Фамилия"] or not data["Серия и номер паспорта"]) and ocr_text:
        import tempfile
        p = Path(tempfile.gettempdir()) / "ocr_last_empty.txt"
        p.write_text(f"=== {image_path} ===\n{ocr_text}\n\n=== PARSED ===\n{data}", encoding="utf-8")
    data_with_num = {"№ п/п": str(index), **data}
    if ocr_text and not any(data.values()) and not _is_garbage(ocr_text):
        data_with_num["Примечания"] = ocr_text.strip()[:500].replace("\n", " ")
    return data_with_num


def _merge_passport_data(base: dict, extra: dict) -> dict:
    """Объединить данные — extra дополняет пустые поля base"""
    merged = base.copy()
    for k, v in extra.items():
        if k == "№ п/п":
            continue
        if v and (not merged.get(k) or (k in ("Адрес регистрации", "Кем выдан") and len(str(v)) > len(str(merged.get(k, ""))))):
            merged[k] = v
    return merged


def _process_one_person(parent: Path, images: list[Path], person_idx: int) -> dict:
    """Обработка одного человека (подпапки) — для параллельного выполнения"""
    texts = []
    if len(images) > 1 and MAX_WORKERS > 1:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(images))) as ex:
            texts = list(ex.map(lambda p: extract_text_from_image(str(p)), images))
    else:
        for img_path in images:
            texts.append(extract_text_from_image(str(img_path)))
    combined_ocr = "\n".join(t for t in texts if t).strip()
    if combined_ocr:
        data = parse_passport_data(combined_ocr)
    else:
        data = {col: "" for col in EXCEL_COLUMNS[1:]}
    if not data["Серия и номер паспорта"]:
        for img_path in images:
            s = _extract_series_from_vertical_red(str(img_path))
            if s:
                data["Серия и номер паспорта"] = s
                break
    data_with_num = {"№ п/п": str(person_idx), **data}
    if combined_ocr and not any(data.values()):
        data_with_num["Примечания"] = combined_ocr[:500].replace("\n", " ")
    if (not data["Фамилия"] or not data["Серия и номер паспорта"]) and combined_ocr:
        import tempfile
        p = Path(tempfile.gettempdir()) / "ocr_last_empty.txt"
        p.write_text(f"=== person {person_idx} ===\n{combined_ocr[:2000]}\n\n=== PARSED ===\n{data}", encoding="utf-8")
    return data_with_num


def process_images_from_folder(folder_path: str) -> list[dict]:
    """
    Обработка: в каждой подпапке 2 файла (разворот + прописка) = 1 человек.
    OCR объединяется — адрес с прописки попадёт в строку.
    Параллелизм: MAX_WORKERS (по умолчанию 4) — при увеличенном CPU/RAM можно повысить.
    """
    folder = Path(folder_path)
    image_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}

    by_parent: dict[Path, list[Path]] = {}
    for f in folder.rglob("*"):
        if f.is_file() and f.suffix.lower() in image_extensions:
            by_parent.setdefault(f.parent, []).append(f)

    parents_sorted = sorted(by_parent.keys(), key=lambda p: str(p))
    if not parents_sorted:
        return []

    if MAX_WORKERS <= 1:
        results = []
        for idx, parent in enumerate(parents_sorted, 1):
            results.append(_process_one_person(parent, sorted(by_parent[parent]), idx))
        return results

    # Параллельная обработка — используем CPU/RAM
    results_by_idx: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {
            ex.submit(_process_one_person, p, sorted(by_parent[p]), i): i
            for i, p in enumerate(parents_sorted, 1)
        }
        for future in as_completed(futures):
            results_by_idx[futures[future]] = future.result()

    return [results_by_idx[i] for i in range(1, len(parents_sorted) + 1)]
