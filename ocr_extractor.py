"""
Извлечение данных из сканов паспортов с помощью OCR
Поддержка: Yandex Vision API (приоритет) и Tesseract (fallback)
Параллельная обработка при наличии CPU/RAM — MAX_WORKERS в .env
"""
import base64
import os
import re

from parse_passport import parse_passport_data
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import numpy as np
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
        diff = cv2.subtract(r, np.maximum(g, b))
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

        def _collect_all_text(obj, out: list):
            """Рекурсивно собрать все строки с кириллицей/цифрами из JSON"""
            if isinstance(obj, str) and len(obj) > 2:
                if re.search(r"[А-Яа-яЁё0-9]", obj):
                    out.append(obj.strip())
            elif isinstance(obj, dict):
                for v in obj.values():
                    _collect_all_text(v, out)
            elif isinstance(obj, list):
                for v in obj:
                    _collect_all_text(v, out)

        def _extract_from_response(data) -> str:
            texts = []
            full_yt = ""
            results = data.get("results") or data.get("result") or []
            if not isinstance(results, list):
                results = [results] if results else []
            if not results and data.get("error"):
                fallback = []
                _collect_all_text(data, fallback)
                return "\n".join(fallback[:200]) if fallback else ""
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
            if not out:
                fallback = []
                _collect_all_text(data, fallback)
                out = "\n".join(fallback[:200]) if fallback else ""
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
                try:
                    from PIL import Image
                    import numpy as np
                    pil_img = Image.open(image_path).convert("RGB")
                    img = np.array(pil_img)
                    img = img[:, :, ::-1].copy()
                except Exception:
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
    try:
        vert = _extract_series_from_vertical_red(image_path)
        if vert:
            return (text + "\n" + vert).strip() if text else vert
    except Exception:
        pass
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


# parse_passport_data импортируется из parse_passport.py (чистая логика с нуля)


def process_passport_image(image_path: str, index: int = 1) -> dict:
    """
    Обработать одно изображение паспорта и вернуть данные для Excel
    """
    ocr_text = extract_text_from_image(image_path)
    data = parse_passport_data(ocr_text)
    if not data["Серия и номер паспорта"]:
        data["Серия и номер паспорта"] = _extract_series_from_vertical_red(image_path)
    # Сохраняем OCR для отладки
    _bad = (
        (not data["Фамилия"] or not data["Серия и номер паспорта"]) or
        (data.get("Имя") or "").lower() in ("выдан", "тп") or
        (data.get("Отчество") or "").lower() in ("выдан", "тп") or
        ("77 87" in (data.get("Серия и номер паспорта") or ""))
    )
    if _bad and ocr_text:
        import tempfile
        for p in [Path(__file__).parent / "debug_ocr_last.txt", Path(tempfile.gettempdir()) / "ocr_last_empty.txt"]:
            try:
                p.write_text(f"=== {image_path} ===\n{ocr_text}\n\n=== PARSED ===\n{data}", encoding="utf-8")
                break
            except Exception:
                pass
    data_with_num = {"№ п/п": str(index), **data}
    if ocr_text and not any(data.values()) and not _is_garbage(ocr_text):
        data_with_num["Примечания"] = ocr_text.strip()[:500].replace("\n", " ")
    return data_with_num


# (старый код парсера удалён — см. parse_passport.py)
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
    _bad = (
        (not data["Фамилия"] or not data["Серия и номер паспорта"]) or
        (data.get("Имя") or "").lower() in ("выдан", "тп") or
        (data.get("Отчество") or "").lower() in ("выдан", "тп") or
        ("77 87" in (data.get("Серия и номер паспорта") or ""))
    )
    if _bad and combined_ocr:
        import tempfile
        for p in [Path(__file__).parent / "debug_ocr_last.txt", Path(tempfile.gettempdir()) / "ocr_last_empty.txt"]:
            try:
                p.write_text(f"=== person {person_idx} ===\n{combined_ocr[:3000]}\n\n=== PARSED ===\n{data}", encoding="utf-8")
                break
            except Exception:
                pass
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
