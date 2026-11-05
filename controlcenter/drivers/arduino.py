"""Устройства на Arduino с HTTP/JSON API: умная лампа (светофор), удалённый терминал, ИК-барьер.
Описание API — «API устройств: лампа, терминал, ИК-барьер»."""
from __future__ import annotations

from ..errors import CCError
from .base import Command, Device

COLORS = ("red", "blue", "green", "yellow")


def _leds_payload(cmd: Command, mapping: dict) -> dict:
    vals = {"L1": cmd.L1, "L2": cmd.L2, "L3": cmd.L3, "L4": cmd.L4}
    out = {}
    for field, color in mapping.items():
        if color in COLORS and field in vals:
            out[color] = bool(vals[field])
    return out


def _leds_feedback(leds: dict, mapping: dict, fb: dict) -> None:
    for field, color in mapping.items():
        if field.startswith("L") and color in leds:
            fb["l" + field[1:]] = int(bool(leds[color]))


class LampDevice(Device):
    """Светофор T -> /api/lamp."""
    driver = "lamp"

    @property
    def mapping(self) -> dict:
        m = dict(self.ctx.settings["lamp_mapping"])
        m.update(self.d.settings.get("lamp_mapping", {}))
        return m

    async def send(self, cmd: Command) -> str:
        body = _leds_payload(cmd, self.mapping)
        r = await self.http("PATCH", "/api/lamp", body)
        if isinstance(r, dict) and "leds" in r:
            _leds_feedback(r["leds"], self.mapping, self.feedback)
            self.raw_state = r
        self.feedback["n"] = cmd.N
        self.last_sent = f"PATCH /api/lamp {body}"
        return self.last_sent

    async def special(self, code: str) -> str:
        if code in ("1", "2", "3"):
            await self.http("POST", "/api/lamp/all/off")
            self.last_sent = "POST /api/lamp/all/off"
            return self.last_sent
        return await super().special(code)

    async def poll(self) -> None:
        r = await self.http("GET", "/api/lamp", retries=0)
        if isinstance(r, dict) and "leds" in r:
            _leds_feedback(r["leds"], self.mapping, self.feedback)
        self.raw_state = r


# --- терминал ----------------------------------------------------------------
_TR = dict(zip("АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ",
               "A B V G D E E Zh Z I Y K L M N O P R S T U F H C Ch Sh Sch ' Y ' E Yu Ya".split()))
_TR.update({k.lower(): v.lower() for k, v in _TR.items()})


def translit(s: str) -> str:
    return "".join(_TR.get(ch, ch) for ch in s)


