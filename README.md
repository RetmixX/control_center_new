# IoT ControlCenter 3

Кроссплатформенная замена **IOT Control Center 2.0.x** (Windows, PyQt5, UDP).
Есть две версии на общем ядре: **desktop** (окно, Windows/Linux/macOS) — для проверки и наладки на стенде, и **CLI** — для постоянной работы на Linux-сервере.

| | Было (2.0.x) | Стало (3.0) |
|---|---|---|
| ОС | только Windows | Windows / Linux / macOS |
| Интерфейс | окно PyQt5 | desktop: окно Qt (PySide6); CLI: консоль + веб-страница |
| Связь с оборудованием | текстовый UDP на порт 8888, без подтверждения | HTTP + JSON: подтверждение, таймауты, повторы, контроль «на связи» |
| Обратная связь | UDP-пакеты от устройств | сервер сам опрашивает устройства (по умолчанию раз в 300 мс) |
| Node-RED | WebSocket 8765/8766, при обрыве — переподключать вручную | **тот же протокол**, автоматическое переподключение |
| Конфигурация | `config/*.csv`, `points/*.csv` | те же форматы + `config/settings.json`; типы P1/M/M1 объединены в `M`, R2 стал `R` (старые файлы читаются автоматически) |

**Флоу в Node-RED менять не нужно.** Формат команд IOT Function и обратной связи прежний, имена устройств (`Robot1_1`, `TrafficLights1_2`, `RemoteTerminal1` …) формируются так же.

## Две версии на одном ядре

| | Desktop | CLI (сервер) |
|---|---|---|
| Для чего | проверка и наладка на стенде, работа «как раньше» в окне | постоянная работа на Linux-сервере |
| Интерфейс | окно Qt (PySide6), раскладка как у 2.0 | консоль с командами + веб-интерфейс `http://сервер:8080/` (можно выключить) |
| ОС | Windows, Linux с графикой, macOS | любой Linux без графики, также Windows/macOS/Docker |
| Зависимости | `aiohttp`, `PySide6` | только `aiohttp` |
| Запуск | `run-desktop.bat` / `run-desktop.sh` или собранный `ControlCenter.exe` | `run-server.sh`, systemd-служба, Docker |

Логика работы с Node-RED и оборудованием (`controlcenter/` без `desktop/`) у обеих версий **одна и та же**. Всё, что проверено в desktop-версии на стенде, на сервере будет работать так же. Папки `config/`, `points/`, `logs/` одинаковые, их можно просто перенести на сервер.

```
controlcenter/
  config.py, controller.py, nodered.py, drivers/   общее ядро
  cli.py         CLI/серверная версия      python -m controlcenter
  web.py, static/   веб-интерфейс (для CLI; в desktop включается флагом --web)
  desktop/       desktop-версия            python -m controlcenter.desktop
  runtime.py     запуск ядра в фоновом потоке для desktop
```

---

## Desktop-версия

Нужен Python 3.9 или новее.

**Windows:** запустите `run-desktop.bat`. При первом запуске он создаст `venv-desktop` и поставит PySide6.
**Linux/macOS:** `./run-desktop.sh`.

Окно повторяет ControlCenter 2.0:
* **Connection tools**: подключение к Node-RED (IP можно поменять вручную).
* **Equipment**: флажки Send Data To Robots / Controls, Block Resending, Parse Data, режим координат, запись логов; кнопка Start Equipment connection.
* **Manual control**: поля зависят от выбранного устройства. Манипулятор: X, Y, T, G, V, D0, N и цель (поля / Start / Parking). Лампа: L1–L4. Терминал: L1–L4, номер строки и текст. Барьер: порог P. Конвейер: N, P. Камера: G. Без Selective Dispatch команда уходит всем устройствам **того же типа**. Кнопки Load / Setup for selected, Selective Dispatch, Special Activity (Send R/S/1/2/3).
* **Манипулятор**: скорость и насос. Есть прямой HTTP-запрос к любому устройству для наладки.
* **Last TeamData**: кнопки команд. **Transmission Viewer**: устройства, связь, режим, обратная связь. **From Item**: подробности по выбранному устройству.
* Внизу журналы: всё / из Node-RED / на оборудование / ошибки / события. Меню **Theme Color**: Dark / Light.

