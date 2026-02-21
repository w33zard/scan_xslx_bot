# -*- coding: utf-8 -*-
"""
B. Preprocess — авто-поворот, deskew, обнаружение документа, улучшение
"""
import time
from typing import Optional

import numpy as np

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


def _ensure_cv2():
    if not HAS_CV2:
        raise ImportError("opencv-python required for preprocessing")


def deskew_simple(img: np.ndarray) -> np.ndarray:
    """Простой deskew по контурам (Hough-подобный подход)"""
    _ensure_cv2()
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img.copy()
    gray = cv2.bitwise_not(gray)
    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thresh > 0))
    if len(coords) < 100:
        return img
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = 90 + angle
    elif angle > 45:
        angle = angle - 90
    if abs(angle) < 0.5:
        return img
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def find_document_contour(img: np.ndarray) -> Optional[np.ndarray]:
    """Найти контур документа (прямоугольник)"""
    _ensure_cv2()
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img.copy()
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(gray, 75, 200)
    contours, _ = cv2.findContours(edged, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:5]
    for c in contours:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4 and cv2.contourArea(approx) > img.size * 0.1:
            return approx
    return None


def perspective_transform(img: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Выравнивание по 4 углам"""
    _ensure_cv2()
    rect = _order_points(pts)
    (tl, tr, br, bl) = rect
    w1 = np.linalg.norm(tr - tl)
    w2 = np.linalg.norm(br - bl)
    h1 = np.linalg.norm(bl - tl)
    h2 = np.linalg.norm(br - tr)
    max_w = max(int(w1), int(w2))
    max_h = max(int(h1), int(h2))
    dst = np.array([
        [0, 0], [max_w - 1, 0], [max_w - 1, max_h - 1], [0, max_h - 1]
    ], dtype=np.float32)
    M = cv2.getPerspectiveTransform(rect.astype(np.float32), dst)
    return cv2.warpPerspective(img, M, (max_w, max_h))


def _order_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def enhance(img: np.ndarray) -> np.ndarray:
    """Улучшение: denoise, CLAHE, sharpen (аккуратно)"""
    _ensure_cv2()
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img.copy()
    gray = cv2.fastNlMeansDenoising(gray, None, 5, 7, 21)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    kernel = np.array([[-0.5, -0.5, -0.5], [-0.5, 5, -0.5], [-0.5, -0.5, -0.5]])
    gray = cv2.filter2D(gray, -1, kernel)
    return gray


def preprocess_pipeline(
    img: np.ndarray,
    do_deskew: bool = True,
    do_detect_doc: bool = True,
    do_enhance: bool = True,
) -> tuple[np.ndarray, dict]:
    """
    Полный пайплайн предобработки.
    Возвращает (clean_image, preprocess_info).
    """
    _ensure_cv2()
    info = {}
    t0 = time.perf_counter()
    out = img.copy()

    if do_detect_doc:
        contour = find_document_contour(out)
        if contour is not None:
            out = perspective_transform(out, contour.reshape(4, 2))
            info["document_detected"] = True
        else:
            info["document_detected"] = False

    if do_deskew:
        out = deskew_simple(out)
        info["deskew"] = True

    if do_enhance:
        out = enhance(out)
        if len(img.shape) == 3:
            out = cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)
        info["enhanced"] = True

    info["time_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return out, info
