#!/bin/bash
cd "$(dirname "$0")"
set -a
[ -f .env ] && . ./.env
set +a
. venv/bin/activate
exec python main.py
