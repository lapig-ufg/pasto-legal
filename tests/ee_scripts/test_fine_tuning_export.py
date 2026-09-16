import json
import pytest
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))
from app.services.fine_tuning_service import sanitize_pii_json_aware, build_sft_dataset_row

def test_sanitize_pii_json_aware():
    payload = {
        "user_input": "Meu CPF é 123.456.789-10 e meu CAR é SP-1234567-ABCD",
        "nested_data": {
            "location": "Minhas coordenadas são -23.5505, -46.6333",
            "safe_value": 42
        },
        "tags": ["123.456.789-10", "texto seguro"]
    }
    
    sanitized = sanitize_pii_json_aware(payload)
    
    assert "123.456.789-10" not in sanitized["user_input"]
    assert "[CPF_OCULTO]" in sanitized["user_input"]
    
    assert "SP-1234567-ABCD" not in sanitized["user_input"]
    assert "[CAR_OCULTO]" in sanitized["user_input"]
    
    assert "-23.5505, -46.6333" not in sanitized["nested_data"]["location"]
    assert "[COORDINATES_OCULTO]" in sanitized["nested_data"]["location"]
    
    assert sanitized["nested_data"]["safe_value"] == 42
    
    assert "123.456.789-10" not in sanitized["tags"]
    assert "[CPF_OCULTO]" in sanitized["tags"]


def test_build_sft_dataset_row_json_serializable():
    recent_runs = [
        {
            "messages": [
                {"role": "user", "content": "Gere as estatísticas de pastagem da Fazenda Vale Verde."},
                {
                    "role": "assistant", 
                    "content": None, 
                    "tool_calls": [
                        {
                            "id": "call_01", 
                            "type": "function", 
                            "function": {"name": "get_pasture_stats", "arguments": "{\"feature_id\": \"Fazenda Vale Verde\"}"}
                        }
                    ]
                },
                {"role": "tool", "tool_call_id": "call_01", "name": "get_pasture_stats", "content": "{\"biomass\": 14.8}"},
                {"role": "assistant", "content": "A Fazenda Vale Verde apresenta estimativa de biomassa de 14.8 t/ha."}
            ]
        }
    ]
    
    row_dict = build_sft_dataset_row(
        recent_runs=recent_runs,
        session_id="test_session_123",
        agent_id="single_agent",
        feedback_score=5.0
    )
    
    try:
        json_string = json.dumps(row_dict)
        assert isinstance(json_string, str)
    except TypeError:
        pytest.fail("O output do SFTDatasetRow não é serializável em JSON.")
        
    assert row_dict["metadata"]["feedback_score"] == 5.0
    assert len(row_dict["messages"]) == 4

def test_build_sft_dataset_row_empty_runs():
    with pytest.raises(ValueError, match="O histórico de execuções está vazio."):
        build_sft_dataset_row([], "session_id", "agent_id", 5.0)