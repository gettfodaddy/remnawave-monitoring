# Мониторинг нод Remnawave и ограниченный автохил

Это комплект для Debian/Ubuntu. Он рассчитан на отдельный сервер мониторинга и ноды с Remnawave Node в Docker-контейнере с именем remnanode. Примеры IP-адресов, паролей и идентификаторов необходимо заменить своими.

## Что входит в комплект

На сервере мониторинга работают Prometheus, Alertmanager, Grafana OSS, blackbox exporter, ежедневный Telegram-отчёт и небольшой исполнитель автохила.

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

### Доступ к Grafana по домену

В комплект добавлен Caddy: он принимает HTTPS-запросы на домене и проксирует их в Grafana. Авторизация выполняется самой Grafana по логину и паролю из .env; анонимный доступ и самостоятельная регистрация отключены.

1. Создайте DNS A-запись GRAFANA_DOMAIN на публичный IP сервера мониторинга. Добавляйте AAAA-запись только если IPv6 на сервере настроен и доступен снаружи.
2. Разрешите входящие TCP-порты 80 и 443 в firewall сервера и у провайдера. Caddy использует их для автоматического получения и обновления TLS-сертификата.
3. В .env задайте GRAFANA_DOMAIN=monitor.example.com и GRAFANA_ROOT_URL=https://monitor.example.com/.
4. Порты 80 и 443 должны быть свободны. Если на сервере уже работает Nginx/Caddy или панель Remnawave использует эти порты, не запускайте второй публичный proxy: добавьте маршрут в имеющийся proxy на http://127.0.0.1:3000 и отключите сервис caddy в docker-compose.yml.

После запуска откройте https://ЗНАЧЕНИЕ_GRAFANA_DOMAIN и войдите пользователем и паролем из .env. Снаружи доступ идёт через Caddy; сама Grafana по-прежнему привязана только к localhost:3000. Caddy автоматически перенаправляет HTTP на HTTPS и обслуживает сертификаты. [Документация Caddy по автоматическому HTTPS](https://caddyserver.com/docs/quick-starts/https), [настройка reverse_proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy).

## 2. Включить встроенные метрики панели Remnawave

