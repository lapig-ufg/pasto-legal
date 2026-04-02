from agno.run import RunContext


def dump_session_state_hook(run_context: RunContext):
    session_state = run_context.get("session_state", None)

    if not session_state:
        return
    
    if "selected_property" in session_state:
        selected_property = session_state.get("selected_property", None)
        if selected_property:
            session_state["selected_property"] = selected_property.dump_model()

    if "all_properties" in session_state:
        all_properties = session_state.get("all_properties", None)
        if all_properties:
            session_state["all_properties"] = [p.dump_model() for p in all_properties]