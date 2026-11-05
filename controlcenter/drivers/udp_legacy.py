"""Старый текстовый UDP-протокол (порт 8888) — для устройств, у которых ещё нет HTTP API
(конвейер C, смарт-камера SC, сканер штрихкода BR и т.д.). Форматы сообщений перенесены
из оригинального ControlCenter без изменений."""
from __future__ import annotations

import asyncio
import time

from ..errors import CCError
from .base import S_OK, Command, Device


class UdpTransport(asyncio.DatagramProtocol):
    """Один сокет на 0.0.0.0:8888: отправка команд и приём обратной связи."""

    def __init__(self, on_message):
        self.on_message = on_message
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        try:
            self.on_message(data.decode("utf-8", errors="replace"), addr)
        except Exception:  # noqa: BLE001
            pass

    def sendto(self, msg: str, addr) -> None:
        if not self.transport:
            raise OSError("UDP-сокет не открыт")
        self.transport.sendto(msg.encode("utf-8"), addr)


def legacy_message(key: str, cmd: Command, coordinate_mode: bool, points) -> str:
    v = lambda x: f"{x:g}" if isinstance(x, float) else str(x)  # noqa: E731
    if key == "T":
        return f"l:{cmd.L1}:{cmd.L4}:{cmd.L3}:{cmd.L2}#"
    if key == "C":
        return f"s:{cmd.N}:{cmd.P}#"
    if key == "SC":
        g = int(cmd.G)
        return {1: "c:2#", 0: "c:1#", -1: "c:0#"}.get(g, "c:1#")
    if key == "R":
        return f"r:{cmd.L1}:{cmd.L2}:{cmd.L3}:{cmd.L4}:{cmd.P}:{cmd.TEXT}#"
    if key == "M":
        if not coordinate_mode:
            p = points(key, int(cmd.X))
            if p is None:
                raise CCError(481, f"позиция {int(cmd.X)}")
            X, Y, T, Z = p
        else:
            X, Y, T, Z = cmd.X, cmd.Y, cmd.T, cmd.G
        return f"g:{v(X)}:{v(Y)}:{v(T)}:{v(Z)}:{cmd.V}#"
    raise CCError(585, f"нет UDP-формата для типа {key}")


class UdpDevice(Device):
    driver = "udp"

    def __init__(self, ddef, ctx, transport_getter):
        super().__init__(ddef, ctx)
        self._tr = transport_getter

    def _send_raw(self, msg: str) -> None:
        tr = self._tr()
        if tr is None:
            raise CCError(601, "UDP-сокет не открыт (порт занят?)")
        try:
            tr.sendto(msg, (self.d.ip, self.d.port))
        except OSError as e:
            raise CCError(581 if self.d.key == "M" else 582, f"{self.name}: {e}") from e
        self.last_sent = f"UDP {self.d.ip}:{self.d.port} <- {msg}"

    async def send(self, cmd: Command) -> str:
        cm = self.coordinate_mode
        if cm is None:
            cm = self.ctx.settings["equipment"]["coordinate_mode"]
        self._send_raw(legacy_message(self.d.key, cmd, cm, self.ctx.points))
        self.feedback["n"] = cmd.N
        return self.last_sent

    async def special(self, code: str) -> str:
        k = self.d.key
        if k == "C" and code == "1":
            for m in ("s:0:1#", "s:1:1#", "s:0:1#"):
                self._send_raw(m)
                await asyncio.sleep(0.05)
            return self.last_sent
        if k == "M" or (k == "C" and code == "2"):
            self._send_raw(code + "#")
        else:
            self._send_raw(code)
        return self.last_sent

    def ingest(self, f: list[str]) -> None:
        """Строка обратной связи «TYPE:id:a:b:...» — разбор как в оригинале."""
        fb, t = self.feedback, f[0]
        to_i = lambda i: int(float(f[i]))  # noqa: E731
        if t in ("M", "T", "L") and len(f) >= 4:
            fb["s"], fb["n"] = to_i(2), to_i(3)
            pref = {"M": "m", "T": "t", "L": "l"}[t]
            for i in range(4, min(len(f), 10)):
                fb[f"{pref}{i - 3}"] = float(f[i]) if t == "M" else to_i(i)
        elif t == "R":
            fb["s"], fb["p"] = 0, to_i(2)
            for i, k in enumerate(("b1", "b2", "b3"), 3):
                if i < len(f):
                    fb[k] = to_i(i)
        elif t == "E":
            for i in range(4, min(len(f), 10)):
                fb[f"e{i - 3}"] = to_i(i)
        elif t == "C":
            fb["n"] = to_i(2)
            for i in range(3, min(len(f), 9)):
                fb[f"l{i - 2}"] = f[i]
        elif t == "B1":
            fb["s"] = 0
            for i, k in enumerate(("d1", "d2", "d3"), 2):
                if i < len(f):
                    fb[k] = to_i(i)
        elif t == "BR":
            fb["s"] = to_i(2)
        self.online = True
        self.last_seen = time.time()
        if fb["s"] == 2:
            fb["s"] = S_OK
        self.raw_state = ":".join(f)
