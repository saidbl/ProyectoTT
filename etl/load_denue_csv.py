"""Carga inicial de un CSV DENUE a denue_raw.

Primera etapa deliberadamente conservadora: preserva el archivo plano para que la
normalización posterior sea reproducible y auditable.
"""
import argparse
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path)
    parser.add_argument("--truncate", action="store_true")
    args = parser.parse_args()

    dsn = os.getenv("ETL_DATABASE_URL", "postgresql://postgres:postgres@localhost:5434/sae_cdmx")
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            if args.truncate:
                cur.execute("TRUNCATE denue_raw")
            with args.csv.open("rb") as f:
                with cur.copy("COPY denue_raw FROM STDIN WITH (FORMAT CSV, HEADER TRUE, ENCODING 'LATIN1')") as copy:
                    while data := f.read(1024 * 1024):
                        copy.write(data)
        conn.commit()
    print(f"Carga terminada: {args.csv}")


if __name__ == "__main__":
    main()
