import re
import pytest
from app.schemas.proactive_suggestion import ProactiveSuggestion

def parse_proactive_response(text: str) -> ProactiveSuggestion:
    chunks = re.split(r'\s*\[PAUS[EA]\]\s*', text, maxsplit=1, flags=re.IGNORECASE)
    
    main_text = chunks[0].strip()
    proactive_text = chunks[1].strip() if len(chunks) > 1 and chunks[1].strip() else None
    
    return ProactiveSuggestion(
        main_response=main_text,
        proactive_suggestion=proactive_text
    )

def test_parse_with_standard_pause():
    text = "*Diagnóstico da Propriedade*\nTudo certo com o pasto leste.\n[PAUSE]\nDeseja ver a capacidade de suporte?"
    result = parse_proactive_response(text)
    
    assert result.main_response == "*Diagnóstico da Propriedade*\nTudo certo com o pasto leste."
    assert result.proactive_suggestion == "Deseja ver a capacidade de suporte?"

def test_parse_with_legacy_pausa():
    text = "Análise concluída.\n\n[PAUSA]\n\nQual o próximo passo?"
    result = parse_proactive_response(text)
    
    assert result.main_response == "Análise concluída."
    assert result.proactive_suggestion == "Qual o próximo passo?"

def test_parse_without_tag():
    text = "Apenas o diagnóstico sem nenhuma sugestão proativa."
    result = parse_proactive_response(text)
    
    assert result.main_response == "Apenas o diagnóstico sem nenhuma sugestão proativa."
    assert result.proactive_suggestion is None

def test_parse_preserves_markdown():
    text = "*Fase 1*: Concluída.\n[PAUSE]\n*Fase 2*: Iniciar?"
    result = parse_proactive_response(text)
    
    assert result.main_response.startswith("*Fase 1*")
    assert result.proactive_suggestion.startswith("*Fase 2*")