Как и в 2.0, программа ищет `config/`, `points/`, `logs/` рядом с собой (или в текущей папке). Если не находит — предлагает выбрать папку. Параметры: `--dir ПАПКА`, `--web 8080` (дополнительно открыть веб-интерфейс).

### Сборка в исполняемый файл (как ControlCenter.exe)

На Windows (exe собирается только на Windows, на Linux получится Linux-бинарник):

```bat
python -m venv venv-build
venv-build\Scripts\pip install -r requirements-desktop.txt pyinstaller
venv-build\Scripts\python build\build_desktop.py
```

Результат — папка `dist\ControlCenter\` с `ControlCenter.exe`, рядом скопированы `config\`, `points\`, `logs\`. Python на целевом компьютере не нужен.

---

## CLI-версия (Linux-сервер)

```bash
cd /opt/controlcenter
./run-server.sh                          # первый запуск создаст venv и поставит aiohttp
./run-server.sh --team 1 --equipment     # сразу подключиться к Node-RED команды 1 и к оборудованию
./run-server.sh --no-web                 # без веб-интерфейса, только консоль
```

Если программа запущена в терминале, работает консоль. Журнал печатается в цвете, команды вводятся с клавиатуры:

```
status                        состояние Node-RED, оборудования, флагов
devices | dev <id>            устройства и обратная связь / подробно по одному
teams | team <N>              список команд / выбрать команду
connect [IP] | disconnect     Node-RED
start | stop                  Start/Stop Equipment connection
send <id|all> K=V ...         ручная команда:  send 102 N=1 X=30 Y=200 G=120 V=1  (X — angel, Y — x)
                              send 106 L1=1 Text="Этап 2|Нажмите СТАРТ"
btn <id|all> <r|s|1|2|3>      кнопки Special Activity
flag [robots|controls|block|parse|coord|log on|off]
mode <id> coord|pos|default   режим манипулятора
http <id> GET|POST|PATCH /path [JSON]   прямой запрос:  http 231 PATCH /api/config {"all":60}
show [all|none|error ...]     какие журналы печатать
reload | help | quit
```

`<id>` — STATE устройства из `_PolygonData.csv` (последний октет IP).

Все параметры:

```
python -m controlcenter [--dir ПАПКА] [--team N] [--nodered-ip IP] [--equipment]
                        [--no-web] [--host 0.0.0.0] [--port 8080] [--no-console] [--console] [--quiet]
```

### Как служба systemd

```bash
sudo useradd -r -s /usr/sbin/nologin controlcenter
sudo mkdir -p /opt/controlcenter && sudo cp -r . /opt/controlcenter && sudo chown -R controlcenter /opt/controlcenter
cd /opt/controlcenter && sudo -u controlcenter python3 -m venv venv && sudo -u controlcenter venv/bin/pip install -r requirements.txt
sudo cp deploy/controlcenter.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now controlcenter
journalctl -u controlcenter -f        # журнал
```

Служба работает без консоли (`--no-console`). Управлять ею можно через веб-интерфейс `http://сервер:8080/`. Чтобы служба при старте сразу подключалась к Node-RED и к оборудованию, задайте в `config/settings.json` поля `"nodered": {"autoconnect_team": 1}` и `"equipment": {"autostart": true}`. Веб-интерфейс на сервере стоит закрыть паролем: `"web": {"username": "...", "password": "..."}`.

### Docker

```bash
docker build -t controlcenter .
docker run -d --name cc --restart unless-stopped --network host -v $(pwd):/data controlcenter
```

