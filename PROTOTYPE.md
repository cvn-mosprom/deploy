# Серверный прототип для жюри

Адреса: https://ochakovo.velikoss.ru/ — лендинг, `/app` — игра, `/hr` — демонстрационная HR-панель. `/landing` перенаправляется на `/`; `/landing/*` остаются медиа. Бот https://t.me/cvnprombot: `/start` → кнопка игры, `WEBAPP_URL=https://ochakovo.velikoss.ru/app`. Кнопка меню бота использует тот же адрес.

Это отдельный односерверный профиль на 185.174.166.93, без Patroni. Все БД и тома проекта `mosprom-prototype` независимы от существующих Patroni, etcd, SeaweedFS, rqlite и RTK CRM. Не подключать к нему их сеть/данные, не запускать глобальные `docker system prune`, `compose down -v` и операции над чужими проектами. Межплощадочный WireGuard и маршрутизацию хоста не менять.

`compose/prototype.yml` запускает API (prod, DEV_AUTH=0), bot, sim, web, обычный PostgreSQL 16 на Alpine 3.24 (images/postgres/Dockerfile удаляет ненужный уязвимый gosu и запускает БД сразу от postgres), Redis и логические резервные копии. API и миграции используют разные ограниченные роли; БД не публикуется на хост. Ресурсы ограничены. Медиа включены в веб-образ, существующий SeaweedFS не используется. `/internal` и `/metrics` закрыты снаружи. Публичную аутентификацию X-Dev-User сервер отвергает.

Общий Caddy хоста завершает TLS и проксирует только этот домен на `127.0.0.1:18081`. До добавления сайта сохранить конфигурацию и PID сервисов, проверить новый конфиг и прочие сайты. На данном сервере Caddy 2.9.1 имеет admin off и не поддерживает SIGUSR1: нужен короткий перезапуск только rabotyaga-caddy после успешной валидации. Patroni/etcd не перезапускаются. При неудаче восстановить исходный конфиг и запустить тот же Caddy.

Telegram недоступен напрямую, но доступен через существующий Xray HTTP-прокси `127.0.0.1:10890`. Отдельный systemd-socket-proxyd слушает только адрес нового Docker bridge `172.30.92.1:18090` и пересылает в этот loopback. Бот получает `TELEGRAM_PROXY_URL=http://172.30.92.1:18090`; API, БД и sim ходят напрямую по своей сети. Новые VPN/TUN, изменение default route и настройки существующего Xray не нужны. При выборе другой подсети заменить адрес в env и socket unit согласованно. В UFW разрешён только вход TCP из 172.30.92.0/24 к 172.30.92.1:18090; остальные правила не меняются. Socket unit стартует после Docker через multi-user.target без зависимости от sockets.target, чтобы избежать цикла при загрузке.

Конфигурация без секретов: `environments/prototype.env.example`. Реальный `/opt/mosprom-prototype/runtime.env` создаётся отдельно, права 0600, вне Git. Пароли БД и INTERNAL_TOKEN — независимые случайные значения. BOT_TOKEN — из предоставленного env-файла. Полные образы именуются уникальным ID релиза и записываются в runtime.env; manifest содержит SHA исходников и image ID. Сборка web: VITE_API_URL=/, REGIONAL_ROUTING=0, VITE_TELEGRAM_ONLY=1, VITE_BOT_USERNAME=cvnprombot, VITE_HR_DEMO=1; EXTERNAL_MEDIA=0. Внутри Telegram игра использует подписанный initData; внешний браузер получает ссылку на бота. HR-панель — презентационные данные, код 123456, не реальная CRM заявок. Реальные заявки лендинга сохраняются через API в отдельной БД.

На сервере конфигурация размещается в `/opt/mosprom-prototype/deploy`. Команды от root:

```sh
/opt/mosprom-prototype/deploy/scripts/prototype.sh up
/opt/mosprom-prototype/deploy/scripts/prototype.sh status
/opt/mosprom-prototype/deploy/scripts/prototype.sh seed
```

`stop` останавливает только этот проект и сохраняет данные. Изменяя релиз, сначала сделать pg_dump и проверить совместимость миграций; автоматического отката схемы нет. Образы перед загрузкой проверяются Trivy без исключения unfixed. Первичный запуск доставлялся архивами; текущий прототип уже прошёл [подписанный GHCR CD](PROTOTYPE-CD.md). Действующие digest и исходные SHA находятся в `/opt/mosprom-prototype/cd/current.json`, образ API для проверки восстановления берётся из `cd/current-images.env`. Операционный `prototype.sh` также учитывает этот файл поверх исходного runtime.env.

Резервная копия создаётся сразу и каждые шесть часов в отдельном volume проекта, хранится семь суток. Такая копия находится на том же сервере: её дополнительно нужно переносить за пределы хоста. Потеря хоста не покрывается локальным volume. При восстановлении `pg_dump --no-acl` в новую БД после pg_restore обязательно повторно выдать роли mosprom_app USAGE на public, DML на все таблицы и USAGE/SELECT на последовательности; также восстановить ALTER DEFAULT PRIVILEGES для роли миграций. Рабочую БД автоматически не заменять. Результаты фактических проверок описаны в PROTOTYPE-VALIDATION.md.

Проверка восстановления: `python3 /opt/mosprom-prototype/deploy/scripts/prototype-restore-check.py`. Она создаёт новый согласованный dump, временную БД mosprom_restore_verification и временную API, проверяет readiness и bootstrap, затем удаляет только эти тестовые ресурсы. При уже существующей тестовой БД скрипт прекращает работу.

Для образа PostgreSQL обязательно задать POSTGRES_IMAGE на результат `docker build --platform linux/amd64 -t <имя-релиза> images/postgres`. Без этой переменной профиль не запустится: непроверенный upstream gosu не должен вернуться через значение по умолчанию.
