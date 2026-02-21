# -*- coding: utf-8 -*-
"""
Извлечение серии/номера из вертикальной полосы (красные цифры справа в паспорте)
"""
import os
import re
from typing import Optional

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

try:
    import pytesseract
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False


def extract_series_from_vertical(
    image_path: str,
    image_array=None,
) -> Optional[tuple[str, str, float]]:
    """
    Серия и номер из правой вертикальной полосы.
    Возвращает (series_4digits, number_6digits, confidence) или None.
    """
    if not HAS_CV2 or not HAS_TESSERACT:
        return None

    if image_array is not None:
        img = image_array
    else:
        img = cv2.imread(image_path)
    if img is None:
        return None

    def _try_ocr(roi_img, rotate=True, psm=6):
        try:
            img_use = cv2.rotate(roi_img, cv2.ROTATE_90_CLOCKWISE) if rotate else roi_img
            img_use = cv2.resize(img_use, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            text = pytesseract.image_to_string(
                img_use, config=f"--psm {psm} -c tessedit_char_whitelist=0123456789 "
            )
            digits = re.sub(r"\D", "", text)
            if len(digits) == 10 and not digits[:4].startswith(("19", "20")):
                return digits[:4], digits[4:], 0.85
            for i in range(max(0, len(digits) - 9)):
                chunk = digits[i : i + 10]
                if not chunk[:4].startswith(("19", "20")):
                    return chunk[:4], chunk[4:], 0.8
        except Exception:
            pass
        return None

    def _process_roi(roi):
        if roi.size == 0:
            return None
        b, g, r = cv2.split(roi)
        red_mask = (r.astype(float) > 80) & (r > g * 1.1) & (r > b * 1.1)
        mono = 255 - (red_mask.astype("uint8") * 255)
        _, binary1 = cv2.threshold(mono, 200, 255, cv2.THRESH_BINARY_INV)
        res = _try_ocr(binary1)
        if res:
            return res
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        _, binary3 = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return _try_ocr(binary3)

    rots = [
        img,
        cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE),
        cv2.rotate(img, cv2.ROTATE_180),
        cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE),
    ]

    for rot_img in rots:
        rw = rot_img.shape[1]
        for frac in (0.88, 0.85, 0.80, 0.75, 0.70):
            x0 = int(rw * frac)
            roi = rot_img[:, x0:].copy()
            if roi.size > 0:
                res = _process_roi(roi)
                if res:
                    return res
        for frac in (0.15, 0.20, 0.25):
            x1 = int(rw * frac)
            roi = rot_img[:, :x1].copy()
            if roi.size > 0:
                res = _process_roi(roi)
                if res:
                    return res

    return None
