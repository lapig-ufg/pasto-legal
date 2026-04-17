from pathlib import Path

from agno.vectordb.pgvector import PgVector
from agno.vectordb.chroma import ChromaDb
from agno.knowledge.embedder.ollama import OllamaEmbedder

from app.database.session import engine, DATABASE_TYPE


if DATABASE_TYPE == 'sqlite':
    db_path = Path("tmp/chromadb").resolve()
    db_path.mkdir(parents=True, exist_ok=True)

    vector_db = ChromaDb(
        collection="vectors", 
        path=db_path,
        persistent_client=True,
        embedder=OllamaEmbedder(id="qwen3-embedding:8b-q8_0", dimensions=4048)
    )
else:
    vector_db = PgVector(
        table_name="vectors",
        engine=engine
    )
