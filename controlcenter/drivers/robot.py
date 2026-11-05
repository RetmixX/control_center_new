"""Манипулятор (M) — Motors API (OpenAPI «Motors API 0.1.0»).

  GET  /api/arm/info              информация о манипуляторе
  GET  /api/motors/pos|temp|load  позиции / температуры / нагрузки моторов
  POST /api/motors/pos/set        {x, z, angel, pov_gripper, gripper_state}
  POST /api/motors/pos/set-paint  {x, z, angel, pov_gripper, paint_pov}
  POST /api/motors/pump           {enabled}
  POST /api/motors/speed          {speed: 1..100}
"""
from __future__ import annotations

import math
import time
from typing import Any

from ..errors import CCError
from .base import S_BUSY, S_OK, Command, Device


def numbers(obj: Any, limit: int = 6) -> list[float]:
    """Достаёт числа из ответа любого вида: список, словарь, вложенные структуры."""
    out: list[float] = []

    def walk(o):
        if len(out) >= limit:
            return
        if isinstance(o, bool):
            out.append(int(o))
        elif isinstance(o, (int, float)):
            out.append(o)
        elif isinstance(o, dict):
            for k, v in o.items():
                if k in ("status", "error", "id", "ok"):
                    continue
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)
    walk(obj)
    return out[:limit]


