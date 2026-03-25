from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class RunInput:
    input_content: str

class Metrics(BaseModel):
    duration: Optional[float] = None
    input_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    time_to_first_token: Optional[float] = None

class ToolExecution:
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None
    created_at: Optional[int] = None
    stop_after_tool_call: Optional[bool] = None
    tool_call_error: Optional[bool] = None
    result: Optional[str] = None
    metrics: Optional[Metrics] = None
    tool_args: Optional[Dict[str, Any]] = Field(default_factory=dict)
    user_input_schema: Optional[List[Any]] = Field(default_factory=list)
    answered: Optional[Any] = None
    confirmed: Optional[Any] = None
    child_run_id: Optional[str] = None
    confirmation_note: Optional[str] = None
    requires_user_input: Optional[bool] = None
    requires_confirmation: Optional[bool] = None
    external_execution_required: Optional[bool] = None

class Run:
    run_id: Optional[str] = None
    status: Optional[str] = None
    content: Optional[str] = None
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    created_at: Optional[int] = None
    session_id: Optional[str] = None
    content_type: Optional[str] = None
    model: Optional[str] = None
    model_provider: Optional[str] = None
    input: RunInput
    metrics: Metrics
    session_state: Dict[str, Any]
    
    tools: List[ToolExecution] = Field(default_factory=list)
    events: List[Any] = Field(default_factory=list)
    
    messages: List[Dict[str, Any]] = Field(default_factory=list) 
    
    parent_run_id: Optional[str] = None

    childs: List['Run'] = Field(default_factory=list)