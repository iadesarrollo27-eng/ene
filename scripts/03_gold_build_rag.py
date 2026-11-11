"""
GOLD: arma un documento por acrónimo (juntando todos sus significados de todas
las fuentes), genera su embedding con Vertex AI y lo guarda en:

    gold.acronimos_rag(
        acronimo STRING, significados ARRAY<STRING>, categorias ARRAY<STRING>,
        fuentes ARRAY<STRING>, contenido STRING, embedding ARRAY<FLOAT64>,
        modelo_embedding STRING, actualizado_en TIMESTAMP
    )

`contenido` es el texto que se le pasa al LLM como contexto.
`embedding` se usa con VECTOR_SEARCH desde n8n.

Uso:
    python scripts/03_gold_build_rag.py
    python scripts/03_gold_build_rag.py --no-embeddings   # sólo texto (para probar)
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
from datetime import datetime, timezone

import config as cfg


def build_documents(rows) -> list[dict]:
    docs: "OrderedDict[str, dict]" = OrderedDict()
    for r in rows:
        d = docs.setdefault(
            r["acronimo"],
            {"acronimo": r["acronimo"], "entradas": [], "_seen": set(), "categorias": [], "fuentes": []},
        )
        key = ((r["significado"] or "").lower(), (r["descripcion"] or "").lower())
        if key not in d["_seen"]:
            d["_seen"].add(key)
            d["entradas"].append(r)
        for field, value in (("categorias", r["categoria"]), ("fuentes", r["fuente"])):
            if value and value not in d[field]:
                d[field].append(value)

    out = []
    for d in docs.values():
        lines = [f"Acrónimo: {d['acronimo']}"]
        significados = []
        for e in d["entradas"]:
            if e["significado"] and e["significado"] not in significados:
                significados.append(e["significado"])
            line = f"- Significado: {e['significado'] or '(sin significado registrado)'}"
            if e["categoria"]:
                line += f" | Categoría: {e['categoria']}"
            if e["descripcion"]:
                line += f" | Descripción: {e['descripcion']}"
            if e["info_adicional"]:
                line += f" | {e['info_adicional']}"
            lines.append(line)
        out.append(
            {
                "acronimo": d["acronimo"],
                "significados": significados,
                "categorias": d["categorias"],
                "fuentes": d["fuentes"],
                "contenido": "\n".join(lines),
            }
        )
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-embeddings", action="store_true")
    args = ap.parse_args()

    from google.cloud import bigquery

    bq = cfg.bq_client()
    rows = list(
        bq.query(
            f"""SELECT acronimo, significado, descripcion, categoria, info_adicional, fuente
                FROM `{cfg.SILVER_TABLE}` ORDER BY acronimo, fuente, fila_origen"""
        ).result()
    )
    docs = build_documents(rows)
    print(f"{len(rows)} filas silver -> {len(docs)} documentos")

    if args.no_embeddings:
        vectors = [[] for _ in docs]
        model = None
    else:
        print(f"Generando embeddings con {cfg.EMBEDDING_MODEL} ({cfg.EMBEDDING_DIM} dims)...")
        vectors = cfg.embed_texts(cfg.genai_client(), [d["contenido"] for d in docs], "RETRIEVAL_DOCUMENT")
        model = cfg.EMBEDDING_MODEL

    now = datetime.now(timezone.utc).isoformat()
    for d, v in zip(docs, vectors):
        d.update(embedding=list(v), modelo_embedding=model, actualizado_en=now)

    schema = [
        bigquery.SchemaField("acronimo", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("significados", "STRING", mode="REPEATED"),
        bigquery.SchemaField("categorias", "STRING", mode="REPEATED"),
        bigquery.SchemaField("fuentes", "STRING", mode="REPEATED"),
        bigquery.SchemaField("contenido", "STRING"),
        bigquery.SchemaField("embedding", "FLOAT64", mode="REPEATED"),
        bigquery.SchemaField("modelo_embedding", "STRING"),
        bigquery.SchemaField("actualizado_en", "TIMESTAMP"),
    ]
    bq.create_dataset(bigquery.Dataset(f"{cfg.PROJECT_ID}.{cfg.DS_GOLD}"), exists_ok=True)
    bq.load_table_from_json(
        docs,
        cfg.GOLD_TABLE,
        job_config=bigquery.LoadJobConfig(
            schema=schema,
            write_disposition="WRITE_TRUNCATE",
            clustering_fields=["acronimo"],
        ),
    ).result()
    print(f"OK {cfg.GOLD_TABLE}: {bq.get_table(cfg.GOLD_TABLE).num_rows} filas")


if __name__ == "__main__":
    main()