class RobotDevice(Device):
    driver = "robot"
    is_robot = True

    def __init__(self, ddef, ctx):
        super().__init__(ddef, ctx)
        self.arm_info: Any = None
        self._last_slow = 0.0
        self._speed: int | None = None
        self._pump: bool | None = None

    @property
    def mapping(self) -> dict:
        m = dict(self.ctx.settings["robot_mapping"])
        m.update(self.d.settings.get("robot_mapping", {}))
        return m

    def _coord_mode(self) -> bool:
        if self.coordinate_mode is not None:
            return bool(self.coordinate_mode)
        return bool(self.ctx.settings["equipment"]["coordinate_mode"])

    def _pose_from_point(self, num: int) -> dict:
        p = self.ctx.points(self.d.key, num)
        if p is None:
            raise CCError(481, f"{self.name}: позиция {num} не найдена в points/ для {self.d.key}")
        return {"X": p[0], "Y": p[1], "T": p[2], "G": p[3]}

    def _special_pose(self, which: str) -> dict:
        m = self.mapping
        num = m["start_point"] if which == "start" else m["parking_point"]
        p = self.ctx.points(self.d.key, num)
        if p is None:
            fb = self.ctx.settings["fallback_poses"].get(self.d.key, {}).get(which)
            if fb is None:
                raise CCError(481, f"{self.name}: нет позиции {num} ({which})")
            self.ctx.log_event(f"{self.name}: позиции {num} нет в points/, взята резервная из settings.json")
            p = fb
        return {"X": p[0], "Y": p[1], "T": p[2], "G": p[3]}

    def _manual_mapping(self) -> dict:
        m = self.mapping
        if m.get("cartesian") or not self._coord_mode():
            return m  # декартовы X/Y и номер позиции в X форма не переставляет
        return {**m, **self.ctx.settings["manual_mapping"]}

    def manual_fields(self, cmd: dict) -> dict:
        m, manual = self.mapping, self._manual_mapping()
        out = dict(cmd)
        for api in ("x", "z", "angel", "pov_gripper"):
            out[manual[api]] = cmd.get(m[api], 0)
        return out

    def build_payload(self, cmd: Command) -> dict:
        m = self.mapping
        text = cmd.TEXT.strip()
        if text:
            if text.lower() == "start":
                vals = self._special_pose("start")
            elif text.lower() == "parking":
                vals = self._special_pose("parking")
            else:
                raise CCError(473, f"{self.name}: Text={cmd.TEXT!r}")
        elif self._coord_mode():
            vals = {"X": cmd.X, "Y": cmd.Y, "T": cmd.T, "G": cmd.G}
            if cmd.manual:
                m = self._manual_mapping()
        else:
            vals = self._pose_from_point(int(cmd.X))
        if cmd.V not in (0, 1):
            raise CCError(482, f"{self.name}: V={cmd.V} (ожидается 0 или 1)")
        vals.update({"V": cmd.V, "D0": cmd.D0, "N": cmd.N, "P": cmd.P, "L0": cmd.L0})

        if m.get("cartesian"):
            x, y = vals[m["x"]], vals[m["angel"]]
            r, a = math.hypot(x, y), math.degrees(math.atan2(y, x))
            vals = dict(vals)
            vals[m["x"]], vals[m["angel"]] = r, a
        return {
            "x": int(round(float(vals[m["x"]]))),
            "z": int(round(float(vals[m["z"]]))),
            "angel": int(round(float(vals[m["angel"]]))),
            "pov_gripper": int(round(float(vals[m["pov_gripper"]]))),
            "gripper_state": bool(int(vals[m["gripper"]])),
        }

    async def send(self, cmd: Command) -> str:
        payload = self.build_payload(cmd)
        m = self.mapping
        sent = []
        self.busy = True
        self.feedback["s"] = S_BUSY
        try:
            sf = m.get("speed_field")
            if sf:
                sp = cmd.as_dict().get(sf, 0) or 0
                sp = int(round(float(sp)))
                if sp > 0:
                    sp = max(1, min(100, sp))
                    if sp != self._speed:
                        await self.http("POST", "/api/motors/speed", {"speed": sp}, robot=True)
                        self._speed = sp
                        sent.append(f"speed={sp}")
            await self.http("POST", "/api/motors/pos/set", payload, robot=True,
                            timeout_ms=self.ctx.settings["equipment"]["robot_timeout_ms"], retries=0)
            sent.append(f"pos/set {payload}")
            if m.get("pump_follows_gripper"):
                want = payload["gripper_state"]
                if want != self._pump:
                    await self.http("POST", "/api/motors/pump", {"enabled": want}, robot=True)
                    self._pump = want
                    sent.append(f"pump={want}")
            self.feedback["n"] = cmd.N
        finally:
            self.busy = False
            self.feedback["s"] = S_OK if self.online else self.feedback["s"]
        self.last_sent = "; ".join(sent)
        return self.last_sent

    async def special(self, code: str) -> str:
        if code == "1":
            return await self.send(Command(TEXT="Start"))
        if code == "2":
            return await self.send(Command(TEXT="Parking"))
        if code == "3":
            raise CCError(585, f"{self.name}: «расслабить звенья» нет в Motors API")
        return await super().special(code)

    async def set_paint(self, x: int, z: int, angel: int, pov_gripper: int, paint_pov: int) -> Any:
        return await self.http("POST", "/api/motors/pos/set-paint",
                               {"x": x, "z": z, "angel": angel, "pov_gripper": pov_gripper,
                                "paint_pov": paint_pov}, robot=True,
                               timeout_ms=self.ctx.settings["equipment"]["robot_timeout_ms"], retries=0)

    async def set_pump(self, enabled: bool) -> Any:
        r = await self.http("POST", "/api/motors/pump", {"enabled": bool(enabled)}, robot=True)
        self._pump = bool(enabled)
        return r

    async def set_speed(self, speed: int) -> Any:
        speed = max(1, min(100, int(speed)))
        r = await self.http("POST", "/api/motors/speed", {"speed": speed}, robot=True)
        self._speed = speed
        return r

    async def poll(self) -> None:
        if self.busy:
            return  # не мешаем выполнению движения
        pos = await self.http("GET", "/api/motors/pos", robot=True, retries=0)
        for i, v in enumerate(numbers(pos), 1):
            self.feedback[f"m{i}"] = v
        raw = {"pos": pos}
        now = time.monotonic()
        # при ошибке API опрашиваем всё: иначе опрос без /temp и /load выглядел бы успешным
        if self.api_error or now - self._last_slow >= self.ctx.settings["equipment"]["robot_slow_poll_ms"] / 1000:
            self._last_slow = now
            temp = await self.http("GET", "/api/motors/temp", robot=True, retries=0)
            load = await self.http("GET", "/api/motors/load", robot=True, retries=0)
            for i, v in enumerate(numbers(temp), 1):
                self.feedback[f"t{i}"] = v
            for i, v in enumerate(numbers(load), 1):
                self.feedback[f"l{i}"] = v
            raw.update(temp=temp, load=load)
            if self.arm_info is None:
                try:
                    self.arm_info = await self.http("GET", "/api/arm/info", robot=True, retries=0)
                except CCError:
                    self.arm_info = {}
        else:
            prev = self.raw_state or {}
            raw.update(temp=prev.get("temp"), load=prev.get("load"))
        raw["info"] = self.arm_info
        self.raw_state = raw
