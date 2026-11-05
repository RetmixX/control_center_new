"""Связь с Node-RED — тот же протокол, что у ControlCenter для Windows:
  ws://<IP>:8765  — приходят JSON-команды IOT Function (robot_name, N, X, Y, T, G, V, D0, L1..L4, P, Text)
  ws://<IP>:8766  — уходит JSON обратной связи (name, n, s, m1..m6, t1..t6, l0..l6, b1..b3, p, e1..e6, d1..d3)
В отличие от оригинала соединения переподключаются автоматически."""
from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable

import aiohttp


class WsLink:
    def __init__(self, name: str, session: aiohttp.ClientSession, on_state: Callable[[str, bool, str], None],
                 on_message: Callable[[str], Awaitable[None]] | None = None):
        self.name = name
        self.session = session
        self.on_state = on_state
        self.on_message = on_message
        self.url = ""
        self.auth: aiohttp.BasicAuth | None = None
        self.reconnect_sec = 3.0
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self.connected = False
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self, url: str, auth: aiohttp.BasicAuth | None, reconnect_sec: float) -> None:
        self.url, self.auth, self.reconnect_sec = url, auth, reconnect_sec
        self._stop.clear()
        if not self._task or self._task.done():
            self._task = asyncio.create_task(self._run(), name=f"ws-{self.name}")

    async def stop(self) -> None:
        self._stop.set()
        if self.ws is not None and not self.ws.closed:
            await self.ws.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._task = None
        self._set(False, "остановлено")

    def _set(self, ok: bool, why: str) -> None:
        if ok != self.connected or not ok:
            self.connected = ok
            self.on_state(self.name, ok, why)

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                async with self.session.ws_connect(self.url, auth=self.auth, heartbeat=10) as ws:
                    self.ws = ws
                    self._set(True, "подключено")
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT and self.on_message:
                            await self.on_message(msg.data)
                        elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                            break
                self._set(False, "соединение закрыто")
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self._set(False, f"{type(e).__name__}: {e}")
            finally:
                self.ws = None
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.reconnect_sec)
            except asyncio.TimeoutError:
                pass

    async def send_json(self, data: dict) -> bool:
        ws = self.ws
        if ws is None or ws.closed:
            return False
        try:
            await ws.send_str(json.dumps(data, ensure_ascii=False))
            return True
        except Exception:  # noqa: BLE001
            return False
