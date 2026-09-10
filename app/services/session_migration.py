import copy
from typing import Any, Dict

CURRENT_SCHEMA_VERSION = 1


def migrate_v0_to_v1(raw_state: Dict[str, Any]) -> Dict[str, Any]:
    state = copy.deepcopy(raw_state)
    
    if "_legacy_data" not in state:
        state["_legacy_data"] = {}

    workflow_state = state.get("workflow_state", {})
    if isinstance(workflow_state, dict):
        workflow_state["schema_version"] = 1
        state["workflow_state"] = workflow_state

    if "all_properties" not in state:
        state["all_properties"] = []
        
    if "user_persona" not in state:
        state["user_persona"] = {}

    return state


def migrate_session_state(raw_state: Dict[str, Any]) -> Dict[str, Any]:
    if not raw_state:
        raw_state = {}
        
    state = copy.deepcopy(raw_state)
    
    current_version = 0
    workflow_state = state.get("workflow_state", {})
    
    if isinstance(workflow_state, dict):
        current_version = workflow_state.get("schema_version", 0)

    if current_version < 1:
        state = migrate_v0_to_v1(state)
        current_version = 1
        
    return state