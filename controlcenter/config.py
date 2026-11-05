"""Загрузка конфигурации.

Форматы CSV остались прежними (как у IOT Control Center для Windows):
  config/_ServerIPs.csv   IP;PORT;NAME;USERNAME;PASSWORD
  config/_PolygonData.csv STATE;KEY;IP;PORT;NAME;ENTRANCE
  points/_Manipulator.csv   NUM;X;Y;T;Z

Новое: config/settings.json — порты HTTP, драйверы по типам устройств,
сопоставление полей Node-RED с API манипулятора и лампы, интервалы опроса.
"""
from __future__ import annotations

import copy
import csv
import json
import os
from dataclasses import dataclass, field
from typing import Any

from .errors import CCError

DEFAULT_SETTINGS: dict[str, Any] = {
    "nodered": {
        "ws_commands_port": 8765,      # отсюда приходят команды IOT Function
        "ws_feedback_port": 8766,      # сюда уходит обратная связь
        "reconnect_sec": 3,
        "use_basic_auth": False,       # слать логин/пароль из _ServerIPs.csv
        "autoconnect_team": None,      # номер команды (1..N) для автоподключения при старте
    },
    "web": {"host": "0.0.0.0", "port": 8080, "username": "", "password": ""},
    "equipment": {
        "autostart": False,            # сразу «Start Equipment connection»
        "poll_interval_ms": 300,       # опрос состояния устройств
        "robot_slow_poll_ms": 2000,    # температура/нагрузка манипулятора
        "http_timeout_ms": 1500,
        "robot_timeout_ms": 15000,     # команда движения может выполняться долго
        "retries": 2,
        "feedback_heartbeat_ms": 1000, # полная рассылка в Node-RED не реже этого
        "send_to_robots": True,
        "send_to_controls": True,
        "block_resend": True,
        "parse_feedback": True,
        "coordinate_mode": True,       # True — координаты, False — номер позиции из points/
        "udp_listen_port": 8888,       # только для устройств на старом UDP-драйвере
    },
    # драйвер по ключу устройства из _PolygonData.csv
    "drivers": {
        "M": {"driver": "robot", "http_port": 8000},
        "T": {"driver": "lamp", "http_port": 80},
        "R": {"driver": "terminal", "http_port": 80},
        "B1": {"driver": "barrier", "http_port": 80},
        "C": {"driver": "udp"},
        "SC": {"driver": "udp"},
        "BR": {"driver": "udp"},
        "F1": {"driver": "udp"},
        "C1": {"driver": "udp"},
    },
    # переопределения для отдельных устройств по STATE (последний октет IP)
    # пример: "102": {"url": "http://10.30.8.102:8000", "coordinate_mode": false}
    "devices": {},
    "robot_mapping": {
        "x": "X",                # поле Node-RED -> поле API /api/motors/pos/set
        "z": "G",                # в старом протоколе G = высота (Z)
        "angel": "Y",
        "pov_gripper": "T",
        "gripper": "V",          # V (вакуум/схват) -> gripper_state
        "pump_follows_gripper": True,  # дублировать V в /api/motors/pump
        "speed_field": "D0",     # если > 0 — POST /api/motors/speed (1..100)
        "cartesian": False,      # True: X,Y декартовы -> x = sqrt(X²+Y²), angel = atan2(Y,X)
        "start_point": 2000,
        "parking_point": 2001,
    },
    # поля формы Manual Control -> поля API; только для координат, Node-RED и points/ идут через robot_mapping
    "manual_mapping": {"x": "Y", "z": "G", "angel": "X", "pov_gripper": "T"},
    # позиции на случай, если в points/ нет строк 2000/2001: [X, Y, T, Z]
    "fallback_poses": {
        "M": {"start": [220, 0, 0, 180], "parking": [220, 0, 0, 180]},
    },
    "lamp_mapping": {"L1": "red", "L2": "yellow", "L3": "green", "L4": "blue"},
    "terminal": {"text_line_separator": "|", "transliterate_on_overflow": True},
}

