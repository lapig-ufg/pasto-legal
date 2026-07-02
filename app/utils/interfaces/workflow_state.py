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
    active_router_loop: bool = Field(
        default=False,
        description="Should run router loop."
    ) 
    active_feedback_eval: bool = Field(
        default=True,
        description="Should run feedback evaluation."
    )