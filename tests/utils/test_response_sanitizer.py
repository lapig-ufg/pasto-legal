"""
Testes do sanitizador de raciocínio vazado (`app/utils/scripts/response_sanitizer.py`).

Cobre os padrões reais de vazamento capturados em produção com o Gemini +
thinking habilitado: a segunda rodada de raciocínio (depois de uma tool call,
antes da resposta final) nem sempre vem marcada como `thought=True` pela API,
então às vezes aparece dentro do `content` visível ao usuário em vez de ficar
isolada em `reasoning_content`.

    .venv/bin/python -m pytest tests/utils/test_response_sanitizer.py -v
"""
from app.utils.scripts.response_sanitizer import strip_leaked_reasoning


def test_normal_message_passes_through_unchanged():
    text = "O boletim em PDF da *Fazenda Blue* foi gerado com sucesso! A propriedade tem *19.82 ha* de pastagem."
    assert strip_leaked_reasoning(text) == text


def test_empty_and_none_pass_through():
    assert strip_leaked_reasoning(None) is None
    assert strip_leaked_reasoning("") == ""


def test_quoted_draft_then_restated_without_quotes():
    leak = (
        "Now let's write the final response. The user wants a summary of the boletim.\n\n"
        "\"A propriedade tem 19,82 hectares de pastagem, com biomassa de 435 toneladas de matéria seca.\"\n\n"
        "A propriedade tem 19,82 hectares de pastagem, com biomassa de 435 toneladas de matéria seca."
    )
    result = strip_leaked_reasoning(leak)
    assert result == "A propriedade tem 19,82 hectares de pastagem, com biomassa de 435 toneladas de matéria seca."


def test_multi_paragraph_answer_after_narration_marker_without_exact_duplicate():
    leak = (
        "Let's write the response:\n\n"
        "Opa, parceiro! O boletim em PDF da Fazenda Blue foi gerado com sucesso!\n\n"
        "Aqui vai um resumo rápido do que ele traz.\n\n"
        "A propriedade tem 19,82 hectares de pastagem, com biomassa de 435 toneladas de matéria seca."
    )
    result = strip_leaked_reasoning(leak)
    assert result == (
        "Opa, parceiro! O boletim em PDF da Fazenda Blue foi gerado com sucesso!\n\n"
        "Aqui vai um resumo rápido do que ele traz.\n\n"
        "A propriedade tem 19,82 hectares de pastagem, com biomassa de 435 toneladas de matéria seca."
    )


def test_exact_multi_paragraph_block_duplicated():
    leak = (
        "I need to draft the answer now.\n\n"
        "Opa! O boletim ficou pronto.\n\n"
        "A área mapeada foi de 19,82 ha.\n\n"
        "Opa! O boletim ficou pronto.\n\n"
        "A área mapeada foi de 19,82 ha."
    )
    result = strip_leaked_reasoning(leak)
    assert result == "Opa! O boletim ficou pronto.\n\nA área mapeada foi de 19,82 ha."


def test_legit_multi_paragraph_answer_starting_with_risky_word():
    text = "Note: segue o resumo.\n\nO boletim foi gerado com sucesso.\n\nQualquer dúvida, chama."
    result = strip_leaked_reasoning(text)
    assert result == "O boletim foi gerado com sucesso.\n\nQualquer dúvida, chama."
