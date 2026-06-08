import pytest

# Simulando a função de split que inserimos no router.py
def process_text_wall(text: str) -> list[str]:
    return [chunk.strip() for chunk in text.split("[PAUSA]") if chunk.strip()]

def test_text_wall_chunking_preserves_markdown():
    mock_llm_response = (
        "*Diagnóstico da Propriedade - Pasto Legal*\n\n"
        "A análise de satélite indicou uma área de degradação moderada no pasto leste.\n\n"
        "[PAUSA]\n\n"
        "*Recomendações Técnicas:*\n"
        "- Rotação imediata do gado.\n"
        "- Análise de solo para possível calagem.\n\n"
        "[PAUSA]\n\n"
        "Me avise se precisar de ajuda com a interpretação desses dados."
    )
    
    chunks = process_text_wall(mock_llm_response)
    
    # Validações de integridade estrutural
    assert len(chunks) == 3, f"Esperava 3 blocos, mas obteve {len(chunks)}"
    
    # Validações de remoção da tag
    for chunk in chunks:
        assert "[PAUSA]" not in chunk, "A tag [PAUSA] vazou para o texto final do usuário"
        
    # Validações de integridade do Markdown
    assert chunks[0].startswith("*Diagnóstico da Propriedade"), "O negrito do primeiro bloco foi corrompido"
    assert chunks[0].endswith("pasto leste."), "O final do primeiro bloco foi cortado incorretamente"
    
    assert chunks[1].startswith("*Recomendações Técnicas:*"), "O negrito do segundo bloco foi corrompido"
    assert "- Análise de solo" in chunks[1], "A lista do segundo bloco foi perdida"
    
    assert chunks[2].startswith("Me avise"), "O terceiro bloco perdeu o conteúdo inicial"