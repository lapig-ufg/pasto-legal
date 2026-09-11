"""Transcrição de áudio na ingestão (Speech-to-Text) — issue #125.

Converte o áudio recebido em texto uma única vez, na entrada, para que os
agentes recebam texto simples em vez de mídia crua.

Interface externa:
    transcrever_audio(audios) -- transcreve áudio(s) para texto (vazio se não houver).
"""

from agno.agent import Agent

from app.configs.config import config


def transcrever_audio(audios: list) -> str:
    """Transcreve áudio(s) para texto com o modelo configurado. Vazio se não houver áudio."""
    if not audios:
        return ""
    transcritor = Agent(
        model=config.model,
        instructions=(
            "Transcreva o áudio para texto em português, exatamente como foi falado. "
            "Responda apenas com a transcrição, sem comentários."
        ),
        markdown=False,
    )
    try:
        resposta = transcritor.run("Transcreva o áudio.", audio=audios)
        return resposta.content or ""
    except Exception:
        return ""