#!/bin/bash
# Скрипт первичной настройки на сервере (запускать на сервере)
set -e

REPO_URL="${1:-https://github.com/YOUR_USERNAME/scan_xslx_bot.git}"
DIR="/root/scan_xslx_bot"

echo "==> Установка Docker..."
apt-get update
apt-get install -y docker.io docker-compose-v2 git

systemctl enable docker
systemctl start docker

echo "==> Клонирование репозитория..."
mkdir -p "$(dirname $DIR)"
if [ -d "$DIR" ]; then
  cd "$DIR" && git pull
else
  git clone "$REPO_URL" "$DIR"
  cd "$DIR"
fi

echo "==> Создание .env..."
if [ ! -f .env ]; then
  cp .env.example .env
  echo "⚠️  Отредактируйте .env и укажите TELEGRAM_BOT_TOKEN: nano $DIR/.env"
else
  echo "Файл .env уже существует"
fi

echo "==> Запуск контейнера..."
docker compose up -d --build

echo "==> Готово! Бот запущен."
