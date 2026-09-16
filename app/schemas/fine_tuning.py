from typing import Any, Dict, List, Optional
from pydantic import BaseModel

class FineTuningMessage(BaseModel):
    role: str
    content: Optional[str] = None
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None

class SFTMetadata(BaseModel):
    session_id: str
    feedback_score: float
    agent_id: str
    timestamp: Optional[str] = None

class SFTDatasetRow(BaseModel):
    messages: List[FineTuningMessage]
    metadata: SFTMetadata

class DPODatasetRow(BaseModel):
    prompt: str
    rejected: str
    chosen: str