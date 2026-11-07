# Запуск ControlCenter в Docker

Инструкция описывает запуск рабочих зон 1–4 через Docker Compose. Каждая зона содержит отдельные ControlCenter, Node-RED, сервис регистрации, MySQL и phpMyAdmin.

## 1. Требования

- Docker Engine с Docker Compose v2 или Docker Desktop.
- Свободные порты из таблицы ниже.
- Команды выполняются из корня проекта, где находится `docker-compose.yml`.

Проверка Docker:

```bash
docker version
docker compose version
```

В Windows команды можно выполнять в PowerShell. Для Linux и macOS подходят те же команды.

## 2. Настройка перед первым запуском

Задайте собственный пароль администратора MySQL и секреты Node-RED. Не используйте значения по умолчанию при доступе из сети.

PowerShell:

```powershell
$env:MYSQL_ROOT_PASSWORD = "задайте-сложный-пароль"
$env:NODE_RED_CREDENTIAL_SECRET_1 = "задайте-случайный-секрет-зоны-1"
```

При запуске нескольких зон задайте также `NODE_RED_CREDENTIAL_SECRET_2`, `NODE_RED_CREDENTIAL_SECRET_3` и `NODE_RED_CREDENTIAL_SECRET_4`.

Переменные действуют только в текущем терминале. Для постоянной настройки можно создать в корне проекта файл `.env`:

```dotenv
MYSQL_ROOT_PASSWORD=задайте-сложный-пароль
NODE_RED_CREDENTIAL_SECRET_1=задайте-случайный-секрет-зоны-1
NODE_RED_CREDENTIAL_SECRET_2=задайте-случайный-секрет-зоны-2
NODE_RED_CREDENTIAL_SECRET_3=задайте-случайный-секрет-зоны-3
NODE_RED_CREDENTIAL_SECRET_4=задайте-случайный-секрет-зоны-4
```

Файл `.env` содержит секреты: не публикуйте и не отправляйте его другим участникам.

Важно: задайте эти значения до первого запуска и сохраните их. Изменение `MYSQL_ROOT_PASSWORD` не меняет пароль в уже инициализированном томе MySQL, а смена секрета Node-RED может сделать сохранённые учётные данные флоу недоступными.

## 3. Запуск

Первая зона:

```bash
docker compose --profile zone1 up -d --build
```

Несколько зон:

```bash
docker compose --profile zone1 --profile zone2 up -d --build
```

Все зоны:

```bash
docker compose --profile zone1 --profile zone2 --profile zone3 --profile zone4 up -d --build
```

Первый запуск может занять несколько минут: Docker загрузит образы и соберёт ControlCenter и Node-RED.

Проверка состояния:

```bash
docker compose --profile zone1 ps
curl http://localhost:3001/health
```

Сервис регистрации должен вернуть `{"status":"ok"}`. Для другой зоны используйте её порт регистрации.

## 4. Адреса сервисов

| Зона | ControlCenter | Node-RED | Регистрация | phpMyAdmin | MySQL, только localhost |
|---|---|---|---|---|---|
| 1 | http://localhost:8081 | http://localhost:1881 | http://localhost:3001 | http://localhost:8091 | 3307 |
| 2 | http://localhost:8082 | http://localhost:1882 | http://localhost:3002 | http://localhost:8092 | 3308 |
| 3 | http://localhost:8083 | http://localhost:1883 | http://localhost:3003 | http://localhost:8093 | 3309 |
| 4 | http://localhost:8084 | http://localhost:1884 | http://localhost:3004 | http://localhost:8094 | 3310 |

При подключении с другого компьютера замените `localhost` на IP-адрес сервера и разрешите соответствующие порты в брандмауэре. Прямой порт MySQL доступен только на самом сервере; участникам для работы с базой достаточно phpMyAdmin и Node-RED.

## 5. Регистрация и работа участника

1. Откройте страницу регистрации своей зоны.
2. Придумайте логин: 3–32 символа, строчные латинские буквы, цифры и `_`; первый символ — буква.
3. Задайте непустой пароль длиной до 128 символов.
4. После регистрации сохраните показанные параметры MySQL.

Одна регистрация создаёт:

- учётную запись Node-RED;
- пользователя MySQL с тем же логином и паролем;
- отдельную базу данных, имя которой совпадает с логином.

Для входа в Node-RED и phpMyAdmin используются созданные логин и пароль. В phpMyAdmin участник видит только свою базу.

В узле **MySQLdatabase** внутри Node-RED укажите:

- хост: `mysql-1`, `mysql-2`, `mysql-3` или `mysql-4` — по номеру зоны;
- порт: `3306`;
- база, пользователь и пароль: данные из результата регистрации.

Перезапуск Node-RED после регистрации нового участника не требуется. Участники одной зоны используют общие флоу, но отдельные базы данных.

## 6. Обновление после изменения кода

Пересоберите образы и пересоздайте контейнеры нужной зоны:

```bash
docker compose --profile zone1 up -d --build
```

Обычный `restart` не подтягивает изменения в файлы, скопированные внутрь Docker-образа.

## 7. Остановка и повторный запуск

Остановить первую зону с сохранением данных:

```bash
docker compose --profile zone1 stop
```

Запустить её снова:

```bash
docker compose --profile zone1 up -d
```

Остановить и удалить контейнеры проекта:

```bash
docker compose down
```

Команда `down` не удаляет именованные тома: аккаунты, базы MySQL, флоу и настройки сохраняются. Не используйте `down -v`, если данные нужны.

## 8. Логи и диагностика

Все сервисы зоны:

```bash
docker compose --profile zone1 logs -f
```

Отдельный сервис:

```bash
docker compose --profile zone1 logs -f registration-1
docker compose --profile zone1 logs -f mysql-1
docker compose --profile zone1 logs -f nodered-1
docker compose --profile zone1 logs -f controlcenter-1
docker compose --profile zone1 logs -f phpmyadmin-1
```

Проверка конфигурации Compose:

```bash
docker compose config -q
```

Если порт занят, задайте другой перед запуском. Например, в PowerShell:

```powershell
$env:PHPMYADMIN_PORT_1 = "18091"
$env:REGISTRATION_PORT_1 = "13001"
docker compose --profile zone1 up -d
```

Доступные переменные портов: `CONTROLCENTER_PORT_N`, `CONTROLCENTER_UDP_PORT_N`, `NODERED_PORT_N`, `REGISTRATION_PORT_N`, `PHPMYADMIN_PORT_N`, `MYSQL_PORT_N`, где `N` — номер зоны от 1 до 4.

Если Node-RED открывается через другой внешний адрес или обратный прокси, задайте `NODERED_URL_N`, чтобы кнопка перехода после регистрации вела на правильный адрес.