`--network host` нужен, если какие-то устройства остались на UDP: им нужен порт 8888 на хосте.

---

## Настройки в программе

Править файлы руками не нужно: все настройки меняются в самой программе.

* **Desktop:** кнопка **⚙ Настройки…** в меню (Ctrl+,).
* **Веб-интерфейс:** кнопка **⚙ Настройки** вверху страницы.
* **CLI:** команды `config`, `get`, `set`, `table`, `row` (см. ниже).

| Вкладка | Что настраивается | Куда записывается |
|---|---|---|
| Основное | порты Node-RED, автоподключение, интервалы опроса и таймауты, флажки по умолчанию, веб-интерфейс и пароль | `config/settings.json` |
| Команды | IP/порт Node-RED, названия, логины | `config/_ServerIPs.csv` |
| Оборудование | ID, тип, IP, имя устройства, свой URL/HTTP-порт, режим координат/позиций (только для манипуляторов `M`); драйвер и HTTP-порт по типам | `config/_PolygonData.csv`, `settings.json` |
| Манипулятор | какое поле Node-RED идёт в `x`, `z`, `angel`, `pov_gripper`, `gripper_state`, скорость; декартовы координаты; номера Start/Parking; резервные позиции | `settings.json` |
| Светофор и терминал | цвета L1..L4, разделитель строк дисплея, транслит | `settings.json` |
| Позиции | точки манипуляторов | `points/_Manipulator.csv` |

**Сохранить и применить** сначала проверяет всё целиком: IP-адреса, числа, диапазоны, повторы ID, имён и номеров позиций. Если есть ошибки, программа ничего не записывает и показывает их список (код 590). Если ошибок нет, она записывает файлы и сразу применяет изменения: связь с Node-RED и оборудованием на секунду останавливается и восстанавливается сама. Только адрес/порт веб-интерфейса и UDP-порт вступают в силу после перезапуска, об этом выводится предупреждение. Перед каждой записью предыдущая версия файла копируется в `config/backup/` (`points/backup/`).

Файлы остаются в прежнем формате, поэтому их по-прежнему можно редактировать вручную или копировать между компьютерами.

Команды CLI:

```
config                                  все настройки (ключ = значение) и список таблиц
get equipment.poll_interval_ms
set equipment.poll_interval_ms 250
set robot_mapping.angel T
table devices                           таблицы: teams, devices, drivers, poses, points_M
row devices 1 URL=http://10.30.8.102:8000 MODE=pos
row teams add IP=192.168.2.50 PORT=1880 NAME="Team 10"
row points_M add NUM=2000 X=220 Y=0 T=0 Z=180
row points_M del 5
```

---

## Структура папок

```
config/_ServerIPs.csv     команды: IP;PORT;NAME;USERNAME;PASSWORD           (как раньше)
config/_PolygonData.csv   оборудование: STATE;KEY;IP;PORT;NAME;ENTRANCE    (как раньше)
config/settings.json      НОВОЕ: драйверы, порты HTTP, сопоставление полей, интервалы
points/_Manipulator.csv   позиции манипуляторов: NUM;X;Y;T;Z
logs/                     log_From_NodeRed_TeamN.txt, log_From_Equipment_TeamN.txt, log_ErrorCode_TeamN.txt
controlcenter/            программа (ядро, cli.py, desktop/)
build/build_desktop.py    сборка desktop-версии в exe (PyInstaller)
deploy/                   служба systemd
tools/emulator.py         эмулятор стенда и Node-RED для проверки без железа
tests/                    сквозные тесты на эмуляторе:  python -m pytest -q
docs/reference/           API устройств, OpenAPI манипулятора, руководство 2.0, протокол 2.0
CLAUDE.md                 описание проекта для Claude Code
```

Если файлы правились вручную, нажмите в интерфейсе «Перечитать config/ и points/». В CLI то же самое делает команда `reload`. Перед этим остановите связь с Node-RED и оборудованием. Можно и просто перезапустить программу.

