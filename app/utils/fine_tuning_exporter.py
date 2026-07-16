import os
import json
import logging
from typing import Any, Dict, List, Optional

from app.database.agno_db import db as agno_db
from app.tools.feedback_tools import _mask_pii

logger = logging.getLogger(__name__)

DATASET_DIR = os.path.join("app", "data")
DATASET_PATH = os.path.join(DATASET_DIR, "fine_tuning_dataset.jsonl")

def anonymize_value(val: Any) -> Any:
    """
    Percorre estruturas de dados de forma recursiva para anonimizar PIIs (CPF, CNPJ, CAR, etc.)
    sem corromper chaves de dicionários ou invalidar a sintaxe estrutural de dados complexos.
    """
    if isinstance(val, str):
        return _mask_pii(val)
    elif isinstance(val, dict):
        return {k: anonymize_value(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [anonymize_value(v) for v in val]
    return val

def format_message_node(msg: Any) -> Dict[str, Any]:
    """
    Normaliza uma mensagem (seja dicionário nativo do PostgreSQL ou objeto de memória)
    para o formato padrão de chat exigido pelas APIs de treinamento e Fine-Tuning.
    """
    if isinstance(msg, dict):
        role = msg.get("role")
        content = msg.get("content")
        tool_calls = msg.get("tool_calls")
        tool_call_id = msg.get("tool_call_id")
        name = msg.get("name")
    else:
        role = getattr(msg, "role", None)
        content = getattr(msg, "content", None)
        tool_calls = getattr(msg, "tool_calls", None)
        tool_call_id = getattr(msg, "tool_call_id", None)
        name = getattr(msg, "name", None)

    formatted = {
        "role": role,
        "content": anonymize_value(content) if content else None
    }

    if role == "assistant" and tool_calls:
        formatted_tool_calls = []
        for tc in tool_calls:
            if isinstance(tc, dict):
                tc_id = tc.get("id")
                tc_type = tc.get("type", "function")
                func_obj = tc.get("function", {})
                func_name = func_obj.get("name")
                func_args = func_obj.get("arguments")
            else:
                tc_id = getattr(tc, "id", None)
                tc_type = getattr(tc, "type", "function")
                func_obj = getattr(tc, "function", None) or {}
                if isinstance(func_obj, dict):
                    func_name = func_obj.get("name")
                    func_args = func_obj.get("arguments")
                else:
                    func_name = getattr(func_obj, "name", None)
                    func_args = getattr(func_obj, "arguments", None)

            if isinstance(func_args, str):
                try:
                    args_dict = json.loads(func_args)
                    func_args_sanitized = json.dumps(anonymize_value(args_dict))
                except Exception:
                    func_args_sanitized = anonymize_value(func_args)
            else:
                func_args_sanitized = anonymize_value(func_args)

            formatted_tool_calls.append({
                "id": tc_id,
                "type": tc_type,
                "function": {
                    "name": func_name,
                    "arguments": func_args_sanitized
                }
            })
        formatted["tool_calls"] = formatted_tool_calls

    if role == "tool":
        formatted["tool_call_id"] = tool_call_id
        formatted["name"] = name
        
        if isinstance(formatted["content"], str):
            try:
                content_dict = json.loads(formatted["content"])
                formatted["content"] = json.dumps(anonymize_value(content_dict))
            except Exception:
                pass 

    return formatted

def export_session_to_fine_tuning(
    session_id: str, 
    feedback_score: float, 
    agent_id: str,
    local_user_msg: Optional[str] = None,
    local_assistant_resp: Optional[str] = None
) -> bool:
    """
    Reidrata o histórico de conversas do banco nativo do Agno, mescla turnos locais em transação pendente (Patch),
    aplica higienização de PII e anexa a interação formatada ao arquivo .jsonl.
    """
    try:
        messages_formatted = []
        
        
        if agno_db:
            runs = getattr(agno_db, "read_runs", lambda session_id: [])(session_id=session_id)
            if not runs and hasattr(agno_db, "get_runs"):
                runs = agno_db.get_runs(session_id=session_id)
                
            if runs:
                for run in runs:
                    run_messages = getattr(run, "messages", None)
                    if not run_messages:
                        memory = getattr(run, "memory", None)
                        if isinstance(memory, dict):
                            run_messages = memory.get("messages", [])
                        elif hasattr(memory, "messages"):
                            run_messages = memory.messages
                            
                    if run_messages:
                        for msg in run_messages:
                            messages_formatted.append(format_message_node(msg))
                        
        if local_user_msg:
            has_user_msg = any(
                m.get("role") == "user" and m.get("content") == local_user_msg 
                for m in messages_formatted
            )
            if not has_user_msg:
                messages_formatted.append({
                    "role": "user", 
                    "content": anonymize_value(local_user_msg)
                })
                if local_assistant_resp:
                    messages_formatted.append({
                        "role": "assistant", 
                        "content": anonymize_value(local_assistant_resp)
                    })

        if not messages_formatted:
            logger.warning(f"Nenhum histórico estruturado pôde ser gerado para a sessão: {session_id}")
            return False

        record = {
            "messages": messages_formatted,
            "metadata": {
                "feedback_score": feedback_score,
                "session_id": session_id,
                "agent_id": agent_id
            }
        }

        os.makedirs(DATASET_DIR, exist_ok=True)
        with open(DATASET_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            
        logger.info(f"Sessão {session_id} exportada com sucesso para o fine-tuning.")
        return True
    except Exception as e:
        logger.error(f"Erro crítico durante a exportação de fine-tuning para {session_id}: {str(e)}", exc_info=True)
        return False