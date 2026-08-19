"""Vector knowledge base for the Pasto Legal single agent.

Indexes the project's markdown documentation under ``docs/knowledge`` into a
vector database so the agent can retrieve relevant excerpts on demand (via the
``search_knowledge_base`` tool auto-injected by Agno) instead of stuffing the
full text into the context window.

Stack:
    * Embedder: ``GeminiEmbedder`` (``gemini-embedding-001``, 1536-dim) reusing
      ``config.GOOGLE_API_KEY``.
    * Vector DB: ``PgVector`` against a **dedicated Postgres database** described
      by the ``PGVECTOR_*`` env vars (separate from the operational ``POSTGRES_*``
      db used by Agno's session store). The ``vector`` extension is created
      automatically on bootstrap.
    * Dev fallback: when ``DATABASE_TYPE == 'sqlite'`` or no ``PGVECTOR_HOST`` is
      configured, a local persistent ``ChromaDb`` under ``tmp/chromadb_pasto_legal``
      is used so development keeps working without a Postgres instance.

External interface:
    pasto_legal_kb  -- the ``Knowledge`` singleton imported by
                       ``app.agents.single_agent``.
"""
import hashlib
from pathlib import Path
from typing import Any

from agno.knowledge.chunking.recursive import RecursiveChunking
from agno.knowledge.embedder.google import GeminiEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.utils.log import log_debug, log_error
from agno.vectordb.chroma import ChromaDb
from agno.vectordb.distance import Distance
from agno.vectordb.pgvector import PgVector
from sqlalchemy import create_engine, select, text

from app.configs.config import config

# ---
# Embedder (shared by both vector backends)
# ---
_embedder = GeminiEmbedder(
    id="gemini-embedding-001",
    api_key=config.GOOGLE_API_KEY,
)

# ---
# Chunking strategy: recursive, mid-size chunks for PT-BR markdown manuals
# ---
_chunking = RecursiveChunking(chunk_size=1000, overlap=100)

# ---
# Vector DB selection
# ---
_table_name = "pasto_legal_kb"
_schema = "ai"
_kb_dir = Path.cwd() / "docs" / "knowledge"
_excluded_files = {"termos_de_uso.md"}


def _build_pgvector() -> PgVector:
    """Build a PgVector backed by the dedicated PGVECTOR_* Postgres database.

    Ensures the ``vector`` extension exists on the target database before
    handing the engine over to PgVector (which expects it).
    """
    db_url = (
        f"postgresql+psycopg://{config.PGVECTOR_USER}:{config.PGVECTOR_PASSWORD}"
        f"@{config.PGVECTOR_HOST}:{config.PGVECTOR_PORT}/{config.PGVECTOR_DBNAME}"
    )
    engine = create_engine(db_url, pool_pre_ping=True)

    # Bootstrap the vector extension on the dedicated KB database.
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            conn.commit()
    except Exception as exc:
        log_error(f"pasto_legal_kb: failed to create 'vector' extension: {exc}")

    return PgVector(
        table_name=_table_name,
        schema=_schema,
        db_engine=engine,
        embedder=_embedder,
        distance=Distance.cosine,
    )


def _build_chroma() -> ChromaDb:
    """Build a local persistent ChromaDb for development without Postgres."""
    persist_path = Path.cwd() / "tmp" / "chromadb_pasto_legal"
    persist_path.mkdir(parents=True, exist_ok=True)

    return ChromaDb(
        collection="pasto_legal_kb",
        path=str(persist_path),
        persistent_client=True,
        embedder=_embedder,
        distance=Distance.cosine,
    )


def _select_vector_db() -> Any:
    """Pick PgVector when configured, otherwise fall back to ChromaDb."""
    use_pgvector = (
        config.DATABASE_TYPE != "sqlite"
        and bool(config.PGVECTOR_HOST)
        and bool(config.PGVECTOR_DBNAME)
        and bool(config.PGVECTOR_USER)
    )
    if use_pgvector:
        try:
            return _build_pgvector()
        except Exception as exc:
            log_error(f"pasto_legal_kb: PgVector setup failed, falling back to ChromaDb: {exc}")
    return _build_chroma()


