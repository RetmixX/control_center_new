"""Сборка desktop-версии в папку dist/ControlCenter (PyInstaller).
Запускать на той ОС, под которую нужна сборка (exe собирается на Windows):

    pip install -r requirements-desktop.txt pyinstaller
    python build/build_desktop.py

Рядом с ControlCenter(.exe) копируются config/, points/, logs/ — как в версии 2.0.
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sep = ";" if os.name == "nt" else ":"
entry = os.path.join("build", "desktop_entry.py")
with open(entry, "w", encoding="utf-8") as f:
    f.write("import sys\nfrom controlcenter.desktop.app import main\nsys.exit(main())\n")
cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", "ControlCenter",
       "--paths", ROOT,
       "--add-data", f"{os.path.join(ROOT, 'controlcenter', 'static')}{sep}controlcenter/static",
       "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.Qt3DCore",
       "--exclude-module", "PySide6.QtQuick", "--exclude-module", "PySide6.QtQml",
       "--exclude-module", "PySide6.QtMultimedia", "--exclude-module", "PySide6.QtCharts",
       "--distpath", "dist", "--workpath", os.path.join("build", "work"), "--specpath", "build", os.path.join(ROOT, entry)]
subprocess.check_call(cmd)
dst = os.path.join("dist", "ControlCenter")
for d in ("config", "points"):
    shutil.copytree(d, os.path.join(dst, d), dirs_exist_ok=True)
os.makedirs(os.path.join(dst, "logs"), exist_ok=True)
print(f"Готово: {os.path.abspath(dst)}")