---

## Связь с Node-RED (без изменений)

* `ws://<IP Node-RED>:8765`: сервер получает команды IOT Function:
  `{"robot_name":"Robot1_1","N":1,"X":200,"Y":30,"T":15,"G":120,"V":1,"D0":0,"L1":0,"L2":0,"L3":0,"L4":0,"P":0,"Text":""}`
* `ws://<IP Node-RED>:8766`: сервер отправляет обратную связь по каждому устройству:
  `{"name":"Robot1_1","n":1,"s":0,"m1":…,"m6":…,"t1":…,"t6":…,"l0":…,"l6":…,"b1":…,"b3":…,"p":…,"e1":…,"e6":…,"d1":…,"d3":…,"online":true}`

Обратная связь уходит при каждом изменении состояния устройства. Кроме того, при каждом (пере)подключении к Node-RED отправляется полный снимок по всем устройствам. Периодический повтор включается в настройках («Повторять обратную связь…», по умолчанию 0 — выключен, чтобы не засыпать IOT Get и debug-узлы). Добавлено поле `online`.

Имя устройства = имя из `_PolygonData.csv` + номер команды: `Robot_1` → `Robot1_1` (команда 1), `Conveyor` → `Conveyor1`.

Пока Node-RED подключён, ручное управление недоступно, как и в 2.0. «Block Resending Transmission» отбрасывает повтор той же самой команды тому же устройству.

---

## Совместимость с плагином node-red-contrib-iot-controlcenter

Проверено вживую: Node-RED 4 + плагин 2.1.1 (узлы **IOT Function**, **IOT Send**, **IOT Get**) + примеры флоу из плагина (Robot Control, TrafficLight, WorkshiftTerminal, LightBarrier).

* Плагин сам поднимает WebSocket-серверы: IOT Send — порт 8765, IOT Get — порт 8766. ControlCenter подключается к ним как клиент, ровно как 2.0. **Плагин менять не нужно.**
* IOT Function отправляет все значения строками (`"N":"0"`, `"X":"170"`), а Text может отсутствовать. ControlCenter это принимает.
* Имена в `robot_name` должны совпадать с именами из таблицы «Оборудование» плюс номер команды. В примерах плагина терминал называется `WorkshiftTerminal1`, а в `_PolygonData.csv` — `RemoteTerminal`. Либо переименуйте устройство в настройках, либо используйте в флоу `RemoteTerminal1`.
* **К одному Node-RED должен быть подключён только один ControlCenter.** IOT Send рассылает команды всем подключённым клиентам. Если одновременно запущены desktop-версия и сервер, каждая команда уйдёт на оборудование дважды.
* У плагина есть два собственных недочёта, они на работу не влияют: `ws` не указан в его зависимостях (работает за счёт модуля из самого Node-RED), а IOT Get без проверки делает `JSON.parse` входящих сообщений (ControlCenter всегда шлёт корректный JSON).

---

## Как поля IOT Function попадают на оборудование

### Манипуляторы M → Motors API (`http://IP:8000`)

| Node-RED | Motors API | Примечание |
|---|---|---|
| X | `x` | |
| G | `z` | в старом протоколе G — высота Z |
| Y | `angel` | поворот основания |
| T | `pov_gripper` | поворот инструмента |
| V (0/1) | `gripper_state` + `POST /api/motors/pump` | другое значение → ошибка 482 |
| D0 (1..100) | `POST /api/motors/speed` | 0 — скорость не трогать |
| Text = `Start` / `Parking` | позиция 2000 / 2001 из `points/` | если строк нет — берутся `fallback_poses` из settings.json |

