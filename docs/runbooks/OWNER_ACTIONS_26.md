# Действия владельца — глава 26 (production-инфраструктура)

ADR 0030. Всё, что требует оплаты, договора, доступа к аккаунтам или ввода ключей, делает владелец; агент
готовит код, проверяет на стенде и выполняет шаги на серверах, как только они доступны. Секреты вводятся
только скриптами со скрытым вводом — не в чат, не в команды агента.

Состояние на 2026-10-19: серверы **не заказаны** (решение владельца) — глава PARTIAL; код, CI и учения —
на локальном стенде (`scripts/infra_stack.sh`).

| № | Действие | Когда | Где проверить |
|---|---|---|---|
| 0 | Продлить домен `etsautogomel.by` или включить автопродление (оплачен до 17.12.2026) | сейчас | Timeweb → Домены и SSL |
| 1 | Заказать ВМ и S3 | решение о запуске | шаги ниже |
| 2 | DNS: шесть A-записей | после 1 | `dig +short api.etsautogomel.by` |
| 3 | Секреты окружений | после 1 | `scripts/set-infra-secrets.sh` |
| 4 | Бот алертов и dead-man | можно сейчас | Telegram, healthchecks.io |
| 5 | A1: разрешить IP серверов | после 1 | ответ поддержки A1 |
| 6 | Firebase-проект production и ключ FCM | до запуска production | `scripts/set-fcm-secret.sh production` |
| 7 | Согласие с Subscriber Agreement Let's Encrypt | первый выпуск сертификатов | ответ в чат |
| 8 | Approve выкладки production | release-PR `develop → main` | GitHub → Actions → Review deployments |
| 9 | Сценарий X5 — SMS на свой телефон | после 5 | staging, мобильное приложение |

## 0. Домен
Timeweb → Домены и SSL → `etsautogomel.by` → Продлить / Автопродление. Production и сайт компании на
одном домене: без продления 17.12.2026 перестанут открываться оба.

## 1. Серверы и S3 (Timeweb Cloud)
1. Ключ администратора на Mac (один раз): `ssh-keygen -t ed25519 -f ~/.ssh/ev_admin -C ev-admin`.
2. Облачные серверы → Создать, оба — **Ubuntu 24.04**, SSH-ключ — содержимое `~/.ssh/ev_admin.pub`,
   публичный IPv4:
   - `ev-production`: регион **Санкт-Петербург**, конструктор Premium NVMe — 4 vCPU, 10 ГБ RAM, 120 ГБ;
   - `ev-staging`: регион **Москва**, 2 vCPU, 6 ГБ RAM, 60 ГБ.
   Ориентир (прейскурант 2026-10-19, с НДС): 8 560 + 4 680 + 2 × 200 ₽ за IPv4.
3. Firewall → группа `ev`: входящие TCP 22, 80, 443; применить к обоим серверам.
4. Хранилище S3 → создать бакеты (Санкт-Петербург, приватные): `ev-production-media`,
   `ev-production-backup`, `ev-staging-media`, `ev-staging-backup` (если имя занято — добавьте суффикс и
   введите его в шаге 3). Ключи доступа — в карточке хранилища. Затем правила хранения:
   `scripts/s3-lifecycle.sh production` и `scripts/s3-lifecycle.sh staging`.
5. Сообщите агенту IP обоих серверов. Агент подготовит ВМ (`deploy/scripts/bootstrap.sh` по вашему
   ключу администратора) и выложит staging.

## 2. DNS (Timeweb → Домены → etsautogomel.by → DNS)
| Имя | Тип | Значение |
|---|---|---|
| `api`, `engineer`, `admin` | A | IP `ev-production` |
| `api.staging`, `engineer.staging`, `admin.staging` | A | IP `ev-staging` |

TTL 600. Записи сайта (`@`, `www`, почта) не трогать.

## 3. Секреты окружений
```bash
scripts/set-infra-secrets.sh staging
```
```bash
scripts/set-infra-secrets.sh production
```
Скрипт генерирует пароли БД и ключ деплоя, **один раз показывает ключ шифрования бэкапов — сохраните его в
менеджер паролей** (без него восстановление невозможно), спрашивает пароль Grafana, ключи S3, имена
бакетов, IP сервера и отпечаток ключа хоста. После него — `gh workflow run secrets-isolation.yml --ref develop`.

## 4. Алерты: Telegram и dead-man
1. Telegram → @BotFather → `/newbot` → имя «EV-ServiceDesk alerts» → токен. Напишите боту `/start`.
2. `scripts/telegram-chat-id.sh` — введите токен, получите `chat_id`.
3. `ONLY="ALERT_TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID" scripts/set-infra-secrets.sh staging` (и production).
4. healthchecks.io → бесплатная регистрация → две проверки `ev-staging`, `ev-production`: Period 5 min,
   Grace 5 min, уведомление на e-mail (и Telegram — интеграция сервиса). Ссылка пинга →
   `ONLY=DEADMAN_URL scripts/set-infra-secrets.sh <окружение>`. В сигналах нет ПД — только «цепочка жива».

## 5. A1 «Smart-рассылка»
Письмо в поддержку A1 (кабинет smart-sender.a1.by → Поддержка):
> Прошу добавить в список разрешённых IP-адресов учётной записи <логин> адреса серверов
> <IP production> и <IP staging> (отправка SMS-кодов входа сервиса EV-ServiceDesk ООО «ЕТСавтоГомель»).

После ответа: `scripts/set-a1-secrets.sh` для staging и production; на staging —
`ONLY=SMS_PROVIDER scripts/set-infra-secrets.sh staging` → `a1`. Проверка — `scripts/a1_check.py` с сервера
(агент запустит на ВМ по вашему разрешению).

## 6. Firebase production
console.firebase.google.com → проект `ev-servicedesk-prod` → Project settings → Service accounts →
Generate new private key → `scripts/set-fcm-secret.sh production`. Без ключа production не стартует
(фейковый push там запрещён, ADR 0019). iOS (APNs) — глава 27.

## 7. Let's Encrypt
Первый выпуск сертификатов принимает Subscriber Agreement Let's Encrypt. Напишите агенту «согласен» и
адрес для уведомлений — агент выполнит `EV_ACME_AGREE_TOS=yes EV_ACME_EMAIL=<адрес> deploy/scripts/certs.sh
letsencrypt <окружение>` на ВМ. Дальше продлевает сервис `certbot` сам.

## 8. Выпуск production
Агент открывает release-PR `develop → main` (merge-коммит). После merge `cd-production` ждёт Approve:
GitHub → Actions → cd-production → Review deployments → production → Approve. До этого production не
меняется.

## 9. X5 — реальный SMS (ADR 0027 п. 11)
На staging, после шага 5: мобильное приложение (сборка staging) → вход по своему номеру → код приходит
SMS от A1 за ≤ 1 мин → вход выполнен. Результат — в отчёт главы (агент сверит по журналу `app.security`).

## Отложено решением владельца
- Аттестация системы защиты информации (класс 3-ин, приказ ОАЦ № 66) — не проводится; что понадобится —
  `docs/compliance/OAC_3IN.md`.
- Договоры с уполномоченными лицами (хостинг, S3, A1, FCM) — позже; обязательные пункты — там же.
- Указ № 60 (ресурсы юрлица РБ — в РБ): размещение в России — риск; перед коммерческим пилотом —
  юридическая проверка или переезд к провайдеру РБ (стек переносим).
