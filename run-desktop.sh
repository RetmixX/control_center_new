#!/usr/bin/env sh
# Desktop-версия (Linux/macOS). Первый запуск создаёт venv-desktop.
cd "$(dirname "$0")"
[ -d venv-desktop ] || { python3 -m venv venv-desktop && ./venv-desktop/bin/pip install -q -r requirements-desktop.txt; }
exec ./venv-desktop/bin/python -m controlcenter.desktop --dir . "$@"
