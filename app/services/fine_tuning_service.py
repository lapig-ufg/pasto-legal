import re
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.schemas.fine_tuning import SFTDatasetRow, DPODatasetRow, FineTuningMessage, SFTMetadata


PII_PATTERNS = {
    'CPF': re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),
    'CNPJ': re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/\d{4}-?\d{2}\b"),
    'CAR': re.compile(r"\b[A-Z]{2}-\d{7}-[A-F0-9.]+\b", re.IGNORECASE),
    'COORDINATES': re.compile(r"(-?\d{1,3}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,})")
}


def _mask_text(text: str) -> str:
    if not isinstance(text, str):
        return text
    
    masked_text = text
    for label, pattern in PII_PATTERNS.items():
        masked_text = pattern.sub(f"[{label}_OCULTO]", masked_text)
        
    return masked_text


def sanitize_pii_json_aware(data: Any) -> Any:
    if isinstance(data, dict):
        return {key: sanitize_pii_json_aware(value) for key, value in data.items()}
    if isinstance(data, list):
        return [sanitize_pii_json_aware(item) for item in data]
    if isinstance(data, str):
        return _mask_text(data)
    return data


def build_sft_dataset_row(
    recent_runs: List[Dict[str, Any]], 
    session_id: str, 
    agent_id: str, 
    feedback_score: float
) -> dict:
    if not recent_runs:
        raise ValueError("O histórico de execuções está vazio.")
        
    latest_run = recent_runs[-1]
    raw_messages = latest_run.get("messages", [])
    fine_tuning_messages = []
    
    for msg in raw_messages:
        sanitized_content = sanitize_pii_json_aware(msg.get("content"))
        sanitized_tool_calls = sanitize_pii_json_aware(msg.get("tool_calls"))
        
        ft_msg = FineTuningMessage(
            role=msg.get("role", "unknown"),
            content=sanitized_content,
            name=msg.get("name"),
            tool_call_id=msg.get("tool_call_id"),
            tool_calls=sanitized_tool_calls
        )
        fine_tuning_messages.append(ft_msg)
        
    metadata = SFTMetadata(
        session_id=session_id,
        feedback_score=feedback_score,
        agent_id=agent_id,
        timestamp=datetime.now(timezone.utc).isoformat()
    )
    
    row = SFTDatasetRow(messages=fine_tuning_messages, metadata=metadata)
    return row.model_dump()


def build_dpo_dataset_row(prompt: str, rejected: str, chosen: str) -> dict:
    row = DPODatasetRow(
        prompt=sanitize_pii_json_aware(prompt),
        rejected=sanitize_pii_json_aware(rejected),
        chosen=sanitize_pii_json_aware(chosen)
    )
    return row.model_dump()