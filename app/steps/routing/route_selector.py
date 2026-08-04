"""Intent router selector: classifies the user's message and returns its route.

Selector for the Intent Router. Runs the Router Agent to classify the user's
message and returns the matching route enum value.

If a non-AUTO route is already set in WorkflowState, returns it directly
(manual override). Falls back to 'default' if the agent fails or the session
state does not contain a valid WorkflowState.

External interface:
    _route_selector  -- Router selector consumed by main_workflow.
"""

from typing import Any, Dict

from agno.utils.log import log_debug
from agno.workflow.types import StepInput

from app.agents.router_agent import router_agent
from app.core.session_state import WorkflowRouteEnum, WorkflowState


def _route_selector(step_input: StepInput, session_state: Dict[str, Any]) -> str:
    """Selector for the Intent Router. Runs the Router Agent to classify
    the user's message and returns the matching route enum value.
    """
    raw_state = session_state.get("workflow_state")
    if raw_state is None:
        log_debug("route_selector: no workflow_state in session, defaulting to 'default'")
        return "default"

    try:
        workflow_state = WorkflowState.model_validate(raw_state)
    except Exception as e:
        log_debug(f"route_selector: invalid workflow_state: {e}, defaulting to 'default'")
        return "default"

    if workflow_state.route != WorkflowRouteEnum.AUTO:
        return workflow_state.route.value

    try:
        user_msg = step_input.get_input_as_string() or ""
        history_data = step_input.get_workflow_history(num_runs=1)

        final_message = ""
        if history_data:
            last_user_msg, last_system_response = history_data[0]
            final_message += "### Talk History ###\n"
            final_message += f"User: {last_user_msg}\n"
            final_message += f"System: {last_system_response}\n"
        final_message += f"User: {user_msg}"

        response = router_agent.run(final_message)
        route_data = response.content

        if route_data and hasattr(route_data, "route"):
            return route_data.route

        if isinstance(route_data, dict) and "route" in route_data:
            return route_data["route"]

        if isinstance(route_data, str) and len(route_data.split(" ")) == 1:
            return route_data

    except Exception as e:
        log_debug(f"route_selector: agent failed: {e}")

    return "default"