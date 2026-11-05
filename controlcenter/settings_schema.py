"""Описание всех настроек для редакторов в интерфейсе (desktop, веб, CLI).

Один источник правды: по схеме строятся формы и таблицы, по ней же проверяются и сохраняются данные
в config/settings.json, config/_ServerIPs.csv, config/_PolygonData.csv и points/*.csv.
"""
from __future__ import annotations

import copy
import ipaddress
import re
from typing import Any

from .config import DEFAULT_SETTINGS, MODE_KEYS, POINT_FILES, Config
from .errors import CCError

NR_FIELDS = ["X", "Y", "T", "G", "V", "D0", "L1", "L2", "L3", "L4", "P", "N"]
COLORS = ["red", "yellow", "green", "blue"]
DEVICE_KEYS = ["M", "T", "R", "B1", "BR", "SC", "C", "F1", "C1"]
DRIVERS = ["robot", "lamp", "terminal", "barrier", "udp"]


def F(key, label, type_="int", **kw):
    d = {"key": key, "label": label, "type": type_}
    d.update(kw)
    return d


# ----------------------------------------------------------------------------- поля (settings.json)
SECTIONS: list[dict] = [
    {"id": "nodered", "title": "Node-RED", "fields": [
        F("nodered.ws_commands_port", "Порт WebSocket команд", min=1, max=65535,
          help="Отсюда приходят команды IOT Function (в 2.0 — 8765)"),
        F("nodered.ws_feedback_port", "Порт WebSocket обратной связи", min=1, max=65535,
          help="Сюда уходит обратная связь (в 2.0 — 8766)"),
        F("nodered.reconnect_sec", "Пауза переподключения, с", "float", min=0.5, max=120),
        F("nodered.use_basic_auth", "Логин/пароль из таблицы команд при подключении", "bool"),
        F("nodered.autoconnect_team", "Автоподключение к команде при запуске", "int", min=0, max=99,
          help="0 — не подключаться"),
    ]},
    {"id": "equipment", "title": "Оборудование и опрос", "fields": [
        F("equipment.autostart", "Запускать связь с оборудованием при старте", "bool"),
        F("equipment.poll_interval_ms", "Интервал опроса устройств, мс", min=50, max=10000,
          help="API устройств рекомендует 100–500 мс"),
        F("equipment.robot_slow_poll_ms", "Опрос температуры/нагрузки манипулятора, мс", min=200, max=60000),
        F("equipment.http_timeout_ms", "Таймаут HTTP-запроса, мс", min=100, max=30000),
        F("equipment.robot_timeout_ms", "Таймаут команды движения манипулятора, мс", min=500, max=300000),
        F("equipment.retries", "Повторов при сетевой ошибке", min=0, max=10),
        F("equipment.feedback_heartbeat_ms", "Повторять обратную связь по всем устройствам, мс", min=0, max=60000,
          help="0 — только при изменениях (меньше сообщений в IOT Get)"),
        F("equipment.udp_listen_port", "UDP-порт для старых устройств", min=1, max=65535, restart=True),
        F("equipment.send_to_robots", "Send Data To Robots (по умолчанию)", "bool"),
        F("equipment.send_to_controls", "Send Data To Controls (по умолчанию)", "bool"),
        F("equipment.block_resend", "Block Resending Transmission (по умолчанию)", "bool"),
        F("equipment.parse_feedback", "Parse Data From Equipment (по умолчанию)", "bool"),
        F("equipment.coordinate_mode", "Режим координат (иначе — номер позиции)", "bool"),
    ]},
    {"id": "robot", "title": "Манипулятор: поля Node-RED → Motors API", "fields": [
        F("robot_mapping.x", "x  ←", "choice", choices=NR_FIELDS),
        F("robot_mapping.z", "z  ←", "choice", choices=NR_FIELDS),
        F("robot_mapping.angel", "angel  ←", "choice", choices=NR_FIELDS),
        F("robot_mapping.pov_gripper", "pov_gripper  ←", "choice", choices=NR_FIELDS),
        F("robot_mapping.gripper", "gripper_state  ←", "choice", choices=NR_FIELDS),
        F("robot_mapping.pump_follows_gripper", "Насос включается вместе со схватом", "bool"),
        F("robot_mapping.speed_field", "Скорость (/api/motors/speed)  ←", "choice", choices=[""] + NR_FIELDS,
          help="пусто — скорость не задавать"),
        F("robot_mapping.cartesian", "X/Y декартовы → x = √(X²+Y²), angel = atan2(Y, X)", "bool"),
        F("robot_mapping.start_point", "Номер позиции Start", min=0, max=999999),
        F("robot_mapping.parking_point", "Номер позиции Parking", min=0, max=999999),
    ]},
    {"id": "manual", "title": "Manual Control: поля формы → Motors API", "fields": [
        F("manual_mapping.x", "x  ←", "choice", choices=NR_FIELDS),
        F("manual_mapping.z", "z  ←", "choice", choices=NR_FIELDS),
        F("manual_mapping.angel", "angel  ←", "choice", choices=NR_FIELDS),
        F("manual_mapping.pov_gripper", "pov_gripper  ←", "choice", choices=NR_FIELDS),
    ]},
    {"id": "lamp", "title": "Светофор и терминал", "fields": [
        F("lamp_mapping.L1", "L1 → цвет", "choice", choices=[""] + COLORS),
        F("lamp_mapping.L2", "L2 → цвет", "choice", choices=[""] + COLORS),
        F("lamp_mapping.L3", "L3 → цвет", "choice", choices=[""] + COLORS),
        F("lamp_mapping.L4", "L4 → цвет", "choice", choices=[""] + COLORS),
        F("terminal.text_line_separator", "Разделитель строк дисплея в Text", "str"),
        F("terminal.transliterate_on_overflow", "Транслит, если больше 8 разных русских букв", "bool"),
        F("terminal.empty_text_clears", "Пустой Text очищает дисплей (как в 2.0)", "bool"),
    ]},
    {"id": "web", "title": "Веб-интерфейс", "fields": [
        F("web.host", "Адрес", "str", restart=True, help="0.0.0.0 — доступен со всех интерфейсов"),
        F("web.port", "Порт", min=1, max=65535, restart=True),
        F("web.username", "Логин", "str", restart=True, help="пусто — без пароля"),
        F("web.password", "Пароль", "password", restart=True),
    ]},
]

