-- =====================================================================
--  Consultas para el nodo "Google BigQuery" de n8n
--  Tabla: `data-lakehouse-494719.gold.acronimos_rag`
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1) Búsqueda EXACTA por acrónimo (rápida, sin embeddings)
--    En n8n reemplaza {{ $json.acronimo }} por la expresión que extrae el acrónimo.
-- ---------------------------------------------------------------------
SELECT acronimo, significados, categorias, contenido
FROM `data-lakehouse-494719.gold.acronimos_rag`
WHERE acronimo = UPPER(TRIM('{{ $json.acronimo }}'));


-- ---------------------------------------------------------------------
-- 2) Búsqueda SEMÁNTICA (RAG)
--    Paso previo en n8n: nodo HTTP Request a Vertex AI para obtener el
--    embedding de la pregunta (con el MISMO modelo que usó 03_gold_build_rag.py):
--
--    POST https://us-central1-aiplatform.googleapis.com/v1/projects/data-lakehouse-494719/locations/us-central1/publishers/google/models/text-multilingual-embedding-002:predict
--    Auth: credencial "Google Service Account" (scope https://www.googleapis.com/auth/cloud-platform)
--    Body:
--      {
--        "instances": [{ "content": "{{ $json.pregunta }}", "task_type": "RETRIEVAL_QUERY" }],
--        "parameters": { "outputDimensionality": 768 }
--      }
--    Respuesta: predictions[0].embeddings.values  -> arreglo de 768 números
--
--    Luego en el nodo BigQuery:
-- ---------------------------------------------------------------------
SELECT
  base.acronimo,
  base.contenido,
  distance
FROM VECTOR_SEARCH(
  TABLE `data-lakehouse-494719.gold.acronimos_rag`,
  'embedding',
  (SELECT [{{ $json.predictions[0].embeddings.values.join(',') }}] AS embedding),
  top_k => 5,
  distance_type => 'COSINE'
)
ORDER BY distance;


-- ---------------------------------------------------------------------
-- 3) Híbrida: exacta primero y, si no hay, semántica (una sola consulta)
-- ---------------------------------------------------------------------
WITH exacta AS (
  SELECT acronimo, contenido, 0.0 AS distance
  FROM `data-lakehouse-494719.gold.acronimos_rag`
  WHERE acronimo IN UNNEST(REGEXP_EXTRACT_ALL(UPPER('{{ $json.pregunta }}'), r'%?[A-Z0-9ÁÉÍÓÚÑ]{2,10}'))
),
semantica AS (
  SELECT base.acronimo, base.contenido, distance
  FROM VECTOR_SEARCH(
    TABLE `data-lakehouse-494719.gold.acronimos_rag`, 'embedding',
    (SELECT [{{ $json.predictions[0].embeddings.values.join(',') }}] AS embedding),
    top_k => 5, distance_type => 'COSINE')
)
SELECT * FROM exacta
UNION ALL
SELECT * FROM semantica WHERE acronimo NOT IN (SELECT acronimo FROM exacta)
ORDER BY distance
LIMIT 5;