class TerminalDevice(Device):
    """Удалённый терминал R -> /api/leds, /api/display, /api/terminal."""
    driver = "terminal"

    def __init__(self, ddef, ctx):
        super().__init__(ddef, ctx)
        self._counts: dict[str, int] | None = None
        self._lines: list[str] | None = None

    @property
    def mapping(self) -> dict:
        m = dict(self.ctx.settings["lamp_mapping"])
        m.update(self.d.settings.get("lamp_mapping", {}))
        return m

    def _split_text(self, text: str) -> list[str]:
        sep = self.ctx.settings["terminal"]["text_line_separator"] or "|"
        parts = text.replace("\r", "").replace("\n", sep).split(sep)[:4]
        parts = [p[:20] for p in parts]
        return parts + [""] * (4 - len(parts))

    async def set_lines(self, lines: list[str]) -> None:
        await self._patch_display({f"line{i}": t for i, t in enumerate(lines)})
        self._lines = lines

    async def set_line(self, index: int, text: str) -> None:
        await self._patch_display({f"line{index}": text})
        if self._lines is not None:
            self._lines[index] = text

    async def _patch_display(self, body: dict) -> None:
        try:
            await self.http("PATCH", "/api/display", body)
        except CCError as e:
            if "Cyrillic" in e.detail and self.ctx.settings["terminal"]["transliterate_on_overflow"]:
                self.ctx.log_event(f"{self.name}: больше 8 разных русских букв — вывожу транслитом")
                body = {k: translit(v)[:20] for k, v in body.items()}
                await self.http("PATCH", "/api/display", body)
            else:
                raise

    async def send(self, cmd: Command) -> str:
        sent = []
        leds = _leds_payload(cmd, self.mapping)
        await self.http("PATCH", "/api/leds", leds)
        sent.append(f"PATCH /api/leds {leds}")
        text = cmd.TEXT
        if text.strip().lower() in ("/clear", "clear()"):
            await self.http("POST", "/api/display/clear")
            self._lines = ["", "", "", ""]
            sent.append("POST /api/display/clear")
        elif text and 1 <= cmd.LINE <= 4:
            await self.set_line(cmd.LINE - 1, text[:20])
            sent.append(f"PATCH /api/display line{cmd.LINE - 1}={text[:20]!r}")
        elif text:
            lines = self._split_text(text)
            if lines != self._lines:
                await self.set_lines(lines)
                sent.append(f"PATCH /api/display {lines}")
        self.feedback["n"] = cmd.N
        self.last_sent = "; ".join(sent)
        return self.last_sent

    async def special(self, code: str) -> str:
        if code in ("1", "2"):
            await self.http("POST", "/api/leds/all/off")
            await self.http("POST", "/api/display/clear")
            await self.http("POST", "/api/buttons/reset")
            self._counts, self._lines = None, ["", "", "", ""]
            self.last_sent = "LED off, дисплей очищен, счётчики кнопок сброшены"
            return self.last_sent
        return await super().special(code)

    async def poll(self) -> None:
        r = await self.http("GET", "/api/terminal", retries=0)
        if not isinstance(r, dict):
            raise CCError(601, f"{self.name}: неожиданный ответ {r!r}")
        self.raw_state = r
        _leds_feedback(r.get("leds", {}), self.mapping, self.feedback)
        btn = r.get("buttons", {})
        counts = {k: int(v.get("count", 0)) for k, v in btn.items()}
        for i, name in enumerate(("green", "yellow", "red"), 1):
            b = btn.get(name, {})
            pressed = bool(b.get("pressed"))
            # короткое нажатие между опросами не теряем: смотрим на рост count
            if self._counts is not None and counts.get(name, 0) > self._counts.get(name, 0):
                pressed = True
            self.feedback[f"b{i}"] = int(pressed)
            self.feedback[f"e{i}"] = counts.get(name, 0)
        self._counts = counts
        self.feedback["p"] = int(bool(r.get("kill_switch")))
        if self._lines is None and isinstance(r.get("lines"), list):
            self._lines = list(r["lines"])


class BarrierDevice(Device):
    """ИК-барьер B1 -> /api/barrier, /api/config."""
    driver = "barrier"
    OUT_OF_RANGE = 500

    async def send(self, cmd: Command) -> str:
        # Порог срабатывания через P (1..500 см); остальное барьер не принимает
        if 1 <= cmd.P <= 500:
            await self.http("PATCH", "/api/config", {"all": int(cmd.P)})
            self.last_sent = f"PATCH /api/config all={cmd.P}"
            return self.last_sent
        return "нет команд для барьера"

    async def special(self, code: str) -> str:
        if code in ("1", "2"):
            await self.http("POST", "/api/barrier/reset")
            self.last_sent = "POST /api/barrier/reset"
            return self.last_sent
        return await super().special(code)

    async def poll(self) -> None:
        r = await self.http("GET", "/api/barrier", retries=0)
        if not isinstance(r, dict) or "sensors" not in r:
            raise CCError(601, f"{self.name}: неожиданный ответ {r!r}")
        self.raw_state = r
        sens = r["sensors"]
        for i, name in enumerate(("top", "middle", "bottom"), 1):
            s = sens.get(name, {})
            dist = s.get("distance_cm")
            self.feedback[f"d{i}"] = self.OUT_OF_RANGE if dist is None else dist
            self.feedback[f"b{i}"] = int(bool(s.get("blocked")))
            self.feedback[f"e{i}"] = int(s.get("count", 0))
        self.feedback["p"] = int(bool(r.get("blocked")))
        self.feedback["n"] = int(r.get("count", 0))