POINT_FILES = {"M": "_Manipulator.csv"}
# режим координат/позиций есть только у этих типов
MODE_KEYS = ("M",)

# старые типы и файлы из конфигураций 2.0: читаются как новые.
# Порядок важен: при слиянии побеждает последний (P1 — манипуляторы стенда).
LEGACY_KEYS = {"M1": "M", "P1": "M", "R2": "R"}
LEGACY_POINT_FILES = ("_Angular.csv", "_Industrial.csv", "_Pallitizer.csv")


def _migrate_keys(user: dict) -> dict:
    for sec in ("drivers", "fallback_poses"):
        table = user.get(sec)
        if isinstance(table, dict):
            for old, new in LEGACY_KEYS.items():
                if old in table:
                    table[new] = table.pop(old)
    return user


def _deep_merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _read_csv(path: str) -> list[list[str]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = [[c.strip() for c in r] for r in csv.reader(f, delimiter=";", quoting=csv.QUOTE_NONE)]
    return [r for r in rows if any(r)]


@dataclass
class Team:
    index: int          # 0-based, как кнопки Team 1..N
    ip: str
    port: int
    name: str
    username: str = ""
    password: str = ""

    @property
    def suffix(self) -> str:
        """Номер команды, который вставляется в имена устройств (Robot1_1)."""
        return str(self.index + 1)


@dataclass
class DeviceDef:
    state: str          # последний октет IP — id устройства
    key: str            # тип: M, T, R, B1, C, SC, BR ...
    ip: str
    port: int
    name: str           # имя из _PolygonData (Robot_1, Conveyor)
    entrance: str
    settings: dict = field(default_factory=dict)

    def name_for_team(self, team: Team) -> str:
        """Robot_1 -> Robot{team}_1, Conveyor -> Conveyor{team}. Как в оригинале."""
        parts = self.name.split("_")
        if len(parts) == 1:
            return f"{parts[0]}{team.suffix}"
        return f"{parts[0]}{team.suffix}_{parts[1]}"


class Config:
    def __init__(self, base_dir: str):
        self.base_dir = os.path.abspath(base_dir)
        self.config_dir = os.path.join(self.base_dir, "config")
        self.points_dir = os.path.join(self.base_dir, "points")
        self.logs_dir = os.path.join(self.base_dir, "logs")
        self.settings: dict = {}
        self.teams: list[Team] = []
        self.devices: list[DeviceDef] = []
        self.points: dict[str, dict[int, list[float]]] = {}
        self.load()

    # ------------------------------------------------------------------
    def load(self) -> None:
        s_path = os.path.join(self.config_dir, "settings.json")
        user = {}
        if os.path.exists(s_path):
            try:
                with open(s_path, encoding="utf-8") as f:
                    user = json.load(f)
            except Exception as e:  # noqa: BLE001
                raise CCError(591, f"settings.json: {e}") from e
        self.settings = _deep_merge(DEFAULT_SETTINGS, _migrate_keys(user))
        self.teams = self._load_teams()
        self.devices = self._load_devices()
        self.points = {}
        for key in POINT_FILES:
            try:
                self.points[key] = self._load_points(key)
            except FileNotFoundError:
                self.points[key] = {}
        os.makedirs(self.logs_dir, exist_ok=True)

    def _load_teams(self) -> list[Team]:
        path = os.path.join(self.config_dir, "_ServerIPs.csv")
        try:
            rows = _read_csv(path)[1:]
            teams = []
            for i, r in enumerate(rows):
                teams.append(Team(i, r[0], int(r[1] or 1880), r[2],
                                  r[3] if len(r) > 3 else "", r[4] if len(r) > 4 else ""))
            return teams
        except Exception as e:  # noqa: BLE001
            raise CCError(591, f"_ServerIPs.csv: {e}") from e

    def _load_devices(self) -> list[DeviceDef]:
        path = os.path.join(self.config_dir, "_PolygonData.csv")
        try:
            rows = _read_csv(path)[1:]
            devs = []
            for r in rows:
                state, key, ip, port, name = r[0], LEGACY_KEYS.get(r[1], r[1]), r[2], int(r[3] or 8888), r[4]
                ent = r[5] if len(r) > 5 else "InOut"
                drv = copy.deepcopy(self.settings["drivers"].get(key, {"driver": "udp"}))
                drv.update(self.settings["devices"].get(state, {}))
                devs.append(DeviceDef(state, key, ip, port, name, ent, drv))
            return devs
        except Exception as e:  # noqa: BLE001
            raise CCError(591, f"_PolygonData.csv: {e}") from e

    def _load_points(self, key: str) -> dict[int, list[float]]:
        path = os.path.join(self.points_dir, POINT_FILES[key])
        paths = [path] if os.path.exists(path) else [
            p for p in (os.path.join(self.points_dir, fn) for fn in LEGACY_POINT_FILES) if os.path.exists(p)]
        if not paths:
            raise FileNotFoundError(path)
        try:
            out = {}
            for p in paths:
                for r in _read_csv(p)[1:]:
                    out[int(float(r[0]))] = [float(x) for x in r[1:5]]  # X, Y, T, Z
            return out
        except Exception as e:  # noqa: BLE001
            raise CCError(592, f"{POINT_FILES[key]}: {e}") from e

    def point(self, key: str, num: int) -> list[float] | None:
        return self.points.get(key, {}).get(int(num))


# ----------------------------------------------------------------------------- запись
def _backup(path: str) -> None:
    if os.path.exists(path):
        bdir = os.path.join(os.path.dirname(path), "backup")
        os.makedirs(bdir, exist_ok=True)
        import shutil
        shutil.copy2(path, os.path.join(bdir, os.path.basename(path) + ".bak"))


def _write_csv(path: str, header: list[str], rows: list[list]) -> None:
    _backup(path)
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";", quoting=csv.QUOTE_NONE, lineterminator="\r\n", escapechar="\\")
        w.writerow(header)
        for r in rows:
            w.writerow(["" if v is None else _fmtnum(v) for v in r])
    os.replace(tmp, path)


