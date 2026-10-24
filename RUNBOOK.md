# Эксплуатация Моспром

## Bootstrap GitHub

1. Сначала опубликуйте frontend, затем обновите `backend/vendor/frontend` до его полного SHA. Submodule сохраняется; URL настроен на `cvn-mosprom/frontend`.
2. Создайте GitHub App, установленное только в frontend/backend/deploy. Автоматизации нужны `Contents: write`, `Pull requests: write`; проверке чтения submodule — доступ к frontend. Сохраните `AUTOMATION_APP_ID` и секрет `AUTOMATION_APP_PRIVATE_KEY`. Для приватного submodule настройте `FRONTEND_READ_TOKEN` только с чтением frontend. Если checkout не имеет доступа, CI падает.
3. В backend задайте публичную переменную `ROUTING_ZONE`, например `game.example.com`. Она должна совпадать с внешними доменами inventory.
4. Укажите действительный GitHub-логин владельца в CODEOWNERS всех репозиториев. `scripts/repository_settings.py --owner <login>` проверяет права и выводит проект настроек; `--apply` применяет защиту `main`. До применения сохраните CODEOWNERS отдельным проверенным коммитом. Не указывайте несуществующие команды.
5. В deploy создайте environments `staging` и `production`, разрешив доверенную ветку `main`. В production включите доступные тарифу required reviewers. Сам запуск production всегда ручной и проверяет успешный staging того же манифеста.
6. Изолируйте runner group `mosprom-cd`: доступ только для доверенного CD workflow на `main`; запретите PR, произвольные workflow и сборки. На раннере нужны Python 3.12, lock-зависимости deploy, Docker/Compose v2 с `!override`, Buildx, gh, cosign, restic, SSH known_hosts и доступ только к целевым узлам.
7. Настройте `DEPLOYMENT_TOPOLOGY=single` либо `ha` отдельно для каждого environment. Секреты приложений хранятся на серверах / в Ansible Vault, не в Git и не в build args.
8. Запустите `infrastructure-images.yml` на `main`, проверьте PR с `infrastructure.lock.json`. Затем backend CI сможет создать полный release PR. Фиктивных digest в production-манифестах нет.

Для автоматических коммитов используется `.github/commit-author.json`: Denis Shipilov <shipiloff.d@gmail.com>. GitHub App остаётся техническим средством доступа; автор коммита задаётся явно.

## Одиночная VM

Требуется Linux amd64, Docker, Compose, Python 3.12, cosign, Buildx, restic, действительный домен и порты 80/443. Пример адресов — документационный; его необходимо заменить реальными.

1. Скопируйте `environments/runtime.env.example` в `/srv/mosprom-staging/.env`, задайте независимые URL-safe секреты и права `0600`. Для production используйте другой каталог, базу, домен, bot token и хранилище копий.
2. Создайте inventory с одним узлом `region_id: local`, `public_origin: https://<домен>`, `readiness_url: http://api:8000/ready`, без `wg_ip`. Он используется только для генерации каталога.
3. Выполните `python scripts/bootstrap_runtime.py releases/<id>.json inventory.yml /srv/mosprom-staging`. Скопируйте и настройте `monitoring/alertmanager.example.yml` как `/srv/mosprom-staging/alertmanager.yml`; создайте файл токена webhook. Дайте UID/GID Alertmanager (65534) право чтения обоих файлов, например `chown root:65534` и `chmod 0640`. Не запускайте примерный receiver без настройки.
4. Инициализируйте off-host restic repository, разместите password file и credentials с правами `0600`; ключ восстановления храните независимо от VM.
5. Проверьте `python scripts/preflight.py /srv/mosprom-staging/.env` и подписи `python scripts/release.py releases/<id>.json --verify`.
6. `python scripts/deploy.py releases/<id>.json --env-file /srv/mosprom-staging/.env` сериализует запуск, проверяет конфигурацию и образы, запускает БД, миграции и сервисы, затем проверяет `/ready` через HTTPS.
7. Установите systemd units `mosprom-backup@` и `mosprom-metrics@`; включите соответствующие timers для `staging` либо `production`. Регулярные копии выполняются раз в шесть часов с обязательным зашифрованным off-host upload.

