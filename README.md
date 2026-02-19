# Telegram-бот: извлечение данных из сканов паспортов

Бот принимает ZIP-архив или фото паспортов и возвращает Excel-файл с извлечёнными данными.

## Установка

### 1. Tesseract OCR

Скачайте и установите Tesseract с поддержкой русского:
- Windows: https://github.com/UB-Mannheim/tesseract/wiki
- При установке отметьте языковые пакеты `Russian` и `English`

### 2. Зависимости Python

```bash
pip install -r requirements.txt
```

### 3. Токен бота и Yandex Vision (рекомендуется)

1. Создайте бота в [@BotFather](https://t.me/BotFather)
2. Для **полного распознавания** паспортов добавьте Yandex Vision API:
   - [Yandex Cloud Console](https://console.cloud.yandex.ru/) → Vision → API-ключ
   - Бесплатно: 1000 запросов/мес
3. В `.env` укажите:
   - `TELEGRAM_BOT_TOKEN` — токен от BotFather
   - `YANDEX_VISION_API_KEY` — ключ Yandex Vision (для полного распознавания паспортов)

## Запуск

```bash
python bot.py
```

## Использование

1. **ZIP-архив** — отправьте боту ZIP с изображениями паспортов (.jpg, .png и т.д.)
2. **Фото** — отправьте несколько фото паспортов, затем команду `/готово`

Бот вернёт Excel с колонками:
- № п/п, Фамилия, Имя, Отчество
- Дата рождения, Место рождения
- Серия и номер паспорта, Дата выдачи, Кем выдан
- ИНН, Адрес регистрации, Примечания

## Формат Excel

Если нужен другой набор колонок, измените `EXCEL_COLUMNS` в `ocr_extractor.py` и парсинг в `parse_passport_data()`.
