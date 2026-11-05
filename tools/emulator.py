"""Эмулятор стенда для проверки ControlCenter без железа.

Поднимает на 127.0.0.1:
  * манипуляторы (Motors API) — порты 9101, 9102 ...
  * лампы /api/lamp            — 9201 ...
  * терминал /api/terminal     — 9301
  * ИК-барьер /api/barrier     — 9401
  * «Node-RED»: ws://127.0.0.1:8765 (шлёт команды), ws://127.0.0.1:8766 (принимает обратную связь)
    и HTTP http://127.0.0.1:1880/inject — POST JSON команды, она уйдёт в ControlCenter;
    GET /feedback — последняя обратная связь по каждому устройству.

  python tools/emulator.py --robots 2 --lamps 2
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random

from aiohttp import web

CYR_OWN = set("БГДЁЖЗИЙЛПФЦЧШЩЪЫЬЭЮЯбвгдёжзийклмнптфцчшщъыьэюя")


def jr(data, status=200):
    return web.Response(text=json.dumps(data, ensure_ascii=False, separators=(",", ":")), status=status,
                        content_type="application/json", charset="utf-8")


def err(msg, status=400):
    return jr({"status": "error", "error": msg}, status)


# ---------------------------------------------------------------- манипулятор
def robot_app(n: int):
    st = {"pos": [0, 0, 0, 0, 0, 0], "speed": 50, "pump": False, "grip": False, "log": []}
    app = web.Application()

    async def info(_):
        return jr({"name": f"emu-arm-{n}", "dof": 5, "version": "0.1.0"})

    async def temp(_):
        return jr({"temp": [round(30 + random.random() * 5, 1) for _ in range(6)]})

    async def load(_):
        return jr({"load": [random.randint(0, 100) for _ in range(6)]})

    async def pos(_):
        return jr({"pos": st["pos"]})

    async def pos_set(req):
        b = await req.json()
        for k in ("x", "z", "angel", "pov_gripper", "gripper_state"):
            if k not in b:
                return jr({"detail": [{"loc": ["body", k], "msg": "Field required", "type": "missing"}]}, 422)
        if not all(isinstance(b[k], int) and not isinstance(b[k], bool) for k in ("x", "z", "angel", "pov_gripper")):
            return jr({"detail": [{"msg": "Input should be a valid integer"}]}, 422)
        await asyncio.sleep(0.3)  # «едет»
        st["pos"] = [b["x"], b["z"], b["angel"], b["pov_gripper"], int(b["gripper_state"]), 0]
        st["grip"] = b["gripper_state"]
        st["log"].append(("set", b))
        return jr({"status": "ok"})

    async def pump(req):
        b = await req.json()
        st["pump"] = bool(b["enabled"])
        st["log"].append(("pump", b))
        return jr({"status": "ok"})

    async def speed(req):
        b = await req.json()
        if not 1 <= b.get("speed", 0) <= 100:
            return jr({"detail": [{"msg": "speed 1..100"}]}, 422)
        st["speed"] = b["speed"]
        st["log"].append(("speed", b))
        return jr({"status": "ok"})

    async def dbg(_):
        return jr({k: v for k, v in st.items()})

    app.add_routes([web.get("/api/arm/info", info), web.get("/api/motors/temp", temp),
                    web.get("/api/motors/load", load), web.get("/api/motors/pos", pos),
                    web.post("/api/motors/pos/set", pos_set), web.post("/api/motors/pump", pump),
                    web.post("/api/motors/speed", speed), web.get("/_debug", dbg)])
    return app


# ---------------------------------------------------------------- лампа / терминал / барьер
COLORS = ("red", "blue", "green", "yellow")


def leds_routes(st, prefix_list):
    async def leds_handler(req):
        if req.method == "GET":
            return jr({"status": "ok", "leds": st["leds"]})
        raw = await req.read()
        if len(raw) > st["max_body"]:
            return err("body too large", 413)
        b = json.loads(raw or b"{}")
        upd = {k: v for k, v in b.items() if k in COLORS}
        if not upd:
            return err("expected JSON with red, blue, green or yellow")
        for k, v in upd.items():
            if v not in (True, False, 0, 1):
                return err("led value must be true or false")
        for k, v in upd.items():
            st["leds"][k] = bool(v)
        return jr({"status": "ok", "leds": st["leds"]})

    async def action(req):
        color, act = req.match_info["color"], req.match_info["act"]
        names = COLORS if color == "all" else (color,)
        if color != "all" and color not in COLORS:
            return err("unknown color", 404)
        for c in names:
            st["leds"][c] = {"on": True, "off": False, "toggle": not st["leds"][c]}[act]
        return jr({"status": "ok", "leds": st["leds"]})

    routes = []
    for p in prefix_list:
        routes += [web.route("*", p, leds_handler), web.post(p + "/{color}/{act}", action)]
    return routes


def lamp_app():
    st = {"leds": dict.fromkeys(COLORS, False), "max_body": 95}
    app = web.Application()
    app.add_routes(leds_routes(st, ["/api/lamp"]) + [web.get("/health", lambda r: jr({"status": "ok"}))])
    return app


def terminal_app():
    st = {"leds": dict.fromkeys(COLORS, False), "max_body": 600,
          "buttons": {c: {"pressed": False, "count": 0} for c in ("green", "yellow", "red")},
          "kill": False, "lines": ["Ready", "IP 127.0.0.1", "", ""]}
    app = web.Application()

    async def terminal(_):
        return jr({"status": "ok", "leds": st["leds"], "buttons": st["buttons"], "kill_switch": st["kill"],
                   "lines": st["lines"]})

    async def display(req):
        if req.method == "GET":
            return jr({"status": "ok", "lines": st["lines"]})
        b = await req.json()
        new = list(st["lines"])
        got = False
        for i in range(4):
            k = f"line{i}"
            if k in b:
                got = True
                if not isinstance(b[k], str):
                    return err("text must be a string")
                if len(b[k]) > 20:
                    return err("text longer than 20 characters")
                new[i] = b[k]
        if not got:
            return err("expected JSON with line0, line1, line2 or line3")
        if len(set("".join(new)) & CYR_OWN) > 8:
            return err("too many different Cyrillic letters on screen (max 8)")
        st["lines"] = new
        return jr({"status": "ok", "lines": st["lines"]})

    async def clear(_):
        st["lines"] = ["", "", "", ""]
        return jr({"status": "ok", "lines": st["lines"]})

    async def reset(_):
        for b in st["buttons"].values():
            b["count"] = 0
        return jr({"status": "ok", "buttons": st["buttons"]})

    async def press(req):  # только для эмулятора
        c = req.match_info["c"]
        if c == "kill":
            st["kill"] = not st["kill"]
        else:
            st["buttons"][c]["count"] += 1
        return jr({"status": "ok"})

    app.add_routes(leds_routes(st, ["/api/leds", "/api/lamp"]) + [
        web.get("/api/terminal", terminal), web.route("*", "/api/display", display),
        web.post("/api/display/clear", clear), web.post("/api/buttons/reset", reset),
        web.post("/_press/{c}", press)])
    return app


def barrier_app():
    st = {"count": 0, "th": {"top": 50, "middle": 50, "bottom": 50},
          "sens": {n: {"distance_cm": 120, "count": 0} for n in ("top", "middle", "bottom")}}
    app = web.Application()

    def view():
        sens = {}
        for n, s in st["sens"].items():
            d = s["distance_cm"]
            blocked = d is not None and d < st["th"][n]
            sens[n] = {"distance_cm": d, "volts": 0.5, "threshold_cm": st["th"][n], "blocked": blocked,
                       "count": s["count"]}
        return {"status": "ok", "blocked": any(s["blocked"] for s in sens.values()), "count": st["count"],
                "sensors": sens}

    async def barrier(_):
        return jr(view())

    async def config(req):
        if req.method == "GET":
            return jr({"status": "ok", "threshold_cm": st["th"], "hysteresis_cm": 5})
        b = await req.json()
        if "all" in b:
            for k in st["th"]:
                st["th"][k] = int(b["all"])
        for k in st["th"]:
            if k in b:
                st["th"][k] = int(b[k])
        return jr({"status": "ok", "threshold_cm": st["th"], "hysteresis_cm": 5})

    async def reset(_):
        st["count"] = 0
        for s in st["sens"].values():
            s["count"] = 0
        return jr(view())

    async def walk(_):  # эмуляция прохода человека
        st["sens"]["middle"]["distance_cm"] = 30
        st["sens"]["middle"]["count"] += 1
        st["count"] += 1
        await asyncio.sleep(0.8)
        st["sens"]["middle"]["distance_cm"] = 120
        return jr({"status": "ok"})

    app.add_routes([web.get("/api/barrier", barrier), web.route("*", "/api/config", config),
                    web.post("/api/barrier/reset", reset), web.post("/_walk", walk)])
    return app


# ---------------------------------------------------------------- «Node-RED»
def nodered_apps():
    clients_cmd: set = set()
    feedback: dict = {}

    async def ws_cmd(req):
        ws = web.WebSocketResponse()
        await ws.prepare(req)
        clients_cmd.add(ws)
        try:
            async for _ in ws:
                pass
        finally:
            clients_cmd.discard(ws)
        return ws

    async def ws_fb(req):
        ws = web.WebSocketResponse()
        await ws.prepare(req)
        async for m in ws:
            try:
                d = json.loads(m.data)
                feedback[d.get("name")] = d
            except ValueError:
                pass
        return ws

    async def inject(req):
        data = await req.text()
        for ws in list(clients_cmd):
            await ws.send_str(data)
        return jr({"sent_to": len(clients_cmd)})

    async def fb(_):
        return jr(feedback)

    a1, a2, a3 = web.Application(), web.Application(), web.Application()
    a1.add_routes([web.get("/", ws_cmd), web.get("/{tail:.*}", ws_cmd)])
    a2.add_routes([web.get("/", ws_fb), web.get("/{tail:.*}", ws_fb)])
    a3.add_routes([web.post("/inject", inject), web.get("/feedback", fb)])
    return a1, a2, a3


async def serve(app, port):
    r = web.AppRunner(app, access_log=None)
    await r.setup()
    await web.TCPSite(r, "127.0.0.1", port).start()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--robots", type=int, default=2)
    ap.add_argument("--lamps", type=int, default=2)
    ap.add_argument("--no-nodered", action="store_true")
    a = ap.parse_args()
    for i in range(a.robots):
        await serve(robot_app(i + 1), 9101 + i)
    for i in range(a.lamps):
        await serve(lamp_app(), 9201 + i)
    await serve(terminal_app(), 9301)
    await serve(barrier_app(), 9401)
    if not a.no_nodered:
        c, f, h = nodered_apps()
        await serve(c, 8765)
        await serve(f, 8766)
        await serve(h, 1880)
    print("emulator ready", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
