import argparse
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

DENUE_CSV_COLUMNS = (
    "id", "clee", "nom_estab", "raz_social", "codigo_act", "nombre_act", "per_ocu",
    "tipo_vial", "nom_vial", "tipo_v_e_1", "nom_v_e_1", "tipo_v_e_2", "nom_v_e_2",
    "tipo_v_e_3", "nom_v_e_3", "numero_ext", "letra_ext", "edificio", "edificio_e",
    "numero_int", "letra_int", "tipo_asent", "nomb_asent", "tipocencom", "nom_cencom",
    "num_local", "cod_postal", "cve_ent", "entidad", "cve_mun", "municipio", "cve_loc",
    "localidad", "ageb", "manzana", "telefono", "correoelec", "www", "tipounieco",
    "latitud", "longitud", "fecha_alta",
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path)
    parser.add_argument("--truncate", action="store_true")
    args = parser.parse_args()

    dsn = os.getenv("ETL_DATABASE_URL", "postgresql://postgres:postgres@localhost:5434/sae_cdmx")
    columns = ", ".join(DENUE_CSV_COLUMNS)

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            if args.truncate:
                cur.execute("TRUNCATE denue_raw")
            with args.csv.open("rb") as f:
                with cur.copy(
                    f"COPY denue_raw ({columns}) FROM STDIN "
                    "WITH (FORMAT CSV, HEADER TRUE, ENCODING 'LATIN1')"
                ) as copy:
                    while data := f.read(1024 * 1024):
                        copy.write(data)
        conn.commit()
    print(f"Carga terminada: {args.csv}")


if __name__ == "__main__":
    main()
