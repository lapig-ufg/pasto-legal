"""Agentes de mídia para a camada de ingestão do Pasto Legal.

Fornece agentes dedicados à descrição rica de imagens e à transcrição fiel de
áudio, usados no passo de pré-processamento do workflow principal para que os
agentes posteriores recebam texto em vez de mídia crua.

Interface externa:
    image_description_agent  -- descreve imagens com o máximo de riqueza de detalhes.
    audio_transcription_agent -- transcreve áudio de forma fiel e literal.
"""
from agno.agent import Agent

from app.configs.config import config


image_description_agent = Agent(
    name="Agente de Descrição de Imagem",
    role="Especialista em descrição visual detalhada de imagens.",
    model=config.model,
    debug_mode=config.DEBUG_MODE,
    markdown=False,
    instructions=(
        "Você é um especialista em descrição visual. Descreva a imagem com o "
        "MAIOR NÍVEL DE RIQUEZA E DETALHE possível, em português do Brasil, para "
        "que outro agente possa usá-la sem precisar ver a imagem.\n\n"
        "Inclua, quando aplicável:\n"
        "- Cena geral e contexto (ambiente, paisagem, tipo de local).\n"
        "- Sujeitos e objetos presentes, com posição espacial entre eles.\n"
        "- Cores, texturas, iluminação e condições climáticas.\n"
        "- Não descvreva textos na imagem "
        "- Inferências úteis sobre o contexto (ex.: pastagem, lavoura, gado, "
        "maquinário), sempre indicando o que é observação vs. inferência.\n\n"
        "Responda APENAS com a descrição. Não use markdown nem formatação "
        "especial. Não comente sobre a tarefa. Apenas descreva o que é visível."
    ),
)


audio_transcription_agent = Agent(
    name="Agente de Transcrição de Áudio",
    role="Especialista em transcrição literal de fala (Speech-to-Text).",
    model=config.model,
    debug_mode=config.DEBUG_MODE,
    markdown=False,
    instructions=(
        "Transcreva o áudio para texto em português do Brasil, EXATAMENTE como "
        "foi falado. Responda APENAS com a transcrição literal.\n\n"
        "Regras:\n"
        "- Não adicione comentários, títulos ou explicações.\n"
        "- Não corrija gramática nem reformule; preserve as palavras do falante.\n"
        "- Não use markdown nem formatação especial.\n"
        "- Se o áudio for ininteligível, transcreva as partes compreensíveis e "
        "omita o restante sem indicadores como [...].\n"
        "- Se não houver fala detectável, responda com texto vazio."
    ),
)