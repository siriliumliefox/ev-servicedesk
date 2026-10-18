#!/usr/bin/env bash
# Подготовка ВМ Ubuntu 24.04 под окружение (глава 26, ADR 0030 п. 5). Идемпотентно, от root:
#
#   sudo deploy/scripts/bootstrap.sh <env> <публичный-ключ-деплоя.pub>
#
# Делает: обновления и unattended-upgrades (перезагрузка при необходимости — 04:30 по Минску),
# Docker из репозитория Docker, вход по SSH только по ключу, ufw (22, 80, 443), fail2ban, chrony,
# swap 2 ГБ, sysctl для Redis, пользователь deploy (ключ деплоя — только forced command ev-ssh),
# каталоги /opt/ev и /var/lib/ev, скрипты в /opt/ev/bin, таймеры бэкапа systemd.
# Повторный запуск ничего не ломает: шаги проверяют текущее состояние.
set -euo pipefail

ENV="${1:-}"
KEY_FILE="${2:-}"
case "$ENV" in staging|production) ;; *) echo "окружение — staging или production" >&2; exit 2 ;; esac
[[ -f "$KEY_FILE" ]] || { echo "нужен файл публичного ключа деплоя" >&2; exit 2; }
[[ "$(id -u)" == 0 ]] || { echo "запуск от root" >&2; exit 2; }
. /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 ]] || { echo "ожидалась Ubuntu 24.04, найдено $PRETTY_NAME" >&2; exit 2; }

SRC="$(cd "$(dirname "$0")" && pwd)"
EV_ROOT=/opt/ev
log() { printf '[bootstrap] %s\n' "$*"; }
export DEBIAN_FRONTEND=noninteractive

log "пакеты и обновления"
apt-get update -q
# EV_BOOTSTRAP_SKIP_UPGRADE=1 — проверка в CI (infra-drill.yml): обновление образа раннера — минуты впустую.
[[ "${EV_BOOTSTRAP_SKIP_UPGRADE:-}" == 1 ]] || apt-get -y -q -o Dpkg::Options::=--force-confold upgrade
apt-get -y -q install ca-certificates curl gnupg ufw fail2ban unattended-upgrades chrony python3 jq rsync openssl

if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  log "Docker из репозитория Docker"
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get -y -q install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
daemon_json='{"log-driver":"json-file","log-opts":{"max-size":"50m","max-file":"5"},"live-restore":true}'
if [[ "$(cat /etc/docker/daemon.json 2>/dev/null)" != "$daemon_json" ]]; then
  printf '%s\n' "$daemon_json" > /etc/docker/daemon.json
  systemctl restart docker
fi
systemctl enable --now docker >/dev/null

log "unattended-upgrades: безопасность, перезагрузка при необходимости в 04:30 по Минску (01:30 UTC)"
cat > /etc/apt/apt.conf.d/52ev-unattended <<'EOF'
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "01:30";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
EOF
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
timedatectl set-timezone UTC
systemctl enable --now chrony >/dev/null

if [[ "$(swapon --show --noheadings | wc -l)" == 0 ]]; then
  log "swap 2 ГБ"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
cat > /etc/sysctl.d/90-ev.conf <<'EOF'
vm.overcommit_memory = 1
vm.swappiness = 10
net.core.somaxconn = 4096
EOF
sysctl -q --system

log "пользователь deploy и ключ деплоя (только ev-ssh)"
id deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash deploy
usermod -aG docker deploy
install -d -m 0700 -o deploy -g deploy /home/deploy/.ssh
key="$(tr -d '\n' < "$KEY_FILE")"
[[ "$key" =~ ^ssh-(ed25519|rsa)\  ]] || { echo "файл ключа — не публичный ключ SSH" >&2; exit 2; }
printf 'command="%s/bin/ev-ssh",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty %s\n' "$EV_ROOT" "$key" \
  > /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys && chmod 0600 /home/deploy/.ssh/authorized_keys

if [[ -d /etc/ssh/sshd_config.d ]]; then
  log "sshd: только ключи, root — только по ключу"
  cat > /etc/ssh/sshd_config.d/10-ev.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
MaxAuthTries 3
X11Forwarding no
EOF
  sshd -t && systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
fi

log "ufw: 22, 80, 443; fail2ban — sshd"
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
for port in 22/tcp 80/tcp 443/tcp; do ufw allow "$port" >/dev/null; done
ufw --force enable >/dev/null
systemctl enable --now fail2ban >/dev/null

log "каталоги и скрипты"
install -d -m 0755 -o root -g root "$EV_ROOT"
install -d -m 0755 -o deploy -g deploy "$EV_ROOT/bin"
install -d -m 0750 -o deploy -g deploy "$EV_ROOT/$ENV"
install -d -m 0755 -o deploy -g deploy "/var/lib/ev/$ENV/textfile"
for file in lib.sh deploy.sh backup.sh restore.sh render.py nightly-load.sh ev-ssh; do
  install -m 0755 -o deploy -g deploy "$SRC/$file" "$EV_ROOT/bin/$file"
done
printf 'EV_ALLOWED_ENV=%s\n' "$ENV" > "$EV_ROOT/bin/ev-ssh.conf"
chown root:root "$EV_ROOT/bin/ev-ssh.conf" && chmod 0644 "$EV_ROOT/bin/ev-ssh.conf"

log "таймеры бэкапа (UTC: Минск −3 ч)"
cat > /etc/systemd/system/ev-backup@.service <<EOF
[Unit]
Description=EV-ServiceDesk backup %i ($ENV)
After=docker.service

[Service]
Type=oneshot
User=deploy
ExecStart=$EV_ROOT/bin/backup.sh %i $ENV
EOF
timer() {
  # timer <тип> <OnCalendar>
  cat > "/etc/systemd/system/ev-backup-$1.timer" <<EOF
[Unit]
Description=EV-ServiceDesk backup $1 ($ENV)

[Timer]
OnCalendar=$2
Persistent=true
RandomizedDelaySec=300
Unit=ev-backup@$1.service

[Install]
WantedBy=timers.target
EOF
}
timer full "Sun *-*-* 00:00:00"
timer diff "Mon..Sat *-*-* 00:00:00"
timer verify "Wed *-*-* 01:00:00"
timer restore-check "*-*-01 02:00:00"
systemctl daemon-reload
for t in full diff verify restore-check; do systemctl enable --now "ev-backup-$t.timer" >/dev/null; done

log "готово: окружение $ENV; первый выпуск — job деплоя (ssh deploy@<ВМ> deploy $ENV < bundle)"
