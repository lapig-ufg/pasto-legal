from agno.run import RunContext
from agno.utils.log import log_warning

from app.schemas.property_feature import PropertyFeature, validate_feature_record


def find_feature_record(run_context: RunContext, feature_id: str) -> dict | None:
    """
    Locates the raw record dict of a registered feature in the session state,
    matching its ``id`` (CAR code for rural properties, generated id for
    buffered areas).
    """
    all_properties = run_context.session_state.get("all_properties", [])
    for record in all_properties:
        feature = validate_feature_record(record)
        if feature.id == feature_id:
            return record
    return None


def resolve_feature(run_context: RunContext, feature_id: str) -> PropertyFeature | None:
    """
    Resolves a registered feature by id into its typed PropertyFeature model.

    Returns None when the feature_id is not registered in the session.
    """
    record = find_feature_record(run_context, feature_id)
    if record is None:
        log_warning(f"Nenhuma feição registrada encontrada para id={feature_id}")
        return None
    return validate_feature_record(record)