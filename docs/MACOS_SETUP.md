# Настройка EV-ServiceDesk на MacBook Pro M5 Pro — полная инструкция

Пошагово, с точными командами для копирования в Терминал. Каждый блок кода —
это то, что нужно вставить и нажать Enter. Приложение → Терминал, или ⌘+Пробел
→ введите «Terminal».

---

## 0. Что получится в итоге

- Локально работающий backend (FastAPI), обе веб-панели, каркас мобильного приложения
- Настоящий репозиторий на GitHub с защищёнными ветками
- Окружения staging и production с разделёнными секретами (модель local → staging → production, ADR 0008)
- Реально зелёный CI на каждый PR

Если что-то в разделах 1–3 у вас уже стоит — просто пропускайте, команды
безопасно повторять (Homebrew сам скажет «already installed»).

---

## 1. Xcode и Command Line Tools (обязательно первым шагом)

1. Откройте **App Store** → найдите **Xcode** → Установить (это долго, займите время на кофе).
2. **После того как установка полностью завершится**, откройте Xcode.app вручную хотя бы один раз — примет лицензионное соглашение через GUI.
3. Только теперь в Терминале, **в этом порядке** (порядок важен — `-license accept` до полной установки Xcode.app даст ошибку `requires Xcode, but active developer directory is a command line tools instance`):

```bash
xcode-select --install
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
sudo xcodebuild -runFirstLaunch
sudo xcodebuild -license accept
```

Если `xcode-select --install` скажет «Command line tools are already installed» — это нормально, идите дальше по списку.

Без этого не соберётся ничего, что связано с iOS/macOS (Flutter, CocoaPods).

---

## 2. Homebrew (менеджер пакетов macOS)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

В конце установщик покажет 2 команды `echo ... >> ~/.zprofile` и `eval ...` —
**выполните их**, иначе `brew` не найдётся в терминале. На Apple Silicon
Homebrew ставится в `/opt/homebrew` (не `/usr/local`, как на старых Intel-Mac —
если где-то в интернете увидите `/usr/local/bin/brew`, это не про ваш Mac).

Проверка:
```bash
brew --version
```

---

## 3. Все остальные инструменты — одним блоком

```bash
brew install git gh node@22 python@3.12 cocoapods
brew install --cask docker
brew install --cask flutter
```

⚠️ **`node@22` часто не линкуется автоматически** (конфликт с уже существующими файлами `npm` в `/opt/homebrew`) — Homebrew сообщит об этом отдельной ошибкой `brew link` посреди вывода, легко пропустить. Сразу после блока выше выполните:

```bash
brew link --overwrite node@22
node --version   # должно показать v22.x
npm --version
```

Если `node --version` не находит команду вообще — добавьте в PATH явно:
```bash
echo 'export PATH="/opt/homebrew/opt/node@22/bin:$PATH"' >> ~/.zprofile
source ~/.zprofile
```

- **`git`** — если Xcode CLT уже поставил свою версию, Homebrew поставит более новую — не конфликтует.
- **`gh`** — GitHub CLI, через него будем управлять репозиторием без ручного создания токенов.
- **`node@22`** — версия сознательно та же, что в CI (`.github/workflows/*.yml`).
- **`python@3.12`** — версия та же, что в `backend/pyproject.toml`.
- **`cocoapods`** — нужен Flutter для iOS/macOS нативных зависимостей.
- **`docker`** (cask) — это Docker Desktop, GUI-приложение. После установки **откройте Docker.app вручную** из Launchpad и дождитесь, пока в строке меню появится стабильный значок кита (иконка не должна мигать/грузиться).
- **`flutter`** (cask) — сам SDK.

Poetry ставится отдельно (свой официальный установщик, не через Homebrew — так рекомендует сама Poetry):
```bash
python3.12 -m ensurepip --upgrade
curl -sSL https://install.python-poetry.org | python3.12 -
```
⚠️ **Используйте именно `python3.12`, не `python3`.** На macOS `python3` почти
всегда указывает на древний Python из Xcode Command Line Tools (например,
3.9), который не умеет создавать venv через symlink и уронит установщик с
ошибкой `This build of python cannot create venvs without using symlinks`.
`python@3.12` — keg-only формула Homebrew, поэтому команда называется
`python3.12`, а не просто `python3`, и в PATH её никто автоматически не
переключает.

После установки откроется подсказка добавить Poetry в PATH — выполните её (обычно `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zprofile`), затем:
```bash
source ~/.zprofile
poetry --version
```
Если видите `poetry: command not found` — значит, установщик упал раньше
(смотрите вывод выше на ошибку) и `~/.local/bin/poetry` не создался; сначала
почините ошибку установки, потом повторяйте `source`/`poetry --version`.

Проверка Flutter (покажет, чего не хватает — донастройте по подсказкам):
```bash
flutter doctor
```
`flutter doctor` почти наверняка попросит принять лицензии Android — на нашем
проекте Android не используется (см. `mobile/README.md`), можно игнорировать
предупреждения про Android toolchain. **Не тратьте время на
`flutter doctor --android-licenses`** — он потребует Android SDK
cmdline-tools, которые нам не нужны, и просто выдаст «sdkmanager not found».

