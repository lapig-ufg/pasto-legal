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
from app.configs.prompts import get_agent_config


_image_config = get_agent_config("image_description_agent")
_audio_config = get_agent_config("audio_transcription_agent")


image_description_agent = Agent(
    name=_image_config["name"],
    role=_image_config["role"],
    model=config.model,
    debug_mode=config.DEBUG_MODE,
    markdown=False,
    instructions=_image_config["instructions"].strip(),
)


audio_transcription_agent = Agent(
    name=_audio_config["name"],
    role=_audio_config["role"],
    model=config.model,
    fallback_models=[config.fallback_model],
    debug_mode=config.DEBUG_MODE,
    markdown=False,
    instructions=_audio_config["instructions"].strip(),
)