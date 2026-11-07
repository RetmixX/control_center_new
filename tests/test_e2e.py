"""Сквозные тесты ControlCenter на эмуляторе стенда (tools/emulator.py), без железа.

    pip install -r requirements.txt pytest
    python -m pytest -q

Каждый тест поднимает эмуляторы устройств и «Node-RED» на свободных портах 127.0.0.1,
пишет временные config/ и points/ и запускает Controller.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import shutil
import socket
import sys

import aiohttp
from aiohttp import web

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from controlcenter.controller import Controller  # noqa: E402
from controlcenter.errors import CCError  # noqa: E402

_spec = importlib.util.spec_from_file_location("emulator", os.path.join(ROOT, "tools", "emulator.py"))
emu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(emu)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Bench:
    """Эмуляторы + конфиг + контроллер."""

    def __init__(self, tmp):
        self.tmp = str(tmp)
        self.runners = []
        self.ports = {}

    async def serve(self, name, app):
        port = free_port()
        r = web.AppRunner(app, access_log=None)
        await r.setup()
        await web.TCPSite(r, "127.0.0.1", port).start()
        self.runners.append(r)
        self.ports[name] = port
        return port

    async def start(self, nodered=True, settings_patch=None, with_udp=False):
        await self.serve("robot", emu.robot_app(1))
        await self.serve("lamp", emu.lamp_app())
        await self.serve("term", emu.terminal_app())
        await self.serve("barrier", emu.barrier_app())
        c, f, h = emu.nodered_apps()
        await self.serve("nr_cmd", c)
        await self.serve("nr_fb", f)
        await self.serve("nr_http", h)

        os.makedirs(os.path.join(self.tmp, "config"))
        shutil.copytree(os.path.join(ROOT, "points"), os.path.join(self.tmp, "points"))
        with open(os.path.join(self.tmp, "points", "_Manipulator.csv"), "a", newline="") as fh:
            fh.write("2000;220;0;0;180\r\n2001;100;50;0;150\r\n")
        with open(os.path.join(self.tmp, "config", "_ServerIPs.csv"), "w", newline="") as fh:
            fh.write("IP;PORT;NAME;USERNAME;PASSWORD\r\n127.0.0.1;1880;Team 1;u;p\r\n10.0.0.2;1880;Team 2;u;p\r\n")
        shutil.copy(os.path.join(ROOT, "config", "_PolygonData.csv"), os.path.join(self.tmp, "config"))
        if with_udp:
            with open(os.path.join(self.tmp, "config", "_PolygonData.csv"), "a", newline="") as fh:
                fh.write("7;C;127.0.0.1;8888;Conveyor;InOut\r\n")
        with open(os.path.join(ROOT, "config", "settings.json"), encoding="utf-8") as fh:
            st = json.load(fh)
        u = lambda n: f"http://127.0.0.1:{self.ports[n]}"  # noqa: E731
        st["devices"] = {"3": {"url": u("robot"), "http_port": 8000},
                         "4": {"url": u("term"), "http_port": 80},
                         "5": {"url": u("barrier"), "http_port": 80},
                         "6": {"url": u("lamp"), "http_port": 80,
                               "lamp_mapping": {"L1": "red", "L2": "blue", "L3": "green", "L4": "yellow"}}}
        st["nodered"].update(autoconnect_team=None, ws_commands_port=self.ports["nr_cmd"],
                             ws_feedback_port=self.ports["nr_fb"], reconnect_sec=0.5)
        st["equipment"].update(autostart=False, poll_interval_ms=100, udp_listen_port=free_port())
        for k, v in (settings_patch or {}).items():
            st.setdefault(k, {}).update(v)
        with open(os.path.join(self.tmp, "config", "settings.json"), "w", encoding="utf-8") as fh:
            json.dump(st, fh, ensure_ascii=False)

        self.ctl = Controller(self.tmp)
        await self.ctl.start()
        self.session = aiohttp.ClientSession()
        if nodered:
            self.ctl.connect_nodered()
            self.ctl.start_equipment()
            await self.wait(lambda: self.ctl.cmd_link.connected and self.ctl.fb_link.connected)
        return self

    async def wait(self, cond, timeout=5.0):
        t = 0.0
        while t < timeout:
            if cond():
                return True
            await asyncio.sleep(0.05)
            t += 0.05
        raise AssertionError("условие не выполнилось за отведённое время")

    async def inject(self, payload: dict):
        async with self.session.post(f"http://127.0.0.1:{self.ports['nr_http']}/inject", json=payload) as r:
            assert (await r.json())["sent_to"] >= 1

    async def get(self, name, path):
        async with self.session.get(f"http://127.0.0.1:{self.ports[name]}{path}") as r:
            return await r.json()

    async def post(self, name, path, body=None):
        async with self.session.post(f"http://127.0.0.1:{self.ports[name]}{path}", json=body) as r:
            return await r.json()

    async def feedback(self):
        return await self.get("nr_http", "/feedback")

    def errors(self):
        return [e["text"] for e in self.ctl.logs_since(0) if e["ch"] == "error"]

    async def close(self):
        await self.ctl.stop()
        await self.session.close()
        for r in self.runners:
            await r.cleanup()


def run(tmp_path, coro_fn, **kw):
    async def main():
        b = await Bench(tmp_path).start(**kw)
        try:
            await coro_fn(b)
        finally:
            await b.close()
    asyncio.run(main())


IOT = dict(N="0", X="0", Y="0", T="0", G="0", V="0", D0="0", L1="0", L2="0", L3="0", L4="0", P="0")


def cmd(name, **kw):
    """Сообщение как от узла IOT Function: все значения строками."""
    d = {"robot_name": name, **IOT}
    d.update({k: str(v) for k, v in kw.items()})
    return d


# ----------------------------------------------------------------------------- тесты
def test_robot_coordinates_start_speed_and_feedback(tmp_path):
    async def t(b):
        await b.inject(cmd("Robot1_1", N=1, X=200, Y=30, T=15, G=120, V=1, D0=70))
        await b.wait(lambda: len(b.ctl.devices[0].last_sent) > 0, 5)
        await asyncio.sleep(0.3)
        r1 = await b.get("robot", "/_debug")
        assert ("speed", {"speed": 70}) in [tuple(x) for x in r1["log"]]
        sets = [x[1] for x in r1["log"] if x[0] == "set"]
        assert sets[-1] == {"x": 30, "z": 120, "angel": 200, "pov_gripper": 15, "gripper_state": True}
        assert r1["pump"] is False
        fb = await b.feedback()
        assert fb["Robot1_1"]["m1"] == 30 and fb["Robot1_1"]["n"] == 1 and fb["Robot1_1"]["online"]
        await b.inject(cmd("Robot1_1", N=5, Text="Start"))
        await asyncio.sleep(1.0)
        sets = [x[1] for x in (await b.get("robot", "/_debug"))["log"] if x[0] == "set"]
        assert sets[-1]["x"] == 0 and sets[-1]["angel"] == 220  # точка 2000
    run(tmp_path, t)


def test_block_resend_and_errors(tmp_path):
    async def t(b):
        c = cmd("Robot1_1", N=1, X=10, G=20)
        await b.inject(c)
        await b.inject(c)  # повтор той же команды отбрасывается
        await b.inject(cmd("Robot9_9"))
        await b.inject({"N": 1})
        await b.inject(cmd("Robot1_1", N=2, V=7))
        await b.inject(cmd("Robot1_1", N=3, Text="Home"))
        await asyncio.sleep(1.2)
        r1 = await b.get("robot", "/_debug")
        assert len([x for x in r1["log"] if x[0] == "set"]) == 1
        errs = " ".join(b.errors())
        for code in ("570", "471", "482", "473"):
            assert f"Code {code}" in errs, code
    run(tmp_path, t)


def test_lamp_terminal_barrier(tmp_path):
    async def t(b):
        await b.inject(cmd("Lamp1_1", L1=1, L3=1))
        await b.inject(cmd("RemoteTerminal1_1", L2=1, Text="Этап 2|Нажмите СТАРТ"))
        await asyncio.sleep(0.6)
        assert (await b.get("lamp", "/api/lamp"))["leds"] == {"red": True, "blue": False, "green": True,
                                                              "yellow": False}
        term = await b.get("term", "/api/terminal")
        assert term["lines"][:2] == ["Этап 2", "Нажмите СТАРТ"] and term["leds"]["green"] is True
        # пустой Text очищает дисплей (как в 2.0 и в примере плагина «clear all»)
        await b.inject(cmd("RemoteTerminal1_1", N=1))
        await asyncio.sleep(0.5)
        assert (await b.get("term", "/api/display"))["lines"] == ["", "", "", ""]
        # больше 8 разных «своих» русских букв -> транслит
        await b.inject(cmd("RemoteTerminal1_1", N=2, Text="Щука Юла Фея|Жук Цирк Ящик"))
        await asyncio.sleep(0.5)
        assert (await b.get("term", "/api/display"))["lines"][0].startswith("Schuka")
        # кнопка и проход через барьер видны в обратной связи
        await b.post("term", "/_press/green")
        await b.post("barrier", "/_walk")
        await asyncio.sleep(0.5)
        fb = await b.feedback()
        assert fb["RemoteTerminal1_1"]["e1"] == 1
        assert fb["IK1_1"]["n"] == 1 and fb["IK1_1"]["d1"] == 120
    run(tmp_path, t)


def test_manual_control_position_mode_and_specials(tmp_path):
    async def t(b):
        ctl = b.ctl
        try:
            await ctl.manual_command("3", {"N": 1, "X": 1})
            raise AssertionError("ручное управление при подключённом Node-RED должно быть запрещено")
        except CCError as e:
            assert e.code == 404
        await ctl.disconnect_nodered()
        ctl.device_by_state("3").coordinate_mode = False
        await ctl.manual_command("3", {"N": 7, "X": 2001, "V": 1})
        await ctl.manual_command("3", {"N": 8, "X": 555})
        await ctl.special("3", "2")
        await asyncio.sleep(1.5)
        sets = [x[1] for x in (await b.get("robot", "/_debug"))["log"] if x[0] == "set"]
        assert sets[0]["x"] == 50 and sets[0]["z"] == 150 and sets[0]["angel"] == 100
        assert any("Code 481" in e for e in b.errors())
        assert all(sets[-1][k] == sets[0][k] for k in ("x", "z", "angel", "pov_gripper"))
        assert sets[-1]["gripper_state"] is False  # Parking = точка 2001, схват по умолчанию выключен
    run(tmp_path, t)


def test_offline_device_reported_once(tmp_path):
    async def t(b):
        await b.runners[1].cleanup()  # «выключили» лампу
        await asyncio.sleep(2.5)
        offline = [e for e in b.errors() if "Code 583" in e and "Lamp1_1" in e]
        assert len(offline) == 1
        assert not b.ctl.device_by_state("6").online
    run(tmp_path, t)


def test_settings_validate_save_apply(tmp_path):
    async def t(b):
        ctl = b.ctl
        v = ctl.get_config()["values"]
        bad = json.loads(json.dumps(v))
        bad["tables"]["devices"][0]["IP"] = "300.1.1.1"
        bad["fields"]["equipment.poll_interval_ms"] = "abc"
        try:
            await ctl.save_config(bad)
            raise AssertionError("ожидалась ошибка 590")
        except CCError as e:
            assert e.code == 590 and "IP" in e.detail
        good = json.loads(json.dumps(v))
        good["fields"]["equipment.poll_interval_ms"] = 250
        good["tables"]["points_M"].append({"NUM": 3000, "X": 1.5, "Y": 2, "T": 0, "Z": 3})
        good["tables"]["teams"].append({"IP": "10.0.0.9", "PORT": 1880, "NAME": "Team 3"})
        res = await ctl.save_config(good)
        assert "points/_Manipulator.csv" in res["files"]
        assert ctl.settings["equipment"]["poll_interval_ms"] == 250
        assert ctl.cfg.point("M", 3000) == [1.5, 2.0, 0.0, 3.0]
        assert len(ctl.cfg.teams) == 3
        assert os.path.exists(os.path.join(b.tmp, "config", "backup", "settings.json.bak"))
        # после применения связь с Node-RED и оборудованием восстановилась
        await b.wait(lambda: ctl.cmd_link.connected and ctl.equipment_running)
    run(tmp_path, t)


def test_web_api(tmp_path):
    async def t(b):
        from controlcenter.runtime import start_web
        port = free_port()
        runner = await start_web(b.ctl, "127.0.0.1", port)
        try:
            async with b.session.get(f"http://127.0.0.1:{port}/api/state") as r:
                s = await r.json()
                assert len(s["devices"]) == 4 and s["nodered"]["commands"]
            async with b.session.get(f"http://127.0.0.1:{port}/") as r:
                assert r.status == 200 and "ControlCenter" in await r.text()
            async with b.session.get(f"http://127.0.0.1:{port}/api/config") as r:
                assert "tabs" in (await r.json())["schema"]
            async with b.session.post(f"http://127.0.0.1:{port}/api/device/5/http",
                                      json={"method": "PATCH", "path": "/api/config", "body": {"all": 70}}) as r:
                assert (await r.json())["response"]["threshold_cm"]["top"] == 70
        finally:
            await runner.cleanup()
    run(tmp_path, t)


def test_udp_hidden_and_config_preserved(tmp_path):
    async def t(b):
        ctl = b.ctl
        assert len(ctl.devices) == 5 and ctl.device_by_state("7").driver == "udp"
        assert [d["state"] for d in ctl.state()["devices"]] == ["3", "4", "5", "6"]
        cfg = ctl.get_config()
        assert [d["STATE"] for d in cfg["values"]["tables"]["devices"]] == ["3", "4", "5", "6"]
        assert all(d["DRIVER"] != "udp" for d in cfg["values"]["tables"]["drivers"])
        assert "equipment.udp_listen_port" not in cfg["values"]["fields"]
        devices_schema = next(t for t in cfg["schema"]["tables"] if t["id"] == "devices")
        drivers_schema = next(t for t in cfg["schema"]["tables"] if t["id"] == "drivers")
        assert all(c["key"] != "PORT" for c in devices_schema["columns"])
        assert "udp" not in next(c for c in drivers_schema["columns"] if c["key"] == "DRIVER")["choices"]
        old_port = ctl.settings["equipment"]["udp_listen_port"]
        await ctl.save_config(cfg["values"])
        assert ctl.device_by_state("7").driver == "udp"
        assert ctl.settings["drivers"]["C"]["driver"] == "udp"
        assert ctl.settings["equipment"]["udp_listen_port"] == old_port
        assert len(ctl.state()["devices"]) == 4
        with open(os.path.join(b.tmp, "config", "_PolygonData.csv"), encoding="utf-8") as fh:
            assert "7;C;127.0.0.1;8888;Conveyor;InOut" in fh.read()
    run(tmp_path, t, with_udp=True)
