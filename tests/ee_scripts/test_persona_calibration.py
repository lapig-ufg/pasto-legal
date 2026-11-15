import os
import pytest
from unittest.mock import Mock

# INJEÇÃO FAKE (GEE):
os.environ["GEE_SERVICE_ACCOUNT"] = "dummy_account_para_passar_no_teste"
os.environ["GEE_KEY_FILE"] = "dummy_key_file.json"
os.environ["GEE_PROJECT"] = "dummy_project"
os.environ["APP_ENV"] = "development" 

# INJEÇÃO FAKE (DATABASE): Injetando o pacote completo
os.environ["POSTGRES_HOST"] = "localhost"
os.environ["POSTGRES_PORT"] = "5432"
os.environ["POSTGRES_USER"] = "postgres"
os.environ["POSTGRES_PASSWORD"] = "postgres"
os.environ["POSTGRES_DBNAME"] = "pasto_legal_db" # <--- Correção feita aqui

# Passo 2: Importar os Elementos Necessários
from domain.agent import get_instructions

# Fixture do Pytest para criar um contexto falso limpo antes de cada teste
@pytest.fixture
def mock_run_context():
    context = Mock()
    context.session_state = {}
    return context

# Criar o Cenário de Fallback (Usuário Novo/Desconhecido)
def test_calibragem_fallback(mock_run_context):
    # Simulando um session_state totalmente vazio ou sem a chave user_persona
    mock_run_context.session_state = {}
    
    instructions = get_instructions(mock_run_context)
    
    assert "Embrapa" in instructions, "O fallback da Embrapa não foi acionado para persona desconhecida"
    assert "DADOS BRUTOS" not in instructions, "Instruções do Técnico vazaram no fallback"
    assert "TRADUÇÃO DE MÉTRICAS" not in instructions, "Instruções do Produtor vazaram no fallback"