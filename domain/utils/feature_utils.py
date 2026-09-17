from semente.context import Context as RunContext
from semente.logging import log_warning

from domain.schemas.feature import Feature, RegisteredFeatures


def get_registered_features(session_state) -> RegisteredFeatures:
    """
    Reads the registered features from the session state.

    ``all_properties`` stores the serialized form of a RegisteredFeatures
    model (plain dict) so agno can persist the session as JSON; this
    accessor rebuilds the typed model on every read.
    """
    value = session_state.get("all_properties")
    if value is None:
        return RegisteredFeatures()
    return RegisteredFeatures.model_validate(value)


def set_registered_features(session_state, registered: RegisteredFeatures) -> None:
    """
    Writes the registered features back to the session state as a plain
    dict (the serialized RegisteredFeatures form).
    """
    session_state["all_properties"] = registered.model_dump()


def resolve_feature(run_context: RunContext, feature_id: str) -> Feature | None:
    """
    Resolves a registered feature by id, user-chosen name, or constituent
    CAR code (see ``RegisteredFeatures.find_by_any``).

    Returns None when the feature is not registered in the session.
    """
    feature = get_registered_features(run_context.session_state).find_by_any(feature_id)
    if feature is None:
        log_warning(f"Nenhuma feição registrada encontrada para id={feature_id}")
    return feature