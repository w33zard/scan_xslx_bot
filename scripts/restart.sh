#!/bin/bash
# Перезапуск бота на сервере (запускать на сервере после git pull)
# ssh root@194.67.88.36 "cd /opt/scan_xslx_bot && git pull && bash scripts/restart.sh"

set -e
echo "==> Обновление и перезапуск scan_xslx_bot..."

if command -v systemctl &>/dev/null && systemctl list-units | grep -q scan-xslx-bot; then
    sudo systemctl restart scan-xslx-bot
    echo "==> systemctl restart scan-xslx-bot OK"
elif [ -f docker-compose.yml ] || [ -f compose.yml ]; then
    docker compose pull 2>/dev/null || true
    docker compose up -d --build
    echo "==> docker compose up OK"
else
    echo "Не найден systemd или docker-compose"
    exit 1
fi
