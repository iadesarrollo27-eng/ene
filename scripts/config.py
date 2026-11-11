"""Configuración: lee .env y crea el cliente de BigQuery."""
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
    value = (os.getenv(name) or "").strip() or default
    if required and not value:
        raise SystemExit(f"[config] Falta la variable {name} en .env")
    return value


PROJECT_ID = env("GCP_PROJECT_ID", required=True)
DS_BRONZE = env("BQ_DATASET_BRONZE", "bronze")
# Opcional: si se deja vacío se usa la región real del dataset
BQ_LOCATION = env("BQ_LOCATION")

_data_dir = Path(env("DATA_DIR", "."))
DATA_DIR = _data_dir if _data_dir.is_absolute() else (ROOT / _data_dir)


def bq_credentials():
    raw = env("GCP_SA_BIGQUERY_JSON")
    if raw:
        return service_account.Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    path = env("GCP_SA_BIGQUERY_FILE")
    if path:
        p = Path(path)
        p = p if p.is_absolute() else ROOT / p
        if p.exists():
            return service_account.Credentials.from_service_account_file(str(p), scopes=SCOPES)
        raise SystemExit(f"[config] No existe el archivo de credenciales: {p}")
    raise SystemExit("[config] Configura GCP_SA_BIGQUERY_FILE o GCP_SA_BIGQUERY_JSON en .env")


def bq_client(location: str | None = None):
    from google.cloud import bigquery

    return bigquery.Client(project=PROJECT_ID, credentials=bq_credentials(), location=location)


def slugify(text: str) -> str:
    """'Indicador (KPI's)' -> 'indicador_kpis'  |  'Acrónimo' -> 'acronimo'"""
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    text = re.sub(r"[^0-9a-zA-Z]+", "_", text.replace("'", "")).strip("_").lower()
    if not text or text[0].isdigit():
        text = f"c_{text}"
    return text
