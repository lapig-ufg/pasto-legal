from enum import StrEnum
from pydantic import BaseModel, Field


class RouteEnum(StrEnum):
    AUTO = "auto"
    ANALYST = "analyst"
    MANAGER = "manager"
    DIAGNOSIS = "diagnosis"
    QUESTION_ANSWER = "question_answer"
    SMALL_TALK = "small_talk"


class WorkflowState(BaseModel):
    route: RouteEnum = Field(
        default=RouteEnum.AUTO,
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