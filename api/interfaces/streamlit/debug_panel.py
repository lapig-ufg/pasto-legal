"""Streamlit debug panel — pi RPC mode.

Renders a sidebar expander with tabs for inspecting session state,
agent routing, tool calls, metrics, and message history.
Data comes from the pi subprocess via HTTP, stored as plain dicts.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
import streamlit as st


def _resolve_prompt_dump_path(user_id: str) -> Path:
    """Resolve the last_prompt.md path for a user, mirroring pi_rpc.py."""
    sessions_dir = Path(os.getenv("PI_SESSIONS_DIR", "/tmp/pi-sessions"))
    return sessions_dir / user_id / "last_prompt.md"


def render_session_state_tab(session_state: Dict[str, Any]) -> None:
    if not session_state:
        st.info("No session state data yet. Send a message to populate.")
        return
    st.subheader("Session State")
    for key in sorted(session_state.keys()):
        value = session_state[key]
        with st.expander(str(key), expanded=False):
            if isinstance(value, (dict, list)):
                st.json(value)
            else:
                st.json({"value": value})


def render_agent_routing_tab(routing_data: List[Dict[str, Any]]) -> None:
    if not routing_data:
        st.info("No agent routing data yet.")
        return
    st.subheader("Agent Routing Trace")
    for i, entry in enumerate(routing_data):
        agent_name = entry.get("agent_name", "unknown")
        content_preview = entry.get("content", "")
        with st.expander(f"Step {i + 1}: {agent_name}", expanded=(i == len(routing_data) - 1)):
            st.caption(f"**Model:** `{entry.get('model', '?')}`")
            if content_preview:
                st.text(content_preview[:500])
            tool_calls = entry.get("tool_calls", [])
            if tool_calls:
                st.caption(f"**Tools called:** {len(tool_calls)}")
                for tc in tool_calls:
                    st.text(f"  → {tc.get('tool_name', '?')}")


def render_tool_calls_tab(tool_calls: List[Dict[str, Any]]) -> None:
    if not tool_calls:
        st.info("No tool calls yet.")
        return
    st.subheader("Tool Calls Log")
    st.caption(f"Total: {len(tool_calls)} tool calls")
    for i, tc in enumerate(tool_calls):
        tool_name = tc.get("tool_name", "unknown")
        status = tc.get("status", "unknown")
        status_icon = "[OK]" if status == "success" else "[FAIL]"
        with st.expander(f"{status_icon} {tool_name}", expanded=False):
            if tc.get("tool_args"):
                st.caption("**Arguments:**")
                st.json(tc["tool_args"])
            if tc.get("result"):
                st.caption("**Result:**")
                st.text(tc["result"])


def render_metrics_tab(metrics_list: List[Dict[str, Any]]) -> None:
    if not metrics_list:
        st.info("No metrics data yet.")
        return
    st.subheader("Metrics")
    current = metrics_list[-1] if metrics_list else {}
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Input Tokens", current.get("input_tokens", 0))
    with col2:
        st.metric("Output Tokens", current.get("output_tokens", 0))
    with col3:
        st.metric("Total Tokens", current.get("total_tokens", 0))
    cost = current.get("cost")
    if cost:
        st.metric("Cost", f"${cost:.6f}")

    if len(metrics_list) > 1:
        st.divider()
        st.markdown("**Session Totals**")
        total_input = sum(m.get("input_tokens", 0) for m in metrics_list if m.get("input_tokens"))
        total_output = sum(m.get("output_tokens", 0) for m in metrics_list if m.get("output_tokens"))
        st.metric("Total Input", total_input)
        st.metric("Total Output", total_output)


def render_messages_tab(messages: List[Dict[str, Any]]) -> None:
    if not messages:
        st.info("No messages yet.")
        return
    st.subheader("Message History")
    st.caption(f"Total: {len(messages)} messages")
    for i, msg in enumerate(messages):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        with st.expander(f"[{role.upper()}] #{i + 1}", expanded=False):
            if content:
                st.text(content[:1000])
            else:
                st.caption("(no content)")

    # ── Full prompt dump viewer ────────────────────────────────────────
    st.divider()
    user_id = st.session_state.get("debug_user_id")
    if not user_id:
        st.caption("Send a message to enable the full prompt dump viewer.")
        return
    dump_path = _resolve_prompt_dump_path(user_id)
    if not dump_path.exists():
        st.caption(
            "No prompt dump found. Set `PI_DUMP_PROMPT=1` on the FastAPI "
            "container to capture `last_prompt.md` per run."
        )
        return
    mtime = datetime.fromtimestamp(dump_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    st.caption(f"Last dump: `{dump_path}`  ({mtime})")
    if st.button("Show full prompt dump", key="show_full_prompt_dump"):
        try:
            content = dump_path.read_text(encoding="utf-8")
        except OSError as exc:
            st.error(f"Failed to read prompt dump: {exc}")
            return
        st.code(content, language="markdown")


def render_debug_panel() -> None:
    session_state = st.session_state.get("debug_session_state", {})
    agent_routing = st.session_state.get("debug_agent_routing", [])
    tool_calls = st.session_state.get("debug_tool_calls", [])
    metrics_list = st.session_state.get("debug_metrics", [])
    messages = st.session_state.get("debug_messages", [])

    with st.sidebar:
        with st.expander("Debug Panel", expanded=False):
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Messages", len(st.session_state.get("messages", [])))
            with col2:
                st.metric("Tool Calls", len(tool_calls))

            if st.button("Clear Debug Log", key="clear_debug"):
                st.session_state.debug_log = []
                st.session_state.debug_agent_routing = []
                st.session_state.debug_tool_calls = []
                st.session_state.debug_metrics = []
                st.session_state.debug_messages = []
                st.session_state.pop("debug_user_id", None)
                st.rerun()

            st.divider()

            tab_state, tab_routing, tab_tools, tab_metrics, tab_messages = st.tabs(
                ["State", "Routing", "Tools", "Metrics", "Messages"]
            )
            with tab_state:
                render_session_state_tab(session_state)
            with tab_routing:
                render_agent_routing_tab(agent_routing)
            with tab_tools:
                render_tool_calls_tab(tool_calls)
            with tab_metrics:
                render_metrics_tab(metrics_list)
            with tab_messages:
                render_messages_tab(messages)
