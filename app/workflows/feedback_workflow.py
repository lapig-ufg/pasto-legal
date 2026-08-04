"""Feedback evaluation and response merging workflow composition.

Thin composition file that assembles the feedback workflow (satisfaction
evaluation, branch routing for feedback persistence, persona management).
The executor logic lives in ``app.steps.feedback``.

External interface:
    feedback_workflow  -- the Workflow imported by main_workflow.
"""

from agno.workflow import Parallel, Router, Step, Workflow

from app.steps.feedback.persist_feedback import (
    persist_negative_feedback,
    persist_positive_feedback,
)
from app.steps.feedback.persona import manage_persona
from app.steps.feedback.satisfaction import (
    evaluate_satisfaction,
    satisfaction_branch_selector,
)


feedback_workflow = Workflow(
    name="Feedback Workflow",
    steps=[
        Step(
            name="Evaluate Satisfaction",
            executor=evaluate_satisfaction,
        ),
        Parallel(
            Router(
                name="Satisfaction Branch Router",
                selector=satisfaction_branch_selector,
                choices=[
                    Step(
                        name="Persist Positive Feedback",
                        executor=persist_positive_feedback,
                    ),
                    Step(
                        name="Persist Negative Feedback",
                        executor=persist_negative_feedback,
                    ),
                    Step(
                        name="Neutral",
                        executor=lambda step_input: None,
                    ),
                ],
            ),
            Step(
                name="Persona Management",
                executor=manage_persona,
            ),
            name="Feedback and Persona Parallel",
        ),
    ],
)