"""CLI-версия (сервер Linux): без графики, журнал в консоль/journald, управление командами из консоли
и (необязательно) через веб-интерфейс.

  python -m controlcenter [--dir ПАПКА] [--team N] [--equipment] [--no-web] [--port 8080] [--no-console]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
import signal
import sys

from . import __version__
from .controller import Controller
from .errors import CCError
from .runtime import start_web

USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
COLORS = {"error": "31", "nodered": "36", "equipment": "32", "event": "90"}
FLAG_ALIASES = {
    "robots": "send_to_robots", "controls": "send_to_controls", "block": "block_resend",
    "parse": "parse_feedback", "coord": "coordinate_mode", "log": "write_log",
}

HELP = """Команды:
  status                     состояние Node-RED, оборудования, флагов
  devices | dev              устройства и обратная связь
  dev <id>                   подробно об одном устройстве (id = STATE из _PolygonData.csv)
  teams                      список команд
  team <N>                   выбрать команду N (1..)
  connect [IP]               подключиться к Node-RED (IP по умолчанию из _ServerIPs.csv)
  disconnect                 отключиться от Node-RED
  start | stop               Start/Stop Equipment connection
  send <id|all> K=V ...      ручная команда IOT Function, например: send 102 N=1 X=30 Y=200 G=120 V=1  (X — angel, Y — x); терминал: send 106 L1=1 Line=2 Text="Привет"
                             send 106 L1=1 Text="Этап 2|Нажмите СТАРТ"
  btn <id|all> <r|s|1|2|3>   кнопки Special Activity
  flag [имя on|off]          флаги: robots controls block parse coord log
  mode <id> coord|pos|default   режим координат/позиций для манипулятора
  http <id> GET|POST|PATCH|PUT /path [JSON]   прямой запрос к HTTP API устройства
  show [all|none|error|nodered|equipment|event ...]   какие журналы печатать
  --- настройки (сохраняются в файлы и сразу применяются) ---
  config                     все настройки и список таблиц
  get <ключ>                 значение, например: get equipment.poll_interval_ms
  set <ключ> <значение>      изменить, например: set robot_mapping.angel T
  table <таблица>            показать таблицу: teams, devices, drivers, poses, points_M
  row <таблица> add K=V ...          добавить строку:  row points_M add NUM=2000 X=220 Y=0 T=0 Z=180
  row <таблица> <номер> K=V ...      изменить строку:  row devices 1 URL=http://10.30.8.102:8000
  row <таблица> del <номер>          удалить строку
  reload                     перечитать config/ и points/ с диска
  help                       эта справка
  quit | exit                завершить"""


def paint(ch: str, text: str) -> str:
    if not USE_COLOR:
        return text
    return f"\033[{COLORS.get(ch, '0')}m{text}\033[0m"


class Console:
    def __init__(self, ctl: Controller, stop: asyncio.Event, show: set[str]):
        self.ctl = ctl
        self.stop = stop
        self.show = show

    def on_log(self, e: dict) -> None:
        if e["ch"] in self.show:
            print(paint(e["ch"], f"<{e['ts']}> [{e['ch']}] {e['text']}"), flush=True)

    # ------------------------------------------------------------------
    def status(self) -> None:
        s = self.ctl.state(10 ** 12)
        nr = s["nodered"]
        team = s["teams"][s["team"]]["name"] if s["team"] is not None else "—"
        print(f"Команда: {team}   Node-RED {nr['ip']}: "
              f"{'вкл' if nr['enabled'] else 'выкл'} (команды :{nr['ports'][0]} "
              f"{'OK' if nr['commands'] else '--'}, обратная связь :{nr['ports'][1]} {'OK' if nr['feedback'] else '--'})")
        on = sum(d["online"] for d in s["devices"])
        print(f"Оборудование: {'запущено' if s['equipment_running'] else 'остановлено'}, на связи {on}/{len(s['devices'])}")
        print("Флаги: " + ", ".join(f"{k}={'on' if v else 'off'}" for k, v in s["flags"].items()))
        if s["udp_error"]:
            print(paint("error", s["udp_error"]))

    def devices(self) -> None:
        s = self.ctl.state(10 ** 12)
        print(f"{'id':>4} {'имя':<18} {'тип':<4} {'драйвер':<9} {'связь':<6} обратная связь")
        for d in s["devices"]:
            fb = " ".join(f"{k}={_fmt(v)}" for k, v in d["feedback"].items() if v not in (0, None, "0"))
            st = ("занят" if d["busy"] else "OK") if d["online"] else "--"
            print(f"{d['state']:>4} {d['name']:<18} {d['key']:<4} {d['driver']:<9} {st:<6} {fb}")

    def device(self, sid: str) -> None:
        d = self.ctl.device_by_state(sid).info()
        d["feedback"] = {k: v for k, v in d["feedback"].items() if v not in (0, None, "0")}
        d.pop("last_seen", None)
        print(json.dumps(d, ensure_ascii=False, indent=1, default=str))

    async def handle(self, line: str) -> None:
        try:
            args = shlex.split(line)
        except ValueError as e:
            print(f"Ошибка разбора: {e}")
            return
        if not args:
            return
        c, a = args[0].lower(), args[1:]
        ctl = self.ctl
        if c in ("help", "?", "h"):
            print(HELP)
        elif c in ("quit", "exit", "q"):
            self.stop.set()
        elif c == "status":
            self.status()
        elif c in ("devices", "dev"):
            self.device(a[0]) if a else self.devices()
        elif c == "teams":
            for t in ctl.cfg.teams:
                mark = "*" if ctl.team and ctl.team.index == t.index else " "
                print(f"{mark}{t.index + 1:>3}  {t.name:<16} {t.ip}:{t.port}")
        elif c == "team":
            ctl.select_team(int(a[0]) - 1)
        elif c == "connect":
            ctl.connect_nodered(a[0] if a else None)
        elif c == "disconnect":
            await ctl.disconnect_nodered()
        elif c == "start":
            ctl.start_equipment()
        elif c == "stop":
            ctl.stop_equipment()
        elif c == "send":
            if not a:
                raise ValueError("send <id|all> K=V ...")
            cmd = {}
            for kv in a[1:]:
                k, _, v = kv.partition("=")
                cmd[k if k.lower() != "text" else "Text"] = v
            await ctl.manual_command(a[0], cmd)
        elif c == "btn":
            for r in await ctl.special(a[0], a[1]):
                print(r)
        elif c == "flag":
            if len(a) >= 2:
                name = FLAG_ALIASES.get(a[0], a[0])
                if name not in ctl.flags:
                    raise ValueError(f"нет флага {a[0]}")
                ctl.set_flags({name: a[1].lower() in ("on", "1", "true", "да")})
            print(", ".join(f"{k}={'on' if v else 'off'}" for k, v in ctl.flags.items()))
        elif c == "mode":
            d = ctl.device_by_state(a[0])
            d.set_mode({"coord": True, "pos": False, "default": None}[a[1]])
            print(f"{d.name}: режим {a[1]}")
        elif c == "http":
            parts = line.split(None, 4)  # JSON берём из исходной строки: shlex съедает кавычки
            if len(parts) < 4:
                raise ValueError("http <id> GET|POST|PATCH|PUT /path [JSON]")
            d = ctl.device_by_state(parts[1])
            a = parts[1:]
            body = json.loads(parts[4]) if len(parts) > 4 else None
            r = await d.http(a[1].upper(), a[2], body, retries=0,
                             timeout_ms=ctl.settings["equipment"]["robot_timeout_ms"])
            print(json.dumps(r, ensure_ascii=False, indent=1))
        elif c == "show":
            chans = {"error", "nodered", "equipment", "event"}
            if not a or a[0] == "all":
                self.show.update(chans)
            elif a[0] == "none":
                self.show.clear()
            else:
                self.show.clear()
                self.show.update(x for x in a if x in chans)
            print("Печатаются журналы: " + (", ".join(sorted(self.show)) or "нет"))
        elif c == "config":
            cfg = ctl.get_config()
            for sec in cfg["schema"]["sections"]:
                print(paint("event", f"[{sec['title']}]"))
                for f in sec["fields"]:
                    v = cfg["values"]["fields"][f["key"]]
                    if f["type"] == "password" and v:
                        v = "***"
                    print(f"  {f['key']:<38} = {v!s:<14} {f['label']}")
            print(paint("event", "Таблицы: ") + ", ".join(
                f"{t['id']} ({len(cfg['values']['tables'].get(t['id'], []))})" for t in cfg["schema"]["tables"]))
        elif c == "get":
            cfg = ctl.get_config()
            print(cfg["values"]["fields"][a[0]])
        elif c == "set":
            if len(a) < 2:
                raise ValueError("set <ключ> <значение>")
            cfg = ctl.get_config()
            if a[0] not in cfg["values"]["fields"]:
                raise KeyError(f"нет настройки {a[0]} (список — команда config)")
            cfg["values"]["fields"][a[0]] = " ".join(a[1:])
            self._saved(await ctl.save_config(cfg["values"]))
        elif c == "table":
            cfg = ctl.get_config()
            t = self._tdef(cfg, a[0])
            rows = cfg["values"]["tables"].get(a[0], [])
            cols = [col["key"] for col in t["columns"]]
            w = {k: max([len(k)] + [len(str(r.get(k, "")) ) for r in rows]) for k in cols}
            print("  № " + " ".join(f"{k:<{w[k]}}" for k in cols))
            for i, r in enumerate(rows, 1):
                print(f"{i:>3} " + " ".join(f"{str(r.get(k, '')):<{w[k]}}" for k in cols))
        elif c == "row":
            if len(a) < 2:
                raise ValueError("row <таблица> add|<номер>|del <номер> K=V ...")
            cfg = ctl.get_config()
            t = self._tdef(cfg, a[0])
            rows = cfg["values"]["tables"].setdefault(a[0], [])
            kv = {}
            for x in a[2:] if a[1] != "del" else []:
                k, _, v = x.partition("=")
                k = k.upper()
                if k not in [col["key"] for col in t["columns"]]:
                    raise KeyError(f"нет столбца {k}; есть: {', '.join(col['key'] for col in t['columns'])}")
                kv[k] = v
            if a[1] == "add":
                if t.get("fixed_rows"):
                    raise ValueError("в этой таблице нельзя добавлять строки")
                rows.append({col["key"]: col.get("default", "") for col in t["columns"]} | kv)
            elif a[1] == "del":
                if t.get("fixed_rows"):
                    raise ValueError("в этой таблице нельзя удалять строки")
                rows.pop(int(a[2]) - 1)
            else:
                rows[int(a[1]) - 1].update(kv)
            self._saved(await ctl.save_config(cfg["values"]))
        elif c == "reload":
            await ctl.reload_config()
        else:
            print(f"Неизвестная команда «{c}». help — список команд")

    @staticmethod
    def _tdef(cfg, tid):
        t = next((x for x in cfg["schema"]["tables"] if x["id"] == tid), None)
        if t is None:
            raise KeyError(f"нет таблицы {tid}; есть: " + ", ".join(x["id"] for x in cfg["schema"]["tables"]))
        return t

    @staticmethod
    def _saved(res):
        print("Сохранено и применено" + (f"; после перезапуска: {', '.join(res['restart'])}" if res["restart"] else ""))

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        print("Введите help для списка команд.", flush=True)
        while not self.stop.is_set():
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if line == "":  # EOF: stdin закрыт — дальше работаем как служба
                return
            try:
                await self.handle(line.strip())
            except CCError as e:
                print(paint("error", str(e)))
            except (ValueError, KeyError, IndexError) as e:
                print(paint("error", f"Ошибка: {e}. help — справка"))


def _fmt(v):
    return round(v, 2) if isinstance(v, float) else v


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="controlcenter",
                                description="IoT ControlCenter — CLI/серверная версия (Linux, macOS, Windows)")
    p.add_argument("--dir", default=os.environ.get("CC_DIR", os.getcwd()),
                   help="папка с config/, points/, logs/ (по умолчанию текущая)")
    p.add_argument("--team", type=int, help="номер команды (1..N): сразу подключиться к её Node-RED")
    p.add_argument("--nodered-ip", help="IP Node-RED вместо указанного в _ServerIPs.csv")
    p.add_argument("--equipment", action="store_true", help="сразу запустить связь с оборудованием")
    p.add_argument("--no-web", action="store_true", help="не запускать веб-интерфейс")
    p.add_argument("--host", help="адрес веб-интерфейса (по умолчанию 0.0.0.0)")
    p.add_argument("--port", type=int, help="порт веб-интерфейса (по умолчанию 8080)")
    p.add_argument("--no-console", action="store_true",
                   help="без интерактивной консоли (для systemd/Docker; включается сам, если нет терминала)")
    p.add_argument("--console", action="store_true", help="включить консоль, даже если stdin не терминал")
    p.add_argument("--quiet", action="store_true", help="печатать только ошибки")
    p.add_argument("--version", action="version", version=f"ControlCenter {__version__}")
    return p.parse_args(argv)


async def amain(args) -> int:
    try:
        ctl = Controller(args.dir)
    except CCError as e:
        print(f"Ошибка конфигурации: {e}", file=sys.stderr)
        return 2
    stop = asyncio.Event()
    show = {"error"} if args.quiet else {"error", "nodered", "equipment", "event"}
    console = Console(ctl, stop, show)
    ctl.listeners.append(console.on_log)
    if args.team:
        ctl.settings["nodered"]["autoconnect_team"] = args.team
    if args.equipment:
        ctl.settings["equipment"]["autostart"] = True
    await ctl.start()
    if args.nodered_ip and ctl.nodered_enabled:
        await ctl.disconnect_nodered()
        ctl.connect_nodered(args.nodered_ip)

    runner = None
    if not args.no_web:
        host = args.host or ctl.settings["web"]["host"]
        port = args.port or ctl.settings["web"]["port"]
        try:
            runner = await start_web(ctl, host, port)
            print(f"ControlCenter {__version__} (CLI): веб-интерфейс http://{host}:{port}/", flush=True)
        except OSError as e:
            print(paint("error", f"Веб-интерфейс не запущен: порт {port} занят? ({e})"), flush=True)
    else:
        print(f"ControlCenter {__version__} (CLI), веб-интерфейс выключен", flush=True)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    console_task = None
    if args.console or (not args.no_console and sys.stdin and sys.stdin.isatty()):
        console_task = asyncio.create_task(console.run())
    try:
        await stop.wait()
    finally:
        print("Остановка...", flush=True)
        if console_task:
            console_task.cancel()
        await ctl.stop()
        if runner:
            await runner.cleanup()
    return 0


def main(argv=None) -> None:
    args = parse_args(argv)
    try:
        code = asyncio.run(amain(args))
    except KeyboardInterrupt:
        code = 0
    # поток чтения stdin может висеть на readline — выходим без ожидания
    sys.stdout.flush()
    os._exit(code)
