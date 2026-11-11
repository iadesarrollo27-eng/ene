"""
Prueba la recuperación igual que lo hará n8n:
  1) búsqueda exacta por acrónimo (si la pregunta contiene uno)
  2) búsqueda semántica con VECTOR_SEARCH

Uso:
    python scripts/04_test_rag.py "¿Qué significa AAD?"
    python scripts/04_test_rag.py "indicador de consumo de diésel" --top-k 5
"""
from __future__ import annotations

import argparse
import re

import config as cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pregunta")
    ap.add_argument("--top-k", type=int, default=5)
    args = ap.parse_args()

    from google.cloud import bigquery

    bq = cfg.bq_client()

    # 1) Exacto: tokens en mayúsculas tipo "AAD", "%DIMA", "CYM"
    tokens = sorted({t.upper() for t in re.findall(r"%?[A-Za-z0-9]{2,10}", args.pregunta)})
    exact = list(
        bq.query(
            f"SELECT acronimo, contenido FROM `{cfg.GOLD_TABLE}` WHERE acronimo IN UNNEST(@tokens)",
            job_config=bigquery.QueryJobConfig(
                query_parameters=[bigquery.ArrayQueryParameter("tokens", "STRING", tokens)]
            ),
        ).result()
    )
    print("=== Coincidencia exacta ===")
    for r in exact:
        print(r["contenido"], "\n")
    if not exact:
        print("(ninguna)\n")

    # 2) Semántico
    [qvec] = cfg.embed_texts(cfg.genai_client(), [args.pregunta], "RETRIEVAL_QUERY")
    sql = f"""
    SELECT base.acronimo, base.contenido, distance
    FROM VECTOR_SEARCH(
      TABLE `{cfg.GOLD_TABLE}`, 'embedding',
      (SELECT @qvec AS embedding),
      top_k => @k, distance_type => 'COSINE')
    ORDER BY distance
    """
    res = bq.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("qvec", "FLOAT64", list(qvec)),
                bigquery.ScalarQueryParameter("k", "INT64", args.top_k),
            ]
        ),
    ).result()
    print("=== Búsqueda semántica ===")
    for r in res:
        print(f"[{r['distance']:.4f}] {r['contenido']}\n")


if __name__ == "__main__":
    main()
