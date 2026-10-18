# PostgreSQL 16 + pgBackRest (глава 26, ADR 0030 п. 9): непрерывный архив WAL и бэкапы в S3/SFTP.
# Базовый образ — официальный, закреплён по digest; pgBackRest — из репозитория PGDG (подключён в
# базовом образе). Версия не ниже 2.59.3: в ранних — слабые ключи шифрования репозитория.
FROM postgres:16-bookworm@sha256:0ea6700a3b4f0ae6ce746519073558aed4d88a79d8d07622a9a644946c7319c4

RUN apt-get update \
 && apt-get install -y --no-install-recommends pgbackrest ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && pgbackrest version | awk '{split($2, v, "."); if (v[1] < 2 || (v[1] == 2 && (v[2] < 59 || (v[2] == 59 && v[3] < 3)))) { print "pgBackRest < 2.59.3: " $2; exit 1 }}' \
 && install -d -o postgres -g postgres -m 0750 /var/log/pgbackrest /var/lib/pgbackrest /tmp/pgbackrest \
 && install -d -o postgres -g postgres -m 0700 /var/lib/postgresql/.ssh

COPY postgresql.conf /etc/postgresql/postgresql.conf
COPY pgbackrest.conf /etc/pgbackrest/pgbackrest.conf
COPY initdb/ /docker-entrypoint-initdb.d/

CMD ["postgres", "-c", "config_file=/etc/postgresql/postgresql.conf"]
