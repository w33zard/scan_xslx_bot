#!/usr/bin/env python3
"""Test OCR on a single image"""
import sys
from ocr_extractor import extract_text_from_image, parse_passport_data

path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/test_passport.jpg"
text = extract_text_from_image(path)
print("=== OCR TEXT (first 800 chars) ===")
print(repr(text[:800]) if text else "EMPTY")
print()
print("=== PARSED ===")
print(parse_passport_data(text))
