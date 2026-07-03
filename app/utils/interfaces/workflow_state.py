from enum import StrEnum
from pydantic import BaseModel, Field


class WorkflowRouteEnum(StrEnum):
    AUTO = "auto"
    ANALYST = "analyst"
    MANAGER = "manager"
    QUESTION_ANSWER = "question_answer"
    SMALL_TALK = "small_talk"


class WorkflowState(BaseModel):
    route: WorkflowRouteEnum = Field(
        default=WorkflowRouteEnum.AUTO,
        description="Route workflow should follow."
    )
    is_loop_active: bool = Field(
        default=False,
        description="Should run router loop."
    ) 
    is_feedback_active: bool = Field(
        default=False,
        description="Should run feedback evaluation."
    )