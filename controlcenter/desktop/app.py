"""Desktop-версия ControlCenter (PySide6 / Qt 6). Работает на Windows, Linux, macOS.

  python -m controlcenter.desktop [--dir ПАПКА] [--web 8080]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QPalette
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
                               QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from .. import __version__
from ..errors import CCError
from ..runtime import ControllerThread

# форма Manual Control: группы полей и какие из них показывать для каждого типа устройства
FORM_GROUPS = {
    "robot": ("Манипулятор", ["X", "Y", "T", "G", "V", "D0", "N"]),
    "leds": ("Лампы", ["L1", "L2", "L3", "L4"]),
    "display": ("Дисплей", []),
    "threshold": ("Порог срабатывания", ["P"]),
    "conveyor": ("Конвейер", ["N", "P"]),
    "camera": ("Смарт-камера", ["G"]),
}
FORMS = {"M": ["robot"], "T": ["leds"], "R": ["leds", "display"], "B1": ["threshold"], "C": ["conveyor"],
         "SC": ["camera"]}
KEYNAMES = {"M": "Манипулятор", "T": "Светофор",
            "R": "Удалённый терминал", "B1": "ИК-барьер", "BR": "Сканер штрихкода", "SC": "Смарт-камера", "C": "Конвейер",
            "F1": "Мобильный робот", "C1": "AR-камера"}
HINTS = {
    "robot": "X — angel, Y — x, G — z, T — pov_gripper; V — насос/схват 0/1; D0 — скорость %; N — номер команды.\n"
             "В режиме позиций X — номер точки из points/.",
    "lamp": "Светофор: L1..L4 — светодиоды (цвета задаются в settings.json → lamp_mapping).",
    "terminal": "Терминал: L1..L4 — светодиоды. Текст — до 20 символов на строку; пусто — дисплей не менять, "
                "/clear — очистить.",
    "barrier": "ИК-барьер: P — порог срабатывания для всех датчиков, см (1..500); 0 — не менять.",
}
LOG_COLORS = {"error": "#f85149", "nodered": "#58a6ff", "equipment": "#3fb950", "event": "#9aa0a6"}
LOG_TABS = [("all", "Все"), ("nodered", "Из Node-RED"), ("equipment", "На оборудование"),
            ("error", "Ошибки"), ("event", "События")]


def dark_palette() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.Window, QColor(53, 53, 53))
    p.setColor(QPalette.WindowText, Qt.white)
    p.setColor(QPalette.Base, QColor(25, 25, 25))
    p.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
    p.setColor(QPalette.ToolTipBase, Qt.black)
    p.setColor(QPalette.ToolTipText, Qt.white)
    p.setColor(QPalette.Text, Qt.white)
    p.setColor(QPalette.Button, QColor(53, 53, 53))
    p.setColor(QPalette.ButtonText, Qt.white)
    p.setColor(QPalette.BrightText, Qt.red)
    p.setColor(QPalette.Link, QColor(42, 130, 218))
    p.setColor(QPalette.Highlight, QColor(42, 130, 218))
    p.setColor(QPalette.HighlightedText, Qt.black)
    p.setColor(QPalette.PlaceholderText, QColor(130, 130, 130))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(127, 127, 127))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(127, 127, 127))
    return p


def light_palette() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.Window, QColor(240, 240, 240))
    p.setColor(QPalette.WindowText, Qt.black)
    p.setColor(QPalette.Base, Qt.white)
    p.setColor(QPalette.AlternateBase, QColor(245, 245, 245))
    p.setColor(QPalette.Text, Qt.black)
    p.setColor(QPalette.Button, QColor(240, 240, 240))
    p.setColor(QPalette.ButtonText, Qt.black)
    p.setColor(QPalette.Highlight, QColor(42, 130, 218))
    p.setColor(QPalette.HighlightedText, Qt.white)
    return p


class Bridge(QObject):
    """Сигналы из потока ядра в поток окна."""
    log = Signal(dict)
    result = Signal(str, str)   # (заголовок, текст) — показать в строке состояния
    failed = Signal(str)
    http_text = Signal(str)


def fmt(v):
    return round(v, 2) if isinstance(v, float) else v


class MainWindow(QMainWindow):
    def __init__(self, core: ControllerThread, base_dir: str):
        super().__init__()
        self.core = core
        self.ctl = core.ctl
        self.base_dir = base_dir
        self.bridge = Bridge()
        self.bridge.log.connect(self.on_log)
        self.bridge.result.connect(lambda t, m: self.statusBar().showMessage(f"{t}: {m}", 8000))
        self.bridge.failed.connect(self.on_failed)
        self.bridge.http_text.connect(lambda t: self.txt_http.setPlainText(t))
        self.core.call(self.ctl.listeners.append, self.bridge.log.emit)
        self.state: dict = {}
        self.rows: dict[str, int] = {}
        self.setWindowTitle(f"IoT Control Center v{__version__}")
        self.resize(1500, 900)
        self._build_menu()
        self._build_ui()
        for e in self.core.call(self.ctl.logs_since, 0):
            self.on_log(e)
        self.timer = QTimer(self, interval=400, timeout=self.refresh)
        self.timer.start()
        self.refresh()

    # ------------------------------------------------------------------ построение окна
    def _build_menu(self):
        mb = self.menuBar()
        self.act_settings = QAction("⚙ Настройки…", self, shortcut="Ctrl+,", triggered=self.open_settings)
        mb.addAction(self.act_settings)
        m = mb.addMenu("Файл")
        m.addAction(self.act_settings)
        m.addAction("Открыть папку config", lambda: self._open_dir("config"))
        m.addAction("Открыть папку points", lambda: self._open_dir("points"))
        m.addAction("Открыть папку logs", lambda: self._open_dir("logs"))
        m.addSeparator()
        m.addAction("Перечитать конфигурацию", lambda: self.run(self.ctl.reload_config, title="Конфигурация",
                                                                ok="перечитана"))
        m.addSeparator()
        m.addAction("Выход", self.close)
        t = mb.addMenu("Theme Color")
        t.addAction("Dark", lambda: QApplication.instance().setPalette(dark_palette()))
        t.addAction("Light", lambda: QApplication.instance().setPalette(light_palette()))
        h = mb.addMenu("Справка")
        h.addAction("О программе", lambda: QMessageBox.about(
            self, "О программе",
            f"IoT Control Center {__version__}\nDesktop-версия\n\nПапка данных:\n{self.base_dir}\n\n"
            "Связь с Node-RED: WebSocket 8765/8766 (как в 2.0)\nОборудование: HTTP/JSON API"))

    def open_settings(self):
        from .settings_dialog import SettingsDialog
        try:
            SettingsDialog(self, self.core).exec()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Настройки", str(e))
        self.refresh()

    def _open_dir(self, sub):
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.join(self.base_dir, sub)))

    def _build_ui(self):
        root = QSplitter(Qt.Vertical)
        top = QSplitter(Qt.Horizontal)
        top.addWidget(self._left())
        top.addWidget(self._center())
        top.addWidget(self._right())
        top.setSizes([300, 380, 820])
        root.addWidget(top)
        root.addWidget(self._logs())
        root.setSizes([620, 260])
        self.setCentralWidget(root)
        self.status_nr = QLabel()
        self.status_eq = QLabel()
        self.statusBar().addPermanentWidget(self.status_nr)
        self.statusBar().addPermanentWidget(self.status_eq)

    def _left(self):
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("Connection tools — Node-RED")
        gl = QVBoxLayout(g)
        self.lbl_nr = QLabel("Disconnected")
        self.lbl_nr.setFont(QFont(self.font().family(), 11, QFont.Bold))
        self.ed_nrip = QLineEdit()
        self.ed_nrip.setPlaceholderText("IP Node-RED")
        self.btn_nr = QPushButton("Start NodeRed connection")
        self.btn_nr.clicked.connect(self.toggle_nodered)
        self.lbl_nr_detail = QLabel()
        self.lbl_nr_detail.setWordWrap(True)
        gl.addWidget(self.lbl_nr)
        row = QHBoxLayout()
        row.addWidget(QLabel("IP:"))
        row.addWidget(self.ed_nrip)
        gl.addLayout(row)
        gl.addWidget(self.btn_nr)
        gl.addWidget(self.lbl_nr_detail)
        v.addWidget(g)

        g = QGroupBox("Equipment")
        gl = QVBoxLayout(g)
        self.flag_boxes = {}
        for key, text in [("send_to_robots", "Send Data To Robots"), ("send_to_controls", "Send Data To Controls"),
                          ("block_resend", "Block Resending Transmission"),
                          ("parse_feedback", "Parse Data From Equipment"),
                          ("coordinate_mode", "Coordinate mode (иначе — номер позиции)"),
                          ("write_log", "Write log (папка logs/)")]:
            cb = QCheckBox(text)
            cb.clicked.connect(lambda checked, k=key: self.run(self.ctl.set_flags, {k: checked}))
            self.flag_boxes[key] = cb
            gl.addWidget(cb)
        self.btn_eq = QPushButton("Start Equipment connection")
        self.btn_eq.setMinimumHeight(34)
        self.btn_eq.clicked.connect(self.toggle_equipment)
        gl.addWidget(self.btn_eq)
        self.lbl_eq = QLabel()
        self.lbl_eq.setWordWrap(True)
        gl.addWidget(self.lbl_eq)
        v.addWidget(g)
        v.addStretch(1)
        return w

    def _center(self):
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("Manual control (IOT Function)")
        gl = QVBoxLayout(g)
        self.cb_dev = QComboBox()
        self.cb_dev.currentIndexChanged.connect(self.on_device_changed)
        gl.addWidget(self.cb_dev)
        self.chk_selective = QCheckBox("Selective Dispatch (только выбранному; иначе — всем этого типа)")
        self.chk_selective.setChecked(True)
        gl.addWidget(self.chk_selective)
        self.form: dict[str, tuple[QGroupBox, dict]] = {}
        self.form_available = False
        for gid, (title, names) in FORM_GROUPS.items():
            box = QGroupBox(title)
            grid = QGridLayout(box)
            grid.setContentsMargins(6, 2, 6, 4)
            grid.setVerticalSpacing(1)
            inputs = {}
            for i, f in enumerate(names):
                if f in ("L1", "L2", "L3", "L4"):
                    inputs[f] = QCheckBox(f)
                    grid.addWidget(inputs[f], 0, i)
                else:
                    inputs[f] = QLineEdit("0")
                    inputs[f].setMaximumWidth(90)
                    grid.addWidget(QLabel(f), i // 4 * 2, i % 4)
                    grid.addWidget(inputs[f], i // 4 * 2 + 1, i % 4)
            if gid == "robot":
                self.cb_pose = QComboBox()
                self.cb_pose.addItem("По полям X, Y, T, G", "")
                self.cb_pose.addItem("Start", "Start")
                self.cb_pose.addItem("Parking", "Parking")
                grid.addWidget(QLabel("Цель"), 4, 0)
                grid.addWidget(self.cb_pose, 4, 1, 1, 3)
            elif gid == "display":
                self.cb_line = QComboBox()
                for n in range(1, 5):
                    self.cb_line.addItem(str(n), n)
                self.cb_line.addItem("все, через |", 0)
                self.ed_text = QLineEdit()
                self.ed_text.setPlaceholderText("Текст")
                grid.addWidget(QLabel("Строка"), 0, 0)
                grid.addWidget(self.cb_line, 0, 1)
                grid.addWidget(self.ed_text, 0, 2)
                grid.setColumnStretch(2, 1)
            box.hide()
            gl.addWidget(box)
            self.form[gid] = (box, inputs)
        row = QHBoxLayout()
        b = QPushButton("Load selected")
        b.clicked.connect(self.load_selected)
        self.btn_setup = QPushButton("Setup for selected")
        self.btn_setup.clicked.connect(self.setup_selected)
        row.addWidget(b)
        row.addWidget(self.btn_setup, 1)
        gl.addLayout(row)
        self.lbl_hint = QLabel()
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet("color: gray")
        gl.addWidget(self.lbl_hint)
        v.addWidget(g)

        g = QGroupBox("Special Activity")
        gl = QGridLayout(g)
        for i, (code, text, tip) in enumerate([("1", "Send 1 (Start)", "Стартовая позиция"),
                                               ("2", "Send 2 (Parking)", "Парковочная позиция"),
                                               ("3", "Send 3 (Relax)", "Расслабить звенья"),
                                               ("r", "Send R", "Включить опрос / обратную связь"),
                                               ("s", "Send S", "Выключить опрос / обратную связь")]):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, c=code: self.special(c))
            gl.addWidget(b, i // 3, i % 3)
        v.addWidget(g)

        self.grp_robot = QGroupBox("Манипулятор — Motors API")
        gl = QFormLayout(self.grp_robot)
        row = QHBoxLayout()
        self.sp_speed = QSpinBox(minimum=1, maximum=100, value=50, suffix=" %")
        b = QPushButton("Задать скорость")
        b.clicked.connect(lambda: self.raw_http("POST", "/api/motors/speed", {"speed": self.sp_speed.value()}))
        row.addWidget(self.sp_speed)
        row.addWidget(b)
        gl.addRow("Скорость", row)
        row = QHBoxLayout()
        for text, val in (("Вкл", True), ("Выкл", False)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, x=val: self.raw_http("POST", "/api/motors/pump", {"enabled": x}))
            row.addWidget(b)
        gl.addRow("Насос", row)
        v.addWidget(self.grp_robot)

        g = QGroupBox("Прямой HTTP-запрос к устройству")
        gl = QVBoxLayout(g)
        row = QHBoxLayout()
        self.cb_method = QComboBox()
        self.cb_method.addItems(["GET", "POST", "PATCH", "PUT"])
        self.ed_path = QLineEdit()
        self.ed_path.setPlaceholderText("/api/...")
        row.addWidget(self.cb_method)
        row.addWidget(self.ed_path, 1)
        gl.addLayout(row)
        row = QHBoxLayout()
        self.ed_body = QLineEdit()
        self.ed_body.setPlaceholderText('JSON, например {"all":60}')
        b = QPushButton("Отправить")
        b.clicked.connect(self.send_raw)
        row.addWidget(self.ed_body, 1)
        row.addWidget(b)
        gl.addLayout(row)
        self.txt_http = QPlainTextEdit(readOnly=True)
        self.txt_http.setMaximumHeight(60)
        gl.addWidget(self.txt_http)
        v.addWidget(g)
        v.addStretch(1)
        return w

    def _right(self):
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("Last TeamData")
        gl = QVBoxLayout(g)
        self.team_grid = QGridLayout()
        self.team_buttons: list[QPushButton] = []
        gl.addLayout(self.team_grid)
        form = QFormLayout()
        self.lbl_team = QLabel("—")
        self.lbl_server = QLabel("—")
        form.addRow("Team:", self.lbl_team)
        form.addRow("Server IP:", self.lbl_server)
        gl.addLayout(form)
        v.addWidget(g)

        g = QGroupBox("Transmission Viewer — устройства")
        gl = QVBoxLayout(g)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["", "Имя (для Node-RED)", "Тип", "Адрес", "Режим", "Обратная связь"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 26)
        for c in (1, 2, 3, 4):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.itemSelectionChanged.connect(self.on_table_select)
        gl.addWidget(self.table)
        v.addWidget(g, 3)

        g = QGroupBox("From Item — выбранное устройство")
        gl = QVBoxLayout(g)
        self.txt_item = QPlainTextEdit(readOnly=True)
        self.txt_item.setFont(QFont("Monospace", 9))
        gl.addWidget(self.txt_item)
        v.addWidget(g, 2)
        return w

    def _logs(self):
        self.tabs = QTabWidget()
        self.log_views = {}
        for ch, title in LOG_TABS:
            t = QPlainTextEdit(readOnly=True)
            t.setMaximumBlockCount(3000)
            t.setFont(QFont("Monospace", 9))
            self.log_views[ch] = t
            self.tabs.addTab(t, title)
        b = QPushButton("Очистить")
        b.clicked.connect(lambda: [t.clear() for t in self.log_views.values()])
        self.tabs.setCornerWidget(b)
        return self.tabs

    # ------------------------------------------------------------------ работа с ядром
    def run(self, fn, *args, title="", ok=""):
        def done(res, err):
            if err:
                self.bridge.failed.emit(str(err))
            elif ok or isinstance(res, list):
                self.bridge.result.emit(title or "Готово", ok or "; ".join(map(str, res)))
        self.core.submit(fn, *args, done=done)

    def on_failed(self, msg):
        self.statusBar().showMessage(msg, 10000)
        QMessageBox.warning(self, "ControlCenter", msg)

    def on_log(self, e: dict):
        line = f"<{e['ts']}> {e['text']}"
        color = LOG_COLORS.get(e["ch"], "")
        html = f'<span style="color:{color}">{_esc(line)}</span>'
        self.log_views["all"].appendHtml(html)
        if e["ch"] in self.log_views:
            self.log_views[e["ch"]].appendHtml(html)

    def selected_state(self) -> str | None:
        return self.cb_dev.currentData()

    def refresh(self):
        try:
            s = self.core.call(self.ctl.state, 10 ** 12, timeout=1.5)
        except Exception:  # noqa: BLE001
            return
        self.state = s
        nr = s["nodered"]
        ok = nr["commands"] and nr["feedback"]
        if nr["enabled"]:
            self.lbl_nr.setText("Connected" if ok else "Connecting…")
            self.lbl_nr.setStyleSheet("color: rgb(0,200,0)" if ok else "color: rgb(210,153,34)")
        else:
            self.lbl_nr.setText("Disconnected")
            self.lbl_nr.setStyleSheet("color: rgb(200,0,0)")
        self.btn_nr.setText("Stop NodeRed connection" if nr["enabled"] else "Start NodeRed connection")
        if not self.ed_nrip.hasFocus():
            self.ed_nrip.setText(nr["ip"])
        self.ed_nrip.setEnabled(not nr["enabled"])
        self.lbl_nr_detail.setText(
            f"команды ws://{nr['ip']}:{nr['ports'][0]} — {'OK' if nr['commands'] else 'нет'}\n"
            f"обратная связь ws://{nr['ip']}:{nr['ports'][1]} — {'OK' if nr['feedback'] else 'нет'}"
            if nr["enabled"] else "Ручное управление доступно, пока Node-RED не подключён.")
        on = sum(d["online"] for d in s["devices"])
        self.btn_eq.setText("Stop Equipment connection" if s["equipment_running"] else "Start Equipment connection")
        self.lbl_eq.setText(f"На связи: {on} из {len(s['devices'])}" if s["equipment_running"] else "")
        for k, cb in self.flag_boxes.items():
            cb.setChecked(bool(s["flags"].get(k)))
        self.btn_setup.setEnabled(not nr["enabled"] and self.form_available)
        self.status_nr.setText(f"Node-RED: {'OK' if ok else ('…' if nr['enabled'] else 'выкл')}")
        self.status_eq.setText(f"Оборудование: {on}/{len(s['devices'])}" if s["equipment_running"]
                               else "Оборудование: выкл")
        self._refresh_teams(s)
        self._refresh_devices(s)

    def _refresh_teams(self, s):
        if len(self.team_buttons) != len(s["teams"]):
            for b in self.team_buttons:
                b.deleteLater()
            self.team_buttons = []
            for t in s["teams"]:
                b = QPushButton(t["name"])
                b.setCheckable(True)
                b.setToolTip(f"{t['ip']}:{t['port']}")
                b.clicked.connect(lambda _=False, i=t["index"]: self.run(self.ctl.select_team, i))
                self.team_grid.addWidget(b, t["index"] // 3, t["index"] % 3)
                self.team_buttons.append(b)
        for i, b in enumerate(self.team_buttons):
            b.setChecked(i == s["team"])
            b.setEnabled(not s["nodered"]["enabled"])
        if s["team"] is not None:
            t = s["teams"][s["team"]]
            self.lbl_team.setText(t["name"])
            self.lbl_server.setText(f"{t['ip']}:{t['port']}")

    def _refresh_devices(self, s):
        devs = s["devices"]
        labels = [f"{d['state']}: {d['name']}" for d in devs]
        current = [self.cb_dev.itemText(i) for i in range(self.cb_dev.count())]
        if labels != current:
            sel = self.selected_state()
            self.cb_dev.blockSignals(True)
            self.cb_dev.clear()
            for d, lab in zip(devs, labels):
                self.cb_dev.addItem(lab, d["state"])
            idx = self.cb_dev.findData(sel)
            self.cb_dev.setCurrentIndex(max(idx, 0))
            self.cb_dev.blockSignals(False)
            self.on_device_changed()
        if self.table.rowCount() != len(devs):
            self.table.setRowCount(len(devs))
            self.rows = {}
            for r, d in enumerate(devs):
                self.rows[d["state"]] = r
                for c in range(6):
                    self.table.setItem(r, c, QTableWidgetItem())
                if d["has_mode"]:
                    cb = QComboBox()
                    cb.addItems(["общий", "координаты", "позиции"])
                    cb.currentIndexChanged.connect(
                        lambda i, st=d["state"]: self.run(self._set_mode, st, [None, True, False][i]))
                    self.table.setCellWidget(r, 4, cb)
        for d in devs:
            r = self.rows.get(d["state"])
            if r is None:
                continue
            st = "●"
            color = QColor("#777")
            if s["equipment_running"] or d["driver"] == "udp":
                color = QColor("#d29922") if d["busy"] else (QColor("#3fb950") if d["online"] else QColor("#f85149"))
            it = self.table.item(r, 0)
            it.setText(st)
            it.setForeground(color)
            it.setToolTip(d["last_error"] or ("на связи" if d["online"] else "нет связи"))
            name = d["name"] + ("" if d["polling"] else "  (опрос выкл.)") + (f"  [очередь {d['queue']}]" if d["queue"] else "")
            self.table.item(r, 1).setText(name)
            self.table.item(r, 2).setText(f"{d['key']} {KEYNAMES.get(d['key'], '')} ({d['driver']})")
            self.table.item(r, 3).setText(d["url"])
            cbw = self.table.cellWidget(r, 4)
            if isinstance(cbw, QComboBox):
                want = {None: 0, True: 1, False: 2}[d["coordinate_mode"]]
                if cbw.currentIndex() != want:
                    cbw.blockSignals(True)
                    cbw.setCurrentIndex(want)
                    cbw.blockSignals(False)
            fb = " ".join(f"{k}={fmt(v)}" for k, v in d["feedback"].items() if v not in (0, None, "0")) or "все 0"
            self.table.item(r, 5).setText(fb)
            self.table.item(r, 5).setToolTip(fb + (f"\n\nПоследняя отправка:\n{d['last_sent']}" if d["last_sent"] else ""))
        self._refresh_item()

    def _refresh_item(self):
        st = self.selected_state()
        d = next((x for x in self.state.get("devices", []) if x["state"] == st), None)
        if not d:
            return
        lines = [f"{d['name']}  ({d['key']}, {d['driver']}, {d['url']})",
                 f"на связи: {'да' if d['online'] else 'нет'}   опрос: {'вкл' if d['polling'] else 'выкл'}"]
        if d["last_error"]:
            lines.append(f"последняя ошибка: {d['last_error']}")
        fb = d["feedback"]
        keys = list(fb)
        for i in range(0, len(keys), 8):
            lines.append("  ".join(f"{k}={fmt(fb[k])}" for k in keys[i:i + 8]))
        if d.get("last_cmd"):
            lines.append("последняя команда: " + json.dumps(d["last_cmd"], ensure_ascii=False))
        if d.get("raw") is not None:
            lines.append("ответ устройства: " + json.dumps(d["raw"], ensure_ascii=False, default=str))
        text = "\n".join(lines)
        if self.txt_item.toPlainText() != text:
            sb = self.txt_item.verticalScrollBar().value()
            self.txt_item.setPlainText(text)
            self.txt_item.verticalScrollBar().setValue(sb)

    def _set_mode(self, state, value):
        self.ctl.device_by_state(state).set_mode(value)

    # ------------------------------------------------------------------ действия
    def toggle_nodered(self):
        if self.state.get("nodered", {}).get("enabled"):
            self.run(self.ctl.disconnect_nodered)
        else:
            self.run(self.ctl.connect_nodered, self.ed_nrip.text().strip() or None)

    def toggle_equipment(self):
        self.run(self.ctl.stop_equipment if self.state.get("equipment_running") else self.ctl.start_equipment)

    def on_device_changed(self, *_):
        st = self.selected_state()
        d = next((x for x in self.state.get("devices", []) if x["state"] == st), None)
        groups = FORMS.get(d["key"], []) if d else []
        for gid, (box, _) in self.form.items():
            box.setVisible(gid in groups)
        self.form_available = bool(groups)
        self.lbl_hint.setText((HINTS.get(d["driver"], "") if groups else "Для этого устройства нет параметров ручной "
                               "отправки.") if d else "")
        self.grp_robot.setVisible(bool(d and d["driver"] == "robot"))
        r = self.rows.get(st)
        if r is not None and self.table.currentRow() != r:
            self.table.blockSignals(True)
            self.table.selectRow(r)
            self.table.blockSignals(False)
        self._refresh_item()

    def on_table_select(self):
        r = self.table.currentRow()
        st = next((k for k, v in self.rows.items() if v == r), None)
        idx = self.cb_dev.findData(st)
        if idx >= 0:
            self.cb_dev.setCurrentIndex(idx)

    def target(self) -> str:
        return (self.selected_state() or "all") if self.chk_selective.isChecked() else "all"

    def setup_selected(self):
        st = self.selected_state()
        d = next((x for x in self.state.get("devices", []) if x["state"] == st), None)
        if not d:
            return
        cmd = {}
        for gid in FORMS.get(d["key"], []):
            for f, w in self.form[gid][1].items():
                cmd[f] = int(w.isChecked()) if isinstance(w, QCheckBox) else w.text().strip() or "0"
            if gid == "robot":
                cmd["Text"] = self.cb_pose.currentData()
            elif gid == "display":
                cmd["Text"] = self.ed_text.text()
                cmd["Line"] = self.cb_line.currentData()
        self.run(self.ctl.manual_command, self.target(), cmd, d["key"], title="Отправлено",
                 ok="команда поставлена в очередь")

    def load_selected(self):
        st = self.selected_state()
        d = next((x for x in self.state.get("devices", []) if x["state"] == st), None)
        if not d or not d.get("last_cmd_form"):
            self.statusBar().showMessage("Для устройства ещё не было команд", 5000)
            return
        last = d["last_cmd_form"]
        for gid in FORMS.get(d["key"], []):
            for f, w in self.form[gid][1].items():
                if isinstance(w, QCheckBox):
                    w.setChecked(bool(last.get(f, 0)))
                else:
                    w.setText(str(last.get(f, 0)))
            if gid == "robot":
                self.cb_pose.setCurrentIndex(max(self.cb_pose.findData(last.get("Text", "")), 0))
            elif gid == "display":
                self.ed_text.setText(last.get("Text", ""))
                self.cb_line.setCurrentIndex(self.cb_line.findData(last.get("Line", 0) or (0 if "|" in last.get("Text", "") else 1)))

    def special(self, code):
        self.run(self.ctl.special, self.target(), code, title=f"Кнопка {code}")

    def raw_http(self, method, path, body):
        st = self.selected_state()

        async def go():
            d = self.ctl.device_by_state(st)
            if d.driver == "udp":
                raise CCError(585, "устройство работает по UDP")
            r = await d.http(method, path, body, retries=0, timeout_ms=self.ctl.settings["equipment"]["robot_timeout_ms"])
            self.ctl.event(f"{d.name}: ручной запрос {method} {path} {body or ''}")
            return json.dumps(r, ensure_ascii=False, indent=1)

        def done(res, err):
            self.bridge.result.emit("HTTP", "ошибка" if err else "ответ получен")
            if err:
                self.bridge.failed.emit(str(err))
            else:
                self.bridge.http_text.emit(res)
        self.core.submit(go, done=done)

    def send_raw(self):
        body = None
        t = self.ed_body.text().strip()
        if t:
            try:
                body = json.loads(t)
            except ValueError:
                QMessageBox.warning(self, "ControlCenter", "Тело запроса — не JSON")
                return
        self.raw_http(self.cb_method.currentText(), self.ed_path.text().strip() or "/", body)

    def closeEvent(self, ev):
        self.timer.stop()
        self.core.shutdown()
        ev.accept()


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def default_dir() -> str:
    """Как в 2.0: папки config/points/logs рядом с программой (exe) или в текущей папке."""
    cands = []
    if getattr(sys, "frozen", False):
        cands.append(os.path.dirname(sys.executable))
    cands += [os.getcwd(), os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))]
    for c in cands:
        if os.path.exists(os.path.join(c, "config", "_PolygonData.csv")):
            return c
    return cands[0]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="controlcenter-desktop", description="IoT ControlCenter — desktop-версия")
    ap.add_argument("--dir", help="папка с config/, points/, logs/")
    ap.add_argument("--web", type=int, metavar="PORT", help="дополнительно открыть веб-интерфейс на порту")
    args = ap.parse_args(argv)

    app = QApplication(sys.argv[:1])
    app.setApplicationName("IoT Control Center")
    app.setStyle("Fusion")
    try:  # тема как в системе (Qt 6.5+), иначе тёмная — как в 2.0
        light = app.styleHints().colorScheme() == Qt.ColorScheme.Light
    except AttributeError:
        light = False
    app.setPalette(light_palette() if light else dark_palette())
    icon = os.path.join(os.path.dirname(__file__), "icon.png")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))

    base = args.dir or default_dir()
    while not os.path.exists(os.path.join(base, "config", "_PolygonData.csv")):
        QMessageBox.information(None, "ControlCenter",
                                f"В папке\n{base}\nнет config/_PolygonData.csv.\n\n"
                                "Выберите папку, в которой лежат config/, points/ и logs/.")
        base = QFileDialog.getExistingDirectory(None, "Папка ControlCenter", base)
        if not base:
            return 1

    core = ControllerThread(base, web_port=args.web)
    core.start()
    core.ready.wait(15)
    if core.error is not None:
        QMessageBox.critical(None, "ControlCenter", f"Ошибка запуска:\n{core.error}")
        return 2
    w = MainWindow(core, base)
    w.show()
    return app.exec()
