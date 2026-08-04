"""Streamlit debug panel renderer for the Pasto Legal multi-agent system.

Renders a sidebar expander with tabs for inspecting session state,
agent routing, tool calls, metrics, and message history in real time.
"""

from typing import Any, Dict, List

import streamlit as st


def render_session_state_tab(session_state: Dict[str, Any]) -> None:
    """Tab 1: Session State Inspector.

    Dynamically renders each key in session_state as a JSON expander.
    New keys appear automatically without code changes.
    """
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
    """Tab 2: Agent Routing Trace.

    Shows which agents ran, in what order, which model they used,
    and a preview of their response.
    """
    if not routing_data:
        st.info("No agent routing data yet. Send a message to populate.")
        return

    st.subheader("Agent Routing Trace")

    for i, agent_data in enumerate(routing_data):
        agent_name = agent_data.get("agent_name", "unknown")
        model = agent_data.get("model", "?")
        provider = agent_data.get("model_provider", "")
        status = agent_data.get("status", "?")
        content_preview = agent_data.get("content", "")

        status_icon = "[OK]" if status == "RunStatus.completed" else "[ERR]" if "error" in status.lower() else "[...]"

        with st.expander(
            f"{status_icon} Step {i + 1}: {agent_name}",
            expanded=(i == len(routing_data) - 1),
        ):
            col1, col2 = st.columns(2)
            with col1:
                st.caption(f"**Model:** `{model}`")
            with col2:
                st.caption(f"**Provider:** `{provider}`")

            st.caption(f"**Status:** {status}")

            if content_preview:
                st.text(content_preview[:500])

            tool_calls = agent_data.get("tool_calls", [])
            if tool_calls:
                st.caption(f"**Tools called:** {len(tool_calls)}")
                for tc in tool_calls:
                    tool_label = tc.get("tool_name", "?")
                    tc_status = "[OK]" if tc.get("status") == "success" else "[FAIL]"
                    st.text(f"  {tc_status} {tool_label}")
                    if tc.get("tool_args"):
                        st.json(tc["tool_args"])

            reasoning = agent_data.get("reasoning_content")
            if reasoning:
                with st.expander("Reasoning", expanded=False):
                    st.text(reasoning)


def render_tool_calls_tab(tool_calls: List[Dict[str, Any]]) -> None:
    """Tab 3: Tool Calls Log.

    Shows all tool calls made across all agents in the session,
    with arguments, results, and timing.
    """
    if not tool_calls:
        st.info("No tool calls yet. Use features that trigger tools to populate.")
        return

    st.subheader("Tool Calls Log")
    st.caption(f"Total: {len(tool_calls)} tool calls in this session")

    for i, tc in enumerate(tool_calls):
        tool_name = tc.get("tool_name", "unknown")
        agent_name = tc.get("agent_name", "?")
        status = tc.get("status", "unknown")
        duration = tc.get("duration")

        status_icon = "[OK]" if status == "success" else "[FAIL]"
        duration_text = f" ({duration:.2f}s)" if duration else ""

        with st.expander(
            f"{status_icon} {tool_name}{duration_text}",
            expanded=False,
        ):
            st.caption(f"**Agent:** {agent_name}")

            # Arguments
            tool_args = tc.get("tool_args")
            if tool_args:
                st.caption("**Arguments:**")
                st.json(tool_args)

            # Result
            result = tc.get("result")
            if result:
                st.caption("**Result:**")
                st.text(result)


