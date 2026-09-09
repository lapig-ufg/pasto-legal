"""Pasto Legal knowledge base — a thin factory call into Semente.

The generic machinery (markdown ingestion, content-hash sync, embedder,
PgVector/ChromaDb selection) lives in ``semente.knowledge``.
"""

from semente.knowledge import build_knowledge

pasto_legal_kb = build_knowledge(
    docs_dir="docs/knowledge",
    name="Pasto Legal KB",
    description=(
        "Manuais e documentação técnica do Pasto Legal. Use para responder relaciondas a plataforma"
    ),
    table_name="pasto_legal_kb",
    collection="pasto_legal_kb",
    excluded_files={"termos_de_uso.md"},
)