def _fmtnum(v):
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def save_config(cfg: "Config", built: dict) -> list[str]:
    """Записывает проверенные данные (см. settings_schema.build) в файлы. Возвращает список файлов."""
    written = []
    try:
        os.makedirs(cfg.config_dir, exist_ok=True)
        os.makedirs(cfg.points_dir, exist_ok=True)
        if "settings" in built:
            path = os.path.join(cfg.config_dir, "settings.json")
            _backup(path)
            s = dict(built["settings"])
            s.setdefault("_readme", "Настройки ControlCenter 3. Удобнее менять в самой программе: «Настройки».")
            s = {"_readme": s.pop("_readme"), **s}
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(s, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(path + ".tmp", path)
            written.append("config/settings.json")
        if "teams" in built:
            _write_csv(os.path.join(cfg.config_dir, "_ServerIPs.csv"), ["IP", "PORT", "NAME", "USERNAME", "PASSWORD"],
                       [[t["IP"], t["PORT"], t["NAME"], t.get("USERNAME") or "", t.get("PASSWORD") or ""]
                        for t in built["teams"]])
            written.append("config/_ServerIPs.csv")
        if "devices" in built:
            _write_csv(os.path.join(cfg.config_dir, "_PolygonData.csv"),
                       ["STATE", "KEY", "IP", "PORT", "NAME", "ENTRANCE"],
                       [[d["STATE"], d["KEY"], d["IP"], d["PORT"], d["NAME"], d.get("ENTRANCE") or "InOut"]
                        for d in built["devices"]])
            written.append("config/_PolygonData.csv")
        for key, rows in built.get("points", {}).items():
            _write_csv(os.path.join(cfg.points_dir, POINT_FILES[key]), ["NUM", "X", "Y", "T", "Z"],
                       [[r["NUM"], r["X"], r["Y"], r["T"], r["Z"]] for r in rows])
            written.append(f"points/{POINT_FILES[key]}")
    except OSError as e:
        raise CCError(593, f"не удалось записать настройки: {e}") from e
    return written