---

## 4. GitHub — вход и создание репозитория

```bash
gh auth login
```
Выберите: `GitHub.com` → `HTTPS` → `Login with a web browser` — откроется
браузер, авторизуетесь через обычный вход GitHub.

Создайте репозиторий (замените `ev-servicedesk` при желании):
```bash
gh repo create ev-servicedesk --private --description "Service Desk для владельцев электромобилей — ООО ЕТСавтоГомель"
```
`--private` — это код реального клиента, не выкладываем публично.

Запомните полное имя репозитория — оно понадобится дальше:
```bash
export GITHUB_REPO="$(gh api user --jq .login)/ev-servicedesk"
echo "$GITHUB_REPO"
```

---

## 5. Распаковать каркас и первый push

1. Распакуйте `ev-servicedesk-skeleton.zip` (двойной клик в Finder, или):
```bash
cd ~/Downloads
unzip ev-servicedesk-skeleton.zip -d ev-servicedesk
cd ev-servicedesk
```

2. Инициализируйте git и запушьте:
```bash
git init
git add -A
git commit -m "chore: repo skeleton — Главы 1-4"
git branch -M main
git remote add origin "https://github.com/${GITHUB_REPO}.git"
git push -u origin main

git checkout -b develop
git push -u origin develop
```

### Если `git push` падает с `Could not resolve host: github.com`

Это DNS/сеть на вашей стороне, не про репозиторий. Проверьте по порядку:
```bash
ping -c 1 github.com          # если "Unknown host" — точно DNS
curl -I https://github.com    # если зависает/ошибка — точно сеть
```
Дальше по возрастанию радикальности:
1. Проверьте Wi-Fi/VPN — отключите VPN, если он есть, попробуйте снова.
2. Сбросьте кэш DNS: `sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder`
3. Временно смените DNS на публичный (Системные настройки → Сеть → Wi-Fi → Подробнее → DNS → добавить `1.1.1.1` и `8.8.8.8`).
4. Если ничего не помогает — попробуйте с телефонного интернета (раздать точку доступа): если оттуда `ping github.com` проходит, проблема в роутере/провайдере, не в Mac.

### ⚠️ Если вы уже выполнили `git init`/`commit` до этого фикса

Есть шанс, что в архиве, который вы распаковали, затесалась моя служебная
`.git`-папка с тестовыми коммитами (мой баг при сборке архива — паттерн
исключения не сработал для папки в корне). Проверьте:
```bash
git log --oneline --all
```
Если видите коммиты вроде `chore: repo skeleton (Глава 4, шаг 1) — backend/web/mobile каркасы, docs` или `feat(backend): add /version endpoint (#1)` **до** вашего собственного коммита — это она. Почистите и начните набело:
```bash
rm -rf .git
git init
git add -A
git commit -m "chore: repo skeleton — Главы 1-4"
git branch -M main
git remote add origin "https://github.com/${GITHUB_REPO}.git"
git push -u origin main
git checkout -b develop
git push -u origin develop
```
Актуальный архив (ссылка ниже в чате) этот баг больше не содержит — если
качаете заново, `.git` в нём уже нет.

Проверка: откройте `https://github.com/<ваш-логин>/ev-servicedesk` в браузере — должны быть видны обе ветки.

---

## 6. Заменить плейсхолдеры на ваш реальный логин

```bash
export GH_USER="$(gh api user --jq .login)"
sed -i '' "s/@your-github-handle/@${GH_USER}/g" .github/CODEOWNERS
git add .github/CODEOWNERS
git commit -m "chore: CODEOWNERS — реальный GitHub-логин"
git push
```

---

## 7. Локальное окружение

```bash
cp .env.example .env
```
Для локальной разработки менять ничего не обязательно — значения уже
рабочие (`ev_local_only` и т.п. — это **только** для local, не переносите в
staging/production, см. `docs/ENVIRONMENTS.md`).

Поднимите Postgres + Redis (Docker Desktop должен быть уже открыт и запущен — см. пункт 3):
```bash
docker compose up -d
docker compose ps
```
Оба сервиса должны быть `healthy` (может занять секунд 10).

Опционально — веб-интерфейс для просмотра БД:
```bash
docker compose --profile tools up -d adminer
```
→ откройте `http://localhost:8080`, сервер `postgres`, логин/пароль/база — из `.env`.

---

## 8. Backend — установить, проверить, запустить

```bash
cd backend
poetry install
poetry run ruff check .
poetry run pytest -v
poetry run uvicorn app.main:app --reload
```
В другом окне терминала:
```bash
curl http://localhost:8000/health
```
Должно вернуть `{"status":"ok","environment":"local"}`. Остановить сервер — `Ctrl+C` в окне, где он запущен.

```bash
cd ..
```

---

## 9. Веб-панели — установить, проверить, запустить

