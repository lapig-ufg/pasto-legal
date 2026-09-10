from pydantic import BaseModel, Field


class WorkflowState(BaseModel):
    schema_version: int = Field(
        default=1,
        description="Schema version of the session state."
    )
    is_feedback_active: bool = Field(
        default=False,
        description="Should run feedback evaluation."
    )