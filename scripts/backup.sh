#!/usr/bin/env bash
set -euo pipefail
mkdir -p backups
STAMP=$(date +%Y%m%d_%H%M%S)
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-sae_cdmx}" -Fc > "backups/sae_cdmx_${STAMP}.dump"
echo "Backup creado: backups/sae_cdmx_${STAMP}.dump"