# ----------------------------------------------------------------------------- таблицы
TABLES: list[dict] = [
    {"id": "teams", "title": "Команды", "file": "config/_ServerIPs.csv", "columns": [
        {"key": "IP", "label": "IP Node-RED", "type": "ip"},
        {"key": "PORT", "label": "Порт", "type": "int", "default": 1880},
        {"key": "NAME", "label": "Название", "type": "str", "default": "Team"},
        {"key": "USERNAME", "label": "Логин", "type": "str", "optional": True},
        {"key": "PASSWORD", "label": "Пароль", "type": "str", "optional": True},
    ]},
    {"id": "devices", "title": "Оборудование", "file": "config/_PolygonData.csv + settings.json", "columns": [
        {"key": "STATE", "label": "ID (STATE)", "type": "int"},
        {"key": "KEY", "label": "Тип", "type": "choice", "choices": DEVICE_KEYS},
        {"key": "IP", "label": "IP", "type": "ip"},
        {"key": "PORT", "label": "UDP-порт", "type": "int", "default": 8888},
        {"key": "NAME", "label": "Имя", "type": "name"},
        {"key": "ENTRANCE", "label": "Режим", "type": "str", "default": "InOut"},
        {"key": "URL", "label": "URL API", "type": "str", "optional": True},
        {"key": "HTTP_PORT", "label": "HTTP-порт", "type": "int", "optional": True},
        {"key": "MODE", "label": "Коорд./позиции", "type": "choice", "choices": ["", "coord", "pos"],
         "labels": {"": "общий", "coord": "координаты", "pos": "позиции"}, "optional": True,
         "only_for": {"KEY": list(MODE_KEYS)}},
    ]},
    {"id": "drivers", "title": "Драйверы по типам", "file": "settings.json", "fixed_rows": True, "columns": [
        {"key": "KEY", "label": "Тип", "type": "choice", "choices": DEVICE_KEYS, "readonly": True},
        {"key": "DRIVER", "label": "Драйвер", "type": "choice", "choices": DRIVERS},
        {"key": "HTTP_PORT", "label": "HTTP-порт", "type": "int", "optional": True},
    ]},
    {"id": "poses", "title": "Резервные позиции Start/Parking", "file": "settings.json", "fixed_rows": True,
     "columns": [
         {"key": "KEY", "label": "Тип", "type": "str", "readonly": True},
         {"key": "WHICH", "label": "Позиция", "type": "str", "readonly": True},
         {"key": "X", "label": "X", "type": "float"}, {"key": "Y", "label": "Y", "type": "float"},
         {"key": "T", "label": "T", "type": "float"}, {"key": "Z", "label": "Z", "type": "float"},
     ]},
] + [
    {"id": f"points_{k}", "title": f"Позиции {k} ({fn})", "file": f"points/{fn}", "columns": [
        {"key": "NUM", "label": "Номер", "type": "int"},
        {"key": "X", "label": "X", "type": "float"}, {"key": "Y", "label": "Y", "type": "float"},
        {"key": "T", "label": "T", "type": "float"}, {"key": "Z", "label": "Z", "type": "float"},
    ]} for k, fn in POINT_FILES.items()
]

