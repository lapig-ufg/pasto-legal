"""Validação de escopo (Context) (#123)

Decide se o conteúdo tem relação com o Pasto Legal. Se estiver fora, barra com
um aviso que DIZ o assunto detectado.
"""

from pydantic import BaseModel, Field

from agno.agent import Agent

from app.configs.config import config


class ResultadoContexto(BaseModel):
    dentro_do_escopo: bool = Field(
        ...,
        description="True se tem relação com pastagem, solo, gado, fazenda, manejo "
                    "ou agro, OU se é conversa normal (saudação). False só quando é "
                    "claramente outro assunto.",
    )
    assunto: str = Field(
        default="",
        description="Quando FORA do escopo, o assunto detectado em 1-3 palavras "
                    "(ex.: 'carro', 'futebol', 'prédio'). Vazio se dentro do escopo.",
    )


class ContextValidator:
    """Julga UMA vez se o conteúdo está no escopo do Pasto Legal."""

    _INSTRUCOES = (
        "Você decide se a mensagem deve ser atendida pelo Pasto Legal, um "
        "assistente sobre pastagem, solo, gado, fazenda, manejo e agropecuária.\n"
        "DENTRO do escopo: perguntas sobre esses temas E também saudações, "
        "agradecimentos e conversa normal.\n"
        "FORA do escopo (dentro_do_escopo=false) APENAS quando é claramente sem "
        "relação: esportes, política, celebridades, receitas, veículos, etc.\n"
        "Quando estiver FORA, preencha 'assunto' com o tema detectado em 1-3 palavras."
    )

    def __init__(self, *textos: str):
        conteudo = "\n".join(t for t in textos if t)
        self._resultado = self._validar(conteudo)

    def _validar(self, conteudo: str) -> ResultadoContexto:
        if not conteudo.strip():
            return ResultadoContexto(dentro_do_escopo=True)
        try:
            juiz = Agent(
                model=config.model,
                output_schema=ResultadoContexto,
                instructions=self._INSTRUCOES,
                markdown=False,
            )
            resposta = juiz.run(conteudo)
            return resposta.content
        except Exception:
            return ResultadoContexto(dentro_do_escopo=True)  # fail-open

    @property
    def dentro_do_escopo(self) -> bool:
        return self._resultado.dentro_do_escopo

    @property
    def assunto(self) -> str:
        return self._resultado.assunto


def mensagem_fora_escopo(assunto: str = "") -> str:
    """Aviso amigável, citando o assunto detectado quando houver."""
    if assunto:
        return (
            f"🌾 Detectei que sua mensagem é sobre **{assunto}**, que não faz parte "
            "do meu escopo. Consigo te ajudar com pastagem, solo, gado e manejo da "
            "sua propriedade. Pode reformular nesse contexto?"
        )
    return (
        "🌾 Consigo te ajudar com temas da sua propriedade — pastagem, solo, gado e "
        "manejo. Não identifiquei relação com esses assuntos na sua mensagem. "
        "Pode reformular nesse contexto?"
    )