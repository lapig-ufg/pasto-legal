"""Testes do guardrail de contexto (#123) — herméticos, sem chamar LLM real.

O ContextValidator usa um modelo pra julgar escopo. Aqui a gente MOCKA o Agent,
então nenhum modelo real é chamado — controlamos a resposta e testamos a lógica.
"""

import os

# Env dummy pra o config importar sem depender de credenciais reais
os.environ.setdefault("GOOGLE_API_KEY", "test")
os.environ.setdefault("MODEL_PROVIDER", "google")
os.environ.setdefault("MODEL_ID", "gemini-3.1-flash-lite")

from unittest.mock import patch, MagicMock

from app.guardrails.context_gate import (
    ContextValidator,
    ResultadoContexto,
    mensagem_fora_escopo,
)


def _mock_agent(resultado: ResultadoContexto):
    """Agent falso cujo .run(...).content é o resultado dado."""
    agente = MagicMock()
    agente.run.return_value = MagicMock(content=resultado)
    return agente


# --- mensagem_fora_escopo (função pura) ---

def test_mensagem_cita_o_assunto():
    assert "carro" in mensagem_fora_escopo("carro")

def test_mensagem_generica_sem_assunto():
    msg = mensagem_fora_escopo("")
    assert "carro" not in msg
    assert "pastagem" in msg   # a genérica cita os temas do escopo


# --- ContextValidator ---

def test_texto_vazio_nao_bloqueia():
    """Sem conteúdo: nem chama o modelo, e não bloqueia (fail-open)."""
    v = ContextValidator("", "", "")
    assert v.dentro_do_escopo is True
    assert v.assunto == ""

def test_apenas_espacos_nao_bloqueia():
    v = ContextValidator("   ", "  ")
    assert v.dentro_do_escopo is True

@patch("app.guardrails.context_gate.Agent")
def test_dentro_do_escopo_passa(MockAgent):
    MockAgent.return_value = _mock_agent(
        ResultadoContexto(dentro_do_escopo=True, assunto="")
    )
    v = ContextValidator("como está o pasto?")
    assert v.dentro_do_escopo is True

@patch("app.guardrails.context_gate.Agent")
def test_fora_do_escopo_bloqueia_com_assunto(MockAgent):
    MockAgent.return_value = _mock_agent(
        ResultadoContexto(dentro_do_escopo=False, assunto="futebol")
    )
    v = ContextValidator("que horas é o jogo do Vasco?")
    assert v.dentro_do_escopo is False
    assert v.assunto == "futebol"

@patch("app.guardrails.context_gate.Agent")
def test_erro_no_modelo_nao_bloqueia(MockAgent):
    """Se o modelo falhar, fail-open (não bloqueia usuário legítimo)."""
    agente = MagicMock()
    agente.run.side_effect = Exception("boom")
    MockAgent.return_value = agente
    v = ContextValidator("qualquer coisa")
    assert v.dentro_do_escopo is True

@patch("app.guardrails.context_gate.Agent")
def test_junta_todos_os_textos(MockAgent):
    """Os 4 textos (digitado, áudio, descrição, texto-imagem) vão juntos pro juiz."""
    agente = _mock_agent(ResultadoContexto(dentro_do_escopo=True))
    MockAgent.return_value = agente
    ContextValidator("oi", "audio aqui", "descricao img", "texto ocr")
    conteudo = agente.run.call_args[0][0]
    assert "oi" in conteudo
    assert "audio aqui" in conteudo
    assert "descricao img" in conteudo
    assert "texto ocr" in conteudo