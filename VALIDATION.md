# Результаты проверок и границы готовности

Дата: 24 октября 2026 года. Проверки выполнены локально на macOS и в Linux-контейнерах Docker Desktop. Реальные четыре площадки, staging и production не развёрнуты. Конфигурации готовы для подключения через inventory; production-приёмка ещё не завершена.

**Ранее найденные High-уязвимости Python/Caddy устранены.** Итоговые API, bot, Caddy и discovery для linux/amd64 прошли строгий Trivy gate с 0 High/Critical. Исключений и обхода сканера нет. Production-приёмка и публикация в registry остаются отдельными шагами. Детали: [security/observed-image-findings.json](security/observed-image-findings.json).

| Проверка | Фактический результат |
|---|---|
| Frontend, полный Vitest 5.0.5 | 844 passed, 1 намеренный skip с владельцем/причиной/сроком в test-exceptions.json |
| Маршрутизация и HTTP-клиент | 43 passed в составе frontend: медиана, ошибки проб, таймаут, TTL/draining, совместимость, доверенные адреса, анонимность, hysteresis, очередь и потерянный ответ |
| Frontend ESLint / svelte-check | пройдены; 0 ошибок и 0 предупреждений проверки типов |
| Frontend production build / bundle budget | пройдены; JS/CSS gzip 505 444 байт при лимите 1 500 000 |
| Браузерный smoke | 1 passed; HTTP 200 для /, /landing, /privacy, изолированные API и Telegram script |
| Production web/Caddy | На arm64 и linux/amd64: 3 страницы запускают JavaScript с CSP hashes; 4 разрешённых HTTPS origin с моделируемыми CORS-ответами; запрос с авторизацией на посторонний origin блокируется браузером до отправки |
| CSP generator | 2 passed; хэши inline bootstrap для вложенных HTML, запрет сборки без bootstrap |
| Инициализация PostgreSQL | SQL hook на чистом PostgreSQL 16: миграции непривилегированной ролью, preflight и доступ приложения к таблицам пройдены новым API linux/amd64 |
| API | 811 passed, без пропусков; настоящие PostgreSQL 16, Redis 7 и sim; полный набор повторён внутри нового Python Alpine runtime |
| Бот | 105 passed, без пропусков; полный набор повторён внутри нового Python Alpine runtime, без Telegram polling |
| Контракт | 200 passed, без пропусков; генерация не создаёт drift; итоговый прогон с Docker sim без пакетных менеджеров |
| Симулятор | 104 passed, без пропусков; typecheck и bundle пройдены |
| Docker E2E | 251 passed, без пропусков; настоящий HttpGameApi, миграции, HTTP-сценарии и перезапуски API/sim/БД. Повторено с новыми Python Alpine runtime и пересобранным Caddy без root |
| Deploy/discovery | 19 passed; отрицательные проверки подписи, provenance и платформы используют моделируемые ответы CLI |
| Ansible | syntax-check трёх playbook пройден; все 4 набора шаблонов реально отрендерены локально и разобраны Docker Compose; подключения к серверам не выполнялись |
| Compose | одиночная и HA конфигурации разобраны; отсутствие image pin блокирует конфигурацию |
| actionlint / ShellCheck / Ruff / Bandit / hadolint | пройдены; Bandit не обнаружил Medium/High; hadolint не обнаружил ошибок, остаётся рекомендация закреплять версии системных apt-пакетов при сборке Patroni |
| Gitleaks, полная история | нет необработанных находок; 2 точных ложных срабатывания имеют владельца, причину и срок 2026-11-24. CI проверяет срок исключений |
| Trivy, исходники всех 3 репозиториев | 0 High/Critical в зависимостях, секретах и конфигурациях после обновления Vitest и генератора |
| pip-audit всех Python lock-файлов | известных уязвимостей не найдено; pytest 9.0.3, ansible-core 2.20.10 |
| pnpm audit frontend / npm audit E2E | 0 High/Critical; E2E — 0 находок; frontend сохраняет 3 Low |
| Trivy, итоговый sim-образ | 0 High/Critical после удаления неиспользуемых npm/yarn/corepack |

