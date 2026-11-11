"""Configuración compartida: lee .env y crea clientes de BigQuery / Vertex AI."""
from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2 import service_account

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


def env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.getenv(name, default)
    if value is not None:
        value = value.strip()
    if required and not value:
        raise SystemExit(f"[config] Falta la variable {name} en .env")
    return value or default


PROJECT_ID = env("GCP_PROJECT_ID", required=True)
BQ_LOCATION = env("BQ_LOCATION", "US")
DS_BRONZE = env("BQ_DATASET_BRONZE", "bronze")
DS_SILVER = env("BQ_DATASET_SILVER", "silver")
DS_GOLD = env("BQ_DATASET_GOLD", "gold")

VERTEX_LOCATION = env("VERTEX_LOCATION", "us-central1")
EMBEDDING_MODEL = env("EMBEDDING_MODEL", "text-multilingual-embedding-002")
EMBEDDING_DIM = int(env("EMBEDDING_DIM", "768"))
EMBEDDING_BATCH_SIZE = int(env("EMBEDDING_BATCH_SIZE", "50"))

_data_dir = Path(env("DATA_DIR", "."))
DATA_DIR = _data_dir if _data_dir.is_absolute() else (ROOT / _data_dir)

# Nombres de tablas
SILVER_TABLE = f"{PROJECT_ID}.{DS_SILVER}.acronimos"
GOLD_TABLE = f"{PROJECT_ID}.{DS_GOLD}.acronimos_rag"


def _load_credentials(json_var: str, file_var: str):
    raw = env(json_var)
    if raw:
        return service_account.Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    path = env(file_var)
    if path:
        p = Path(path)
        p = p if p.is_absolute() else ROOT / p
        if p.exists():
            return service_account.Credentials.from_service_account_file(str(p), scopes=SCOPES)
        print(f"[config] Aviso: {file_var}={path} no existe.")
    return None


def bq_credentials():
    creds = _load_credentials("GCP_SA_BIGQUERY_JSON", "GCP_SA_BIGQUERY_FILE")
    if creds is None:
        raise SystemExit("[config] Configura GCP_SA_BIGQUERY_FILE o GCP_SA_BIGQUERY_JSON en .env")
    return creds


def vertex_credentials():
    # Si no hay cuenta específica de Vertex, reutiliza la de BigQuery
    return _load_credentials("GCP_SA_VERTEX_JSON", "GCP_SA_VERTEX_FILE") or bq_credentials()


def bq_client():
    from google.cloud import bigquery

    return bigquery.Client(project=PROJECT_ID, credentials=bq_credentials(), location=BQ_LOCATION)


def genai_client():
    from google import genai

    return genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location=VERTEX_LOCATION,
        credentials=vertex_credentials(),
    )


def slugify(text: str) -> str:
    """'Indicador (KPI's)' -> 'indicador_kpis'  |  'Acrónimo' -> 'acronimo'"""
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    text = re.sub(r"[^0-9a-zA-Z]+", "_", text.replace("'", "")).strip("_").lower()
    if not text or text[0].isdigit():
        text = f"c_{text}"
    return text


def embed_texts(client, texts: list[str], task_type: str) -> list[list[float]]:
    """Genera embeddings con Vertex AI. task_type: RETRIEVAL_DOCUMENT o RETRIEVAL_QUERY."""
    from google.genai import types

    out: list[list[float]] = []
    for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[i : i + EMBEDDING_BATCH_SIZE]
        resp = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=batch,
            config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=EMBEDDING_DIM),
        )
        out.extend(e.values for e in resp.embeddings)
        print(f"  embeddings {min(i + EMBEDDING_BATCH_SIZE, len(texts))}/{len(texts)}")
    return out
