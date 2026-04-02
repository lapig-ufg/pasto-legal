from agno.run import RunContext

from app.utils.interfaces.rural_property_interface import RuralProperty


def dump_session_state_hook(run_context: RunContext):
    session_state = run_context.session_state or {}

    if not session_state:
        return
    
    if "selected_property" in session_state:
        selected_property = session_state.get("selected_property", None)
        if selected_property is not None and isinstance(selected_property, RuralProperty):
            session_state["selected_property"] = selected_property.model_dump()

    if "all_properties" in session_state:
        all_properties = session_state.get("all_properties", None)
        if all_properties is not None and isinstance(all_properties, list):
            session_state["all_properties"] = [p.model_dump() for p in all_properties]

    if "candidate_properties" in session_state:
        candidate_properties = session_state.get("candidate_properties", None)
        if candidate_properties is not None and isinstance(candidate_properties, list):
            session_state["candidate_properties"] = [p.model_dump() for p in candidate_properties]