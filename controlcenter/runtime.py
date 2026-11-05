"""Общий запуск ядра для обеих версий.

* CLI (сервер) работает прямо в asyncio-цикле главного потока.
* Desktop запускает ядро в фоновом потоке (ControllerThread), окно Qt общается с ним через call().
"""
from __future__ import annotations

import asyncio
import inspect
import threading
from typing import Any, Callable

from aiohttp import web

from .controller import Controller
from .web import make_app


async def start_web(ctl: Controller, host: str, port: int) -> web.AppRunner:
    runner = web.AppRunner(make_app(ctl), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    return runner


class ControllerThread(threading.Thread):
    """Ядро ControlCenter в отдельном потоке со своим event loop."""

    def __init__(self, base_dir: str, web_port: int | None = None, web_host: str = "0.0.0.0"):
        super().__init__(daemon=True, name="controlcenter-core")
        self.base_dir = base_dir
        self.web_port = web_port
        self.web_host = web_host
        self.loop: asyncio.AbstractEventLoop | None = None
        self.ctl: Controller | None = None
        self.error: BaseException | None = None
        self.ready = threading.Event()
        self._runner: web.AppRunner | None = None

    def run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.ctl = Controller(self.base_dir)
            self.loop.run_until_complete(self.ctl.start())
            if self.web_port:
                self._runner = self.loop.run_until_complete(start_web(self.ctl, self.web_host, self.web_port))
        except BaseException as e:  # noqa: BLE001
            self.error = e
            self.ready.set()
            return
        self.ready.set()
        self.loop.run_forever()

    def call(self, fn: Callable[..., Any], *args, timeout: float | None = 5.0, **kw) -> Any:
        """Выполнить fn(*args) в потоке ядра и вернуть результат (исключения пробрасываются)."""
        async def wrap():
            r = fn(*args, **kw)
            if inspect.isawaitable(r):
                r = await r
            return r
        fut = asyncio.run_coroutine_threadsafe(wrap(), self.loop)
        return fut.result(timeout)

    def submit(self, fn: Callable[..., Any], *args, done: Callable[[Any, BaseException | None], None] | None = None,
               **kw) -> None:
        """То же, но без ожидания: результат придёт в done(result, error) из потока ядра."""
        async def wrap():
            r = fn(*args, **kw)
            if inspect.isawaitable(r):
                r = await r
            return r
        fut = asyncio.run_coroutine_threadsafe(wrap(), self.loop)
        if done:
            fut.add_done_callback(lambda f: done(None if f.exception() else f.result(), f.exception()))

    def shutdown(self) -> None:
        if not self.loop or not self.loop.is_running():
            return
        async def stop():
            await self.ctl.stop()
            if self._runner:
                await self._runner.cleanup()
        try:
            asyncio.run_coroutine_threadsafe(stop(), self.loop).result(5)
        except Exception:  # noqa: BLE001
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.join(3)