# вкладки редактора: какие разделы и таблицы на какой вкладке
TABS: list[dict] = [
    {"title": "Основное", "sections": ["nodered", "equipment", "web"], "tables": []},
    {"title": "Команды", "sections": [], "tables": ["teams"]},
    {"title": "Оборудование", "sections": [], "tables": ["devices", "drivers"]},
    {"title": "Манипулятор", "sections": ["robot", "manual"], "tables": ["poses"]},
    {"title": "Светофор и терминал", "sections": ["lamp"], "tables": []},
    {"title": "Позиции", "sections": [], "tables": [f"points_{k}" for k in POINT_FILES]},
]

KEY_HINT = ("Типы: M — манипулятор, T — светофор, R — удалённый терминал, "
            "B1 — ИК-барьер, BR — сканер штрихкода, SC — смарт-камера, C — конвейер, F1 — мобильный робот, "
            "C1 — AR-камера. Имя: «Robot_1» превратится в «Robot1_1» для команды 1, «Conveyor» — в «Conveyor1».")


# ----------------------------------------------------------------------------- чтение
def _get(d: dict, path: str):
    for p in path.split("."):
        d = d.get(p) if isinstance(d, dict) else None
    return d


def _set(d: dict, path: str, value):
    parts = path.split(".")
    for p in parts[:-1]:
        d = d.setdefault(p, {})
    d[parts[-1]] = value


def export(cfg: Config, settings: dict) -> dict:
    fields = {}
    for sec in SECTIONS:
        for f in sec["fields"]:
            v = _get(settings, f["key"])
            if f["key"] == "nodered.autoconnect_team":
                v = v or 0
            if f["type"] == "choice" and v is None:
                v = ""
            fields[f["key"]] = v
    tables: dict[str, list[dict]] = {}
    tables["teams"] = [{"IP": t.ip, "PORT": t.port, "NAME": t.name, "USERNAME": t.username, "PASSWORD": t.password}
                       for t in cfg.teams]
    devs = []
    for d in cfg.devices:
        ov = settings.get("devices", {}).get(d.state, {})
        cm = ov.get("coordinate_mode")
        devs.append({"STATE": d.state, "KEY": d.key, "IP": d.ip, "PORT": d.port, "NAME": d.name,
                     "ENTRANCE": d.entrance, "URL": ov.get("url", ""),
                     "HTTP_PORT": ov.get("http_port", ""),
                     "MODE": "" if cm is None or d.key not in MODE_KEYS else ("coord" if cm else "pos")})
    tables["devices"] = devs
    drv = settings.get("drivers", {})
    keys = DEVICE_KEYS + [k for k in drv if k not in DEVICE_KEYS]
    tables["drivers"] = [{"KEY": k, "DRIVER": drv.get(k, {}).get("driver", "udp"),
                          "HTTP_PORT": drv.get(k, {}).get("http_port", "")} for k in keys]
    poses = []
    fb = settings.get("fallback_poses", {})
    for k in POINT_FILES:
        for which in ("start", "parking"):
            p = (fb.get(k, {}).get(which) or [0, 0, 0, 0]) + [0, 0, 0, 0]
            poses.append({"KEY": k, "WHICH": which, "X": p[0], "Y": p[1], "T": p[2], "Z": p[3]})
    tables["poses"] = poses
    for k in POINT_FILES:
        tables[f"points_{k}"] = [{"NUM": n, "X": _n(p[0]), "Y": _n(p[1]), "T": _n(p[2]), "Z": _n(p[3])}
                                 for n, p in cfg.points.get(k, {}).items()]
    return {"schema": {"sections": SECTIONS, "tables": TABLES, "tabs": TABS, "key_hint": KEY_HINT},
            "values": {"fields": fields, "tables": tables}}


