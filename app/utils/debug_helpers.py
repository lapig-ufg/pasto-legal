"""Data extraction helpers for the debug panel.

Converts agno framework objects (WorkflowRunOutput, RunOutput, etc.)
into plain dicts/lists that Streamlit can safely serialize and store
in st.session_state across reruns.
"""

from time import time
from typing import Any, Dict, List

from agno.run.workflow import WorkflowRunOutput
from agno.run.agent import RunOutput


def truncate_string(s: Any, max_len: int = 500) -> str:
    """Convert any value to a string and truncate if too long."""
    if s is None:
        return "None"
    text = str(s)
    if len(text) > max_len:
        return text[:max_len] + f"... (truncated, {len(text)} chars total)"
    return text


def extract_session_state(session_state: Dict[str, Any]) -> Dict[str, Any]:
    """Format session_state dict with human-readable values for known keys.

    Known keys get special treatment; unknown keys fall back to truncated strings.
    """
    if not session_state:
        return {}

    result: Dict[str, Any] = {}
    for key, value in session_state.items():
        try:
            result[key] = _format_state_value(key, value)
        except Exception:
            result[key] = truncate_string(value, 200)
    return result


def _format_state_value(key: str, value: Any) -> Any:
    """Format a single session state value based on its key."""
    if value is None:
        return None

    # Boolean flags
    if key in ("is_greeted", "terms_acceptance"):
        return bool(value)

    # String routing keys
    if key in ("workflow_route", "registration_state"):
        return str(value) if value else "None"

    # User mood — nested dict with satisfaction data
    if key == "user_mood":
        if isinstance(value, dict):
            return {k: truncate_string(v, 100) for k, v in value.items()}
        return truncate_string(value, 200)

    # User persona — nested dict
    if key == "user_persona":
        if isinstance(value, dict):
            return {k: truncate_string(v, 100) for k, v in value.items()}
        return truncate_string(value, 200)

    # Properties — list of dicts, summarize each
    if key in ("all_properties", "candidate_properties"):
        if isinstance(value, list):
            return [
                {k: truncate_string(v, 100) for k, v in prop.items()}
                if isinstance(prop, dict)
                else truncate_string(prop, 200)
                for prop in value
            ]
        return truncate_string(value, 300)

    # Delivered media — show count
    if key == "delivered_media":
        if isinstance(value, dict):
            return f"{len(value)} entries"
        if isinstance(value, list):
            return f"{len(value)} entries"
        return truncate_string(value, 200)

    # Default — truncate if it's a string, pass through if it's a simple type
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return truncate_string(value, 200)
    if isinstance(value, (list, dict)):
        return truncate_string(value, 500)
    return truncate_string(value, 300)


def extract_tool_calls(agent_run: RunOutput) -> List[Dict[str, Any]]:
    """Extract tool call information from a single agent RunOutput."""
    tool_calls: List[Dict[str, Any]] = []

    if not hasattr(agent_run, "tools") or not agent_run.tools:
        return tool_calls

    for tool in agent_run.tools:
        tool_info: Dict[str, Any] = {
            "tool_name": getattr(tool, "tool_name", "unknown"),
            "tool_args": {},
            "result": None,
            "status": "unknown",
            "duration": None,
            "agent_name": getattr(agent_run, "agent_name", "unknown"),
        }

        # Tool arguments
        if hasattr(tool, "tool_args") and tool.tool_args:
            try:
                tool_info["tool_args"] = dict(tool.tool_args) if isinstance(tool.tool_args, dict) else truncate_string(tool.tool_args, 300)
            except Exception:
                tool_info["tool_args"] = truncate_string(tool.tool_args, 300)

        # Tool result
        if hasattr(tool, "result") and tool.result:
            tool_info["result"] = truncate_string(tool.result, 500)

        # Status
        if hasattr(tool, "tool_call_error") and tool.tool_call_error:
            tool_info["status"] = "error"
        else:
            tool_info["status"] = "success"

        # Duration from metrics
        if hasattr(tool, "metrics") and tool.metrics:
            try:
                tool_info["duration"] = getattr(tool.metrics, "time", None)
            except Exception:
                pass

        tool_calls.append(tool_info)

    return tool_calls


