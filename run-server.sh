#!/usr/bin/env sh
# CLI/серверная версия (Linux/macOS). Первый запуск создаёт venv.
cd "$(dirname "$0")"
[ -d venv ] || { python3 -m venv venv && ./venv/bin/pip install -q -r requirements.txt; }
exec ./venv/bin/python -m controlcenter --dir . "$@"
