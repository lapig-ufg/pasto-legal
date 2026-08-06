"""
Tool-RAG Router — FAISS-powered tool selection for Pasto Legal.

Embeds all tool schemas into an in-memory FAISS index. For each user prompt,
runs cosine similarity search to find the top-K most relevant tools.

Enables:
- Zero Prompt Bloat: only relevant tool names passed to the LLM
- Deterministic RPC Execution: same prompt → same tools
- Fail-safe: always-available tools included regardless of similarity
"""
import logging
import numpy as np
from fastembed import TextEmbedding

from agent.registry import TOOLS, ALWAYS_AVAILABLE

log = logging.getLogger("pasto-legal.tool_rag")

# ── Embedding model (lazy-loaded) ────────────────────────────────────────

_model: TextEmbedding | None = None


def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        log.info("[tool-rag] loading embedding model BAAI/bge-small-en-v1.5 ...")
        _model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
        log.info("[tool-rag] model loaded")
    return _model


# ── FAISS index (built once) ──────────────────────────────────────────────

_index: "faiss.IndexFlatIP | None" = None
_tool_names: list[str] = []
_embeddings: np.ndarray | None = None


def _build_index() -> None:
    """Build FAISS index from tool schemas (idempotent)."""
    global _index, _tool_names, _embeddings
    if _index is not None:
        return

    import faiss

    model = _get_model()
    texts = [f"{t['name']}: {t['description']}" for t in TOOLS]
    _tool_names = [t["name"] for t in TOOLS]

    log.info(f"[tool-rag] embedding {len(texts)} tool schemas ...")
    embeddings_list = list(model.embed(texts))
    _embeddings = np.array(embeddings_list, dtype=np.float32)

    # Normalize for cosine similarity (inner product on normalized vectors)
    norms = np.linalg.norm(_embeddings, axis=1, keepdims=True)
    _embeddings = _embeddings / norms

    dim = _embeddings.shape[1]
    _index = faiss.IndexFlatIP(dim)
    _index.add(_embeddings)
    log.info(f"[tool-rag] FAISS index built  dim={dim}  tools={len(_tool_names)}")


# ── Public API ────────────────────────────────────────────────────────────

def search_tools(
    query: str,
    top_k: int = 5,
    min_similarity: float = 0.3,
    recent_queries: list[str] | None = None,
) -> list[str]:
    """Find the top-K most relevant tools for a user prompt.

    Args:
        query: The user's current message text.
        top_k: Maximum number of tools to return.
        min_similarity: Minimum cosine similarity threshold (0-1).
        recent_queries: Last N user messages for context (default: None).

    Returns:
        List of tool names, ordered by relevance (most relevant first).
        Always includes ALWAYS_AVAILABLE tools.
    """
    _build_index()

    # Build context-aware query: current message + recent history
    parts = [query]
    if recent_queries:
        parts.extend(recent_queries[-3:])  # Last 3 messages for context
    context_query = " ".join(parts)

    model = _get_model()
    query_vec = np.array(list(model.embed([context_query])), dtype=np.float32)
    query_vec = query_vec / np.linalg.norm(query_vec, axis=1, keepdims=True)

    scores, indices = _index.search(query_vec, min(top_k, len(_tool_names)))

    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0 or idx >= len(_tool_names):
            continue
        if float(score) < min_similarity:
            continue
        results.append(_tool_names[idx])

    # Add always-available tools (deduplicated, at the end)
    for t in ALWAYS_AVAILABLE:
        if t not in results:
            results.append(t)

    log.info(
        f"[tool-rag] query={query[:80]!r}  "
        f"history={len(recent_queries or [])}  "
        f"top_k={top_k}  min_sim={min_similarity}  "
        f"found={len(results)}  tools={results[:5]}"
    )
    return results


def get_tool_descriptions(tool_names: list[str]) -> str:
    """Build a compact tool reference string for the LLM prompt.

    Only includes the tools that were selected by RAG, reducing prompt bloat.
    """
    name_to_desc = {t["name"]: t["description"] for t in TOOLS}
    lines = []
    for name in tool_names:
        desc = name_to_desc.get(name, "")
        lines.append(f"- `{name}`: {desc}")
    return "\n".join(lines)