def extract_metrics(metrics: Any) -> Dict[str, Any]:
    """Extract metrics from RunMetrics or WorkflowMetrics into a flat dict.

    Handles both RunMetrics (from agent runs) and WorkflowMetrics (from workflow level).
    """
    if metrics is None:
        return {}

    result: Dict[str, Any] = {}

    # Common fields from BaseMetrics
    for field in ("input_tokens", "output_tokens", "total_tokens",
                   "audio_input_tokens", "audio_output_tokens", "audio_total_tokens",
                   "cache_read_tokens", "cache_write_tokens", "reasoning_tokens", "cost"):
        val = getattr(metrics, field, None)
        if val is not None:
            result[field] = val

    # RunMetrics-specific fields
    duration = getattr(metrics, "duration", None)
    if duration is not None:
        result["duration"] = duration
    time_to_first_token = getattr(metrics, "time_to_first_token", None)
    if time_to_first_token is not None:
        result["time_to_first_token"] = time_to_first_token

    # Per-model breakdowns (RunMetrics.details)
    details = getattr(metrics, "details", None)
    if details:
        model_breakdowns: List[Dict[str, Any]] = []
        for model_type, model_metrics_list in details.items():
            for mm in model_metrics_list:
                model_breakdowns.append({
                    "model_type": model_type,
                    "model_id": getattr(mm, "id", "unknown"),
                    "provider": getattr(mm, "provider", "unknown"),
                    "input_tokens": getattr(mm, "input_tokens", 0),
                    "output_tokens": getattr(mm, "output_tokens", 0),
                    "total_tokens": getattr(mm, "total_tokens", 0),
                    "cost": getattr(mm, "cost", None),
                })
        result["model_breakdowns"] = model_breakdowns

    # WorkflowMetrics-specific: steps dict
    steps = getattr(metrics, "steps", None)
    if steps and isinstance(steps, dict):
        step_metrics: Dict[str, Any] = {}
        for step_name, step_metric in steps.items():
            step_metrics[step_name] = {
                "input_tokens": getattr(step_metric, "input_tokens", 0),
                "output_tokens": getattr(step_metric, "output_tokens", 0),
                "total_tokens": getattr(step_metric, "total_tokens", 0),
                "cost": getattr(step_metric, "cost", None),
                "duration": getattr(step_metric, "duration", None),
            }
        result["step_metrics"] = step_metrics

    return result


def extract_messages(agent_run: RunOutput) -> List[Dict[str, Any]]:
    """Extract message history from a single agent RunOutput."""
    messages: List[Dict[str, Any]] = []

    if not hasattr(agent_run, "messages") or not agent_run.messages:
        return messages

    for msg in agent_run.messages:
        content = getattr(msg, "content", None)
        role = getattr(msg, "role", "unknown")
        name = getattr(msg, "name", None)

        msg_dict: Dict[str, Any] = {
            "role": role,
            "content": truncate_string(content, 300) if content else None,
            "name": name,
            "agent_name": getattr(agent_run, "agent_name", None),
        }

        # Include tool calls if present
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            msg_dict["tool_calls"] = [
                {"name": tc.get("function", {}).get("name"), "args": truncate_string(tc.get("function", {}).get("arguments"), 200)}
                for tc in tool_calls
                if isinstance(tc, dict)
            ]

        messages.append(msg_dict)

    return messages


def extract_agent_run_data(agent_run: RunOutput) -> Dict[str, Any]:
    """Extract debug data from a single agent RunOutput.

    Returns a dict with agent identification, content preview, tool calls,
    reasoning, metrics, and messages.
    """
    result: Dict[str, Any] = {
        "agent_id": getattr(agent_run, "agent_id", None),
        "agent_name": getattr(agent_run, "agent_name", "unknown"),
        "model": getattr(agent_run, "model", None),
        "model_provider": getattr(agent_run, "model_provider", None),
        "run_id": getattr(agent_run, "run_id", None),
        "status": str(getattr(agent_run, "status", "unknown")),
        "content": truncate_string(getattr(agent_run, "content", None), 500),
        "content_type": getattr(agent_run, "content_type", None),
    }

    # Tool calls
    result["tool_calls"] = extract_tool_calls(agent_run)

    # Reasoning
    reasoning_content = getattr(agent_run, "reasoning_content", None)
    if reasoning_content:
        result["reasoning_content"] = truncate_string(reasoning_content, 500)

    reasoning_steps = getattr(agent_run, "reasoning_steps", None)
    if reasoning_steps:
        result["reasoning_steps"] = [
            truncate_string(step, 200) for step in reasoning_steps
        ]

    # Metrics
    metrics = getattr(agent_run, "metrics", None)
    if metrics:
        result["metrics"] = extract_metrics(metrics)

    # Messages
    result["messages"] = extract_messages(agent_run)

    # Session state snapshot from this agent run
    agent_session_state = getattr(agent_run, "session_state", None)
    if agent_session_state:
        result["session_state"] = extract_session_state(agent_session_state)

    return result