Команда уходит в `POST /api/motors/pos/set`. Значения округляются до целых: так требует API.
В режиме позиций (флажок «Режим координат» снят или режим задан для устройства в таблице) X — номер точки из `points/` (столбцы X;Y;T;Z). Если такого номера нет — ошибка 481.
В **Manual Control** (окно, веб, команда `send`) в режиме координат X и Y переставлены: X → `angel`, Y → `x`; G → `z`, T → `pov_gripper`, V — как в таблице. Настраивается в `manual_mapping`. Node-RED, `points/` и Start/Parking это не затрагивает, а **Load selected** переводит команду из Node-RED в поля формы так, чтобы поза не менялась.
Сопоставление для Node-RED настраивается в `robot_mapping`. Если в Node-RED X/Y декартовы, а манипулятор принимает «вылет + угол», включите `"cartesian": true`: тогда `x = √(X²+Y²)`, `angel = atan2(Y, X)`.

Команды одному манипулятору выполняются строго по очереди, следующая уходит после ответа на предыдущую. Разные устройства работают параллельно.

Обратная связь: `m1..m6` — из `GET /api/motors/pos`, `t1..t6` — из `/temp`, `l1..l6` — из `/load` (раз в 2 с), `n` — N последней выполненной команды, `s`: 0 — готов, 1 — выполняет, 2 — нет связи.

### Светофор T → лампа `/api/lamp`

`L1..L4` → цвета по `lamp_mapping` (по умолчанию L1=red, L2=yellow, L3=green, L4=blue), `PATCH /api/lamp`.
Обратная связь: `l1..l4` — фактическое состояние светодиодов.

### Терминал R → `/api/leds`, `/api/display`, `/api/terminal`

`L1..L4` — светодиоды (как у лампы). `Text` — дисплей, строки разделяются `|` (до 4 строк по 20 символов): `"Этап 2|Нажмите СТАРТ"`. Необязательное поле `Line` = 1..4 записывает `Text` только в эту строку, остальные не меняются. Пустой Text очищает дисплей, как в 2.0 (пример «WorkshiftTerminal clear all» из плагина). Это поведение выключается в настройках. `/clear` тоже очищает его. Если дисплей отказывает из-за более чем 8 разных «своих» русских букв, текст автоматически выводится транслитом.
Обратная связь: `b1` / `b2` / `b3` — кнопки СТАРТ (зелёная) / ПАУЗА (жёлтая) / ОТМЕНА (красная). Короткое нажатие между опросами не теряется. `e1..e3` — счётчики нажатий, `p` — kill switch, `l1..l4` — светодиоды.

### ИК-барьер B1 → `/api/barrier`

Обратная связь: `d1` / `d2` / `d3` — расстояние top / middle / bottom в см (500 — вне диапазона), `b1..b3` — датчик перекрыт, `p` — барьер перекрыт, `n` — общий счётчик проходов, `e1..e3` — счётчики датчиков.
Команда: `P` = 1..500 задаёт порог срабатывания для всех датчиков.

### Конвейер C, смарт-камера SC, сканер BR и прочие — старый UDP

Для них новый API не передан, поэтому они работают по прежнему UDP-протоколу (порт 8888, те же форматы сообщений). Когда появится HTTP API, достаточно добавить драйвер и указать его в `settings.json → drivers`.

### Кнопки Special Activity

| Кнопка | Действие |
|---|---|
| Send R / Send S | включить / выключить опрос (обратную связь) устройства |
| Send 1 / Send 2 | манипуляторы — Start / Parking; лампа и терминал — сброс (всё выкл., дисплей очищен); барьер — сброс счётчиков |
| Send 3 | «расслабить звенья» — в Motors API такой команды нет, выдаётся код 585 |

---

## settings.json

Всё из этой таблицы меняется в окне **Настройки**. Описание оставлено для справки.

