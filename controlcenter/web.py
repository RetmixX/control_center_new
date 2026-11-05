"""Веб-интерфейс и REST API (замена окна PyQt)."""
from __future__ import annotations

import base64
import os

from aiohttp import web

from .controller import Controller
from .errors import CCError

STATIC = os.path.join(os.path.dirname(__file__), "static")


def make_app(ctl: Controller) -> web.Application:
    user = ctl.settings["web"].get("username") or ""
    pwd = ctl.settings["web"].get("password") or ""

    @web.middleware
    async def auth_mw(request, handler):
        if user:
            expected = "Basic " + base64.b64encode(f"{user}:{pwd}".encode()).decode()
            if request.headers.get("Authorization") != expected:
                return web.Response(status=401, headers={"WWW-Authenticate": 'Basic realm="ControlCenter"'})
        return await handler(request)

    @web.middleware
    async def error_mw(request, handler):
        try:
            return await handler(request)
        except CCError as e:
            ctl.error(e.code, e.detail)
            return web.json_response({"ok": False, "code": e.code, "error": str(e)}, status=400)
        except (ValueError, KeyError, TypeError) as e:
            return web.json_response({"ok": False, "error": f"{type(e).__name__}: {e}"}, status=400)

    app = web.Application(middlewares=[auth_mw, error_mw])
    r = web.RouteTableDef()

    async def body(request) -> dict:
        try:
            return await request.json()
        except Exception:  # noqa: BLE001
            return {}

    @r.get("/")
    async def index(_):
        return web.FileResponse(os.path.join(STATIC, "index.html"))

    @r.get("/api/state")
    async def state(request):
        return web.json_response(ctl.state(int(request.query.get("since", 0))))

    @r.post("/api/team")
    async def team(request):
        ctl.select_team(int((await body(request))["index"]))
        return web.json_response({"ok": True})

    @r.post("/api/nodered")
    async def nodered(request):
        b = await body(request)
        if b.get("action") == "connect":
            ctl.connect_nodered(b.get("ip"))
        else:
            await ctl.disconnect_nodered()
        return web.json_response({"ok": True})

    @r.post("/api/equipment")
    async def equipment(request):
        b = await body(request)
        ctl.start_equipment() if b.get("action") == "start" else ctl.stop_equipment()
        return web.json_response({"ok": True})

    @r.post("/api/flags")
    async def flags(request):
        ctl.set_flags(await body(request))
        return web.json_response({"ok": True, "flags": ctl.flags})

    @r.post("/api/device/{state}/mode")
    async def dev_mode(request):
        d = ctl.device_by_state(request.match_info["state"])
        v = (await body(request)).get("coordinate_mode")
        d.set_mode(None if v is None else bool(v))
        return web.json_response({"ok": True})

    @r.post("/api/command")
    async def command(request):
        b = await body(request)
        await ctl.manual_command(str(b.get("target", "all")), b.get("cmd", {}), b.get("key"))
        return web.json_response({"ok": True})

    @r.post("/api/special")
    async def special(request):
        b = await body(request)
        res = await ctl.special(str(b.get("target", "all")), str(b["code"]))
        return web.json_response({"ok": True, "result": res})

    @r.post("/api/device/{state}/http")
    async def raw_http(request):
        """Прямой запрос к HTTP API устройства — для наладки (скорость, насос, пороги барьера...)."""
        d = ctl.device_by_state(request.match_info["state"])
        if d.driver == "udp":
            raise CCError(585, "устройство работает по UDP")
        b = await body(request)
        method = str(b.get("method", "GET")).upper()
        if method not in ("GET", "POST", "PUT", "PATCH"):
            raise ValueError("метод должен быть GET/POST/PUT/PATCH")
        path = "/" + str(b.get("path", "")).lstrip("/")
        res = await d.http(method, path, b.get("body"), retries=0,
                           timeout_ms=ctl.settings["equipment"]["robot_timeout_ms"])
        ctl.event(f"{d.name}: ручной запрос {method} {path} {b.get('body') or ''}")
        return web.json_response({"ok": True, "response": res})

    @r.get("/api/config")
    async def get_config(_):
        return web.json_response(ctl.get_config())

    @r.post("/api/config")
    async def save_config(request):
        res = await ctl.save_config(await body(request))
        return web.json_response({"ok": True, **res})

    @r.post("/api/reload")
    async def reload(_):
        await ctl.reload_config()
        return web.json_response({"ok": True})

    app.add_routes(r)
    app.router.add_static("/static", STATIC)
    return app
