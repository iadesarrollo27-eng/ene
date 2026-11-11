"""
BRONZE: sube cada archivo (.xlsx / .csv) de DATA_DIR tal cual a BigQuery.

- Una tabla por archivo (y por hoja si el Excel trae varias): bronze.<nombre_archivo>[__<hoja>]
- Todas las columnas como STRING, nombres normalizados (sin acentos ni espacios).
- Columnas de linaje: _source_file, _sheet, _row_number, _ingested_at.
- WRITE_TRUNCATE: se puede re-ejecutar sin duplicar.

Uso:
    python scripts/01_bronze_load.py            # sube todo
    python scripts/01_bronze_load.py --dry-run  # sólo muestra lo que subiría
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import pandas as pd

import config as cfg


def read_sources():
    files = sorted([*cfg.DATA_DIR.glob("*.xlsx"), *cfg.DATA_DIR.glob("*.csv")])
    files = [f for f in files if not f.name.startswith("~$")]  # archivos temporales de Excel
    if not files:
        raise SystemExit(f"No hay .xlsx/.csv en {cfg.DATA_DIR}")

    for f in files:
        if f.suffix.lower() == ".csv":
            sheets = {"csv": _read_csv(f)}
        else:
            sheets = pd.read_excel(f, sheet_name=None, dtype=str)
        multi = len(sheets) > 1
        for sheet, df in sheets.items():
            table = cfg.slugify(f.stem) + (f"__{cfg.slugify(sheet)}" if multi else "")
            yield f, sheet, table, df


def _read_csv(path):
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(path, dtype=str, encoding=enc, sep=None, engine="python")
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"No se pudo leer {path}")


def clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(how="all")
    df = df.loc[:, [c for c in df.columns if not str(c).startswith("Unnamed")]]
    cols, seen = [], {}
    for c in df.columns:
        s = cfg.slugify(c)
        seen[s] = seen.get(s, 0) + 1
        cols.append(s if seen[s] == 1 else f"{s}_{seen[s]}")
    df.columns = cols
    return df.apply(lambda col: col.map(lambda v: v.strip() if isinstance(v, str) else v))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    client = None
    if not args.dry_run:
        from google.cloud import bigquery

        client = cfg.bq_client()
        client.create_dataset(
            bigquery.Dataset(f"{cfg.PROJECT_ID}.{cfg.DS_BRONZE}"), exists_ok=True
        )

    now = datetime.now(timezone.utc).isoformat()
    for path, sheet, table, df in read_sources():
        df = clean(df)
        rows = []
        for i, rec in enumerate(df.to_dict(orient="records"), start=2):  # fila 1 = encabezado
            row = {k: (None if pd.isna(v) or v == "" else str(v)) for k, v in rec.items()}
            row.update(_source_file=path.name, _sheet=str(sheet), _row_number=i, _ingested_at=now)
            rows.append(row)

        table_id = f"{cfg.PROJECT_ID}.{cfg.DS_BRONZE}.{table}"
        print(f"- {path.name} [{sheet}] -> {table_id}: {len(rows)} filas, columnas {list(df.columns)}")
        if args.dry_run:
            continue

        from google.cloud import bigquery

        schema = [bigquery.SchemaField(c, "STRING") for c in df.columns] + [
            bigquery.SchemaField("_source_file", "STRING"),
            bigquery.SchemaField("_sheet", "STRING"),
            bigquery.SchemaField("_row_number", "INT64"),
            bigquery.SchemaField("_ingested_at", "TIMESTAMP"),
        ]
        job = client.load_table_from_json(
            rows,
            table_id,
            job_config=bigquery.LoadJobConfig(
                schema=schema, write_disposition="WRITE_TRUNCATE"
            ),
        )
        job.result()
        print(f"  OK ({client.get_table(table_id).num_rows} filas en BigQuery)")


if __name__ == "__main__":
    main()
