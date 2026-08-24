#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ne 1 ]; then echo "Uso: scripts/restore.sh backups/archivo.dump"; exit 1; fi
cat "$1" | docker compose exec -T db pg_restore -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-sae_cdmx}" --clean --if-exists --no-owner
