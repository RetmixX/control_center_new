"""Окно «Настройки» desktop-версии. Строится по той же схеме, что и веб-редактор (settings_schema)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QScrollArea, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)


def _combo(choices, value, labels=None):
    cb = QComboBox()
    for c in choices:
        cb.addItem((labels or {}).get(c) or c or "—", c)
    i = cb.findData("" if value is None else str(value))
    cb.setCurrentIndex(max(i, 0))
    return cb


class TableEditor(QWidget):
    def __init__(self, tdef: dict, rows: list[dict]):
        super().__init__()
        self.tdef = tdef
        self.cols = tdef["columns"]
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, len(self.cols))
        self.table.setHorizontalHeaderLabels([c["label"] for c in self.cols])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(True)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        for r in rows:
            self.add_row(r)
        self.table.resizeColumnsToContents()
        for j in range(len(self.cols)):
            self.table.setColumnWidth(j, max(self.table.columnWidth(j) + 16, 80))
        v.addWidget(self.table)
        if not tdef.get("fixed_rows"):
            h = QHBoxLayout()
            b = QPushButton("+ строка")
            b.clicked.connect(lambda: self.add_row(None))
            d = QPushButton("Удалить выбранные строки")
            d.clicked.connect(self.del_rows)
            h.addWidget(b)
            h.addWidget(d)
            h.addStretch(1)
            v.addLayout(h)
        self.table.setMinimumHeight(min(60 + 28 * max(len(rows), 3), 420))

    def add_row(self, r: dict | None):
        new = r is None
        if new:  # новая строка: значения по умолчанию или как в последней
            last = self.row(self.table.rowCount() - 1) if self.table.rowCount() else {}
            r = {c["key"]: c.get("default", last.get(c["key"], "") if c["type"] == "choice" else "")
                 for c in self.cols}
        i = self.table.rowCount()
        self.table.insertRow(i)
        for j, c in enumerate(self.cols):
            val = r.get(c["key"], "")
            if c["type"] == "choice" and not c.get("readonly"):
                self.table.setCellWidget(i, j, _combo(c["choices"], val, c.get("labels")))
            else:
                it = QTableWidgetItem("" if val is None else str(val))
                if c.get("readonly"):
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(i, j, it)
        self._link_only_for(i)
        if new:
            self.table.scrollToBottom()

    def _link_only_for(self, i):
        """Столбец с only_for доступен только при нужном значении другого столбца (MODE — только у M)."""
        keys = [c["key"] for c in self.cols]
        for j, c in enumerate(self.cols):
            for dep, allowed in c.get("only_for", {}).items():
                src, dst = self.table.cellWidget(i, keys.index(dep)), self.table.cellWidget(i, j)
                dst.setPlaceholderText("—")
                self._sync_only_for(src, dst, allowed)
                src.currentIndexChanged.connect(lambda _, s=src, d=dst, a=allowed: self._sync_only_for(s, d, a))

    @staticmethod
    def _sync_only_for(src, dst, allowed):
        ok = src.currentData() in allowed
        if not ok:
            dst.setCurrentIndex(-1)
        elif dst.currentIndex() < 0:
            dst.setCurrentIndex(max(dst.findData(""), 0))
        dst.setEnabled(ok)

    def del_rows(self):
        for i in sorted({ix.row() for ix in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(i)

    def row(self, i) -> dict:
        out = {}
        for j, c in enumerate(self.cols):
            w = self.table.cellWidget(i, j)
            if isinstance(w, QComboBox):
                out[c["key"]] = w.currentData()
            else:
                it = self.table.item(i, j)
                out[c["key"]] = it.text() if it else ""
        return out

    def value(self) -> list[dict]:
        return [self.row(i) for i in range(self.table.rowCount())]


class SettingsDialog(QDialog):
    def __init__(self, parent, core):
        super().__init__(parent)
        self.core = core
        self.ctl = core.ctl
        self.setWindowTitle("Настройки")
        scr = QGuiApplication.primaryScreen().availableGeometry()
        self.resize(min(1150, scr.width() - 60), min(820, scr.height() - 60))
        v = QVBoxLayout(self)
        self.tabs = QTabWidget()
        v.addWidget(self.tabs)
        h = QHBoxLayout()
        self.msg = QLabel()
        self.msg.setWordWrap(True)
        h.addWidget(self.msg, 1)
        b = QPushButton("Закрыть")
        b.clicked.connect(self.reject)
        self.btn_save = QPushButton("Сохранить и применить")
        self.btn_save.setDefault(True)
        self.btn_save.clicked.connect(self.save)
        h.addWidget(b)
        h.addWidget(self.btn_save)
        v.addLayout(h)
        self.load()

    def load(self):
        cfg = self.core.call(self.ctl.get_config)
        self.schema, vals = cfg["schema"], cfg["values"]
        cur = self.tabs.currentIndex()
        self.tabs.clear()
        self.field_widgets: dict[str, tuple[str, QWidget]] = {}
        self.table_widgets: dict[str, TableEditor] = {}
        secs = {s["id"]: s for s in self.schema["sections"]}
        tdefs = {t["id"]: t for t in self.schema["tables"]}
        for tab in self.schema["tabs"]:
            page = QWidget()
            pv = QVBoxLayout(page)
            for sid in tab["sections"]:
                sec = secs[sid]
                g = QGroupBox(sec["title"])
                form = QFormLayout(g)
                for f in sec["fields"]:
                    w = self._field(f, vals["fields"].get(f["key"]))
                    lab = f["label"] + ("  (после перезапуска)" if f.get("restart") else "")
                    row = QHBoxLayout()
                    row.addWidget(w)
                    help_ = (f.get("help") or "") + (f"  [{f['min']}..{f['max']}]" if f.get("min") is not None else "")
                    if help_:
                        hl = QLabel(help_)
                        hl.setStyleSheet("color: gray")
                        row.addWidget(hl, 1)
                    else:
                        row.addStretch(1)
                    form.addRow(lab, row)
                    self.field_widgets[f["key"]] = (f["type"], w)
                pv.addWidget(g)
            for tid in tab["tables"]:
                t = tdefs[tid]
                g = QGroupBox(f"{t['title']} — {t['file']}")
                gv = QVBoxLayout(g)
                if tid == "devices":
                    hl = QLabel(self.schema["key_hint"] + " URL/HTTP-порт пустые — берутся из «Драйверы по типам».")
                    hl.setWordWrap(True)
                    hl.setStyleSheet("color: gray")
                    gv.addWidget(hl)
                te = TableEditor(t, vals["tables"].get(tid, []))
                gv.addWidget(te)
                self.table_widgets[tid] = te
                pv.addWidget(g)
            pv.addStretch(1)
            sa = QScrollArea()
            sa.setWidgetResizable(True)
            sa.setWidget(page)
            self.tabs.addTab(sa, tab["title"])
        if cur >= 0:
            self.tabs.setCurrentIndex(cur)

    def _field(self, f, val):
        t = f["type"]
        if t == "bool":
            w = QCheckBox()
            w.setChecked(bool(val))
        elif t == "choice":
            w = _combo(f["choices"], val, f.get("labels"))
        else:
            w = QLineEdit("" if val is None else str(val))
            w.setMaximumWidth(260)
            if t == "password":
                w.setEchoMode(QLineEdit.Password)
        return w

    def collect(self) -> dict:
        fields = {}
        for k, (t, w) in self.field_widgets.items():
            if t == "bool":
                fields[k] = w.isChecked()
            elif t == "choice":
                fields[k] = w.currentData()
            else:
                fields[k] = w.text()
        return {"fields": fields, "tables": {tid: te.value() for tid, te in self.table_widgets.items()}}

    def save(self):
        data = self.collect()
        self.btn_save.setEnabled(False)
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            res = self.core.call(self.ctl.save_config, data, timeout=30)
        except Exception as e:  # noqa: BLE001
            QGuiApplication.restoreOverrideCursor()
            self.msg.setStyleSheet("color: #f85149")
            self.msg.setText("Не сохранено")
            QMessageBox.warning(self, "Настройки не сохранены", str(e))
            return
        finally:
            self.btn_save.setEnabled(True)
        QGuiApplication.restoreOverrideCursor()
        self.msg.setStyleSheet("color: #3fb950")
        text = "Сохранено и применено: " + ", ".join(res["files"])
        if res["restart"]:
            text += "\nПосле перезапуска программы применится: " + ", ".join(res["restart"])
        self.msg.setText(text)
        self.load()
