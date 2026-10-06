# Мониторинг нод Remnawave и ограниченный автохил

Это комплект для Debian/Ubuntu. Он рассчитан на отдельный сервер мониторинга и ноды с Remnawave Node в Docker-контейнере с именем remnanode. Примеры IP-адресов, паролей и идентификаторов необходимо заменить своими.

## Что входит в комплект

На сервере мониторинга работают Prometheus, Alertmanager, Grafana OSS, blackbox exporter, Telegram-отчёт каждые 3 часа и небольшой исполнитель автохила. Каждый отчёт суммирует последние 24 часа.

На каждой VPN-ноде работают node_exporter, таймер проверки контейнера и ограниченная SSH-команда. Автохил может перезапустить только контейнер remnanode. Он не перезагружает VPS.

Сигнал автохила формируется, только если VPN-порт недоступен 3 минуты, Node Exporter отвечает, контейнер remnanode отмечен работающим и проверка его состояния свежая. Если недоступна вся нода или сам Node Exporter, исполнитель не перезапускает контейнер и отправляет обычный алерт.

## 1. Подготовить сервер мониторинга

Установите Docker Engine и Docker Compose plugin по официальной инструкции Docker для Debian/Ubuntu. Скопируйте каталог комплекта в /opt/remnawave-monitoring:

~~~bash
sudo mkdir -p /opt/remnawave-monitoring
sudo chown "$USER":"$USER" /opt/remnawave-monitoring
cd /opt/remnawave-monitoring
~~~

Создайте локальный файл настроек и секреты:

~~~bash
cp .env.example .env
mkdir -p secrets
chmod 700 secrets
openssl rand -hex 24
~~~

Скопируйте сгенерированную строку в .env как GRAFANA_ADMIN_PASSWORD. Укажите пользователя Grafana и числовой Telegram chat ID в TELEGRAM_CHAT_ID. Для пароля используйте hex-строку, чтобы избежать проблем с символами подстановки Docker Compose. Также задайте свой домен в GRAFANA_DOMAIN и полный URL в GRAFANA_ROOT_URL, например monitor.example.com и https://monitor.example.com/.

Создайте секреты:

~~~bash
umask 077
read -r -s -p 'Токен Telegram-бота: ' TG_TOKEN; echo
printf '%s' "$TG_TOKEN" > secrets/telegram_bot_token
unset TG_TOKEN
openssl rand -hex 32 > secrets/healer_bearer_token
ssh-keygen -t ed25519 -N '' -f secrets/healer_ssh_key
chmod 600 .env secrets/telegram_bot_token secrets/healer_bearer_token secrets/healer_ssh_key
~~~

Не отправляйте секреты в переписку и не добавляйте их в Git. Каталог secrets исключён из Git файлом .gitignore. Контейнеры Alertmanager и healer читают секреты только из смонтированного каталога, без доступа к Docker socket сервера.

### Настроить Caddy и открыть Grafana на домене

Caddy уже добавлен в docker-compose.yml, а прокси настроен в caddy/Caddyfile. Вручную писать конфиг Caddy не требуется. Он принимает запросы на домене и пересылает их на внутренний адрес Grafana. Логин и пароль проверяет сама Grafana; анонимный доступ и регистрацию новых пользователей мы отключили.

**Шаг 1. Указать домен.** Зарегистрируйте домен или используйте свой поддомен, например stats.example.com. В DNS создайте A-запись этого имени на публичный IPv4-адрес сервера мониторинга. Убедитесь, что запись уже разрешается на правильный адрес:

~~~bash
dig +short stats.example.com
~~~

Если у сервера настроен публичный IPv6, можно добавить AAAA-запись. Не добавляйте её, если IPv6 не настроен: некоторые клиенты будут пытаться подключаться по нему и не попадут на сервер.

**Шаг 2. Заполнить .env.** В /opt/remnawave-monitoring/.env замените примеры на свои значения:

~~~dotenv
GRAFANA_ADMIN_USER=свой_логин
GRAFANA_ADMIN_PASSWORD=длинный_случайный_пароль
GRAFANA_DOMAIN=stats.example.com
GRAFANA_ROOT_URL=https://stats.example.com/
~~~

Значение GRAFANA_DOMAIN должно совпадать с DNS-именем, а GRAFANA_ROOT_URL — содержать полный адрес с https:// и завершающим слешем. Генерируйте пароль, например, командой openssl rand -hex 24. Конфигурация Grafana запрещает анонимный вход и регистрацию пользователей.

**Шаг 3. Разрешить порты.** В панели управления VPS и в локальном firewall откройте входящие TCP-порты 80 и 443. В Compose дополнительно опубликован UDP-порт 443 для HTTP/3; его можно разрешить по желанию. Caddy использует TCP 80/443 для HTTP и HTTPS, проверки домена и выпуска сертификата.

Проверьте, что порты 80 и 443 свободны:

~~~bash
sudo ss -ltnp | grep -E ':(80|443)( |$)'
~~~

Если эту команду выполняли через PowerShell/Windows, проверять нужно на самом Linux-сервере. Если там уже слушает Nginx, другой Caddy, Remnawave proxy или другой веб-сервер, встроенный сервис Caddy не сможет занять порты. В таком случае выключите сервис caddy в docker-compose.yml и добавьте в существующий proxy виртуальный хост stats.example.com с upstream http://127.0.0.1:3000. Порт Grafana уже привязан только к localhost.

