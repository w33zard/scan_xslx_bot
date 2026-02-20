#!/bin/bash
# Полная проверка сервера — ключи, версия, зависимости
# Запуск: ssh root@194.67.88.36 "cd /opt/scan_xslx_bot && bash scripts/check_server.sh"

cd /opt/scan_xslx_bot 2>/dev/null || { echo "Папка /opt/scan_xslx_bot не найдена"; exit 1; }

echo "=========================================="
echo "  ПРОВЕРКА scan_xslx_bot"
echo "=========================================="
echo ""

# 1. Git — последняя версия
echo "1. Git:"
git fetch origin 2>/dev/null || true
LOCAL=$(git rev-parse HEAD 2>/dev/null)
REMOTE=$(git rev-parse origin/main 2>/dev/null)
if [ "$LOCAL" = "$REMOTE" ]; then
    echo "   ✅ Код актуален (commit: ${LOCAL:0:7})"
else
    echo "   ⚠️  НЕ АКТУАЛЬНО. Локально: ${LOCAL:0:7}, на GitHub: ${REMOTE:0:7}"
    echo "   Выполните: git pull"
fi
echo ""

# 2. .env — ключи
echo "2. Переменные окружения (.env):"
if [ ! -f .env ]; then
    echo "   ❌ Файл .env НЕ НАЙДЕН"
    echo "   Создайте: cp .env.example .env && nano .env"
else
    source .env 2>/dev/null
    [ -n "$TELEGRAM_BOT_TOKEN" ] && [ "$TELEGRAM_BOT_TOKEN" != "your_token_here" ] && echo "   ✅ TELEGRAM_BOT_TOKEN задан" || echo "   ❌ TELEGRAM_BOT_TOKEN пустой или не задан"
    [ -n "$YANDEX_VISION_API_KEY" ] && echo "   ✅ YANDEX_VISION_API_KEY задан" || echo "   ⚠️  YANDEX_VISION_API_KEY не задан (будет только Tesseract)"
    [ -n "$ADMIN_IDS" ] && echo "   ✅ ADMIN_IDS = $ADMIN_IDS" || echo "   ADMIN_IDS по умолчанию"
fi
echo ""

# 3. venv и зависимости
echo "3. Python venv:"
if [ -f venv/bin/python ]; then
    echo "   ✅ venv есть"
    venv/bin/python -c "import telegram, pytesseract, cv2" 2>/dev/null && echo "   ✅ Основные пакеты OK" || echo "   ⚠️  Проверьте: venv/bin/pip list"
else
    echo "   ❌ venv НЕ НАЙДЕН"
    echo "   Создайте: python3 -m venv venv && venv/bin/pip install -r requirements.txt"
fi
echo ""

# 4. Tesseract
echo "4. Tesseract OCR:"
if command -v tesseract &>/dev/null; then
    tesseract --version 2>&1 | head -1
    echo "   ✅ Tesseract установлен"
else
    echo "   ❌ Tesseract НЕ УСТАНОВЛЕН"
    echo "   Установите: apt-get install -y tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng"
fi
echo ""

# 5. systemd сервис
echo "5. Сервис scan-xslx-bot:"
if systemctl is-active --quiet scan-xslx-bot 2>/dev/null; then
    echo "   ✅ Запущен"
    systemctl status scan-xslx-bot --no-pager 2>/dev/null | head -3
else
    echo "   ❌ НЕ запущен"
    echo "   Запустите: systemctl start scan-xslx-bot"
fi
echo ""

# 6. Быстрый тест Python
echo "6. Тест импорта:"
venv/bin/python -c "
from ocr_extractor import parse_passport_data
d = parse_passport_data('ЦИЦАР ФЕДОР 4008 595794')
print('   Парсинг:', 'OK' if d.get('Серия и номер паспорта') else 'FAIL')
" 2>/dev/null && echo "   ✅ Импорты работают" || echo "   ❌ Ошибка импорта"
echo ""

echo "=========================================="
echo "  Для перезапуска: systemctl restart scan-xslx-bot"
echo "  Команда в боте: /diagnose"
echo "=========================================="
