"""Summarization workflow composition for the Pasto Legal multi-agent system.

Thin composition file that assembles the summarization step. The executor
logic lives in ``app.steps.summarization``.

External interface:
    summarization_workflow  -- the Step imported by main_workflow.
"""

from agno.workflow import Step

from app.steps.summarization.summarization import summarization_executor


summarization_workflow = Step(
    name="Summarization Step",
    executor=summarization_executor,
)