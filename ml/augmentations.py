# -*- coding: utf-8 -*-
"""Аугментации для обучения OCR на паспортах"""
import cv2
import numpy as np
from typing import Tuple


def add_blur(img: np.ndarray, k: int = 3) -> np.ndarray:
    return cv2.GaussianBlur(img, (k, k), 0)


def add_noise(img: np.ndarray, sigma: float = 10) -> np.ndarray:
    noise = np.random.normal(0, sigma, img.shape).astype(np.float32)
    out = img.astype(np.float32) + noise
    return np.clip(out, 0, 255).astype(np.uint8)


def add_rotation(img: np.ndarray, angle: float) -> np.ndarray:
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_REPLICATE)


def adjust_brightness(img: np.ndarray, factor: float) -> np.ndarray:
    out = img.astype(np.float32) * factor
    return np.clip(out, 0, 255).astype(np.uint8)


def jpeg_artifacts(img: np.ndarray, quality: int = 70) -> np.ndarray:
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)