def _n(v):
    return int(v) if float(v).is_integer() else v


# ----------------------------------------------------------------------------- проверка
class _Errors(list):
    def check(self):
        if self:
            raise CCError(590, "исправьте и сохраните ещё раз:\n• " + "\n• ".join(self[:30]))


def _conv(val, typ: str, label: str, errs: _Errors, *, optional=False, mn=None, mx=None, choices=None):
    if isinstance(val, str):
        val = val.strip()
    if val in (None, "") and typ not in ("str", "password", "choice", "bool"):
        if optional:
            return None
        errs.append(f"{label}: пусто")
        return None
    try:
        if typ == "int":
            f = float(str(val).replace(",", "."))
            if not f.is_integer():
                raise ValueError
            v: Any = int(f)
        elif typ == "float":
            v = float(str(val).replace(",", "."))
            v = int(v) if v.is_integer() else v
        elif typ == "bool":
            v = val if isinstance(val, bool) else str(val).lower() in ("1", "true", "on", "yes", "да")
        elif typ == "ip":
            v = str(val)
            ipaddress.ip_address(v)
        elif typ == "name":
            v = str(val)
            if not v or not re.fullmatch(r"[^\s;_]+(_[^\s;_]+)?", v):
                errs.append(f"{label}: «{v}» — без пробелов и «;», не больше одного «_» (Robot_1, Conveyor)")
                return None
        elif typ == "choice":
            v = "" if val is None else str(val)
            if choices is not None and v not in choices:
                errs.append(f"{label}: «{v}» — допустимо: {', '.join(c or '(пусто)' for c in choices)}")
                return None
        else:
            v = "" if val is None else str(val)
            if ";" in v:
                errs.append(f"{label}: символ «;» недопустим")
                return None
    except (ValueError, TypeError):
        errs.append(f"{label}: «{val}» — ожидается {'IP-адрес' if typ == 'ip' else 'число'}")
        return None
    if typ in ("int", "float"):
        if mn is not None and v < mn or mx is not None and v > mx:
            errs.append(f"{label}: {v} вне диапазона {mn}..{mx}")
            return None
    return v


