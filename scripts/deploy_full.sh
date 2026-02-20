#!/bin/bash
# Полный деплой: обновление, зависимости, перезапуск
# ssh root@194.67.88.36 "cd /opt/scan_xslx_bot && bash scripts/deploy_full.sh"

set -e
cd /opt/scan_xslx_bot

echo "==> 1. Git pull..."
git pull origin main

echo "==> 2. Tesseract..."
apt-get update -qq
apt-get install -y tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng 2>/dev/null || true

echo "==> 3. venv и зависимости..."
if [ ! -d venv ]; then
    python3 -m venv venv
fi
./venv/bin/pip install -q -r requirements.txt

echo "==> 4. .env..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "⚠️  Отредактируйте .env: nano /opt/scan_xslx_bot/.env"
fi

echo "==> 5. Перезапуск..."
systemctl restart scan-xslx-bot

echo "==> 6. Статус..."
sleep 2
systemctl status scan-xslx-bot --no-pager | head -5

echo ""
echo "✅ Готово. Проверьте бота: /diagnose"