```bash
npm install
npm run lint --workspace web-engineer
npm run lint --workspace web-admin
npm run build --workspace web-engineer
npm run build --workspace web-admin
```

Запуск в dev-режиме (в отдельных окнах терминала, либо по очереди):
```bash
npm run dev --workspace web-engineer   # http://localhost:5173
npm run dev --workspace web-admin      # обычно http://localhost:5174 (Vite сам найдёт свободный порт)
```

---

## 10. Мобильное приложение — здесь будет самое интересное

Каркас (`mobile/pubspec.yaml`, `mobile/lib/main.dart`) написан вручную — без
запуска `flutter create`, у него нет папок `ios/`/`macos/` с нативными
Xcode-проектами. Сгенерируйте их поверх существующего кода:

```bash
cd mobile
flutter create --platforms=ios,macos --org com.etsavtogomel --project-name ev_servicedesk .
```

⚠️ Flutter может спросить о перезаписи `pubspec.yaml` — **откажитесь**
(`n`) или после выполните `git diff pubspec.yaml` и вручную верните наши
зависимости (`http`, `flutter_secure_storage`, `firebase_messaging`), если
он их стёр. Папки `lib/` и `test/` он не тронет, если файлы уже существуют.

Дальше — как обычно:
```bash
flutter pub get
flutter analyze
flutter test
```

Если всё зелёное — запустите на симуляторе:
```bash
open -a Simulator
flutter run -d "iPhone 15"
```
(имя симулятора зависит от того, какие у вас скачаны в Xcode → Settings → Platforms)

Для macOS-таргета:
```bash
flutter run -d macos
```

```bash
cd ..
```

---

## 11. Защита веток и GitHub Environments

Уже применено к репозиторию (Глава 4, ADR 0008); скрипты идемпотентны —
нужны только для нового репозитория или восстановления настроек. Требуют `gh auth login` с правами admin.

```bash
./scripts/setup-branch-protection.sh      # main/develop: только PR, обязательный ci-gate, на админа тоже
```

```bash
./scripts/setup-github-environments.sh    # staging ← develop, production ← main + reviewer
```

```bash
./scripts/set-environment-secrets.sh      # разные JWT_SECRET для staging/production; повторный запуск = ротация
```

Проверка: `https://github.com/<логин>/ev-servicedesk/settings/environments` — `staging` и `production`,
у `production` — вы в Required reviewers; Actions → `secrets-isolation` → Run workflow (ветка `develop`) — все строки `PASS`.

---

## 12. Проверка CI

```bash
gh pr checks --watch
```

На любом PR запускается `ci` (без path-фильтров): job `changes` выбирает нужные проверки
(`backend`/`web`/`mobile`/`docs`), `secret-scan` идёт всегда, итог — `ci-gate`. Для PR, не
затрагивающего сервисы, проверки сервисов будут `skipped`, а `ci-gate` — зелёным.

---

## 13. Проверка CD на staging и откат

Merge в `develop` с изменениями в `backend/` или `web-*/` запускает `cd-staging.yml`:
```bash
gh run list --workflow=cd-staging.yml
```
Job `deploy-staging` выводит TODO — staging-сервера нет до Главы 26 (ADR 0008).
Образы: `https://github.com/<логин>/ev-servicedesk/pkgs/container/ev-servicedesk%2Fbackend`.

Откат на ранее собранный коммит (без пересборки, с проверкой digest):
```bash
./scripts/rollback-staging.sh <sha>
```

---

## Известные грабли (уже наступала, чтобы вы не наступали)

- **`git branch -d` после squash-merge откажет** — Git не считает ветку смерженной. Нужно `git branch -D feature/...`.
- **`npm run lint` — это `oxlint`, не ESLint** — свежий Vite ставит именно его по умолчанию.
- **`docker compose config` без `.env` раньше падал** — уже исправлено (`required: false`), но если видите такую ошибку — значит, `cp .env.example .env` не выполнен.
- **`xcodebuild -license accept` раньше времени** — упадёт с `requires Xcode, but active developer directory is a command line tools instance`, если полный Xcode.app ещё не выбран через `xcode-select --switch`. Порядок команд в разделе 1 уже это учитывает.
- **`node@22` не линкуется автоматически** — `brew link --overwrite node@22`, иначе `node`/`npm` могут указывать в никуда или на другую версию.
- **`python3` ≠ `python3.12` на свежем Mac** — Poetry-установщик, запущенный через голый `python3`, попадёт на древний Python 3.9 из Xcode CLT и упадёт на создании venv. Используйте `python3.12` явно.
- **Apple Developer аккаунт** — бесплатного достаточно для `flutter run` на симуляторе и даже на своём iPhone через USB. Платный ($99/год) нужен только когда дойдём до push-уведомлений (Главы 15/20) и TestFlight (Глава 27).

---

## Если что-то не так

Пришлите мне точный текст ошибки и на каком шаге — почти наверняка это
что-то версионное (Xcode/Flutter обновляются часто), поправим по месту.
