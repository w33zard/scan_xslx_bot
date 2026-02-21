# Telegram-бот: извлечение данных из паспортов РФ

Бот принимает изображение/скан/PDF или ZIP-архив паспортов и возвращает **структурированный JSON** + Excel.

## Структура проекта

```
project/
  main.py                 # Точка входа
  bot/
    handlers.py           # document, photo, /ready, /ocr_raw
    config.py             # .env
    utils_files.py
  passport_ocr/
    pipeline.py           # Главный пайплайн
    ingest.py             # Приём, нормализация (PDF → images)
    preprocess.py         # Deskew, document detection, enhance
    classify.py           # main_spread / registration
    detect.py             # Серия/номер из вертикальной полосы
    ocr_engines/          # Paddle, Tesseract, EasyOCR, Yandex
    parse.py              # Извлечение полей
    validate.py           # Валидация форматов
    schemas.py            # PassportResult, FieldValue
  ml/
    README_TRAINING.md    # План обучения
    augmentations.py
    infer.py
  tests/
  requirements.txt
  .env.example
```

## Установка

### 1. Tesseract OCR

- **Linux**: `apt-get install tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng`
- **Windows**: [tesseract/wiki](https://github.com/UB-Mannheim/tesseract/wiki) — выберите русский и английский

### 2. Зависимости

```bash
pip install -r requirements.txt
```

### 3. .env

Скопируйте `.env.example` в `.env` и укажите:

- `TELEGRAM_BOT_TOKEN`
- `ADMIN_IDS` (через запятую)
- `OCR_ENGINE` — tesseract | yandex | easyocr | paddle
- `YANDEX_VISION_API_KEY` — при OCR_ENGINE=yandex

## Запуск

```bash
python main.py
```

Или через run.sh / Docker.

## Использование

1. **Фото** — отправьте фото паспорта (или несколько), затем `/ready`
2. **Документ** — отправьте JPG/PNG/PDF (один файл)
3. **ZIP** — архив с изображениями → Excel + JSON

Бот вернёт краткое резюме полей + **JSON-файл** и при необходимости Excel.

## Формат JSON

```json
{
  "doc_type": "passport_rf_internal",
  "page_type": "main_spread",
  "fields": {
    "surname": {"value": "ИВАНОВ", "confidence": 0.9, "source": "ocr"},
    "name": {"value": "ПЕТР", "confidence": 0.9, "source": "ocr"},
    "passport_series": {"value": "4008", "confidence": 0.85, "source": "ocr"},
    "passport_number": {"value": "595794", "confidence": 0.85, "source": "ocr"}
  },
  "checks": {...},
  "errors": [],
  "debug": {...}
}
```

## Тесты

```bash
python -m pytest tests/ -v
```

## Обучение

См. `ml/README_TRAINING.md` — план дообучения OCR и NER на паспортах РФ.
