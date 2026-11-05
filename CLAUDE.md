# CLAUDE.md — IoT ControlCenter 3

Связующее ПО между **Node-RED** (плагин `node-red-contrib-iot-controlcenter`) и оборудованием учебного
IoT-полигона: манипуляторы, светофоры, терминал, ИК-барьер, конвейер, камера и т.д.
Это замена ControlCenter 2.0.x (Windows, PyQt5, текстовый UDP). Новая версия работает на Python 3.9+
на Linux, Windows и macOS, оборудование подключается по HTTP/JSON.

Язык проекта — русский: интерфейс, сообщения журнала, комментарии, README. Пиши так же.

## Команды

```bash
pip install -r requirements.txt pytest          # ядро + CLI (только aiohttp)
pip install -r requirements-desktop.txt         # + PySide6 для desktop-версии
python -m pytest -q                             # сквозные тесты на эмуляторе (~10 с), должны быть зелёными
python -m controlcenter --dir . --console       # CLI-версия + веб-интерфейс :8080
python -m controlcenter.desktop --dir .         # desktop-версия (окно Qt)
python tools/emulator.py                        # эмулятор стенда и «Node-RED» для ручной проверки
python build/build_desktop.py                   # сборка desktop в exe (PyInstaller)
```

Без дисплея desktop проверяется так: `QT_QPA_PLATFORM=offscreen`, затем `MainWindow(...).grab().save(...)`.

## Архитектура

```
controlcenter/
  config.py           загрузка/запись config/*.csv, points/*.csv, settings.json; DEFAULT_SETTINGS
  settings_schema.py  схема ВСЕХ настроек для редакторов (поля, таблицы, вкладки), проверка, build()
  errors.py           коды ошибок (как в 2.0 + 583–585, 590) и CCError
  nodered.py          WsLink — WebSocket-клиент к Node-RED с автопереподключением
  controller.py       ядро: команды из Node-RED -> очереди устройств -> драйверы; опрос; обратная связь;
                      журналы; save_config() — сохранение и применение настроек «на лету»
  drivers/
    base.py           Device (общий HTTP-клиент: компактный JSON, таймаут, повторы, 1 запрос за раз),
                      Command (разбор IOT Function), FEEDBACK_KEYS
    robot.py          манипуляторы P1/M/M1 -> Motors API
    arduino.py        лампа (T), терминал (R2), ИК-барьер (B1) -> HTTP API на Arduino
    udp_legacy.py     старый UDP-протокол 2.0 для устройств без HTTP API (C, SC, BR, ...)
  web.py + static/index.html   REST API и веб-интерфейс (используется CLI; в desktop — флаг --web)
  cli.py              CLI/серверная версия: консольные команды, systemd (--no-console)
  runtime.py          start_web(); ControllerThread — ядро в фоновом потоке для desktop
  desktop/app.py, desktop/settings_dialog.py   desktop-версия (PySide6)
tools/emulator.py     эмуляторы устройств и Node-RED (используются тестами)
tests/test_e2e.py     сквозные тесты
docs/reference/       исходные документы: API устройств, OpenAPI манипулятора, руководство 2.0 (PDF),
                      восстановленный протокол 2.0 (legacy_protocol.md)
```

Одно ядро на обе версии. Логику оборудования и Node-RED меняй только в ядре (`controller.py`, `drivers/`),
а не в `cli.py` или `desktop/`. Новая настройка добавляется в `DEFAULT_SETTINGS` (config.py) и в
`SECTIONS`/`TABLES` (settings_schema.py), после этого она сама появляется в desktop, веб-интерфейсе и CLI (`set`).

## Инварианты — не ломать

1. **Протокол с Node-RED совместим с 2.0 и с плагином** `node-red-contrib-iot-controlcenter` 2.1.1
   (github.com/M1khailF/node-red-contrib-iot-controlcenter). Плагин сам поднимает WS-серверы
   (IOT Send — :8765, IOT Get — :8766), ControlCenter подключается как **клиент**.
   - Команды: `{"robot_name","N","X","Y","T","G","V","D0","L1".."L4","P","Text"}`; значения приходят **строками**,
     `Text` может отсутствовать.
   - Обратная связь: `{"name","n","s","m1".."m6","t1".."t6","l0".."l6","b1".."b3","p","e1".."e6","d1".."d3","online"}`.
     IOT Get делает `JSON.parse` без try: отправлять только корректный JSON.
   - Имя устройства для Node-RED: `Robot_1` -> `Robot{N}_1`, `Conveyor` -> `Conveyor{N}`, где N — номер команды.
   - Поля и порты не переименовывать: на них завязаны флоу команд.
2. **Форматы файлов** `_ServerIPs.csv`, `_PolygonData.csv`, `points/*.csv` (разделитель `;`, CRLF) — как в 2.0.
3. Коды ошибок 2.0 (404, 471–474, 481, 482, 570, 571, 591–593) сохраняют смысл.
4. Arduino-устройства обслуживают одного клиента за раз: все запросы к устройству идут под `Device._lock`.
5. Команды одному манипулятору выполняются строго по очереди (FIFO). Для ламп и терминала важна только
   последняя команда (очередь схлопывается).
6. К одному Node-RED подключается только один ControlCenter: IOT Send рассылает команды всем клиентам.

## Ограничения от владельца

- **Смарт-камеру (SC, TrackingCam v3) не трогать.** Она остаётся на драйвере `udp` (`udp_legacy.py`).
  Не добавляй драйверы, настройки или зависимости для камеры, пока владелец не попросит явно.
- Без согласования не добавляй зависимости, кроме `aiohttp` (ядро/CLI) и `PySide6` (desktop).

## Не подтверждено на реальном оборудовании (всё проверено только на эмуляторе)

- Порт Motors API — по умолчанию 8000 (`drivers.P1.http_port`).
- Сопоставление полей манипулятора: X→x, G→z, Y→angel, T→pov_gripper, V→gripper_state+насос, D0→скорость
  (`robot_mapping`; есть опция `cartesian`).
- Формат ответа `/api/motors/pos|temp|load` — схема пустая; берутся первые 6 чисел (`robot.numbers()`).
- Кнопка «Send 3» (расслабить звенья) — в Motors API нет, выдаётся 585.
- Позиций 2000/2001 (Start/Parking) в поставляемых points/ нет — используются `fallback_poses`.

## Как вести работу

- После любых изменений запускай `python -m pytest -q`. Новое поведение покрывай тестом в `tests/test_e2e.py`;
  если нужно, расширяй эмулятор в `tools/emulator.py`.
- При изменениях интерфейса проверь веб-страницу (Playwright, скриншот) и desktop (offscreen + grab).
- Обновляй README.md (раздел для пользователя) при изменении поведения или настроек.