| Раздел | Поле | По умолчанию | Смысл |
|---|---|---|---|
| nodered | ws_commands_port / ws_feedback_port | 8765 / 8766 | порты WebSocket Node-RED |
| | reconnect_sec | 3 | пауза между попытками переподключения |
| | use_basic_auth | false | отправлять логин/пароль из `_ServerIPs.csv` |
| | autoconnect_team | null | номер команды для автоподключения при старте |
| web | host / port | 0.0.0.0 / 8080 | адрес веб-интерфейса |
| | username / password | "" | если заданы — вход по паролю (Basic Auth) |
| equipment | autostart | false | запускать связь с оборудованием при старте |
| | poll_interval_ms | 300 | интервал опроса (API рекомендует 100–500 мс) |
| | http_timeout_ms / robot_timeout_ms | 1500 / 15000 | таймаут запроса / команды движения |
| | retries | 2 | повторы при сетевой ошибке (кроме команды движения) |
| | feedback_heartbeat_ms | 0 | период повтора обратной связи по всем устройствам; 0 — только при изменениях |
| | udp_listen_port | 8888 | порт для устройств на UDP |
| drivers | `<KEY>` | см. файл | драйвер (`robot`, `lamp`, `terminal`, `barrier`, `udp`) и `http_port` для типа устройства |
| devices | `<STATE>` | {} | переопределения для конкретного устройства: `url`, `http_port`, `coordinate_mode`, `robot_mapping`, `lamp_mapping` |
| robot_mapping | | см. выше | сопоставление полей Node-RED с Motors API |
| manual_mapping | | x=Y, z=G, angel=X, pov_gripper=T | сопоставление полей формы Manual Control с Motors API (режим координат) |
| lamp_mapping | | L1=red… | сопоставление L1..L4 с цветами |
| fallback_poses | | | Start/Parking, если в `points/` нет строк 2000/2001 |

Пример: манипулятор с id 102 слушает другой порт и работает в режиме позиций:

```json
"devices": { "102": { "url": "http://10.30.8.102:5000", "coordinate_mode": false } }
```

Столбец PORT в `_PolygonData.csv` (8888) используется только UDP-устройствами. HTTP-порт берётся из `drivers` или `devices`.

---

## Коды ошибок

Прежние коды сохранены: 404, 471, 472, 473, 481, 482, 570, 571, 591, 592, 593. Изменённые и новые:

| Код | Значение |
|---|---|
| 590 | в настройках ошибка, ничего не сохранено (в сообщении — список, что исправить) |
| 581 | ошибка HTTP-запроса к манипулятору (нет ответа) |
| 582 | ошибка HTTP-запроса к остальному оборудованию |
| 583 | устройство перестало отвечать на опрос (пишется один раз, до восстановления связи) |
| 584 | устройство ответило HTTP-ошибкой, в тексте — причина. Команда: пишется каждый раз. Опрос: пишется один раз, устройство считается не на связи (`online: false`, `s: 2`), пока опрос снова не пройдёт полностью |
| 585 | команда не поддерживается API устройства |
| 601 | ошибка разбора обратной связи |

---

## Проверка без оборудования

```bash
python3 tools/emulator.py      # манипуляторы :9101/:9102, лампы :9201/:9202, терминал :9301, барьер :9401,
                               # «Node-RED» ws :8765/:8766 и http://127.0.0.1:1880/inject
```

В `settings.json → devices` пропишите `url` эмулятора: 102 → `:9101`, 104 → `:9102`, 103 → `:9201`, 101 → `:9202`, 106 → `:9301`, 231 → `:9401` (например `"102": {"url": "http://127.0.0.1:9101"}`), и выберите команду с IP `127.0.0.1` (Team 9, устройства называются `Robot9_1` и т.д.). Конвейер, камера и сканер работают по UDP, эмулятора для них нет. Команду «из Node-RED» можно отправить так:

```bash
curl -d '{"robot_name":"Robot9_1","N":1,"X":200,"Y":30,"T":15,"G":120,"V":1,"Text":""}' http://127.0.0.1:1880/inject
curl http://127.0.0.1:1880/feedback       # что пришло в Node-RED
```
