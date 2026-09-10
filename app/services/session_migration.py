import copy
from typing import Any, Callable, Dict

CURRENT_SCHEMA_VERSION = 1


def migrate_v0_to_v1(state: Dict[str, Any]) -> Dict[str, Any]:
    if "_legacy_data" not in state:
        state["_legacy_data"] = {}

    if "all_properties" not in state:
        state["all_properties"] = []
        
    if "user_persona" not in state:
        state["user_persona"] = {}

    return state


MIGRATIONS: Dict[int, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    0: migrate_v0_to_v1,
}


def migrate_session_state(raw_state: Dict[str, Any]) -> Dict[str, Any]:
    if not raw_state:
        raw_state = {}
        
    state = copy.deepcopy(raw_state)
    
    current_version = 0
    workflow_state = state.get("workflow_state", {})
    
    if isinstance(workflow_state, dict):
        current_version = workflow_state.get("schema_version", 0)

    while current_version < CURRENT_SCHEMA_VERSION:
        migration_func = MIGRATIONS.get(current_version)
        
        if not migration_func:
            break
            
        state = migration_func(state)
        current_version += 1
        
        if "workflow_state" not in state or not isinstance(state["workflow_state"], dict):
            state["workflow_state"] = {}
            
        state["workflow_state"]["schema_version"] = current_version
        
    return state