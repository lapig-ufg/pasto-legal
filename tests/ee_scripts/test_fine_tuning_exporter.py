import os
import json
import pytest
from unittest.mock import patch, MagicMock

from app.utils.fine_tuning_exporter import (
    anonymize_value,
    format_message_node,
    export_session_to_fine_tuning
)

# --- 1. Teste da Anonimização Recursiva ---
def test_anonymize_value_recursive():
    """Valida se o _mask_pii alcança strings profundas sem quebrar listas e dicionários."""
    raw_data = {
        "user_data": "Meu CPF é 123.456.789-00 e meu CAR é MT-1234567-ABCDEF123456",
        "nested_info": {
            "coords": "A fazenda fica em -12.3456, -45.6789",
            "safe_list": ["Tudo limpo aqui", "O CNPJ da empresa é 12.345.678/0001-99"]
        }
    }
    
    sanitized = anonymize_value(raw_data)
    
    # Validações de máscara de PII
    assert "[CPF_OCULTO]" in sanitized["user_data"]
    assert "123.456.789-00" not in sanitized["user_data"]
    
    assert "[CAR_OCULTO]" in sanitized["user_data"]
    assert "MT-1234567-ABCDEF123456" not in sanitized["user_data"]
    
    assert "[COORDINATES_OCULTO]" in sanitized["nested_info"]["coords"]
    
    assert "[CNPJ_OCULTO]" in sanitized["nested_info"]["safe_list"][1]
    assert "12.345.678/0001-99" not in sanitized["nested_info"]["safe_list"][1]
    
    # Validação de integridade estrutural
    assert sanitized["nested_info"]["safe_list"][0] == "Tudo limpo aqui"


# --- 2. Teste da Normalização de Mensagens (com Tool Calls) ---
def test_format_message_node_with_tools():
    """Garante que argumentos JSON de chamadas de função são limpos e re-serializados."""
    raw_msg = {
        "role": "assistant",
        "content": "Vou consultar a propriedade no SICAR...",
        "tool_calls": [
            {
                "id": "call_abc123",
                "type": "function",
                "function": {
                    "name": "consultar_sicar",
                    "arguments": '{"car_numero": "MT-1234567-ABCDEF123456", "filtro": "ativo"}'
                }
            }
        ]
    }
    
    formatted = format_message_node(raw_msg)
    
    assert formatted["role"] == "assistant"
    
    tool_call = formatted["tool_calls"][0]
    assert tool_call["function"]["name"] == "consultar_sicar"
    
    # O argumento era string JSON. O exportador tem que dar parse, limpar e voltar para string JSON
    args_str = tool_call["function"]["arguments"]
    assert "[CAR_OCULTO]" in args_str
    assert "MT-1234567" not in args_str
    
    # Confirma que o JSON resultante é válido
    args_dict = json.loads(args_str)
    assert args_dict["filtro"] == "ativo"


# --- 3. Teste do Fluxo de Exportação (Mockando Agno Db e FileSystem) ---
@patch("app.utils.fine_tuning_exporter.agno_db")
def test_export_session_to_fine_tuning(mock_agno_db, tmp_path):
    """Testa a reidratação Híbrida do banco e o append no arquivo .jsonl"""
    
    # Gerando diretórios temporários compatíveis com qualquer S.O. (Windows/Linux/Mac)
    fake_dir = str(tmp_path / "data")
    fake_path = str(tmp_path / "data" / "fake_dataset.jsonl")
    
    with patch("app.utils.fine_tuning_exporter.DATASET_DIR", fake_dir), \
         patch("app.utils.fine_tuning_exporter.DATASET_PATH", fake_path):

        # 1. Configurando o Mock do Agno Db
        mock_run = MagicMock()
        mock_run.messages = [
            {"role": "user", "content": "Faz um check no CPF 111.222.333-44"},
            {"role": "assistant", "content": "Processando."}
        ]
        
        # O mock finge que o Agno retornou o histórico ao ler a sessão
        mock_agno_db.read_runs.return_value = [mock_run]
        
        # 2. Executando a função principal (testando também o patch em memória)
        result = export_session_to_fine_tuning(
            session_id="session_test_999",
            feedback_score=1.0,
            agent_id="pasto_legal_agent",
            local_user_msg="Essa resposta tá ruim, era no CPF 111.222.333-44",
            local_assistant_resp="Desculpe."
        )
        
        assert result is True
        
        # 3. Validando o arquivo .jsonl gravado
        assert os.path.exists(fake_path)
        
        with open(fake_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            assert len(lines) == 1  # Deve ter gerado exatamente uma linha JSON
            
            record = json.loads(lines[0])
            
            # Validando Metadados
            assert record["metadata"]["feedback_score"] == 1.0
            assert record["metadata"]["session_id"] == "session_test_999"
            
            # Validando se o conteúdo histórico do banco foi salvo e anonimizado
            assert "[CPF_OCULTO]" in record["messages"][0]["content"]
            assert "111.222.333-44" not in record["messages"][0]["content"]
            
            # Validando se o patch híbrido em memória funcionou
            assert record["messages"][-2]["role"] == "user"
            assert "[CPF_OCULTO]" in record["messages"][-2]["content"]