from pydantic import BaseModel, Field


class WorkflowState(BaseModel):
    is_feedback_active: bool = Field(
        default=False,
        description="Should run feedback evaluation."
    )