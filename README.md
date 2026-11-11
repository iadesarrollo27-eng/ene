# Acrónimos → BigQuery (bronze / silver / gold) → RAG con n8n

## Archivos de entrada
| Archivo | Columnas | Filas |
|---|---|---|
| acronimos_area_depto.xlsx | Acronimo, Significado, Descripcion, AreaDpto | 33 |
| acronimos_kpi.xlsx | Acrónimo, Indicador (KPI's), Descripción | 226 |
| acronimos_mexamerik.xlsx | Acrónimo, Significado Acrónimo, Descripción, Agrupador | 413 |
| mexamerik.xlsx | Acrónimo, Significado Acrónimo, Descripción, Agrupador, Rango de Gestion | 251 |

## Flujo
```
xlsx ──01──► bronze.<archivo>        (crudo, 1 tabla por archivo, todo STRING + linaje)
     ──02──► silver.acronimos        (esquema único: acronimo, significado, descripcion, categoria, info_adicional, fuente)
     ──03──► gold.acronimos_rag      (1 documento por acrónimo + embedding Vertex AI)
n8n  ──────► gold.acronimos_rag      (búsqueda exacta + VECTOR_SEARCH) ──► LLM responde
```

## Configuración (una sola vez)
1. Copia los JSON de las cuentas de servicio a `credentials/` (ya está en `.gitignore`).
2. Edita `.env` (ya creado a partir de `.env.example`) con las rutas. Si BigQuery y Vertex usan la misma cuenta, deja vacío lo de Vertex.
3. Revisa `BQ_LOCATION`: debe ser la región de los datasets `bronze/silver/gold` (en la consola: dataset → Detalles → Ubicación de los datos).
4. Instala dependencias:
   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

**Permisos necesarios**
- Cuenta BigQuery: `BigQuery Data Editor` + `BigQuery Job User` en el proyecto.
- Cuenta Vertex: `Vertex AI User`.

## Ejecución
```powershell
python scripts/01_bronze_load.py --dry-run   # ver qué se va a subir
python scripts/01_bronze_load.py
python scripts/02_silver_build.py
python scripts/03_gold_build_rag.py
python scripts/04_test_rag.py "¿Qué significa AAD?"
```
Todos los pasos usan `WRITE_TRUNCATE` / `CREATE OR REPLACE`: puedes re-ejecutarlos cuando cambien los Excel.
Para agregar otro archivo, déjalo en la carpeta y vuelve a correr 01→03 (las columnas se detectan por nombre en `02_silver_build.py → COLUMN_RULES`).

## n8n
Ver `sql/n8n_queries.sql`. Flujo sugerido:
1. **Trigger** (Chat / Webhook) con la pregunta.
2. **HTTP Request** → Vertex AI `text-multilingual-embedding-002:predict` (task_type `RETRIEVAL_QUERY`) — **mismo modelo y dimensión que en `.env`**.
3. **Google BigQuery** → consulta híbrida (#3 del archivo SQL).
4. **AI Agent / LLM (Gemini en Vertex)** con prompt tipo:
   > Responde qué significa el acrónimo usando SÓLO este contexto. Si hay varios significados, enuméralos con su categoría. Si no está en el contexto, dilo.
   > Contexto: `{{ $json.contenido }}`
