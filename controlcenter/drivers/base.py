"""Общая часть драйверов оборудования."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

import aiohttp

from ..config import MODE_KEYS, DeviceDef
from ..errors import CCError

FEEDBACK_KEYS = (
    ["n", "s"]
    + [f"m{i}" for i in range(1, 7)]
    + [f"t{i}" for i in range(1, 7)]
    + [f"l{i}" for i in range(0, 7)]
    + ["b1", "b2", "b3", "p"]
    + [f"e{i}" for i in range(1, 7)]
    + ["d1", "d2", "d3"]
)

# s (состояние) в обратной связи
S_OK, S_BUSY, S_OFFLINE = 0, 1, 2


def _num(v: Any, cast=float, default=0):
    if v is None or v == "":
        return default
    try:
        return cast(float(v)) if cast is int else cast(v)
    except (TypeError, ValueError):
        if isinstance(v, bool):
            return int(v)
        raise CCError(571, f"значение {v!r}")


@dataclass
class Command:
    """Одна команда IOT Function из Node-RED (или из ручного управления)."""
    N: int = 0
    X: float = 0
    Y: float = 0
    T: float = 0
    G: float = 0
    V: int = 0
    D0: float = 0
    L0: int = 0
    L1: int = 0
    L2: int = 0
    L3: int = 0
    L4: int = 0
    P: int = 0
    TEXT: str = ""
    LINE: int = 0   # строка дисплея терминала 1..4; 0 — Text задаёт весь дисплей, строки через разделитель
    raw: dict = field(default_factory=dict)
    manual: bool = False   # из формы Manual Control, а не из Node-RED

    @classmethod
    def from_json(cls, d: dict) -> "Command":
        g = lambda *keys: next((d[k] for k in keys if k in d), None)  # noqa: E731
        return cls(
            N=_num(g("N", "n"), int), X=_num(g("X", "x")), Y=_num(g("Y", "y")),
            T=_num(g("T", "t")), G=_num(g("G", "g")), V=_num(g("V", "v"), int),
            D0=_num(g("D0", "D1", "d0")), L0=_num(g("L0"), int), L1=_num(g("L1"), int),
            L2=_num(g("L2"), int), L3=_num(g("L3"), int), L4=_num(g("L4"), int),
            P=_num(g("P", "p"), int),
            TEXT=str(g("Text", "TEXT", "text") or ""), LINE=_num(g("Line", "LINE", "line"), int), raw=dict(d),
        )

    def signature(self) -> tuple:
        return (self.N, self.X, self.Y, self.T, self.G, self.V, self.D0,
                self.L0, self.L1, self.L2, self.L3, self.L4, self.P, self.TEXT, self.LINE)

    def as_dict(self) -> dict:
        return {"N": self.N, "X": self.X, "Y": self.Y, "T": self.T, "G": self.G, "V": self.V,
                "D0": self.D0, "L0": self.L0, "L1": self.L1, "L2": self.L2, "L3": self.L3,
                "L4": self.L4, "P": self.P, "Text": self.TEXT, "Line": self.LINE}


class Device:
    """Базовый класс. Подклассы реализуют send(), poll(), special()."""
    driver = "base"
    is_robot = False

    def __init__(self, ddef: DeviceDef, ctx: "DeviceContext"):
        self.d = ddef
        self.ctx = ctx
        self.name = ddef.name
        self.online = False
        self.polling = True
        self.last_error = ""
        self.api_error = ""    # опрос получает HTTP-ошибку: устройство отвечает, но его API не работает
        self.last_sent = ""
        self.last_seen = 0.0
        self.busy = False
        self.raw_state: Any = None
        self.feedback: dict[str, Any] = {k: 0 for k in FEEDBACK_KEYS}
        self.feedback["s"] = S_OFFLINE
        self.last_cmd: Command | None = None
        self.coordinate_mode = ddef.settings.get("coordinate_mode") if self.has_mode else None
        self._lock = asyncio.Lock()
        self._fails = 0

    # --- переопределяется -------------------------------------------------
    async def send(self, cmd: Command) -> str:
        raise CCError(585, f"{self.driver}: отправка команд не поддерживается")

    async def poll(self) -> None:
        return None

    async def special(self, code: str) -> str:
        raise CCError(585, f"{self.driver}: кнопка {code} не поддерживается")

    async def close(self) -> None:
        return None

    def manual_fields(self, cmd: dict) -> dict:
        """Команда из Node-RED в полях формы Manual Control (для Load selected)."""
        return cmd

    # --- общее ---------------------------------------------------------------
    @property
    def has_mode(self) -> bool:
        return self.d.key in MODE_KEYS

    def set_mode(self, value: bool | None) -> None:
        if not self.has_mode:
            raise CCError(585, f"{self.name}: координаты/позиции можно задать только манипулятору")
        self.coordinate_mode = value

    @property
    def base_url(self) -> str:
        url = self.d.settings.get("url")
        port = int(self.d.settings.get("http_port", 80))
        if url:
            u = urlsplit(url.rstrip("/"))
            if u.port is None and port != 80:  # порт в самом URL главнее столбца «HTTP-порт»
                u = u._replace(netloc=f"{u.netloc}:{port}")
            return urlunsplit(u)
        return f"http://{self.d.ip}" + ("" if port == 80 else f":{port}")

    def mark_online(self) -> None:
        if self.api_error:
            return  # связь вернёт только полностью успешный опрос (clear_api_error)
        if not self.online:
            self.ctx.log_event(f"{self.name}: на связи")
        self.online = True
        self._fails = 0
        self.last_seen = time.time()
        self.feedback["s"] = S_BUSY if self.busy else S_OK

    def mark_offline(self, err: str) -> None:
        self._fails += 1
        self.last_error = err
        if self.online or self._fails == 1:
            self.ctx.error(583, f"{self.name} ({self.base_url}): {err}")
        self.online = False
        self.feedback["s"] = S_OFFLINE

    def mark_api_error(self, err: str) -> None:
        if err != self.api_error:  # в журнал один раз, а не при каждом опросе
            self.ctx.error(584, err)
        self.api_error = self.last_error = err
        self.online = False
        self.feedback["s"] = S_OFFLINE

    def clear_api_error(self) -> None:
        if self.api_error:
            self.api_error = self.last_error = ""
            self.mark_online()

    async def http(self, method: str, path: str, body: Any = None, *, timeout_ms: int | None = None,
                   robot: bool = False, retries: int | None = None) -> Any:
        """HTTP-запрос с компактным JSON, таймаутом, повтором и одним запросом за раз на устройство
        (Arduino обслуживает клиентов строго по очереди)."""
        eq = self.ctx.settings["equipment"]
        timeout_ms = timeout_ms or eq["http_timeout_ms"]
        retries = eq["retries"] if retries is None else retries
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        url = self.base_url + path
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                async with self._lock:
                    async with self.ctx.session.request(
                        method, url, data=data, headers=headers,
                        timeout=aiohttp.ClientTimeout(total=timeout_ms / 1000),
                    ) as r:
                        text = await r.text(encoding="utf-8", errors="replace")
                        try:
                            payload = json.loads(text) if text else None
                        except ValueError:
                            payload = text
                        if r.status >= 400:
                            msg = payload.get("error") if isinstance(payload, dict) else None
                            if isinstance(payload, dict) and "detail" in payload:
                                msg = json.dumps(payload["detail"], ensure_ascii=False)
                            raise _HTTPStatus(r.status, msg or " ".join(text.split())[:200])
                        self.mark_online()
                        return payload
            except _HTTPStatus as e:
                raise CCError(584, f"{self.name} {method} {path}: HTTP {e.status} {e.msg}") from e
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
                last_exc = e
                if attempt < retries:
                    await asyncio.sleep(0.15 * (attempt + 1))
        err = f"{type(last_exc).__name__}: {last_exc}" if last_exc else "нет ответа"
        self.mark_offline(err)
        raise CCError(581 if robot else 582, f"{self.name} {method} {url}: {err}")

    def info(self) -> dict:
        return {
            "state": self.d.state, "key": self.d.key, "ip": self.d.ip, "name": self.name,
            "driver": self.driver, "url": self.base_url if self.driver != "udp" else f"udp://{self.d.ip}:{self.d.port}",
            "online": self.online, "polling": self.polling, "busy": self.busy,
            "last_error": self.last_error, "last_sent": self.last_sent,
            "last_seen": self.last_seen, "feedback": self.feedback, "raw": self.raw_state,
            "coordinate_mode": self.coordinate_mode, "has_mode": self.has_mode,
        }


class _HTTPStatus(Exception):
    def __init__(self, status: int, msg: str):
        self.status, self.msg = status, msg


class DeviceContext:
    """То, что драйверам нужно от контроллера."""
    def __init__(self, settings: dict, session: aiohttp.ClientSession,
                 log_event: Callable[[str], None], error: Callable[[int, str], None],
                 points: Callable[[str, int], list | None]):
        self.settings = settings
        self.session = session
        self.log_event = log_event
        self.error = error
        self.points = points
