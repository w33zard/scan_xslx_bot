#!/usr/bin/env python3
"""Test Yandex Vision API"""
import base64
import os
import sys

api_key = os.environ.get("YANDEX_VISION_API_KEY")
if not api_key:
    print("YANDEX_VISION_API_KEY not set")
    sys.exit(1)

path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/test_pass.jpg"
if not os.path.exists(path):
    print(f"File not found: {path}")
    sys.exit(1)

try:
    import requests
    import cv2
    img = cv2.imread(path)
    if img is None:
        print("Cannot read image")
        sys.exit(1)
    h, w = img.shape[:2]
    max_side = 1200
    if max(h, w) > max_side:
        scale = max_side / max(h, w)
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    print(f"Image size: {len(buf)} bytes (resized from original)")
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
    print("Calling Yandex Vision API...")
    r = requests.post(url, json=body, headers=headers, timeout=30)
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text[:500]}...")
    r.raise_for_status()
    data = r.json()
    texts = []
    for res in data.get("results", []):
        for item in res.get("results", []):
            td = item.get("textDetection") or item.get("textAnnotation") or {}
            for page in td.get("pages", []):
                for block in page.get("blocks", []):
                    for line in block.get("lines", []):
                        t = line.get("text") or " ".join(w.get("text", "") for w in line.get("words", []))
                        if t:
                            texts.append(t)
    print("\n--- Extracted text ---")
    print("\n".join(texts)[:1500])
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
