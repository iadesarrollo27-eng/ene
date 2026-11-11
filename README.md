# Acrónimos → BigQuery (bronze)

Sube cada `.xlsx` / `.csv` de `DATA_DIR` a una tabla en el dataset `bronze`
(una tabla por archivo, todas las columnas como STRING, nombres sin acentos ni espacios,
más columnas de linaje `_source_file`, `_sheet`, `_row_number`, `_ingested_at`).
El tratamiento posterior de los datos se hace en n8n.

## Configuración
1. Copia el JSON de la cuenta de servicio a `credentials/` y pon la ruta en `.env`.
2. Permisos de la cuenta: `BigQuery Data Editor` + `BigQuery Job User`.
3. Instala dependencias:
   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

## Ejecución
```powershell
python scripts/01_bronze_load.py --dry-run   # ver qué se va a subir
python scripts/01_bronze_load.py
```
Usa `WRITE_TRUNCATE`: re-ejecutarlo reemplaza las tablas, no duplica.