Панель Remnawave уже умеет отдавать метрики Prometheus: состояние нод, онлайн-пользователей, счётчики трафика и показатели процессов панели. Для этого не требуется API-токен с избыточными правами. [Документация Remnawave по метрикам](https://docs.rw/install/environment-variables/)

На сервере панели отредактируйте /opt/remnawave/.env и задайте отдельные учётные данные:

~~~dotenv
METRICS_PORT=3001
METRICS_USER=monitoring
METRICS_PASS=ЗАМЕНИТЕ_НА_СЛУЧАЙНЫЙ_СЕКРЕТ
~~~

Секрет можно создать командой openssl rand -hex 32. Не используйте стандартные значения admin/change_me.

Порт 3001 должен быть доступен Prometheus только через приватную сеть. Если панель и мониторинг на одном Docker-хосте, подключите Prometheus к Docker-сети панели и используйте имя сервиса панели с портом 3001. Если серверы разные, опубликуйте порт метрик только на WireGuard-IP сервера панели. Например, добавьте в список ports существующего сервиса панели запись 10.20.0.2:3001:3001, сохранив текущие публикации портов. В firewall разрешите вход на 3001 только с WireGuard-IP сервера мониторинга. Не публикуйте этот порт в интернет.

Укажите доступный Prometheus адрес в prometheus/panel-targets.yml. Например, 10.20.0.2:3001. На сервере мониторинга создайте файл пароля:

~~~bash
umask 077
read -r -s -p 'Пароль метрик Remnawave: ' METRICS_PASS; echo
printf '%s' "$METRICS_PASS" > secrets/remnawave_metrics_password
unset METRICS_PASS
sudo chown 65534:65534 secrets/remnawave_metrics_password
sudo chmod 0400 secrets/remnawave_metrics_password
~~~

Пользователь monitoring в prometheus/prometheus.yml должен совпадать со значением METRICS_USER в панели.

## 3. Заполнить список нод

Отредактируйте prometheus/targets.yml. В нём указываются только адреса node_exporter на порту 9100:

~~~yaml
- targets: ["198.51.100.20:9100"]
  labels:
    node: "de-01"
    role: "vpn-node"
~~~

Отредактируйте prometheus/vpn-targets.yml. В нём укажите публичный IP и пользовательский VPN-порт, к которому подключаются клиенты:

~~~yaml
- targets: ["198.51.100.20:443"]
  labels:
    node: "de-01"
    role: "vpn-node"
~~~

Идентификатор node должен совпадать в обоих файлах. Для одной ноды это должен быть стабильный идентификатор, например de-01. В targets.yml не добавляйте VPN-порты; в vpn-targets.yml не добавляйте порт 9100.

Порт NODE_PORT панели и ноды не используйте как проверку доступности пользовательского VPN. По документации Remnawave этот порт предназначен для связи панели с нодой и должен быть разрешён только панели. Проверка TCP подтверждает доступность порта, но не полноценное подключение VPN-клиента.

Создайте инвентарь SSH для исполнителя:

~~~bash
cp healer/nodes.json.example healer/nodes.json
chmod 600 healer/nodes.json
~~~

Замените адреса в healer/nodes.json на адреса управления, доступные с сервера мониторинга. Можно использовать WireGuard-IP:

~~~json
{
  "de-01": {"ssh_host": "10.20.0.20"}
}
~~~

Идентификатор ноды должен совпадать с меткой node в файлах Prometheus.

## 4. Установить Node Exporter на каждой VPN-ноде

Скопируйте каталог node из комплекта на ноду, например в /opt/rw-monitor-node. Установщик предназначен для Debian/Ubuntu x86_64, устанавливает Node Exporter версии 1.12.1 и проверяет SHA-256 архива.

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
curl -fsS http://127.0.0.1:9100/metrics | head
~~~

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

Проверьте выполнение с сервера мониторинга:

~~~bash
ssh -i /opt/remnawave-monitoring/secrets/healer_ssh_key \
  -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile=/opt/remnawave-monitoring/healer/known_hosts \
  monitorheal@198.51.100.20 restart-remnanode
~~~

Пользователь monitorheal не входит в группу docker. Доступ к Docker daemon даёт широкие права, поэтому ключ имеет принудительную команду, а в контейнер исполнителя не смонтирован Docker socket.

## 7. Указать Telegram-канал

В alertmanager/alertmanager.yml замените оба примера -1001234567890 на настоящий числовой ID канала или группы. Бот должен быть добавлен в канал и иметь право отправлять сообщения. Такой же ID укажите в TELEGRAM_CHAT_ID файла .env.

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

Дашборд Remnawave Nodes Overview создаётся автоматически.

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

Ежедневный отчёт настроен на 09:00 по московскому времени. Он включает максимумы CPU/RAM, минимум свободного диска, доступность VPN-порта, сетевой трафик интерфейсов хоста, состояние контейнера и трафик inbound по счётчикам Remnawave. Сетевой RX+TX хоста — не биллинг; счётчики inbound берутся из метрик панели.

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

- Сервер мониторинга должен иметь исходящий TCP-доступ к порту 9100 нодам, порту 3001 панели по приватной сети, SSH и HTTPS к Telegram Bot API.
- Если используете встроенный Caddy, разрешите входящие TCP-порты 80 и 443 на сервере мониторинга и у провайдера.
- На нодах разрешите порт 9100 и SSH только от адреса сервера мониторинга.
- Панельный порт метрик 3001 разрешите только от сервера мониторинга по WireGuard или другой приватной сети.
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

## Принятые допущения

- VPN-ноды: Debian/Ubuntu x86_64. Для ARM64 надо выбрать соответствующий Node Exporter архив и SHA-256.
- Имя Docker-контейнера Remnawave Node: remnanode.
- На нодах есть команда /usr/bin/docker.
- Метки node в трёх инвентарных файлах совпадают.
- Проверка VPN использует TCP на публичном входящем порту. Она не заменяет подключение тестового клиента и проверку полного VPN-handshake.
- Метрики Remnawave доступны Prometheus через приватный адрес и Basic Auth.