**Шаг 4. Запустить и проверить.** Из каталога проекта выполните:

~~~bash
cd /opt/remnawave-monitoring
docker compose config
docker compose up -d --build
docker compose ps caddy grafana
docker compose logs -f caddy
~~~

В логах Caddy дождитесь успешной выдачи сертификата. Затем откройте https://stats.example.com. Браузер должен показать страницу входа Grafana; войдите логином и паролем из .env. После первого старта сменить пароль можно в интерфейсе Grafana либо через .env перед первоначальным запуском.

Если сертификат не выдался, проверьте: DNS указывает на этот сервер; TCP 80/443 разрешены и доступны извне; домен не проксируется через другой сервис; имя в .env совпадает с адресом браузера. Смотрите подробности в docker compose logs caddy.

Caddy автоматически перенаправляет HTTP на HTTPS и продлевает сертификат. Это стандартный автоматический HTTPS Caddy и reverse_proxy на внутренний Grafana. [Документация Caddy по HTTPS](https://caddyserver.com/docs/quick-starts/https), [директива reverse_proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy).

## 2. Подключить метрики Remnawave Panel к Prometheus (два VPS с постоянными публичными IP)

Этот раздел выполняется на **двух серверах с постоянными публичными IPv4**. WireGuard и панель управления хостером не используются. Prometheus подключается к публичному адресу VPS панели на порту `3001`; доступ ограничивается UFW на самой панели. Grafana и дашборд уже включены в комплект.

**Сначала запишите свои адреса** — не копируйте эти слова как IP:

~~~text
PANEL_PUBLIC_IP   = публичный IPv4 сервера, где установлена Remnawave Panel
MONITOR_PUBLIC_IP = публичный IPv4 сервера, где будет Prometheus и Grafana
~~~

Например, если IP панели `198.51.100.20`, а IP мониторинга `203.0.113.10`, то в местах ниже вместо `PANEL_PUBLIC_IP` пишите `198.51.100.20`, а вместо `MONITOR_PUBLIC_IP` — `203.0.113.10`. Это демонстрационные IP; подставьте адреса своих VPS. Значения не взаимозаменяемы.

### 2.1. На VPS с Remnawave Panel: задать логин и пароль метрик

Подключитесь по SSH именно к серверу панели. Откройте файл окружения (в стандартной установке Remnawave он находится в `/opt/remnawave/.env`):

~~~bash
cd /opt/remnawave
sudo nano .env
~~~

В файле найдите строки `METRICS_USER` и `METRICS_PASS`. Измените их или добавьте в конец файла, если их нет. Задайте собственный длинный пароль и сохраните его отдельно — он понадобится на VPS мониторинга:

~~~dotenv
METRICS_PORT=3001
METRICS_USER=admin
METRICS_PASS=ВСТАВЬТЕ_СЮДА_СВОЙ_ДЛИННЫЙ_СЛУЧАЙНЫЙ_ПАРОЛЬ
~~~

Не оставляйте примерный пароль и не отправляйте его в чат. В `nano`: сохранить — `Ctrl+O`, затем Enter; выйти — `Ctrl+X`.

### 2.2. На VPS с Remnawave Panel: разрешить порт только с IP мониторинга через UFW

На сервере панели откройте `/opt/remnawave/docker-compose.yml`. В секции сервиса `remnawave` добавьте публикацию порта в список `ports:` (остальные строки не удаляйте). Порт хоста должен слушать публичный интерфейс, а не только `127.0.0.1`:

~~~yaml
      - "PANEL_PUBLIC_IP:3001:3001"
~~~

Замените `PANEL_PUBLIC_IP` на реальный публичный IPv4 панели. Затем разрешите входящий маршрут TCP `3001` только с публичного IP сервера мониторинга. Команда выполняется **на VPS панели**:

~~~bash
sudo ufw route allow proto tcp from MONITOR_PUBLIC_IP to any port 3001
~~~

Пример для адреса мониторинга `193.0.2.10`: `sudo ufw route allow proto tcp from 193.0.2.10 to any port 3001`. В `ufw status numbered` такое правило может отображаться как `ALLOW FWD`. Не открывайте порт для `Anywhere`. Не устанавливайте `ufw-docker` специально для этой инструкции.

### 2.3. Применить настройки на VPS панели

Из `/opt/remnawave` проверьте имя сервиса панели в `docker-compose.yml` (это ключ под `services:`, часто `remnawave`). Пересоздайте **только контейнер панели**, чтобы применились `.env` и новая публикация порта:

~~~bash
docker compose config --services
docker compose up -d --force-recreate ИМЯ_СЕРВИСА_ПАНЕЛИ
docker compose ps
~~~

При пересоздании панель будет недоступна короткое время. Не запускайте `docker compose down`: он остановит весь стек Remnawave. Проверьте, что порт 3001 опубликован:

~~~bash
sudo ss -ltnp | grep ':3001'
~~~

### 2.4. На VPS мониторинга: передать Prometheus тот же пароль

Подключитесь по SSH к VPS мониторинга, перейдите в каталог проекта (ниже предполагается `/opt/remnawave-monitoring`) и создайте файл секрета. Когда появится приглашение, вставьте **точно тот пароль**, который записали в `METRICS_PASS` на сервере панели, затем нажмите Enter:

~~~bash
cd /opt/remnawave-monitoring
sudo install -o 65534 -g 65534 -m 0400 /dev/null secrets/remnawave_metrics_password
sudo nano secrets/remnawave_metrics_password
~~~

В `nano` вставьте пароль одной строкой, сохраните `Ctrl+O`, Enter, выйдите `Ctrl+X`. Файл содержит только пароль, без `METRICS_PASS=` и без кавычек.

### 2.5. На VPS мониторинга: указать адрес панели в Prometheus

На VPS мониторинга откройте файл `prometheus/panel-targets.yml`. Здесь используется IP **сервера панели**. Замените `PANEL_PUBLIC_IP` на его реальный IPv4; порт оставьте `3001`:

~~~yaml
- targets: ["PANEL_PUBLIC_IP:3001"]
  labels:
    app: "remnawave"
~~~

В файле `prometheus/prometheus.yml` задан путь `/metrics`, логин `admin` и чтение пароля из созданного файла. Логин в Prometheus должен в точности совпадать с `METRICS_USER` на панели. Проверьте соединение с VPS мониторинга:

~~~bash
curl -u admin http://PANEL_PUBLIC_IP:3001/metrics
~~~

Введите пароль при запросе. Поле останется пустым — curl не показывает вводимые символы и это нормально. Вставьте пароль и нажмите Enter. Если видите строки метрик (`# HELP`, `# TYPE`, `remnawave_...`), сеть и авторизация работают. Если `timeout` — проверьте публичный IP, привязку Docker-порта и правило UFW; если `401` — логин/пароль не совпадают; если `connection refused` — проверьте публикацию порта и контейнер панели. Не запускайте `ufw-docker` специально для этой инструкции.

Перезапустите Prometheus, чтобы он перечитал конфигурацию, и проверьте статус сбора:

~~~bash
docker compose restart prometheus
~~~

Откройте `https://ДОМЕН_GRAFANA`, войдите учётными данными Grafana и перейдите в **Dashboards → Remnawave**. Через один-два интервала сбора откройте **Status → Targets** в Prometheus (локально на VPS мониторинга: `http://127.0.0.1:9090/targets`). У job `remnawave` должен быть статус **UP**. Если `DOWN`, откройте его ошибку: там будет причина подключения.

`UP` означает, что метрики панели уже поступают. Дашборд Grafana в этом комплекте provisioned автоматически. Метрики CPU/RAM каждой VPN-ноды появятся после установки Node Exporter на нодах и добавления их адресов в `prometheus/targets.yml` (следующие разделы инструкции). Встроенные метрики панели сами по себе не заменяют Node Exporter.

## 3. Заполнить список нод

Отредактируйте prometheus/targets.yml. В нём указываются только адреса node_exporter на порту 9100:

~~~yaml
- targets: ["198.51.100.20:9100"]
  labels:
    node: "est-001"
    role: "vpn-node"
~~~

Отредактируйте prometheus/vpn-targets.yml. В нём укажите публичный IP и пользовательский VPN-порт, к которому подключаются клиенты:

~~~yaml
- targets: ["198.51.100.20:443"]
  labels:
    node: "est-001"
    role: "vpn-node"
~~~

Идентификатор `node` должен совпадать в обоих файлах. В примере комплекта используются три тестовых ID: `est-001`, `lat-001`, `ltu-001`. В `targets.yml` не добавляйте VPN-порты; в `vpn-targets.yml` не добавляйте порт 9100. Примеры IP в репозитории документальные — замените их адресами своих серверов.

Порт NODE_PORT панели и ноды не используйте как проверку доступности пользовательского VPN. По документации Remnawave этот порт предназначен для связи панели с нодой и должен быть разрешён только панели. Проверка TCP подтверждает доступность порта, но не полноценное подключение VPN-клиента.

### Этот файл нужен автохилу

`healer/nodes.json` — таблица соответствий для автохила: ключ, например `est-001`, должен совпасть с меткой `node` в Prometheus, а `ssh_host` — публичный IP VPN-ноды, на который сервер мониторинга подключается по SSH, чтобы выполнить разрешённый перезапуск Remnawave Node.

Если пока настраиваешь только сбор метрик и Grafana, **пропусти создание `healer/nodes.json`** и переходи к пункту 4. Метрики и дашборды без этого файла работают; автоматический перезапуск нод — нет. Чтобы включить автохил, выполни команды ниже.

Создай инвентарь на сервере мониторинга:

~~~bash
cp healer/nodes.json.example healer/nodes.json
chmod 600 healer/nodes.json
~~~

`healer/nodes.json` должен быть **файлом**, не каталогом. Перед копированием проверьте `ls -ld healer/nodes.json`. Если там каталог, сначала посмотрите его содержимое; если он создан ошибочно и содержит только пример, переименуйте его в резервную копию, затем выполните `cp healer/nodes.json.example healer/nodes.json`. То же правило относится к `secrets/remnawave_metrics_password` и `healer/known_hosts`: эти пути должны быть файлами. Не добавляйте завершающий `/` в имя файла.

В `healer/nodes.json` укажи IP, по которому сервер мониторинга может подключиться к SSH каждой ноды. WireGuard не обязателен: в твоём случае это может быть публичный IP ноды. Ограничь SSH на ноде так, чтобы соединения принимались только с публичного IP сервера мониторинга. Это **адрес управления нодой**, а не VPN-порт и не адрес `node_exporter`.

~~~json
{
  "de-01": {"ssh_host": "198.51.100.200"}
}
~~~

В примере `est-001` — метка `node`, она должна совпадать в `prometheus/targets.yml`, `prometheus/vpn-targets.yml` и `healer/nodes.json`. `198.51.100.200` — демонстрационный адрес; замени его адресом нужной ноды.

## 4. Установить Node Exporter на каждой VPN-ноде

Если репозиторий публичный и на ноду нужно получить только каталог `node`, используйте sparse checkout. Подставьте URL своего репозитория и имя ветки (обычно `main`):

~~~bash
sudo apt update && sudo apt install -y git
sudo git clone --filter=blob:none --no-checkout URL_ВАШЕГО_GITHUB_РЕПОЗИТОРИЯ /opt/rw-monitor-node
cd /opt/rw-monitor-node
sudo git sparse-checkout init --cone
sudo git sparse-checkout set node
sudo git checkout main
cd /opt/rw-monitor-node/node
~~~

Если git уже склонирован целиком, просто перейдите в его каталог `node`. Установщик предназначен для Debian/Ubuntu x86_64, устанавливает Node Exporter версии 1.12.1 и проверяет SHA-256 архива.

~~~bash
cd /opt/rw-monitor-node
sudo bash install-node-exporter.sh
~~~

Node Exporter слушает порт 9100. Разрешите его только от сервера мониторинга. Пример для UFW, замените адрес:

~~~bash
sudo ufw allow from MONITORING_VPS_IP to any port 9100 proto tcp
~~~

Не открывайте 9100 всему интернету. Проверьте локально:

~~~bash
systemctl is-active node_exporter
curl -fsS --max-time 5 -o /dev/null -w 'HTTP %{http_code}\n' http://127.0.0.1:9100/metrics
~~~

Ожидается `active` и `HTTP 200`. Команда с `| head` тоже выводит метрики, но часто завершает curl сообщением `curl: (23)` потому, что `head` закрывает канал после первых строк; это не означает отказ Node Exporter.

В комплекте приведены архив и контрольная сумма для amd64. Для ARM64 загрузите подходящий архив и контрольную сумму с [официальной страницы загрузок Prometheus](https://prometheus.io/download/); amd64-сумму для ARM64 использовать нельзя.

## 5. Экспортировать состояние контейнера remnanode

Проверьте фактическое имя контейнера:

~~~bash
docker ps --format '{{.Names}}'
~~~

По умолчанию скрипт ожидает имя remnanode. Если имя другое, замените его в node/collect-remnanode-state.sh до установки. Скрипт записывает состояние контейнера в формат textfile collector Node Exporter. Сам Node Exporter читает этот файл; отдельный тяжёлый агент не нужен. [Описание textfile collector](https://github.com/prometheus/node_exporter#textfile-collector)

Установите проверку состояния:

~~~bash
cd /opt/rw-monitor-node
sudo bash install-node-files.sh
~~~

Проверьте результат:

~~~bash
curl -fsS http://127.0.0.1:9100/metrics | grep -E '^remnawave_container_(up|check_timestamp_seconds)'
systemctl list-timers remnanode-state-check.timer
~~~

Ожидаются метрики remnawave_container_up 1 и remnawave_container_check_timestamp_seconds с актуальным Unix-временем. Таймер обновляет состояние раз в 30 секунд.

Убедитесь, что Compose-конфигурация Remnawave Node содержит политику перезапуска контейнера, обычно restart: always. Docker сам поднимет контейнер, если его основной процесс завершится. Автохилер предназначен для другого случая: контейнер работает, но внешний VPN-порт перестал отвечать.

## 6. Настроить ограниченное SSH-действие на каждой ноде

На сервере мониторинга покажите публичную часть ключа:

~~~bash
cat /opt/remnawave-monitoring/secrets/healer_ssh_key.pub
~~~

На каждой ноде установщик из node/ создаёт пользователя monitorheal, wrapper, root-owned действие и правило sudo. После установки добавьте публичный ключ одной строкой в /home/monitorheal/.ssh/authorized_keys:

~~~text
restrict,command="/usr/local/sbin/monitor-heal-wrapper" ssh-ed25519 AAAA... remnawave-healer
~~~

Это одна строка в `/home/monitorheal/.ssh/authorized_keys` **на ноде**, а не команда оболочки. Вместо `AAAA...` вставьте всю реальную строку из `/opt/remnawave-monitoring/secrets/healer_ssh_key.pub`. Не вводите в терминал слова `restrict,command=...` отдельно и не используйте примерный/фальшивый ключ.

Wrapper разрешает только запрос restart-remnanode. Root-owned скрипт выполняет только docker restart remnanode. Другие команды отклоняются. Для пользователя monitorheal пароль заблокирован.

Создайте файл с закреплёнными SSH host keys:

~~~bash
cp healer/known_hosts.example healer/known_hosts
chmod 600 healer/known_hosts
~~~

Добавьте в healer/known_hosts проверенные ключи всех нод. Получайте отпечатки через консоль провайдера или ранее доверенное SSH-подключение. Не полагайтесь только на непроверенный вывод ssh-keyscan.

Стандартная строка файла выглядит так:

~~~text
198.51.100.20 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA...
~~~

Безопасный тест ключа — отправить запрещённую команду `true`. Wrapper должен отклонить её с кодом `64`; это подтверждает, что принудительная команда не принимает произвольные shell-команды:

~~~bash
ssh -i /opt/remnawave-monitoring/secrets/healer_ssh_key \
  -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile=/opt/remnawave-monitoring/healer/known_hosts \
  monitorheal@198.51.100.20 true
~~~

Пользователь monitorheal не входит в группу docker. Доступ к Docker daemon даёт широкие права, поэтому ключ имеет принудительную команду, а в контейнер исполнителя не смонтирован Docker socket.

Разрешённая команда `restart-remnanode` **реально перезапускает контейнер**. Не запускайте её вручную для теста на рабочей ноде; сначала проверяйте автохил в `DRY_RUN=true`.

## 7. Указать Telegram-канал и формат алертов

В `alertmanager/alertmanager.yml` укажите настоящий числовой ID канала или группы в обоих `chat_id`. Бот должен быть добавлен в канал и иметь право отправлять сообщения. Тот же ID укажите в `TELEGRAM_CHAT_ID` файла `.env`. В шаблонах сообщений есть русские заголовки, статусы, имя ноды, endpoint проверки и время начала. После изменения конфигурации:

~~~bash
docker compose exec alertmanager amtool check-config /etc/alertmanager/alertmanager.yml
docker compose restart alertmanager
~~~

Старые Telegram-сообщения не переформатируются; изменения видны на новых алертах.

## 8. Запустить центральный стек в режиме dry-run

Проверьте, что все примеры адресов заменены и созданы файлы секретов, targets, panel-targets.yml, nodes.json и known_hosts. Оставьте HEALER_DRY_RUN=true в .env.

~~~bash
cd /opt/remnawave-monitoring
docker compose config
docker compose pull
docker compose up -d --build
docker compose ps
docker compose logs -f prometheus alertmanager healer digest
~~~

При настроенных DNS и firewall откройте https://ЗНАЧЕНИЕ_GRAFANA_DOMAIN и войдите с учётными данными из .env. Для локальной диагностики Grafana также доступна через SSH-туннель:

~~~bash
ssh -L 3000:127.0.0.1:3000 USER@MONITORING_VPS_IP
~~~

Дашборд **Remnawave Nodes Overview** создаётся автоматически. В нём есть CPU, занятая RAM, свободный диск, VPN TCP probe, статус Remnawave Node и inbound-трафик. Панели заполняются после успешного получения соответствующих метрик Prometheus.

Проверьте targets запросом на сервере мониторинга:

~~~bash
curl -s http://127.0.0.1:9090/api/v1/targets | python3 -c 'import json,sys; d=json.load(sys.stdin); [print(t["labels"].get("job"), t["labels"].get("node", "-"), t["health"], t["lastError"]) for t in d["data"]["activeTargets"]]'
~~~

Ожидаются `up` для job `node`, `vpn_tcp` и `remnawave`. Для проверки метрики состояния контейнеров:

~~~bash
curl -sG --data-urlencode 'query=remnawave_container_up' http://127.0.0.1:9090/api/v1/query | python3 -c 'import json,sys; d=json.load(sys.stdin); [print(r["metric"].get("node"), r["value"][1]) for r in d["data"]["result"]]'
~~~

Для трёх тестовых нод ожидается значение `1` у `est-001`, `lat-001`, `ltu-001`.

Prometheus и Alertmanager доступны только на localhost; blackbox exporter и healer доступны только во внутренней Docker-сети. Grafana снаружи открывается через Caddy по HTTPS и требует входа.

Для проверки конфигураций:

~~~bash
docker compose exec prometheus promtool check config /etc/prometheus/prometheus.yml
docker compose exec prometheus promtool check rules /etc/prometheus/rules/nodes.yml
docker compose exec alertmanager amtool check-config /etc/alertmanager/alertmanager.yml
~~~

Порты 9090 и 9093 опубликованы только на localhost сервера мониторинга. Для проверки откройте SSH-туннель:

~~~bash
ssh -L 9090:127.0.0.1:9090 -L 9093:127.0.0.1:9093 USER@MONITORING_VPS_IP
~~~

Откройте http://127.0.0.1:9090/targets и проверьте доступность целей. Также проверьте логи Prometheus: там будут ошибки недоступных targets или аутентификации.

Дайджест отправляется каждые 3 часа по московскому времени: 00:00, 03:00, 06:00 и далее. Каждое сообщение суммирует последние 24 часа. Ручная отправка без пересоздания постоянного контейнера:

~~~bash
docker compose run --rm --no-deps --entrypoint python digest -c 'import runpy; m=runpy.run_path("/app/digest.py"); m["send"](m["build_report"]())'
~~~

Он включает пик CPU/RAM, минимум свободного диска, доступность VPN-порта, сетевой трафик интерфейсов хоста, состояние контейнера и inbound-трафик Remnawave. Сетевой RX+TX хоста — не биллинг. Прочерк `—` означает, что Prometheus не нашёл ряд метрики в окне отчёта, а не измеренный ноль. Серверный список ограничен `est-001`, `lat-001`, `ltu-001`, список панели — `EST-001`, `LAT-001`, `LTU-001`. Для включения новых нод синхронно измените `REPORT_NODES` и `REPORT_PANEL_NODES` в `docker-compose.yml`, затем выполните `docker compose build digest` и `docker compose up -d --force-recreate digest`.

## 9. Проверить автохил и включить реальные перезапуски

Пока HEALER_DRY_RUN=true, исполнитель не перезапускает контейнер, а пишет в лог и Telegram, какое действие выполнил бы. На тестовой ноде временно сделайте недоступным проверяемый VPN-порт, сохранив доступность SSH, Node Exporter и контейнера. Убедитесь, что:

1. VPNPortUnreachable приходит в Telegram;
2. через 3 минуты срабатывает VPNNodeNeedsHeal;
3. executor пишет DRY RUN и сообщает имя ноды;
4. после восстановления порта алерт закрывается.

Если всё работает, измените HEALER_DRY_RUN=false и пересоздайте только healer:

~~~bash
docker compose up -d --build healer
docker compose logs -f healer
~~~

Перед этим проверьте адреса в healer/nodes.json, публичный ключ, закреплённые host keys, cooldown и firewall.

Исполнитель самостоятельно повторяет проверки через Prometheus. Он требует, чтобы все пробы за предыдущие 3 минуты были неуспешными, Node Exporter отвечал, контейнер был запущен, а метрика его состояния была свежей. Разрешено одно действие на fingerprint инцидента и действует 15-минутный cooldown на ноду. Если после рестарта порт не восстановился, повторный цикл не запускается: инцидент остаётся открытым, а в Telegram приходит результат команды.

## 10. Какие алерты настроены

| Алерт | Условие | Автохил |
|---|---|---|
| NodeExporterDown | Node Exporter недоступен 3 минуты | Нет |
| NodeHighCPU | CPU выше 90% в течение 10 минут | Нет |
| NodeLowMemory | Доступно менее 10% RAM в течение 5 минут | Нет |
| NodeLowDiskSpace | Свободно менее 10% диска в течение 10 минут | Нет |
| RemnawaveContainerStopped | Контейнер остановлен 2 минуты | Нет; срабатывает Docker restart policy |
| RemnawaveStateCheckStale | Проверка контейнера не обновлялась более 90 секунд | Нет |
| VPNPortUnreachable | Внешняя TCP-проверка не проходит 3 минуты | Отдельно отправляет алерт |
| VPNNodeNeedsHeal | Порт недоступен, exporter и контейнер доступны | Да, только remnanode |
| RemnawavePanelMetricsDown | Метрики панели недоступны 3 минуты | Нет |
| RemnawaveNodeDisconnected | Панель считает ноду отключённой 2 минуты | Нет |

Пороги CPU, RAM и диска — начальные. Через неделю эксплуатации сравните их с реальной нагрузкой и настройте под свою инфраструктуру.

## 11. Firewall и безопасность

- Сервер мониторинга должен иметь исходящий TCP-доступ к порту 9100 нодам, порту 3001 публичного IP панели, SSH и HTTPS к Telegram Bot API.
- Если используете встроенный Caddy, разрешите входящие TCP-порты 80 и 443 на сервере мониторинга и у провайдера.
- На нодах разрешите порт 9100 и SSH только от адреса сервера мониторинга.
- Панельный порт метрик 3001 разрешите через UFW только от постоянного публичного IP сервера мониторинга (см. пункт 2).
- Не публикуйте порты Prometheus, Alertmanager, blackbox exporter и healer в интернет.
- NODE_PORT Remnawave оставьте доступным только панели.
- Не публикуйте напрямую порт Grafana 3000; доступ снаружи должен идти через HTTPS reverse proxy и вход Grafana.
- Храните резервные копии данных Prometheus, Grafana, Alertmanager, состояния SQLite healer, секретов и known_hosts.
- Держите сервер мониторинга отдельно от VPN-нод.

## 12. Добавление ноды и обслуживание

Чтобы добавить ноду, внесите её в prometheus/targets.yml, prometheus/vpn-targets.yml и healer/nodes.json. Prometheus автоматически перечитывает target-файлы.

После изменения Prometheus или Alertmanager проверьте и перезапустите соответствующие сервисы:

~~~bash
docker compose exec prometheus promtool check config /etc/prometheus/prometheus.yml
docker compose exec prometheus promtool check rules /etc/prometheus/rules/nodes.yml
docker compose exec alertmanager amtool check-config /etc/alertmanager/alertmanager.yml
docker compose restart prometheus alertmanager
~~~

Версии контейнерных образов зафиксированы. Обновляйте их намеренно, проверяя release notes и состояние дашборда после обновления. Версии подобраны по официальным страницам [Prometheus](https://prometheus.io/download/) и [Grafana OSS](https://grafana.com/grafana/download?edition=oss&src=rt) на дату подготовки комплекта.

## 13. Итоговая рабочая схема и исправления, проверенные при настройке

В тестовой конфигурации используются два VPS с постоянными публичными IPv4: отдельный VPS мониторинга и VPS панели Remnawave. WireGuard не используется. Подключены три тестовые VPN-ноды: `est-001`, `lat-001`, `ltu-001`.

Потоки метрик:

1. Prometheus на VPS мониторинга опрашивает node_exporter на каждой ноде по TCP `9100`.
2. Blackbox Exporter проверяет внешний IP и реальный VPN inbound-порт каждой ноды. Это проверка TCP-доступности порта, а не полноценный VPN-handshake.
3. Prometheus опрашивает `/metrics` панели Remnawave на TCP `3001` с Basic Auth. В проверенной конфигурации логин — `admin`; пароль одинаково задан в `METRICS_PASS` панели и файле `secrets/remnawave_metrics_password` на VPS мониторинга.
4. Grafana использует provisioned Prometheus datasource и автоматически загруженный дашборд. Открывайте Grafana по HTTPS через Caddy; напрямую порт `3000` наружу не публикуется.
5. Alertmanager отправляет русские алерты в Telegram. При автохиле webhook Alertmanager обращается к healer, который повторно сверяет состояние в Prometheus и имеет SSH-доступ только к разрешённой команде перезапуска `remnanode`.
6. Дайджест отправляется каждые 3 часа по Москве и показывает скользящую сводку за 24 часа.

Фактически проверялись: `systemctl is-active node_exporter` возвращал `active`; локальный `/metrics` отвечал; Prometheus показывал targets `node`, `vpn_tcp`, `remnawave` в состоянии `up`; `remnawave_container_up` был равен `1` для трёх тестовых нод; Grafana отображала системные, VPN и panel-метрики; Telegram получал алерты; контейнеры healer и digest запускались. В журнале healer подтверждался запуск с `dry_run=True`. **Это не подтверждает выполнение реального перезапуска**: до переключения `HEALER_DRY_RUN=false` убедитесь, что dry-run сигнал и уведомление получены.

### Частые ошибки при вводе файлов и проверках

- Секреты, `healer/nodes.json` и `healer/known_hosts` — обычные файлы. `mkdir -p secrets/remnawave_metrics_password` или `mkdir healer/nodes.json` создаёт каталог, который редактор не сможет открыть как файл. Проверяйте тип через `ls -ld ПУТЬ`. Перед исправлением каталога изучите содержимое; не удаляйте неизвестные файлы вслепую. Для секрета создайте файл командой `sudo install -o 65534 -g 65534 -m 0400 /dev/null secrets/remnawave_metrics_password`, затем откройте сам файл редактором.
- Basic Auth в `curl -u admin URL` запрашивает пароль интерактивно. При вводе терминал не рисует символы; вставьте пароль и нажмите Enter. `401 Unauthorized` означает несовпадающие логин/пароль. На панели и в Prometheus должен быть одинаковый логин; в проверенной схеме это `admin`.
- Если `docker ps` показывает привязку панели `127.0.0.1:3001->3001/tcp`, другой VPS не подключится. Привяжите порт хоста к публичному IP панели и пересоздайте только сервис панели.
- `curl .../metrics | head` может завершиться `curl: (23) Failure writing output to destination`: `head` закрыл pipe после первых строк. Это само по себе не означает отказ Node Exporter.
- Строка SSH-ключа с `restrict,command=...` добавляется в `authorized_keys` на ноде, а не запускается как команда. Публичный ключ должен быть реальным, полученным из `healer_ssh_key.pub`. Проверка запрещённой команды `true` с кодом `64` ожидаема; разрешённая команда `restart-remnanode` действительно перезапускает контейнер.
- Если healer падает с `sqlite3.OperationalError: unable to open database file`, проверьте владельца его volume. Применявшееся исправление:

~~~bash
docker compose run --rm --no-deps --cap-add CHOWN --entrypoint sh healer -c 'chown 0:0 /var/lib/healer && ls -ld /var/lib/healer'
docker compose up -d --force-recreate healer
docker compose logs --since=2m healer
~~~

Ожидаемая строка запуска: `healer listening on :8080; dry_run=True`.

### Как применять последние изменения

После `git pull` конфиги, смонтированные как bind mounts, обновляются на диске. Для изменённого кода дайджеста пересоберите образ:

~~~bash
cd /opt/remnawave-monitoring
docker compose build digest
docker compose up -d --force-recreate digest
~~~

Для изменённого шаблона Alertmanager проверьте конфигурацию и перезапустите только Alertmanager:

~~~bash
docker compose exec alertmanager amtool check-config /etc/alertmanager/alertmanager.yml
docker compose restart alertmanager
~~~

## 14. Откат изменений

Откатывайте компоненты отдельно. Не останавливайте весь стек Remnawave на VPS панели ради отката мониторинга.

### 14.1. Сохранить настройки и данные

На VPS мониторинга из каталога проекта создайте защищённую резервную копию. В неё входят секреты, поэтому не загружайте архив в публичный GitHub и не отправляйте его в чат:

~~~bash
cd /opt/remnawave-monitoring
sudo tar -czf /root/remnawave-monitoring-backup-$(date +%Y%m%d-%H%M%S).tar.gz .env secrets prometheus alertmanager grafana caddy healer docker-compose.yml
sudo chmod 600 /root/remnawave-monitoring-backup-*.tar.gz
~~~

Для отмены изменения Git сначала посмотрите `git log -2 --oneline`, затем восстановите нужные файлы из известного commit. Пример: `git checkout COMMIT_ДО_ИЗМЕНЕНИЯ -- alertmanager/alertmanager.yml`. Не выполняйте `git reset --hard`, если в рабочем дереве есть свои правки.

### 14.2. Остановить центральный мониторинг, сохранив историю

Команда остановит контейнеры и сеть проекта, но **оставит именованные volumes** Prometheus, Grafana, Alertmanager и healer; файлы `.env` и `secrets/` тоже останутся:

~~~bash
cd /opt/remnawave-monitoring
docker compose down
~~~

Для последующего запуска используйте `docker compose up -d --build`. Не добавляйте `-v`, если хотите сохранить историю метрик, данные Grafana и состояние healer.

### 14.3. Откатить только экспорт метрик панели

На VPS панели восстановите прежние `/opt/remnawave/.env` и `docker-compose.yml` из резервной копии либо удалите только публикацию порта `3001` и параметры `METRICS_PORT`, `METRICS_USER`, `METRICS_PASS`, если они добавлялись исключительно для мониторинга. Пересоздайте только сервис панели:

~~~bash
cd /opt/remnawave
docker compose config --services
docker compose up -d --force-recreate remnawave
~~~

Если сервис называется иначе, используйте его имя из `docker compose config --services`. На VPS панели выполните `sudo ufw status numbered`, найдите правило маршрута `3001/tcp` от IP мониторинга и удалите его по номеру: `sudo ufw delete НОМЕР`. Перепроверьте правила; не удаляйте неизвестные правила и не сбрасывайте UFW целиком. На VPS мониторинга удалите панель из `prometheus/panel-targets.yml` и перезапустите Prometheus.

### 14.4. Откатить node_exporter и автохил на нодах

Сначала удалите restricted public key из `/home/monitorheal/.ssh/authorized_keys` на каждой ноде. Если пользователь и файлы созданы только этим комплектом, на каждой ноде выполните:

~~~bash
sudo systemctl disable --now remnanode-state-check.timer node_exporter.service
sudo rm -f /etc/systemd/system/remnanode-state-check.timer /etc/systemd/system/remnanode-state-check.service /etc/systemd/system/node_exporter.service
sudo rm -f /usr/local/sbin/collect-remnanode-state /usr/local/sbin/monitor-heal-wrapper /usr/local/sbin/monitor-heal-action /etc/sudoers.d/monitor-heal /usr/local/bin/node_exporter
sudo systemctl daemon-reload
~~~

Следующие команды удаляют также пользователя и накопленные данные. Выполняйте их только если они не используются другими задачами:

~~~bash
sudo userdel monitorheal
sudo userdel node_exporter
sudo groupdel node_exporter
sudo rm -rf /home/monitorheal /var/lib/node_exporter
~~~

Удалите UFW-разрешение порта `9100` от мониторинга по номеру правила после проверки `sudo ufw status numbered`. Удалите ноду из `prometheus/targets.yml`, `prometheus/vpn-targets.yml` и `healer/nodes.json`.

### 14.5. Полностью удалить проект и данные мониторинга

Сначала создайте резервную копию из пункта 14.1. Если хотите удалить контейнеры **и необратимо стереть все именованные volumes**, выполните:

~~~bash
cd /opt/remnawave-monitoring
docker compose down -v --remove-orphans
~~~

Будут удалены история Prometheus, данные Grafana и база состояния healer. Файлы `.env`, `secrets/` и проект на диске команда не удалит. После проверки архива каталог можно убрать или сначала переименовать для обратимого отката: `sudo mv /opt/remnawave-monitoring /opt/remnawave-monitoring.disabled`. Не применяйте эти команды к `/opt/remnawave` — там находится отдельная установка Remnawave Panel.

Если Caddy был единственным сервисом на VPS мониторинга, после его остановки удалите разрешения UFW для TCP `80` и `443` по номерам из `sudo ufw status numbered`. Не удаляйте эти правила, если ими пользуется другой сайт или reverse proxy. Данные сертификатов Caddy находятся в Docker volumes и удалятся при `docker compose down -v`.

## Принятые допущения

- VPN-ноды: Debian/Ubuntu x86_64. Для ARM64 надо выбрать соответствующий Node Exporter архив и SHA-256.
- Имя Docker-контейнера Remnawave Node: remnanode.
- На нодах есть команда /usr/bin/docker.
- Метки node в трёх инвентарных файлах совпадают.
- Проверка VPN использует TCP на публичном входящем порту. Она не заменяет подключение тестового клиента и проверку полного VPN-handshake.
- Метрики Remnawave доступны Prometheus через публичный IPv4 панели на порту 3001, ограниченный UFW по адресу мониторинга, и Basic Auth.
