#!/usr/bin/env bash
# PreToolUse-хук Claude Code: страж правил AGENTS.md («Безопасность», генерируемые файлы, защита веток).
#   deny — правило нарушено, действие не выполняется;
#   ask  — действие допустимо, но только с подтверждением владельца (секреты, удалённые хосты, откат).
# Это страховка от случайных нарушений, а не граница безопасности: команды разбираются эвристически
# (тела heredoc и цитаты с пробелами отбрасываются, `$(...)` и `;`/`&&`/`|` режут команду на части),
# обход через `bash -c`, `eval` и переменные не ловится. Главная защита — pre-commit gitleaks, `secret-scan`
# и защита веток на GitHub (ADR 0008).
# Подключение: .claude/settings.json → hooks.PreToolUse. Проверка правил: .claude/hooks/guard.test.sh.
# Нужны: jq, perl. Совместимо с bash 3.2 (системный bash macOS).

if ! command -v jq >/dev/null 2>&1; then
    echo "guard.sh: jq не найден (brew install jq) — правила AGENTS.md не проверяются." >&2
    exit 1
fi

input=$(cat)
tool=$(jq -r '.tool_name // ""' <<<"$input")
cwd=$(jq -r '.cwd // ""' <<<"$input")

decide() {
    jq -n --arg decision "$1" --arg reason "$2" \
        '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: $decision, permissionDecisionReason: $reason}}'
    exit 0
}

# .env и .env.* (кроме .env.example) — AGENTS.md: не читать и не выводить.
is_env_file() {
    case "${1##*/}" in
        .env.example) return 1 ;;
        .env | .env.*) return 0 ;;
    esac
    return 1
}

ends_with() { [ "$1" = "$2" ] || [[ "$1" == */"$2" ]]; }

# Генерируемые файлы: правятся только генератором. Печатает команду-генератор или ничего.
generated_hint() {
    if ends_with "$1" web-shared/src/api/schema.ts; then
        echo "npm run gen:api (источник — docs/openapi.yaml, ADR 0007)"
    elif ends_with "$1" web-shared/src/theme/tokens.css || ends_with "$1" mobile/lib/theme/tokens.g.dart; then
        echo "npm run tokens (источник — design/tokens.json, ADR 0010)"
    elif ends_with "$1" docs/EV_ServiceDesk_Glava2_DDL.sql; then
        echo "cd backend && poetry run python scripts/export_ddl.py (источник — миграции Alembic, ADR 0003)"
    elif ends_with "$1" docs/ERD_EV_ServiceDesk_Glava2.mermaid; then
        echo "cd backend && poetry run python scripts/export_erd.py (источник — ORM, ADR 0003)"
    fi
}

# ---------- Инструменты чтения и правки файлов ----------
case "$tool" in
    Read | Edit | Write | NotebookEdit | MultiEdit | Grep)
        path=$(jq -r '.tool_input.file_path // .tool_input.notebook_path // .tool_input.path // ""' <<<"$input")
        [ -n "$path" ] || exit 0
        if is_env_file "$path"; then
            decide deny "AGENTS.md → Безопасность: не читать и не выводить .env. Имена переменных — в .env.example."
        fi
        case "$tool" in
            Edit | Write | NotebookEdit | MultiEdit)
                hint=$(generated_hint "$path")
                if [ -n "$hint" ]; then
                    decide deny "Файл генерируемый, руками не правится. Обновить: $hint."
                fi
                if ends_with "$path" docs/EV_ServiceDesk_SwaggerUI.html; then
                    decide ask "В HTML встроен docs/openapi.yaml: он обновляется python3 scripts/sync_swagger_html.py, вручную правится только остальное. Продолжить?"
                fi
                case "${path##*/}" in
                    package-lock.json | poetry.lock | pubspec.lock)
                        decide ask "Lock-файл генерирует менеджер пакетов (npm ci / poetry lock / flutter pub get); ручная правка ломает воспроизводимость. Продолжить?"
                        ;;
                esac
                ;;
        esac
        exit 0
        ;;
    Bash) ;;
    *) exit 0 ;;