vector_db = _select_vector_db()

pasto_legal_kb = Knowledge(
    name="Pasto Legal KB",
    description=(
        "Manuais e documentação técnica do Pasto Legal. Use para responder relaciondas a plataforma"
    ),
    vector_db=vector_db,
    max_results=3
)


def _index_documents() -> None:
    """Synchronize the KB with the markdown files currently in ``docs/knowledge``.

    Identity is the sha256 of each file's content (stored as the
    ``source_content_hash`` metadata field on every chunk). On every startup:

        1. Build ``current_hashes`` from the markdown files on disk.
        2. Read ``db_hashes`` already indexed in the vector DB (via the
           ``source_content_hash`` metadata field).
        3. Drop DB entries whose hash is no longer on disk (handles edits and
           deletions; renames with unchanged content are a no-op).
        4. Insert files whose hash is not yet in the DB.

    Only new/changed files are re-embedded; unchanged files are left alone.
    """
    if not _kb_dir.exists():
        log_error(f"pasto_legal_kb: knowledge directory not found at {_kb_dir}")
        return

    current_hashes: set[str] = set()
    hash_to_path: dict = {}
    for md_file in sorted(_kb_dir.glob("*.md")):
        if md_file.name in _excluded_files:
            continue
        try:
            file_hash = _compute_file_hash(md_file)
        except Exception as exc:
            log_error(f"pasto_legal_kb: failed to hash {md_file.name}: {exc}")
            continue
        current_hashes.add(file_hash)
        hash_to_path[file_hash] = md_file

    db_hashes = _get_indexed_source_hashes()

    for stale_hash in db_hashes - current_hashes:
        try:
            vector_db.delete_by_metadata({"source_content_hash": stale_hash})
            log_debug(f"pasto_legal_kb: dropped stale hash {stale_hash}")
        except Exception as exc:
            log_error(f"pasto_legal_kb: failed to drop stale hash {stale_hash}: {exc}")

    for new_hash in current_hashes - db_hashes:
        md_file = hash_to_path[new_hash]
        try:
            pasto_legal_kb.insert(
                path=str(md_file),
                metadata={"source_content_hash": new_hash},
                skip_if_exists=False,
                upsert=True,
            )
            log_debug(f"pasto_legal_kb: indexed {md_file.name} ({new_hash})")
        except Exception as exc:
            log_error(f"pasto_legal_kb: failed to index {md_file.name}: {exc}")


def _compute_file_hash(path: Path) -> str:
    """Return the first 16 hex chars of the sha256 of a file's content."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _get_indexed_source_hashes() -> set[str]:
    """Return the set of ``source_content_hash`` values currently in the DB.

    Backend-aware: PgVector is queried via SQL on its ``meta_data`` JSONB
    column; ChromaDb is queried via the collection ``get`` API. Returns an
    empty set on any failure (which makes the caller reinsert everything).
    """
    hashes: set[str] = set()
    try:
        if isinstance(vector_db, PgVector):
            with vector_db.Session() as sess:
                stmt = (
                    select(vector_db.table.c.meta_data["source_content_hash"].astext)
                    .where(vector_db.table.c.meta_data["source_content_hash"].isnot(None))
                    .distinct()
                )
                for row in sess.execute(stmt):
                    if row[0] is not None:
                        hashes.add(row[0])
        elif isinstance(vector_db, ChromaDb):
            collection = vector_db.client.get_collection(name=vector_db.collection_name)
            result = collection.get(include=["metadatas"])
            for meta in result.get("metadatas", []) or []:
                value = meta.get("source_content_hash") if meta else None
                if value is not None:
                    hashes.add(value)
    except Exception as exc:
        log_error(f"pasto_legal_kb: failed to read indexed source hashes: {exc}")
    return hashes


_index_documents()