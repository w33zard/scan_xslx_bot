# -*- coding: utf-8 -*-
"""Утилиты для работы с файлами в боте"""
import os
import tempfile
import uuid
from pathlib import Path


def safe_temp_path(prefix: str = "passport", suffix: str = ".jpg") -> str:
    """Безопасный путь во временной директории"""
    base = os.environ.get("TEMP_DIR") or tempfile.gettempdir()
    path = Path(base) / f"{prefix}_{uuid.uuid4().hex[:12]}{suffix}"
    return str(path)


def cleanup_path(path: str) -> None:
    """Удалить файл (в finally для гарантии)"""
    if not path:
        return
    try:
        if os.path.exists(path):
            os.unlink(path)
    except Exception:
        pass
