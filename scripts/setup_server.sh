#!/bin/bash
# Установка зависимостей на сервере (запускать от root)
# ssh root@SERVER "bash -s" < scripts/setup_server.sh

set -e
echo "==> Установка Tesseract и языков..."
apt-get update
apt-get install -y tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng 2>/dev/null || true

echo "==> Проверка Tesseract..."
tesseract --version || echo "Tesseract не найден"

echo "==> Готово. Перезапустите бота: systemctl restart scan-xslx-bot"
