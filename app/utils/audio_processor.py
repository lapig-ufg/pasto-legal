"""Processamento de áudio na entrada (#123) — transcrição (Speech-to-Text).

Converte o áudio em texto UMA vez, na entrada, para os agentes receberem
texto em vez de mídia crua.
"""

from agno.agent import Agent

from app.configs.config import config


class AudioProcessor:
    """Transcreve o áudio UMA vez e guarda o texto."""

    _INSTRUCOES = (
        "Transcreva o áudio para texto em português, exatamente como foi falado. "
        "Responda apenas com a transcrição, sem comentários."
    )

    def __init__(self, audios: list):
        # A transcrição acontece UMA vez, aqui.
        self._texto = self._transcrever(audios)

    def _transcrever(self, audios: list) -> str:
        if not audios:
            return ""
        transcritor = Agent(
            model=config.model,
            instructions=self._INSTRUCOES,
            markdown=False,
        )
        try:
            resposta = transcritor.run("Transcreva o áudio.", audio=audios)
            return resposta.content or ""
        except Exception:
            return ""

    @property
    def texto(self) -> str:
        return self._texto