def render_metrics_tab(metrics_list: List[Dict[str, Any]]) -> None:
    """Tab 4: Metrics.

    Shows token usage, costs, and timing for the current message
    and cumulative totals across the session.
    """
    if not metrics_list:
        st.info("No metrics data yet. Send a message to populate.")
        return

    st.subheader("Metrics")

    # Current message metrics (last entry)
    current = metrics_list[-1]
    st.markdown("**Latest Message**")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Input Tokens", current.get("input_tokens", 0))
    with col2:
        st.metric("Output Tokens", current.get("output_tokens", 0))
    with col3:
        st.metric("Total Tokens", current.get("total_tokens", 0))
    with col4:
        cost = current.get("cost")
        st.metric("Cost", f"${cost:.6f}" if cost else "$0")

    duration = current.get("duration")
    if duration:
        st.metric("Duration", f"{duration:.2f}s")

    time_to_first = current.get("time_to_first_token")
    if time_to_first:
        st.metric("Time to First Token", f"{time_to_first:.2f}s")

    # Per-model breakdown
    model_breakdowns = current.get("model_breakdowns", [])
    if model_breakdowns:
        st.markdown("**Model Breakdown**")
        for mb in model_breakdowns:
            st.caption(
                f"`{mb.get('provider', '?')}/{mb.get('model_id', '?')}` — "
                f"in: {mb.get('input_tokens', 0)}, out: {mb.get('output_tokens', 0)}, "
                f"total: {mb.get('total_tokens', 0)}"
            )

    # Step metrics (from WorkflowMetrics)
    step_metrics = current.get("step_metrics", {})
    if step_metrics:
        st.markdown("**Step Metrics**")
        for step_name, sm in step_metrics.items():
            with st.expander(f"{step_name}", expanded=False):
                st.json(sm)

    # Cumulative metrics
    if len(metrics_list) > 1:
        st.divider()
        st.markdown("**Session Totals**")
        total_input = sum(m.get("input_tokens", 0) for m in metrics_list if m.get("input_tokens"))
        total_output = sum(m.get("output_tokens", 0) for m in metrics_list if m.get("output_tokens"))
        total_tokens = sum(m.get("total_tokens", 0) for m in metrics_list if m.get("total_tokens"))
        total_cost = sum(m.get("cost", 0) or 0 for m in metrics_list if m.get("cost"))

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Input", total_input)
        with col2:
            st.metric("Total Output", total_output)
        with col3:
            st.metric("Total Tokens", total_tokens)
        with col4:
            st.metric("Total Cost", f"${total_cost:.6f}")


def render_messages_tab(messages: List[Dict[str, Any]]) -> None:
    """Tab 5: Message History.

    Shows the full message history with role badges, agent attribution,
    and expandable content.
    """
    if not messages:
        st.info("No messages yet. Send a message to populate.")
        return

    st.subheader("Message History")
    st.caption(f"Total: {len(messages)} messages in this session")

    ROLE_LABELS = {
        "system": "[SYS]",
        "user": "[USR]",
        "assistant": "[AST]",
        "tool": "[TOOL]",
    }

    for i, msg in enumerate(messages):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        name = msg.get("name")
        agent_name = msg.get("agent_name")

        role_tag = ROLE_LABELS.get(role, f"[{role.upper()}]")

        # Header line
        header_parts = [f"{role_tag} **{role.upper()}**"]
        if agent_name:
            header_parts.append(f"({agent_name})")
        if name:
            header_parts.append(f"[{name}]")

        with st.expander(" ".join(header_parts), expanded=False):
            if content:
                st.text(content[:1000])
            else:
                st.caption("(no content)")

            # Tool calls within this message
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                st.caption(f"**Tool calls:** {len(tool_calls)}")
                for tc in tool_calls:
                    st.text(f"  → {tc.get('name', '?')}")


def render_debug_panel() -> None:
    """Main entry point: renders the debug panel in the Streamlit sidebar.

    Reads debug data from st.session_state and renders tabs for
    session state, agent routing, tool calls, metrics, and messages.
    """
    # Get data from session state (populated by the webapp after each run)
    session_state = st.session_state.get("debug_session_state", {})
    agent_routing = st.session_state.get("debug_agent_routing", [])
    tool_calls = st.session_state.get("debug_tool_calls", [])
    metrics_list = st.session_state.get("debug_metrics", [])
    messages = st.session_state.get("debug_messages", [])

    with st.sidebar:
        with st.expander("Debug Panel", expanded=False):
            # Quick stats at the top
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Messages", len(st.session_state.get("messages", [])))
            with col2:
                st.metric("Tool Calls", len(tool_calls))

            # Refresh session state from workflow (live)
            if st.button("Refresh State", key="refresh_debug_state"):
                try:
                    from app.workflows.pasto_legal_workflow import pasto_legal_workflow
                    from app.interfaces.streamlit.debug_helpers import extract_session_state
                    live_state = pasto_legal_workflow.get_session_state(
                        session_id=st.session_state.session_id
                    )
                    if live_state:
                        st.session_state.debug_session_state = extract_session_state(live_state)
                        st.rerun()
                except Exception as e:
                    st.error(f"Failed to refresh: {e}")

            # Clear debug log button
            if st.button("Clear Debug Log", key="clear_debug"):
                st.session_state.debug_log = []
                st.session_state.debug_agent_routing = []
                st.session_state.debug_tool_calls = []
                st.session_state.debug_metrics = []
                st.session_state.debug_messages = []
                st.rerun()

            st.divider()

            # Tabs for different debug views
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