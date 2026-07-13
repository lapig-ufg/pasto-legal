"""Streamlit debug panel renderer for the Pasto Legal multi-agent system.

Renders a sidebar expander with tabs for inspecting session state,
agent routing, tool calls, metrics, and message history in real time.
"""

from typing import Any, Dict, List

import streamlit as st


def _render_key_value(key: str, value: Any) -> None:
    """Render a single key-value pair with appropriate formatting.

    Known session state keys get human-readable labels.
    Lists and dicts are rendered in expanders; scalars inline.
    """
    # Human-readable labels for known keys
    LABELS = {
        "is_greeted": "👋 Greeted",
        "workflow_route": "🔀 Workflow Route",
        "registration_state": "📋 Registration State",
        "all_properties": "🏡 All Properties",
        "candidate_properties": "📝 Candidate Properties",
        "user_mood": "😊 User Mood",
        "user_persona": "👤 User Persona",
        "terms_acceptance": "📜 Terms Accepted",
        "delivered_media": "🖼️ Delivered Media",
        "workflow_id": "🔑 Workflow ID",
        "workflow_name": "📛 Workflow Name",
        "current_user_id": "👤 Current User ID",
        "current_session_id": "🔗 Current Session ID",
        "current_run_id": "🏃 Current Run ID",
    }

    label = LABELS.get(key, f"🔑 {key}")

    if value is None or value == "None":
        st.caption(f"{label}: `None`")
        return

    # Lists — show count and expandable details
    if isinstance(value, list):
        with st.expander(f"{label} ({len(value)} items)", expanded=False):
            if len(value) == 0:
                st.caption("Empty list")
            else:
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        st.json(item)
                    else:
                        st.text(str(item))
        return

    # Dicts — show in expander as JSON
    if isinstance(value, dict):
        with st.expander(f"{label}", expanded=False):
            st.json(value)
        return

    # Booleans — use colored badges
    if isinstance(value, bool):
        if value:
            st.success(f"{label}: ✅ True")
        else:
            st.error(f"{label}: ❌ False")
        return

    # Strings — show inline
    if isinstance(value, str):
        display = value if len(value) <= 100 else value[:100] + "..."
        st.caption(f"{label}: `{display}`")
        return

    # Numbers — show inline
    if isinstance(value, (int, float)):
        st.caption(f"{label}: `{value}`")
        return

    # Fallback
    st.caption(f"{label}: `{str(value)[:100]}`")


def render_session_state_tab(session_state: Dict[str, Any]) -> None:
    """Tab 1: Session State Inspector.

    Shows the current workflow session state with human-readable formatting
    for known keys and raw values for unknown keys.
    """
    if not session_state:
        st.info("No session state data yet. Send a message to populate.")
        return

    st.subheader("🔑 Session State")

    # Priority keys shown first
    priority_keys = [
        "is_greeted", "workflow_route", "registration_state",
        "all_properties", "candidate_properties",
        "user_mood", "user_persona", "terms_acceptance",
        "delivered_media",
    ]

    # Render priority keys first
    for key in priority_keys:
        if key in session_state:
            _render_key_value(key, session_state[key])

    # Render remaining keys
    remaining = {k: v for k, v in session_state.items() if k not in priority_keys}
    if remaining:
        st.divider()
        st.caption("Other keys:")
        for key, value in remaining.items():
            _render_key_value(key, value)


