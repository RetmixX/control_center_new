"""Ядро: связывает Node-RED, оборудование и веб-интерфейс."""
from __future__ import annotations

import asyncio
import collections
import json
import logging
import os
import time
from typing import Any

import aiohttp

from .config import Config, DeviceDef, Team
from .drivers import DRIVERS, Command, Device, DeviceContext, UdpDevice, UdpTransport
from .errors import ERROR_TEXT, CCError
from .nodered import WsLink

log = logging.getLogger("controlcenter")

ROBOT_KEYS = {"M", "F1"}


def pending_workers(ctl) -> list:
    return list(ctl._workers.values())


class Controller:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.cfg = Config(base_dir)
        self.settings = self.cfg.settings
        eq = self.settings["equipment"]
        self.flags = {
            "send_to_robots": eq["send_to_robots"],
            "send_to_controls": eq["send_to_controls"],
            "block_resend": eq["block_resend"],
            "parse_feedback": eq["parse_feedback"],
            "coordinate_mode": eq["coordinate_mode"],
            "selective_dispatch": True,
            "write_log": True,
        }
        self.team: Team | None = None
        self.nodered_ip = ""
        self.nodered_port = 0
        self.devices: list[Device] = []
        self.session: aiohttp.ClientSession | None = None
        self.udp: UdpTransport | None = None
        self.udp_error = ""
        self.equipment_running = False
        self.nodered_enabled = False
        self.last_error_code = 0
        self._logs: collections.deque = collections.deque(maxlen=3000)
        self._log_id = 0
        self._tasks: list[asyncio.Task] = []
        self._queues: dict[str, asyncio.Queue] = {}
        self._workers: dict[str, asyncio.Task] = {}
        self._last_sig: dict[str, tuple] = {}
        self._last_fb: dict[str, str] = {}
        self._last_cmd: dict[str, dict] = {}
        self.cmd_link: WsLink | None = None
        self.fb_link: WsLink | None = None
        self.listeners: list = []   # callback(entry) — живой вывод журнала (CLI, desktop)

    # ------------------------------------------------------------------ жизненный цикл
    async def start(self) -> None:
        self.session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=64, force_close=True))
        self.ctx = DeviceContext(self.settings, self.session, self.event, self.error, self.cfg.point)
        self._build_devices()
        if any(isinstance(d, UdpDevice) for d in self.devices):
            await self._open_udp()
        self.cmd_link = WsLink("commands", self.session, self._ws_state, self.on_nodered_message)
        self.fb_link = WsLink("feedback", self.session, self._ws_state)
        auto = self.settings["nodered"].get("autoconnect_team")
        if self.cfg.teams and not auto:
            self.select_team(0)
        if auto:
            self.select_team(int(auto) - 1)
            self.connect_nodered()
        if self.settings["equipment"]["autostart"]:
            self.start_equipment()
        self._tasks.append(asyncio.create_task(self._heartbeat(), name="feedback-heartbeat"))
        self.event(f"ControlCenter запущен: {len(self.devices)} устройств, {len(self.cfg.teams)} команд")

    async def stop(self) -> None:
        self.stop_equipment()
        for link in (self.cmd_link, self.fb_link):
            if link:
                await link.stop()
        pending = list(self._tasks) + list(self._workers.values())
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        self._tasks.clear()
        self._workers.clear()
        self._queues.clear()
        if self.udp and self.udp.transport:
            self.udp.transport.close()
        if self.session:
            await self.session.close()

    async def _open_udp(self) -> None:
        port = self.settings["equipment"]["udp_listen_port"]
        loop = asyncio.get_running_loop()
        try:
            _, proto = await loop.create_datagram_endpoint(
                lambda: UdpTransport(self._on_udp), local_addr=("0.0.0.0", port))
            self.udp = proto
            self.udp_error = ""
        except OSError as e:
            self.udp_error = f"UDP-порт {port} занят или недоступен: {e}"
            self.error(601, self.udp_error)

    def _build_devices(self) -> None:
        self.devices = []
        for dd in self.cfg.devices:
            drv = dd.settings.get("driver", "udp")
            if drv == "udp":
                dev: Device = UdpDevice(dd, self.ctx, lambda: self.udp)
            elif drv in DRIVERS:
                dev = DRIVERS[drv](dd, self.ctx)
            else:
                self.error(591, f"неизвестный драйвер {drv!r} для {dd.name}")
                continue
            self.devices.append(dev)

    async def reload_config(self) -> None:
        if self.nodered_enabled or self.equipment_running:
            raise CCError(591, "остановите связь с Node-RED и оборудованием перед перезагрузкой конфигурации")
        self.cfg.load()
        self.settings.clear()
        self.settings.update(self.cfg.settings)
        self.cfg.settings = self.settings
        self._build_devices()
        if any(isinstance(d, UdpDevice) for d in self.devices) and self.udp is None:
            await self._open_udp()
        if self.cfg.teams:
            self.select_team(min(self.team.index if self.team else 0, len(self.cfg.teams) - 1))
        self.event("Конфигурация перечитана")

    # ------------------------------------------------------------------ журналы
    def _push(self, channel: str, text: str) -> None:
        self._log_id += 1
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = {"id": self._log_id, "ts": ts, "ch": channel, "text": text}
        self._logs.append(entry)
        log.info("[%s] %s", channel, text)
        for cb in list(self.listeners):
            try:
                cb(entry)
            except Exception:  # noqa: BLE001
                pass
        if self.flags["write_log"] and self.team is not None and channel in ("nodered", "equipment", "error"):
            fname = {"nodered": "log_From_NodeRed_Team", "equipment": "log_From_Equipment_Team",
                     "error": "log_ErrorCode_Team"}[channel]
            try:
                with open(os.path.join(self.cfg.logs_dir, f"{fname}{self.team.suffix}.txt"), "a",
                          encoding="utf-8") as f:
                    f.write(f"[log_info] <{ts}> {text}\n")
            except OSError as e:
                if channel != "error":
                    self.flags["write_log"] = False
                    self.error(593, str(e))

    def event(self, text: str) -> None:
        self._push("event", text)

    def error(self, code: int, detail: str = "") -> None:
        self.last_error_code = code
        self._push("error", f"Code {code}: {ERROR_TEXT.get(code, '')}" + (f" — {detail}" if detail else ""))

    def logs_since(self, since: int) -> list[dict]:
        return [e for e in self._logs if e["id"] > since]

    # ------------------------------------------------------------------ команды / устройства
    def device_by_state(self, state: str) -> Device:
        for d in self.devices:
            if d.d.state == str(state):
                return d
        raise CCError(570, f"нет устройства с id {state}")

    def select_team(self, index: int) -> None:
        if self.nodered_enabled:
            raise CCError(404, "сначала остановите связь с Node-RED")
        if not 0 <= index < len(self.cfg.teams):
            raise CCError(591, f"нет команды с номером {index + 1}")
        self.team = self.cfg.teams[index]
        self.nodered_ip, self.nodered_port = self.team.ip, self.team.port
        for d in self.devices:
            d.name = d.d.name_for_team(self.team)
        self._last_sig.clear()
        self.event(f"Выбрана команда «{self.team.name}» (Node-RED {self.team.ip}); имена устройств: "
                   + ", ".join(d.name for d in self.devices))

    def connect_nodered(self, ip: str | None = None) -> None:
        if self.team is None:
            raise CCError(591, "не выбрана команда")
        if ip:
            self.nodered_ip = ip.split(":")[0].strip()
        nr = self.settings["nodered"]
        auth = None
        if nr.get("use_basic_auth") and self.team.username:
            auth = aiohttp.BasicAuth(self.team.username, self.team.password)
        host = self.nodered_ip
        self.nodered_enabled = True
        self.cmd_link.start(f"ws://{host}:{nr['ws_commands_port']}", auth, nr["reconnect_sec"])
        self.fb_link.start(f"ws://{host}:{nr['ws_feedback_port']}", auth, nr["reconnect_sec"])
        self.event(f"Подключение к Node-RED ws://{host}:{nr['ws_commands_port']} и :{nr['ws_feedback_port']}")

    async def disconnect_nodered(self) -> None:
        self.nodered_enabled = False
        await self.cmd_link.stop()
        await self.fb_link.stop()
        self._last_sig.clear()
        self.event("Связь с Node-RED остановлена")

    def _ws_state(self, name: str, ok: bool, why: str) -> None:
        link = self.cmd_link if name == "commands" else self.fb_link
        if link is None:
            return
        if ok:
            link._reported = False  # type: ignore[attr-defined]
            self.event(f"Node-RED [{name}]: подключено ({link.url})")
            if name == "feedback":
                # после (пере)подключения отдаём Node-RED полный снимок состояния
                asyncio.get_event_loop().call_later(0.3, lambda: asyncio.ensure_future(self._publish_all()))
        elif self.nodered_enabled and not getattr(link, "_reported", False):
            # ошибка 404 как в оригинале, но без спама: один раз на обрыв
            link._reported = True  # type: ignore[attr-defined]
            self.error(404, f"Node-RED [{name}] {link.url}: {why}; переподключение каждые "
                            f"{self.settings['nodered']['reconnect_sec']} с")

    def set_flags(self, flags: dict) -> None:
        for k, v in flags.items():
            if k in self.flags:
                self.flags[k] = bool(v)
                if k in self.settings["equipment"]:
                    self.settings["equipment"][k] = bool(v)
        if "block_resend" in flags:
            self._last_sig.clear()

    async def on_nodered_message(self, text: str) -> None:
        try:
            data = json.loads(text)
        except ValueError:
            return  # оригинал тоже молча ждал корректного JSON
        if isinstance(data, list):
            for item in data:
                await self._handle_nodered(item)
        elif isinstance(data, dict):
            await self._handle_nodered(data)

    async def _handle_nodered(self, data: dict) -> None:
        name = data.get("robot_name")
        if name is None:
            self.error(471, json.dumps(data, ensure_ascii=False)[:200])
            return
        dev = next((d for d in self.devices if d.name == str(name)), None)
        if dev is None:
            self.error(570, f"{name!r}; ожидаются: {', '.join(d.name for d in self.devices)}")
            return
        try:
            cmd = Command.from_json(data)
        except CCError as e:
            self.error(e.code, f"{name}: {e.detail}")
            return
        sig = cmd.signature()
        if self.flags["block_resend"] and self._last_sig.get(dev.d.state) == sig:
            return
        self._last_sig[dev.d.state] = sig
        self._last_cmd[dev.d.state] = cmd.as_dict()
        self._push("nodered", json.dumps(data, ensure_ascii=False))
        self.enqueue(dev, cmd)

    def enqueue(self, dev: Device, cmd: "Command | tuple") -> None:
        q = self._queues.get(dev.d.state)
        if q is None:
            q = self._queues[dev.d.state] = asyncio.Queue(maxsize=100)
            self._workers[dev.d.state] = asyncio.create_task(self._worker(dev, q), name=f"cmd-{dev.d.state}")
        if not dev.is_robot:
            # для ламп/терминала важна только последняя команда
            while not q.empty():
                q.get_nowait()
        if q.full():
            q.get_nowait()
            self.event(f"{dev.name}: очередь команд переполнена, самая старая отброшена")
        q.put_nowait(cmd)

    async def _worker(self, dev: Device, q: asyncio.Queue) -> None:
        while True:
            cmd = await q.get()
            try:
                if isinstance(cmd, tuple):  # ("special", code) — кнопки Send 1/2/3
                    if not self.equipment_running or not self._allowed(dev):
                        continue
                    r = await dev.special(cmd[1])
                    self._push("equipment", f"{dev.name} <- кнопка {cmd[1]}: {r}")
                    await self._publish(dev, force=True)
                else:
                    await self._execute(dev, cmd)
            except CCError as e:
                self.error(e.code, e.detail)
            except Exception as e:  # noqa: BLE001
                self.error(582, f"{dev.name}: {type(e).__name__}: {e}")

    def _allowed(self, dev: Device) -> bool:
        robot = dev.is_robot or dev.d.key in ROBOT_KEYS
        return self.flags["send_to_robots"] if robot else self.flags["send_to_controls"]

    async def _execute(self, dev: Device, cmd: Command) -> None:
        if not self.equipment_running or not self._allowed(dev):
            why = "связь с оборудованием не запущена" if not self.equipment_running else "отправка отключена флажком"
            self._push("equipment", f"[не отправлено: {why}] {dev.name} <- {cmd.as_dict()}")
            return
        t0 = time.monotonic()
        res = await dev.send(cmd)
        self._push("equipment", f"{dev.name} [{dev.base_url if dev.driver != 'udp' else 'udp'}] <- {res} "
                                f"[N={cmd.N} V={cmd.V}] {int((time.monotonic() - t0) * 1000)} мс")
        await self._publish(dev, force=True)

    async def manual_command(self, target: str, data: dict, key: str | None = None) -> None:
        """key: при target == "all" команда уходит только устройствам этого типа (форма показывает его поля)."""
        if self.nodered_enabled:
            raise CCError(404, "при подключении к Node-RED ручное управление недоступно")
        cmd = Command.from_json(data)
        cmd.manual = True
        if target == "all":
            targets = [d for d in self.devices if key is None or d.d.key == key]
        else:
            targets = [self.device_by_state(target)]
        for d in targets:
            self.enqueue(d, cmd)

    async def special(self, target: str, code: str) -> list[str]:
        targets = self.devices if target == "all" else [self.device_by_state(target)]
        out = []
        for d in targets:
            if code in ("r", "s"):
                d.polling = code == "r"
                out.append(f"{d.name}: опрос {'включён' if d.polling else 'выключен'}")
                if isinstance(d, UdpDevice) and self.equipment_running:
                    try:
                        await d.special(code)
                    except CCError:
                        pass
                continue
            if not self.equipment_running:
                raise CCError(582, "сначала запустите связь с оборудованием")
            if not self._allowed(d):
                out.append(f"{d.name}: пропущено (отправка отключена флажком)")
                continue
            if target == "all" and code == "3" and d.driver != "udp" and not d.is_robot:
                continue  # «расслабить звенья» касается только манипуляторов
            self.enqueue(d, ("special", code))
            out.append(f"{d.name}: кнопка {code} поставлена в очередь")
        return out

    # ------------------------------------------------------------------ опрос и обратная связь
    def start_equipment(self) -> None:
        if self.equipment_running:
            return
        self.equipment_running = True
        for d in self.devices:
            if d.driver != "udp":
                self._tasks.append(asyncio.create_task(self._poll_loop(d), name=f"poll-{d.d.state}"))
        self.event("Связь с оборудованием запущена")

    def stop_equipment(self) -> None:
        self.equipment_running = False
        for t in list(self._tasks):
            if t.get_name().startswith("poll-"):
                t.cancel()
                self._tasks.remove(t)
        for d in self.devices:
            d.online = False
            d.api_error = ""
        self.event("Связь с оборудованием остановлена")

    async def _poll_loop(self, dev: Device) -> None:
        eq = self.settings["equipment"]
        while self.equipment_running:
            delay = eq["poll_interval_ms"] / 1000
            if dev.polling and self.flags["parse_feedback"]:
                try:
                    await dev.poll()
                    dev.clear_api_error()
                    await self._publish(dev)
                except CCError as e:
                    if e.code == 584:
                        dev.mark_api_error(e.detail)
                    elif e.code not in (581, 582, 583):  # недоступность уже записана в журнал
                        self.error(e.code, e.detail)
                    if not dev.online:
                        delay = max(delay, 2.0)
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    self.error(601, f"{dev.name}: {type(e).__name__}: {e}")
                    delay = max(delay, 2.0)
            await asyncio.sleep(delay)

    def _on_udp(self, text: str, addr) -> None:
        if not self.flags["parse_feedback"]:
            return
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            f = line.split("#")[0].split(":")
            if len(f) < 2:
                continue
            try:
                dev = self.device_by_state(f[1])
            except CCError:
                continue
            if isinstance(dev, UdpDevice):
                try:
                    dev.ingest(f)
                except (ValueError, IndexError) as e:
                    self.error(601, f"{line}: {e}")
                    continue
                asyncio.get_event_loop().create_task(self._publish(dev))

    def feedback_message(self, dev: Device) -> dict:
        msg = {"name": dev.name}
        msg.update(dev.feedback)
        msg["online"] = dev.online
        return msg

    async def _publish(self, dev: Device, force: bool = False) -> None:
        if not self.flags["parse_feedback"] or self.fb_link is None or not self.fb_link.connected:
            return
        msg = self.feedback_message(dev)
        s = json.dumps(msg, sort_keys=True)
        if not force and self._last_fb.get(dev.d.state) == s:
            return
        self._last_fb[dev.d.state] = s
        await self.fb_link.send_json(msg)

    async def _publish_all(self) -> None:
        for d in self.devices:
            await self._publish(d, force=True)

    async def _heartbeat(self) -> None:
        while True:
            ms = self.settings["equipment"]["feedback_heartbeat_ms"]
            if not ms or ms <= 0:
                await asyncio.sleep(1)
                continue
            await asyncio.sleep(max(ms, 100) / 1000)
            if self.equipment_running:
                await self._publish_all()

    # ------------------------------------------------------------------ редактор настроек
    def get_config(self) -> dict:
        from . import settings_schema
        return settings_schema.export(self.cfg, self.settings)

    async def save_config(self, data: dict) -> dict:
        """Проверить, записать в файлы и сразу применить. Связь с Node-RED и оборудованием
        на время перезагрузки останавливается и затем восстанавливается."""
        from . import settings_schema
        from .config import save_config
        data = settings_schema.preserve_hidden(self.cfg, self.settings, data)
        built = settings_schema.build(data, self.settings)
        restart = settings_schema.restart_needed(self.settings, built["settings"])
        was_nr, was_eq = self.nodered_enabled, self.equipment_running
        team_name = self.team.name if self.team else None
        old_udp_port = self.settings["equipment"]["udp_listen_port"]
        files = save_config(self.cfg, built)
        if was_nr:
            await self.disconnect_nodered()
        if was_eq:
            self.stop_equipment()
        for t in pending_workers(self):
            t.cancel()
        self._workers.clear()
        self._queues.clear()
        await self.reload_config()
        for k in ("send_to_robots", "send_to_controls", "block_resend", "parse_feedback", "coordinate_mode"):
            self.flags[k] = bool(self.settings["equipment"][k])
        if self.settings["equipment"]["udp_listen_port"] != old_udp_port and self.udp and self.udp.transport:
            self.udp.transport.close()
            self.udp = None
            if any(isinstance(d, UdpDevice) for d in self.devices):
                await self._open_udp()
            restart = [r for r in restart if "UDP" not in r]
        if team_name:
            idx = next((t.index for t in self.cfg.teams if t.name == team_name), None)
            if idx is not None:
                self.select_team(idx)
        if was_eq:
            self.start_equipment()
        if was_nr and self.team:
            self.connect_nodered()
        self.event("Настройки сохранены: " + ", ".join(files)
                   + (f". После перезапуска программы применится: {', '.join(restart)}" if restart else ""))
        return {"files": files, "restart": restart}

    # ------------------------------------------------------------------ для веб-интерфейса
    def state(self, since: int = 0) -> dict:
        return {
            "teams": [{"index": t.index, "name": t.name, "ip": t.ip, "port": t.port} for t in self.cfg.teams],
            "team": self.team.index if self.team else None,
            "nodered": {
                "enabled": self.nodered_enabled, "ip": self.nodered_ip,
                "commands": bool(self.cmd_link and self.cmd_link.connected),
                "feedback": bool(self.fb_link and self.fb_link.connected),
                "ports": [self.settings["nodered"]["ws_commands_port"], self.settings["nodered"]["ws_feedback_port"]],
            },
            "equipment_running": self.equipment_running,
            "flags": self.flags,
            "udp_error": self.udp_error,
            "last_error_code": self.last_error_code,
            "devices": [dict(d.info(), last_cmd=self._last_cmd.get(d.d.state),
                             last_cmd_form=d.manual_fields(self._last_cmd[d.d.state])
                             if d.d.state in self._last_cmd else None,
                             queue=self._queues[d.d.state].qsize() if d.d.state in self._queues else 0)
                        for d in self.devices if d.driver != "udp"],
            "logs": self.logs_since(since),
        }