Grafana доступна на loopback:3000; используйте SSH tunnel или отдельный защищённый ingress. Не публикуйте PostgreSQL, Redis, discovery и служебные метрики в Интернет.

## Распределённый профиль

Подготовка и сертификаты описаны в [docs/ha.md](docs/ha.md). Внешний LoadBalancer предоставляется инфраструктурой, проверяет `/lb-ready` и исключает draining/неработающие площадки. Общий домен и региональные адреса обслуживают HTTPS; региональный DNS не должен возвращать другую площадку.

```sh
python scripts/rollout.py releases/<id>.json \
  --inventory /etc/mosprom/staging/inventory.yml \
  --vault /etc/mosprom/staging/vault.yml --provision
```

Для последующих релизов опустите `--provision`. Ansible использует три etcd, четыре PostgreSQL/Patroni и распределённый слой приложения. Одна миграция проходит через прямой primary endpoint, затем узлы обновляются последовательно: draining всех discovery → TTL + завершение запросов → новый образ → readiness → публикация фактической версии региона. Пулы PgBouncer проверяются по общему connection budget.

Обновление PostgreSQL/etcd/Redis и их конфигурации выполняйте отдельным обслуживанием, реплики прежде primary, с проверкой кворума и отставания после каждого узла. Не запускайте повторный bootstrap с новыми инфраструктурными digest одновременно на всех узлах рабочего кластера.

## Откат и восстановление

- Для одиночного профиля: `python scripts/deploy.py releases/<id>.json --env-file <env> --rollback`. Откат берёт предыдущий успешный комплект и его сохранённую конфигурацию. Он запрещён, если последний релиз не отметил `schemaCompatibility.rollbackSafe=true`.
- Флаг совместимости требует проверки миграций и старого приложения на новой схеме. По умолчанию он `false`. Предпочитайте expand/contract; удаление столбцов — отдельным релизом после вывода старых клиентов.
- Сбой HA rollout оставляет проблемный регион в draining и останавливает обновление. Верните совместимый предыдущий комплект на этот узел и проверьте готовность перед активацией; при несовместимой схеме выполняйте управляемое восстановление. Автоматический restore production запрещён.
- Проверка логического дампа: `python scripts/backup.py current.json --env-file <env> --restore-test <dump>`. Она создаёт отдельную Docker-сеть без публичных портов, проверяет таблицы/версию миграций и запускает восстановленное приложение до `/ready`, затем удаляет только свои контейнеры. Плановый workflow сначала получает копию из off-host restic через `recovery_single.py`.
- HA использует pgBackRest: diff-копии каждые шесть часов, full еженедельно и непрерывное архивирование WAL. `backup_ha.py` выполняется только на проверенном primary. Обязательны отдельное S3-хранилище, шифрование, контроль возраста копий и репетиция PITR на изолированном стенде.
- Перед восстановлением остановите запись и бот, сохраните аварийный дамп/диски, выберите точку восстановления и восстановите в новый каталог. Проверьте целостность и readiness, затем направьте трафик. Не выполняйте `pg_restore --clean` или `docker compose down -v` на рабочем окружении в автоматическом откате.

## Диагностика

Проверяйте `/health`, `/ready`, `/lb-ready`, `/routing/regions`, identity `/routing/ping` и метрики Prometheus. Публичный API показывает request ID, но не внутренние адреса. Логи Caddy исключают Telegram initData, Authorization и cookies; API access logs не содержат Telegram ID и user ID.

Контролируйте API error rate/p95, клиентскую HTTPS-задержку, частоту выбора LoadBalancer, готовность регионов, роль Patroni, свободную RAM/диск, CPU контейнеров и возраст резервной копии. Тестовое оповещение сначала отправляйте в изолированный receiver staging. Сбои плановых security workflows видны в GitHub Actions; не отключайте scanner ради зелёного статуса.

Справочники восстановления: [restic restore](https://restic.readthedocs.io/en/stable/050_restore.html), [pgBackRest restore и PITR](https://pgbackrest.org/command.html#command-restore).
