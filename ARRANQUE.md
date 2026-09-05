# Arranque de Py_LastRAG_Index_v2_triple

Este documento proporciona las instrucciones completas para arrancar la versión con índice y motor triple simultáneo (vectorial, estructural y de grafo).

## 1. Requisitos Previos

- Python 3.10+
- Base de datos de grafos Neo4j (local o en la nube)
- API Key de Gemini configurada (`GOOGLE_API_KEY`)
- Credenciales de Neo4j (`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`)

## 2. Instalación del Entorno

```bash
# 1. Crear entorno virtual
python -m venv .venv
source .venv/bin/activate  # En Windows: .venv\Scripts\activate

# 2. Instalar dependencias
pip install -e .
```

## 3. Configuración del Entorno (.env)

Copiar el archivo de ejemplo y configurar las variables:

```bash
cp .env.example .env
```

Asegúrate de llenar en el archivo `.env`:
- `GOOGLE_API_KEY=tu_api_key_aqui`
- `LASTRAG_GEN_MODEL=gemini-2.5-flash`
- (Opcional, para Neo4j)
  - `NEO4J_URI=bolt://localhost:7687`
  - `NEO4J_USER=neo4j`
  - `NEO4J_PASSWORD=tu_password`

## 4. Ejecución del Servidor (Frontend y Backend)

El sistema arranca de manera unificada mediante `app.py`, levantando el servidor FastAPI y exponiendo el frontend.

```bash
source .venv/bin/activate
python app.py
```

El servidor estará disponible en `http://localhost:8000`.

## 5. Pruebas y Validación (Humo)

Puedes correr el test de humo integrado para asegurar que el motor triple responde como se espera:

```bash
pytest tests/test_smoke.py -v
```

## Notas sobre la arquitectura "Triple Simultáneo"

El motor (`core/rag/engine.py`) ahora ejecuta de manera paralela las consultas usando `asyncio.gather` para:
- Búsqueda Vectorial (Gemini o Qdrant)
- Búsqueda Estructural (Índice en Neo4j)
- Contexto de Grafo de Relaciones Médicas

Esto acelera los tiempos de respuesta e inyecta todo el conocimiento de la base documental antes de llamar al LLM final.
