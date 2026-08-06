"""Debug data helpers — bridge mode.

Converts bridge HTTP responses into plain dicts for Streamlit session_state.
No agno types needed.
"""

from time import time
from typing import Any, Dict, List


def truncate_string(s: Any, max_len: int = 500) -> str:
    if s is None:
        return "None"
    text = str(s)
    if len(text) > max_len:
        return text[:max_len] + f"... (truncated, {len(text)} chars total)"
    return text


def extract_session_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """Format session state for debug display."""
    if not state:
        return {}
    result: Dict[str, Any] = {}
    for key, value in state.items():
        try:
            if isinstance(value, (bool, int, float)):
                result[key] = value
            elif isinstance(value, str):
                result[key] = truncate_string(value, 200)
            elif isinstance(value, (list, dict)):
                result[key] = truncate_string(value, 500)
            else:
                result[key] = truncate_string(value, 200)
        except Exception:
            result[key] = truncate_string(value, 200)
    return result


def extract_bridge_debug_data(
    bridge_result: Dict[str, Any],
    session_id: str,
    user_query: str,
) -> Dict[str, Any]:
    """Extract debug data from a bridge HTTP response."""
    return {
        "timestamp": int(time()),
        "session_id": session_id,
        "user_query": truncate_string(user_query, 300),
        "content": truncate_string(bridge_result.get("content", ""), 500),
        "session_state": extract_session_state(bridge_result.get("sessionState", {})),
        "agent_routing_trace": bridge_result.get("agentRouting", []),
        "tool_calls_log": bridge_result.get("toolCalls", []),
        "metrics_summary": bridge_result.get("metrics", {}),
        "message_history": bridge_result.get("messages", []),
    }
