"""Processamento de imagem na entrada (#123) — OCR + descrição da cena.

Uma ÚNICA passada de VLM extrai o texto visível (OCR) e uma descrição da
imagem. A validação de escopo (é do Pasto Legal?) fica no Context, não aqui.
"""

from pydantic import BaseModel, Field

from agno.agent import Agent

from app.configs.config import config


class LeituraImagem(BaseModel):
    texto_visivel: str = Field(
        default="",
        description="Todo texto legível na imagem (placas, documentos, números), "
                    "exatamente como aparece. Vazio se não houver texto.",
    )
    descricao: str = Field(
        default="",
        description="Descrição técnica da cena: o que é a imagem e o estado da "
                    "pastagem/terreno, se houver.",
    )


class ImageProcessor:
    """Lê a imagem UMA vez e guarda o resultado (texto visível + descrição)."""

    _INSTRUCOES = (
        "Você é o componente visual do Pasto Legal. Para a(s) imagem(ns), faça:\n"
        "1) Extraia TODO texto legível em 'texto_visivel' (placas, documentos, números).\n"
        "2) Gere uma descrição técnica da cena em 'descricao' (o que é, estado da "
        "pastagem/terreno). Seja objetivo."
    )

    def __init__(self, imagens: list):
        self._resultado = self._ler(imagens)

    def _ler(self, imagens: list) -> LeituraImagem:
        if not imagens:
            return LeituraImagem()
        leitor = Agent(
            model=config.model,
            output_schema=LeituraImagem,
            instructions=self._INSTRUCOES,
            markdown=False,
        )
        try:
            resposta = leitor.run("Analise a(s) imagem(ns).", images=imagens)
            return resposta.content
        except Exception:
            return LeituraImagem()

    @property
    def texto_visivel(self) -> str:
        return self._resultado.texto_visivel

    @property
    def descricao(self) -> str:
        return self._resultado.descricao