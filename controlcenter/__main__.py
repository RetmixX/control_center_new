"""python -m controlcenter            — CLI/серверная версия
python -m controlcenter.desktop    — desktop-версия (окно, нужен PySide6)"""
from .cli import main

if __name__ == "__main__":
    main()
