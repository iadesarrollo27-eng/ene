"""
SILVER: unifica todas las tablas de bronze en una sola tabla con esquema común.

    silver.acronimos(
        acronimo, significado, descripcion, categoria, info_adicional,
        fuente, fila_origen, actualizado_en
    )

Las columnas de cada tabla bronze se detectan por nombre (ver COLUMN_RULES),
así que si agregas otro Excel con columnas parecidas no hay que tocar código.
Las columnas que no encajan se concatenan en `info_adicional`.

Uso:
    python scripts/02_silver_build.py             # crea/reemplaza la tabla
    python scripts/02_silver_build.py --print-sql # sólo imprime el SQL
"""
from __future__ import annotations

import argparse

import config as cfg

# campo destino -> fragmentos que identifican la columna en bronze (en orden de prioridad)
COLUMN_RULES = {
    "acronimo": ["acronimo", "sigla"],
    "significado": ["significado", "indicador", "nombre"],
    "descripcion": ["descripcion", "definicion"],
    "categoria": ["agrupador", "areadpto", "area", "categoria", "tipo"],
}

# Categoría por defecto cuando la tabla no trae columna de categoría (por nombre de tabla)
DEFAULT_CATEGORY = {
    "acronimos_kpi": "Indicadores o KPI's",
}


def map_columns(columns: list[str]) -> tuple[dict[str, str | None], list[str]]:
    data_cols = [c for c in columns if not c.startswith("_")]
    used: set[str] = set()
    mapping: dict[str, str | None] = {}
    for target, keys in COLUMN_RULES.items():
        mapping[target] = None
        for key in keys:
            match = next((c for c in data_cols if key in c and c not in used), None)
            if match:
                mapping[target] = match
                used.add(match)
                break
    extras = [c for c in data_cols if c not in used]
    return mapping, extras


def q(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def select_for_table(table) -> str | None:
    cols = [f.name for f in table.schema]
    mapping, extras = map_columns(cols)
    if not mapping["acronimo"]:
        print(f"  ! {table.table_id}: sin columna de acrónimo, se omite")
        return None

    def col(target):
        c = mapping[target]
        return f"NULLIF(TRIM(`{c}`), '')" if c else "CAST(NULL AS STRING)"

    categoria = col("categoria")
    default = DEFAULT_CATEGORY.get(table.table_id)
    if default:
        categoria = f"COALESCE({categoria}, {q(default)})"

    if extras:
        desc = mapping["descripcion"]

        def extra_expr(c: str) -> str:
            # omite valores vacíos o que sólo repiten la descripción
            skip = f"`{c}` IS NULL OR TRIM(`{c}`) = ''"
            if desc:
                skip += f" OR TRIM(`{c}`) = TRIM(COALESCE(`{desc}`, ''))"
            return f"IF({skip}, NULL, CONCAT({q(c)}, ': ', TRIM(`{c}`)))"

        parts = ", ".join(extra_expr(c) for c in extras)
        info = f"NULLIF(ARRAY_TO_STRING([{parts}], ' | '), '')"
    else:
        info = "CAST(NULL AS STRING)"

    print(f"  {table.table_id}: {mapping} extras={extras}")
    return f"""
  SELECT
    UPPER(TRIM(`{mapping['acronimo']}`)) AS acronimo,
    {col('significado')} AS significado,
    {col('descripcion')} AS descripcion,
    {categoria} AS categoria,
    {info} AS info_adicional,
    {q(table.table_id)} AS fuente,
    _row_number AS fila_origen
  FROM `{table.project}.{table.dataset_id}.{table.table_id}`
  WHERE TRIM(COALESCE(`{mapping['acronimo']}`, '')) != ''"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--print-sql", action="store_true")
    args = ap.parse_args()

    from google.cloud import bigquery

    client = cfg.bq_client()
    selects = []
    for item in client.list_tables(f"{cfg.PROJECT_ID}.{cfg.DS_BRONZE}"):
        sel = select_for_table(client.get_table(item.reference))
        if sel:
            selects.append(sel)
    if not selects:
        raise SystemExit("No hay tablas en bronze. Ejecuta primero 01_bronze_load.py")

    sql = f"""
CREATE OR REPLACE TABLE `{cfg.SILVER_TABLE}`
CLUSTER BY acronimo
OPTIONS(description = 'Acrónimos unificados desde bronze')
AS
WITH unioned AS ({' UNION ALL '.join(selects)}
)
SELECT
  *,
  CURRENT_TIMESTAMP() AS actualizado_en
FROM unioned
-- elimina duplicados exactos dentro de la misma fuente
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY fuente, acronimo, LOWER(COALESCE(significado, '')), LOWER(COALESCE(descripcion, ''))
  ORDER BY fila_origen
) = 1
"""
    if args.print_sql:
        print(sql)
        return

    client.create_dataset(bigquery.Dataset(f"{cfg.PROJECT_ID}.{cfg.DS_SILVER}"), exists_ok=True)
    client.query(sql).result()
    t = client.get_table(cfg.SILVER_TABLE)
    print(f"OK {cfg.SILVER_TABLE}: {t.num_rows} filas")


if __name__ == "__main__":
    main()
