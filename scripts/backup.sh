#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
leave_stopped=false
backup_complete=false
if [[ "${1:-}" == "--leave-stopped" ]]; then
  leave_stopped=true
  shift
fi
backup_destination="${1:-backups/$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$backup_destination"
# Quiesce writers; a second check catches submissions racing the shutdown.
docker compose exec -T api python -m genjutsu.maintenance check-backup
restore_services() {
  if [[ "$leave_stopped" != true || "$backup_complete" != true ]]; then
    docker compose start temporal api worker >/dev/null
  fi
}
trap restore_services EXIT
docker compose stop api worker >/dev/null
docker compose run --rm --no-deps api python -m genjutsu.maintenance check-backup
docker compose stop temporal >/dev/null
docker compose exec -T db pg_dump -U genjutsu -d genjutsu -Fc > "$backup_destination/application.dump"
docker compose exec -T temporal-db pg_dumpall -U temporal > "$backup_destination/temporal.sql"
docker compose run --rm --no-deps api tar -C /data -cf - . > "$backup_destination/media.tar"
cp .env "$backup_destination/environment.env"
sha256sum "$backup_destination/application.dump" "$backup_destination/temporal.sql" "$backup_destination/media.tar" "$backup_destination/environment.env" > "$backup_destination/SHA256SUMS"
printf 'Backup saved to %s. Encrypt it before copying off-host.\n' "$backup_destination"
backup_complete=true
