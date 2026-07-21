"""Extração de texto de imagem (OCR via VLM) para checagem de PII.

Lê o texto visível na imagem (números de documento, etc.) para que o guardrail
de PII possa varrer. NÃO faz descrição de cena nem filtro de escopo (isso é a #123).

Interface externa:
    extrair_texto_imagem(imagens) -- texto visível na(s) imagem(ns) (vazio se não houver).
"""

from agno.agent import Agent

from app.configs.config import config


def extrair_texto_imagem(imagens: list) -> str:
    """Lê o texto visível em imagem(ns) via VLM. Vazio se não houver imagem."""
    if not imagens:
        return ""
    leitor = Agent(
        model=config.model,
        instructions=(
            "Extraia TODO texto visível nas imagens — especialmente números de "
            "documentos (CPF, CNPJ, RG), cartões e e-mails, exatamente como aparecem. "
            "Se não houver texto, responda vazio. Responda apenas o texto extraído."
        ),
        markdown=False,
    )
    try:
        resposta = leitor.run("Extraia o texto das imagens.", images=imagens)
        return resposta.content or ""
    except Exception:
        return ""