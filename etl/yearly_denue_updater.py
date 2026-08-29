from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import psycopg
from dotenv import load_dotenv

from update_denue_api import SOURCE_NAME, SyncConfig, ensure_schema, run_sync

load_dotenv()


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def _last_success(database_url: str):
    with psycopg.connect(database_url) as conn:
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT last_success_at FROM denue_sync_state WHERE source = %s",
                (SOURCE_NAME,),
            )
            row = cur.fetchone()
            return row[0] if row else None


def main() -> None:
    enabled = _bool_env("DENUE_AUTO_UPDATE", True)
    check_hours = max(1, int(os.getenv("DENUE_CHECK_INTERVAL_HOURS", "24")))
    interval_days = max(1, int(os.getenv("DENUE_UPDATE_INTERVAL_DAYS", "365")))

    print(
        f"[DENUE-SCHEDULER] auto_update={enabled}, intervalo={interval_days} días, "
        f"revisión={check_hours} h."
    )

    while True:
        try:
            config = SyncConfig.from_env()
            if not enabled:
                print("[DENUE-SCHEDULER] Actualización automática deshabilitada.")
            elif not config.token:
                print("[DENUE-SCHEDULER] DENUE_TOKEN no configurado; esperando configuración.")
            else:
                last_success = _last_success(config.database_url)
                now = datetime.now(timezone.utc)
                due = last_success is None or now - last_success >= timedelta(days=interval_days)

                if due:
                    if last_success is None:
                        print("[DENUE-SCHEDULER] No existe sincronización previa; se ejecutará ahora.")
                    else:
                        print(
                            "[DENUE-SCHEDULER] La última sincronización ya superó el intervalo; "
                            "se ejecutará ahora."
                        )
                    run_sync(config)
                else:
                    next_due = last_success + timedelta(days=interval_days)
                    print(
                        f"[DENUE-SCHEDULER] Sincronización al día. Próxima fecha mínima: "
                        f"{next_due.isoformat(timespec='seconds')}."
                    )
        except Exception as exc:
            print(f"[DENUE-SCHEDULER] Error: {exc}")

        time.sleep(check_hours * 3600)


if __name__ == "__main__":
    main()
