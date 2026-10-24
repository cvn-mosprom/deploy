# CD односерверного прототипа

Канал обслуживает только `https://ochakovo.velikoss.ru` и проект `mosprom-prototype` на 185.174.166.93. Он независим от `deploy.yml`, staging/production и HA-профиля. Patroni, etcd, Xray, Caddy хоста, PostgreSQL и Redis этим каналом не обновляются. Лендинг находится на `/`, игра и кнопка бота — на `/app`.

Доверенная ветка всех трёх репозиториев — **`main`**. PR и другие ветки не выпускают образы прототипа и не выполняют доставку.

1. Успешный frontend CI открывает PR обновления submodule в `main` backend. PR нужно проверить и слить.
2. После quality, integration и security backend собирает четыре linux/amd64 образа с SBOM/provenance. Trivy High/Critical, включая unfixed, блокирует публикацию. В GHCR поступает тот же OCI-архив, без повторной сборки.
3. Подпись cosign привязана к `backend/.github/workflows/ci.yml@refs/heads/main`. Аттестация SLSA v1 включает профиль, исходные SHA, номер и попытку CI в `buildDefinition.externalParameters`. Манифест не допускает смешивания запусков.
4. `deliver-prototype` работает в environment `prototype`, только при `PROTOTYPE_CD_ENABLED=true`. Манифест и краткоживущий GITHUB_TOKEN с чтением packages передаются по SSH с закреплённым host key. Токен удаляется вместе с временным Docker config после доставки.
5. Сервер повторно проверяет подписи/provenance, загружает digest, сохраняет дамп, останавливает бот, выполняет миграции и обновляет только sim/API/bot/web с `--no-deps`. Проверяются readiness, фактический release ID, лендинг, `/app`, процесс бота и настоящий Bot API. Default menu сверяется с `WEBAPP_URL` и при необходимости исправляется на `/app`, без отправки сообщений. Hosted runner дополнительно проверяет публичный HTTPS.

Общий `publish`/`release-pr` отключён при `PROTOTYPE_CD_ENABLED=true`, чтобы один push не выпускал одновременно два разных профиля.

При включённом CD новый push не отменяет начавшийся workflow. Доставки сериализованы. Манифест, предыдущий релиз и дамп находятся в `/opt/mosprom-prototype/cd`; манифест также сохраняется как Actions artifact.

Новый release ID включает ревизию операционных исходников deploy: повторная доставка тех же образов после изменения проверок создаёт отдельный манифест, не переписывая уже сохранённый. Исторические ID первого выпуска остаются проверяемыми.

## Переменные и секреты

В **backend → Settings → Environments → prototype**:

| Имя | Тип | Значение |
|---|---|---|
| `PROTOTYPE_SSH_KEY` | secret | Отдельный ed25519 приватный ключ `mosprom-cd`, не root-ключ |
| `PROTOTYPE_SSH_HOST` | variable | `185.174.166.93` |
| `PROTOTYPE_SSH_KNOWN_HOSTS` | variable | Проверенная строка `185.174.166.93 ssh-ed25519 …` |

В repository variables backend: `PROTOTYPE_CD_ENABLED=true` после bootstrap. При `false` прототип не собирается и не доставляется; общий профиль выпускает отдельный комплект для staging/production. Разрешите environment только ветку `main`; если тариф поддерживает reviewers, можно включить дополнительное ручное подтверждение.

Frontend/backend используют существующие `AUTOMATION_APP_ID` и `AUTOMATION_APP_PRIVATE_KEY`. App достаточно Contents/Pull requests. Backend также использует `FRONTEND_READ_TOKEN` для приватного submodule. GITHUB_TOKEN выдаётся автоматически: отдельный PAT для GHCR и долговременный registry password на сервере не нужны.

BOT_TOKEN, пароли БД, INTERNAL_TOKEN и Telegram proxy остаются только в `/opt/mosprom-prototype/runtime.env` с правами 0600. Файл не попадает в CI. Будущим staging/production нужны независимые боты, домены, данные и секреты; прототип не заменяет эти окружения.

## Bootstrap сервера

После проверки исходников скопировать файлы профиля в `/opt/mosprom-prototype/deploy`, установить cosign **v3.0.5** из официального релиза с проверкой опубликованного SHA256, создать отдельный ed25519 ключ и передать серверу только публичную часть. От root:

```sh
bash /opt/mosprom-prototype/deploy/scripts/install-prototype-cd.sh /root/mosprom-cd.pub
```

`mosprom-cd` не входит в Docker group и не имеет произвольного sudo. Ключ имеет `restrict` и forced command: shell, forwarding, PTY и другие команды запрещены. Receiver принимает ограниченный JSON, а не shell или исполняемый архив. Приватный ключ хранится только в environment secret.

Compose/Caddy/init-db/backup имеют общий SHA256. При расхождении сервер отказывает до изменений приложения. Конфигурацию сначала отдельно проверяют и устанавливают, затем выпускают релиз. Через CD нельзя подменить конфигурацию или runtime secrets.

## Сбой и откат

Сбой подписи, загрузки, конфигурации, проверки Bot API или бэкапа останавливает доставку до остановки бота. После изменения меню его подтверждение ожидается ограниченное время; в журнал попадает только фиксированный код ошибки, без токена и адреса запроса Bot API. При ошибке миграций/smoke прежние образы возвращаются автоматически только при неизменившемся наборе Alembic revisions. При изменении схемы автоматический откат и restore запрещены: требуется управляемое восстановление или исправляющий релиз. `down -v`, `prune` и глобальные операции Docker не используются.

Для повтора тех же образов перезапустите только неуспешный `deliver-prototype`. Полный повтор workflow получает новую попытку и отдельный immutable release ID. Для запрета будущих доставок задайте `PROTOTYPE_CD_ENABLED=false`; не прерывайте уже начавшуюся миграцию.

## Фактическая приёмка — 24 октября 2026

[Первая успешная доставка](https://github.com/cvn-mosprom/backend/actions/runs/40125062014/job/120969767492) доставила backend `86ca5fe` и frontend `7bf8190`. Доставлены те же четыре подписанных digest; повторялся только CD-job. Серверный манифест ссылается на deploy `e082b4a`. Проверены HTTPS, фактические image references, отказ dev-авторизации, закрытые служебные маршруты и восстановленная API с аутентифицированным bootstrap. Patroni, etcd, Xray, PostgreSQL и Redis сохранили исходные PID/ID и время запуска. Это проверка одной VM; многоузловые отказы и отдельные staging/production в эту приёмку не входят.

### Актуальный выпуск — 24–25 октября 2026

[Полный CI/CD 40130740889](https://github.com/cvn-mosprom/backend/actions/runs/40130740889) завершился успешно с первой попытки: backend `dd73560`, frontend `98caa33`, операционные исходники deploy `ff943c6`. Доставлены четыре проверенных digest; ночной bootstrap исправлен, публичные HTTPS-проверки и независимая приёмка прошли. Свежий бэкап восстановлен в отдельную БД, текущий API прошёл readiness и аутентифицированный bootstrap; временные API и БД удалены. Default menu `/app` подтверждено через серверный маршрут и тремя прямыми TLS-запросами к Telegram с Mac.

Для внешней диагностики GitHub Actions оператору достаточно `Actions: Read-only` существующего App; токен диагностики ограничивается этим правом и чтением содержимого/PR. Для работы самого канала доставки дополнительный постоянный PAT не нужен. Подробные SHA, digest, результаты и границы проверки — в [PROTOTYPE-VALIDATION.md](PROTOTYPE-VALIDATION.md).