esac

# ---------- Bash ----------
command=$(jq -r '.tool_input.command // ""' <<<"$input")
[ -n "$command" ] || exit 0

# Нормализация: тела heredoc убираем; цитаты с пробелами (проза: сообщения коммитов, тела PR) заменяем на "";
# цитаты без пробелов (пути, аргументы) раскрываем; подстановки и разделители команд превращаем в переводы строк.
segments=$(printf '%s' "$command" | perl -0777 -pe '
    s/(<<-?[ \t]*([\x27"]?)(\w+)\2[^\n]*\n)(.*?\n)[ \t]*\3[ \t]*(?=\n|\z)/$1/sg;
    s/"((?:[^"\\]|\\.)*)"/ my $s = $1; $s =~ m{\s} ? "\x22\x22" : $s /sge;
    s/\x27([^\x27]*)\x27/ my $s = $1; $s =~ m{\s} ? "\x27\x27" : $s /sge;
    s/\$\(|`|\(|\)|&&|\|\||[;|&]/\n/g;
')

current_branch() { (cd "$1" 2>/dev/null && git branch --show-current 2>/dev/null); }

is_protected() { [ "$1" = main ] || [ "$1" = develop ]; }

# Цель refspec: «+src:dst» → dst; «HEAD»/«@» → текущая ветка; «refs/heads/x» → x.
refspec_target() {
    local spec=${1#+} branch_dir=$2
    case "$spec" in
        *:*) spec=${spec##*:} ;;
    esac
    case "$spec" in
        HEAD | @) spec=$(current_branch "$branch_dir") ;;
    esac
    echo "${spec#refs/heads/}"
}

# check_git_push <каталог> <аргументы push...>
check_git_push() {
    local dir=$1 arg positional=0 spec target
    shift
    local have_refspec=0
    while [ $# -gt 0 ]; do
        arg=$1
        shift
        case "$arg" in
            --all | --mirror)
                decide deny "git push $arg отправляет и защищённые ветки main/develop. Прямой push в них запрещён (ADR 0008): только PR."
                ;;
            -o | --push-option | --receive-pack | --exec | --repo) shift ;;
            -*) ;;
            *)
                positional=$((positional + 1))
                [ "$positional" -gt 1 ] || continue # первый позиционный аргумент — remote
                have_refspec=1
                target=$(refspec_target "$arg" "$dir")
                if is_protected "$target"; then
                    decide deny "Прямой push в $target запрещён (ADR 0008, AGENTS.md): только PR, обязательная проверка ci-gate."
                fi
                ;;
        esac
    done
    if [ "$have_refspec" -eq 0 ] && is_protected "$(current_branch "$dir")"; then
        decide deny "Ветка $(current_branch "$dir") защищена: прямой push запрещён (ADR 0008). Создать ветку feature/…, fix/… или chore/… и открыть PR."
    fi
}

# Разбор одной команды сегмента. Режим deny — запреты, режим ask — подтверждения.
scan() {
    local mode=$1 seg tok i cmd sub j t gdir gitc dir eff target
    eff=$cwd
    while IFS= read -r seg; do
        read -ra tok <<<"$seg"
        [ "${#tok[@]}" -gt 0 ] || continue

        if [ "$mode" = deny ]; then
            for t in "${tok[@]}"; do
                t=${t#--*=}
                t=${t##[<>]}
                if is_env_file "$t"; then
                    decide deny "AGENTS.md → Безопасность: не читать и не выводить .env. Имена переменных — в .env.example."
                fi
            done
        fi

        i=0
        while [ "$i" -lt "${#tok[@]}" ]; do
            case "${tok[$i]}" in
                [A-Za-z_]*=* | sudo | env | command | builtin | time | nohup | exec | nice | xargs | if | then | else | elif | do | while | until | '!' | '{') i=$((i + 1)) ;;
                *) break ;;
            esac
        done
        [ "$i" -lt "${#tok[@]}" ] || continue
        cmd=${tok[$i]##*/}

        case "$cmd" in
            cd)
                target=${tok[$((i + 1))]:-}
                case "$target" in
                    /*) eff=$target ;;
                    "" | -) ;;
                    *) eff="$eff/$target" ;;
                esac
                ;;
            git)
                gdir=""
                gitc=""
                sub=""
                j=$((i + 1))
                while [ "$j" -lt "${#tok[@]}" ]; do
                    t=${tok[$j]}
                    case "$t" in
                        -C)
                            gdir=${tok[$((j + 1))]:-}
                            j=$((j + 2))
                            ;;
                        -c)
                            gitc="$gitc ${tok[$((j + 1))]:-}"
                            j=$((j + 2))
                            ;;
                        --git-dir | --work-tree | --namespace) j=$((j + 2)) ;;
                        -*) j=$((j + 1)) ;;
                        *)
                            sub=$t
                            break
                            ;;
                    esac
                done
                [ -n "$sub" ] || continue
                local -a args
                args=("${tok[@]:$((j + 1))}")
                case "$gdir" in
                    "") dir=$eff ;;
                    /*) dir=$gdir ;;
                    *) dir="$eff/$gdir" ;;
                esac
                [ "$mode" = deny ] || continue
                case "$sub" in
                    commit | push | merge | rebase | cherry-pick | am | revert)
                        for t in "${args[@]}"; do
                            if [ "$t" = --no-verify ]; then
                                decide deny "AGENTS.md → Безопасность: --no-verify не использовать (обходит pre-commit gitleaks)."
                            fi
                        done
                        case "$gitc" in
                            *core.hooksPath*)
                                decide deny "AGENTS.md → Безопасность: подмена core.hooksPath обходит pre-commit gitleaks."
                                ;;
                        esac
                        ;;
                esac
                if [ "$sub" = commit ]; then
                    for t in "${args[@]}"; do
                        case "$t" in
                            -[A-Za-z]*)
                                # Кластер коротких флагов: после флага с аргументом (m, F, C, c, t, S, u) идёт его значение.
                                local rest=${t#-} ch
                                while [ -n "$rest" ]; do
                                    ch=${rest:0:1}
                                    rest=${rest:1}
                                    case "$ch" in
                                        n) decide deny "AGENTS.md → Безопасность: git commit -n (--no-verify) не использовать." ;;
                                        m | F | C | c | t | S | u) break ;;
                                    esac
                                done
                                ;;
                        esac
                    done
                fi
                if [ "$sub" = push ]; then
                    check_git_push "$dir" "${args[@]}"
                fi
                ;;
        esac

        if [ "$mode" = ask ]; then
            case "$cmd" in
                ssh | scp | sftp)
                    decide ask "$cmd подключается к удалённому хосту (production/staging, глава 26). Продолжить только с подтверждением владельца."
                    ;;
                gh)
                    for t in "${tok[@]:$((i + 1))}"; do
                        case "$t" in
                            -*) ;;
                            secret) decide ask "gh secret меняет секреты GitHub. Ключи вводит владелец (скрипты scripts/set-*-secrets.sh). Продолжить?" ;;
                            *) break ;;
                        esac
                    done
                    ;;
            esac
            for t in "${tok[@]}"; do
                case "${t##*/}" in
                    set-*-secret.sh | set-*-secrets.sh)
                        decide ask "${t##*/} записывает секреты в GitHub Environments: запускает владелец, значения не выводятся в чат."
                        ;;
                    generate-secret.sh)
                        decide ask "generate-secret.sh печатает секрет на экран, а стенограммы чатов попадают в MemPalace дословно. Запустить лучше владельцу."
                        ;;
                    rollback-staging.sh)
                        decide ask "rollback-staging.sh откатывает staging: подтвердить действие."
                        ;;
                    setup-github-environments.sh | setup-branch-protection.sh)
                        decide ask "${t##*/} меняет настройки GitHub (окружения, защита веток): подтвердить действие."
                        ;;
                esac
            done
        fi
    done <<<"$segments"
}

scan deny
scan ask
exit 0