Генератор обновлён до datamodel-code-generator 0.86.0. Сгенерированные command.py/snapshot.py побайтно совпадают с файлами API-образа, прошедшего 251 E2E-сценарий. Публикация CI ориентирована на linux/amd64. В этой сессии API, bot, Caddy и discovery действительно собраны и просканированы для linux/amd64; Caddy browser smoke и API migrations/preflight также повторены на amd64 через эмуляцию. Полные API/bot/E2E-наборы выполнялись на linux/arm64 в Docker Desktop.

## Повторное сканирование образов после исправления

Trivy 0.76.1, база от **2026-10-24 07:11:13 UTC**. `--severity HIGH,CRITICAL --exit-code 1`, без `ignore-unfixed` и без CVE-исключений. Идентификаторы локальных образов и SHA256 полных JSON-отчётов записаны в [security/observed-image-findings.json](security/observed-image-findings.json).

| Образ | Ранее High | Теперь High/Critical | Архитектура повторной проверки |
|---|---:|---:|---|
| API | 44 | 0 | linux/amd64 и linux/arm64 |
| bot | 44 | 0 | linux/amd64 и linux/arm64 |
| web/Caddy | 6 | 0 | linux/amd64 и linux/arm64 |
| discovery | ранее не сканировался отдельно | 0 | linux/amd64 |
| sim | 0 | 0 | linux/arm64 |

API, bot и discovery переведены с Debian slim на официальный **Python 3.12 Alpine 3.24**, закреплённый digest. Hash-locked зависимости приложения сохранены; сборка подтвердила наличие musllinux wheels для обеих архитектур. В API и bot сохранены непривилегированные UID.

Caddy **2.11.7** собирается из официального main-пакета с **Go 1.27.3** и **golang.org/x/net 0.60.0**. Полный Go module graph закреплён в `backend/web/caddy/go.mod` и `go.sum`, выполняются `go mod verify` и `go build -mod=readonly`. Минимальный Alpine runtime содержит CA bundle и стандартные модули Caddy; curl/libbrotli и Go build tooling в него не копируются. Это устраняет прежние уязвимые компоненты без отключения проверок. Подробности обновления — в `backend/web/caddy/README.md`.

Полный GitHub CI и выпуск OCI/SBOM/provenance с настоящими cosign-подписями в registry в этой сессии не выполнялись. Нулевой результат относится к перечисленным локальным образам и дате базы; он не заменяет очередной обязательный scan при выпуске и отдельную проверку остальных инфраструктурных образов.

## Что моделировалось

Клиентские сетевые отказы, задержки, устаревание каталога, несовместимые релизы, потеря ответа и смена региона проверены с управляемыми транспортом и временем. Отрицательные проверки подписи/provenance/platform используют подменённые ответы CLI. Unit-тесты не подтверждают реальный межплощадочный failover. Docker E2E действительно перезапускает сервисы изолированного одноузлового стенда.

## Что нужно подтвердить на выделенном staging

1. Выполнить полный GitHub CI из чистого checkout с повторным image scan при публикации, включая linux/amd64 и браузерные CORS/CSP/redirect/cache проверки с реальными региональными HTTPS origins.
2. Настроить GitHub App, действительные CODEOWNERS, защиту main, environments и изолированный CD runner. GitHub-логин владельца не выводится из commit email; в этой сессии он не был предоставлен.
3. Выпустить подписанные immutable-образы, проверить identity/digest/provenance; выполнить автоматическую доставку staging и ручное продвижение идентичных digest в production, а также совместимый откат.
4. Восстановить из off-host restic и pgBackRest/WAL/PITR до работоспособного приложения. Recovery workflow подготовлен; реальное S3/backup repository не подключалось.
5. Проверить Patroni primary failover, Redis/Sentinel failover, отказ приложения/площадки, сетевое разделение, fencing/watchdog, возврат узла и измерить RPO/RTO. `ansible/fault-tests.yml` подготовлен, на реальных площадках не запускался.
6. Выполнить нагрузочные серии при разном числе экземпляров и разных CPU/RAM/воркерах. `loadtest` сохраняет RPS/p50/p95/errors; численные результаты горизонтального и вертикального масштабирования пока не получены.

МОСКВА-1 / КАЗАНЬ / САНКТ-ПЕТЕРБУРГ / МОСКВА-2 — референс inventory, а не заявление о наличии серверов в этих дата-центрах. PostgreSQL реплицируется асинхронно: RPO=0 не обещается, защита от повторов опирается на сохранённую историю БД.