def render_agent_routing_tab(routing_data: List[Dict[str, Any]]) -> None:
    """Tab 2: Agent Routing Trace.

    Shows which agents ran, in what order, which model they used,
    and a preview of their response.
    """
    if not routing_data:
        st.info("No agent routing data yet. Send a message to populate.")
        return

    st.subheader("🔀 Agent Routing Trace")

    for i, agent_data in enumerate(routing_data):
        agent_name = agent_data.get("agent_name", "unknown")
        model = agent_data.get("model", "?")
        provider = agent_data.get("model_provider", "")
        status = agent_data.get("status", "?")
        content_preview = agent_data.get("content", "")

        # Status icon
        status_icon = "✅" if status == "RunStatus.completed" else "⚠️" if "error" in status.lower() else "⏳"

        with st.expander(
            f"{status_icon} Step {i + 1}: {agent_name}",
            expanded=(i == len(routing_data) - 1),  # Expand last step by default
        ):
            col1, col2 = st.columns(2)
            with col1:
                st.caption(f"**Model:** `{model}`")
            with col2:
                st.caption(f"**Provider:** `{provider}`")

            st.caption(f"**Status:** {status}")

            if content_preview:
                st.text(content_preview[:500])

            # Show tool calls for this agent
            tool_calls = agent_data.get("tool_calls", [])
            if tool_calls:
                st.caption(f"**Tools called:** {len(tool_calls)}")
                for tc in tool_calls:
                    tool_label = f"🔧 {tc.get('tool_name', '?')}"
                    tc_status = "✅" if tc.get("status") == "success" else "❌"
                    st.text(f"  {tc_status} {tool_label}")
                    if tc.get("tool_args"):
                        st.json(tc["tool_args"])

            # Reasoning
            reasoning = agent_data.get("reasoning_content")
            if reasoning:
                with st.expander("🧠 Reasoning", expanded=False):
                    st.text(reasoning)


def render_tool_calls_tab(tool_calls: List[Dict[str, Any]]) -> None:
    """Tab 3: Tool Calls Log.

    Shows all tool calls made across all agents in the session,
    with arguments, results, and timing.
    """
    if not tool_calls:
        st.info("No tool calls yet. Use features that trigger tools to populate.")
        return

    st.subheader("🔧 Tool Calls Log")
    st.caption(f"Total: {len(tool_calls)} tool calls in this session")

    for i, tc in enumerate(tool_calls):
        tool_name = tc.get("tool_name", "unknown")
        agent_name = tc.get("agent_name", "?")
        status = tc.get("status", "unknown")
        duration = tc.get("duration")

        status_icon = "✅" if status == "success" else "❌"
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

    st.subheader("📊 Metrics")

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
            with st.expander(f"📦 {step_name}", expanded=False):
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

    st.subheader("💬 Message History")
    st.caption(f"Total: {len(messages)} messages in this session")

    # Role-based coloring
    ROLE_COLORS = {
        "system": "🔵",
        "user": "🟢",
        "assistant": "🟣",
        "tool": "🟡",
    }

    for i, msg in enumerate(messages):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        name = msg.get("name")
        agent_name = msg.get("agent_name")

        role_icon = ROLE_COLORS.get(role, "⚪")

        # Header line
        header_parts = [f"{role_icon} **{role.upper()}**"]
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
        with st.expander("🐛 Debug Panel", expanded=False):
            # Quick stats at the top
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Messages", len(st.session_state.get("messages", [])))
            with col2:
                st.metric("Tool Calls", len(tool_calls))

            # Refresh session state from workflow (live)
            if st.button("🔄 Refresh State", key="refresh_debug_state"):
                try:
                    from app.workflows.main_workflow import pasto_legal_workflow
                    from app.utils.debug_helpers import extract_session_state
                    live_state = pasto_legal_workflow.get_session_state(
                        session_id=st.session_state.session_id
                    )
                    if live_state:
                        st.session_state.debug_session_state = extract_session_state(live_state)
                        st.rerun()
                except Exception as e:
                    st.error(f"Failed to refresh: {e}")

            # Clear debug log button
            if st.button("🗑️ Clear Debug Log", key="clear_debug"):
                st.session_state.debug_log = []
                st.session_state.debug_agent_routing = []
                st.session_state.debug_tool_calls = []
                st.session_state.debug_metrics = []
                st.session_state.debug_messages = []
                st.rerun()

            st.divider()

            # Tabs for different debug views
            tab_state, tab_routing, tab_tools, tab_metrics, tab_messages = st.tabs(
                ["🔑 State", "🔀 Routing", "🔧 Tools", "📊 Metrics", "💬 Messages"]
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