def extract_step_results(response: WorkflowRunOutput) -> List[Dict[str, Any]]:
    """Extract step results summary from WorkflowRunOutput."""
    step_summaries: List[Dict[str, Any]] = []

    if not hasattr(response, "step_results") or not response.step_results:
        return step_summaries

    for step in response.step_results:
        # step_results can contain lists (from Parallel) or individual StepOutputs
        if isinstance(step, list):
            for sub_step in step:
                step_summaries.append(_extract_single_step(sub_step))
        else:
            step_summaries.append(_extract_single_step(step))

    return step_summaries


def _extract_single_step(step: Any) -> Dict[str, Any]:
    """Extract debug data from a single StepOutput."""
    return {
        "step_name": getattr(step, "step_name", None),
        "step_type": getattr(step, "step_type", None),
        "executor_type": getattr(step, "executor_type", None),
        "executor_name": getattr(step, "executor_name", None),
        "content": truncate_string(getattr(step, "content", None), 300),
        "success": getattr(step, "success", None),
        "error": getattr(step, "error", None),
        "is_paused": getattr(step, "is_paused", None),
    }


def extract_workflow_debug_data(
    response: WorkflowRunOutput,
    session_id: str,
    user_query: str,
) -> Dict[str, Any]:
    """Top-level extractor called after pasto_legal_workflow.run().

    Returns a dict with all debug data for this interaction, safe for
    st.session_state storage (all agno objects converted to plain types).
    """
    result: Dict[str, Any] = {
        "timestamp": int(time()),
        "session_id": session_id,
        "user_query": truncate_string(user_query, 300),
        "status": str(getattr(response, "status", "unknown")),
        "workflow_id": getattr(response, "workflow_id", None),
        "workflow_name": getattr(response, "workflow_name", None),
        "content": truncate_string(getattr(response, "content", None), 500),
    }

    # --- Session State ---
    # First try the response's session_state, then fall back to None
    wf_session_state = getattr(response, "session_state", None)
    if wf_session_state:
        result["session_state"] = extract_session_state(wf_session_state)
    else:
        result["session_state"] = {}

    # --- Agent Routing Trace ---
    agent_routing_trace: List[Dict[str, Any]] = []
    step_executor_runs = getattr(response, "step_executor_runs", None)
    if step_executor_runs:
        for run in step_executor_runs:
            try:
                agent_routing_trace.append(extract_agent_run_data(run))
            except Exception:
                agent_routing_trace.append({
                    "agent_name": getattr(run, "agent_name", "unknown"),
                    "error": "Failed to extract agent run data",
                })
    result["agent_routing_trace"] = agent_routing_trace

    # --- Tool Calls Log (aggregated from all agent runs) ---
    all_tool_calls: List[Dict[str, Any]] = []
    for agent_data in agent_routing_trace:
        if "tool_calls" in agent_data and agent_data["tool_calls"]:
            all_tool_calls.extend(agent_data["tool_calls"])
    result["tool_calls_log"] = all_tool_calls

    # --- Metrics ---
    wf_metrics = getattr(response, "metrics", None)
    if wf_metrics:
        result["metrics_summary"] = extract_metrics(wf_metrics)
    else:
        result["metrics_summary"] = {}

    # --- Message History (aggregated from all agent runs) ---
    all_messages: List[Dict[str, Any]] = []
    for agent_data in agent_routing_trace:
        if "messages" in agent_data and agent_data["messages"]:
            all_messages.extend(agent_data["messages"])
    result["message_history"] = all_messages

    # --- Step Results Summary ---
    result["step_results_summary"] = extract_step_results(response)

    return result