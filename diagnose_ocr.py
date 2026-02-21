#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Диагностика OCR: запустить на изображениях паспорта, сохранить OCR и разбор.
Использование: python diagnose_ocr.py photo1.jpg photo2.jpg
Результат: diagnose_result.txt
"""
import sys
from pathlib import Path

def main():
    if len(sys.argv) < 2:
        print("Usage: python diagnose_ocr.py image1.jpg [image2.jpg ...]")
        print("Result saved to diagnose_result.txt")
        return 1

    from ocr_extractor import extract_text_from_image, process_images_from_folder
    from parse_passport import parse_passport_data

    paths = [p for p in sys.argv[1:] if Path(p).exists()]
    if not paths:
        print("No valid image paths")
        return 1

    lines = []
    if len(paths) == 1:
        ocr = extract_text_from_image(paths[0])
        data = parse_passport_data(ocr)
        vert = getattr(
            __import__("ocr_extractor", fromlist=["_extract_series_from_vertical_red"]),
            "_extract_series_from_vertical_red",
        )(paths[0])
        if vert:
            data["Серия и номер паспорта"] = vert
        lines.append(f"=== IMAGE: {paths[0]} ===\n")
        lines.append(f"OCR ({len(ocr)} chars):\n{ocr[:2000]}\n\n")
        lines.append("PARSED:\n")
        for k, v in data.items():
            lines.append(f"  {k}: {v}\n")
    else:
        import tempfile
        import shutil
        folder = tempfile.mkdtemp()
        try:
            for i, p in enumerate(paths):
                dst = Path(folder) / f"page_{i}.jpg"
                shutil.copy(p, dst)
            results = process_images_from_folder(folder)
            for i, p in enumerate(paths):
                ocr = extract_text_from_image(str(Path(folder) / f"page_{i}.jpg"))
                lines.append(f"=== IMAGE {i+1}: {p} ===\n")
                lines.append(f"OCR ({len(ocr)} chars):\n{ocr[:1500]}\n\n")
            lines.append("=== COMBINED RESULT ===\n")
            for k, v in (results[0] or {}).items():
                lines.append(f"  {k}: {v}\n")
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    out = Path(__file__).parent / "diagnose_result.txt"
    out.write_text("".join(lines), encoding="utf-8")
    print(f"Saved to {out}")
    print("\n--- OCR preview ---")
    print(lines[1][:500] if len(lines) > 1 else lines[0][:500])
    return 0

if __name__ == "__main__":
    sys.exit(main())