def build(data: dict, current_settings: dict) -> dict:
    """Проверяет всё, что прислал редактор, и возвращает готовое к записи:
    {"settings": dict, "teams": rows, "devices": rows, "points": {key: rows}}."""
    errs = _Errors()
    fields = data.get("fields", {})
    tables = data.get("tables", {})
    st = copy.deepcopy(current_settings)
    for sec in SECTIONS:
        for f in sec["fields"]:
            if f["key"] not in fields:
                continue
            v = _conv(fields[f["key"]], f["type"], f"{sec['title']} / {f['label']}", errs,
                      mn=f.get("min"), mx=f.get("max"), choices=f.get("choices"))
            if f["key"] == "nodered.autoconnect_team":
                v = v or None
            if v is not None or f["key"] == "nodered.autoconnect_team":
                if f["key"] == "robot_mapping.speed_field" and v == "":
                    v = None
                _set(st, f["key"], v)

    out: dict[str, Any] = {"settings": st}
    tdefs = {t["id"]: t for t in TABLES}

    def rows(tid):
        res = []
        for i, r in enumerate(tables.get(tid, []), 1):
            row = {}
            for c in tdefs[tid]["columns"]:
                v = r.get(c["key"], c.get("default"))
                row[c["key"]] = _conv(v, c["type"], f"{tdefs[tid]['title']}, строка {i}, {c['label']}", errs,
                                      optional=c.get("optional", False), choices=c.get("choices"))
            res.append(row)
        return res

    if "teams" in tables:
        teams = rows("teams")
        if not teams:
            errs.append("Команды: нужна хотя бы одна команда")
        for i, t in enumerate(teams, 1):
            if t.get("PORT") is not None and not 1 <= t["PORT"] <= 65535:
                errs.append(f"Команды, строка {i}: порт {t['PORT']}")
        out["teams"] = teams
    if "devices" in tables:
        devs = rows("devices")
        seen = {}
        for i, d in enumerate(devs, 1):
            if d["STATE"] is not None:
                if d["STATE"] in seen:
                    errs.append(f"Оборудование: ID {d['STATE']} повторяется (строки {seen[d['STATE']]} и {i})")
                seen[d["STATE"]] = i
            if d.get("URL") and not re.match(r"^https?://", d["URL"]):
                errs.append(f"Оборудование, строка {i}: URL должен начинаться с http://")
            if d.get("MODE") and d["KEY"] not in MODE_KEYS:
                errs.append(f"Оборудование, строка {i}: координаты/позиции можно задать только манипулятору (M)")
        names = [d["NAME"] for d in devs if d["NAME"]]
        for n in set(names):
            if names.count(n) > 1:
                errs.append(f"Оборудование: имя {n} повторяется")
        out["devices"] = devs
        overrides = {}
        for d in devs:
            if d["STATE"] is None:
                continue
            ov = {}
            if d.get("URL"):
                ov["url"] = d["URL"]
            if d.get("HTTP_PORT"):
                ov["http_port"] = d["HTTP_PORT"]
            if d.get("MODE"):
                ov["coordinate_mode"] = d["MODE"] == "coord"
            # прочие ручные переопределения из settings.json (robot_mapping и т.п.) сохраняем
            old = current_settings.get("devices", {}).get(str(d["STATE"]), {})
            for k, v in old.items():
                if k not in ("url", "http_port", "coordinate_mode"):
                    ov[k] = v
            if ov:
                overrides[str(d["STATE"])] = ov
        st["devices"] = overrides
    if "drivers" in tables:
        drivers = {}
        for r in rows("drivers"):
            if not r["KEY"]:
                continue
            e = {"driver": r["DRIVER"] or "udp"}
            if r.get("HTTP_PORT"):
                e["http_port"] = r["HTTP_PORT"]
            drivers[r["KEY"]] = e
        st["drivers"] = drivers
    if "poses" in tables:
        fb: dict = {}
        for r in rows("poses"):
            fb.setdefault(r["KEY"], {})[r["WHICH"]] = [r["X"], r["Y"], r["T"], r["Z"]]
        st["fallback_poses"] = fb
    pts = {}
    for k in POINT_FILES:
        tid = f"points_{k}"
        if tid in tables:
            rws = rows(tid)
            nums = [r["NUM"] for r in rws if r["NUM"] is not None]
            for n in set(nums):
                if nums.count(n) > 1:
                    errs.append(f"Позиции {k}: номер {n} повторяется")
            pts[k] = rws
    out["points"] = pts
    errs.check()
    return out


def restart_needed(old: dict, new: dict) -> list[str]:
    res = []
    for sec in SECTIONS:
        for f in sec["fields"]:
            if f.get("restart") and _get(old, f["key"]) != _get(new, f["key"]):
                res.append(f["label"])
    return res


def defaults() -> dict:
    return copy.deepcopy(DEFAULT_SETTINGS)
