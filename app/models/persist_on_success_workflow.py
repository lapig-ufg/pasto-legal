"""Workflow variant that skips DB persistence when a step stops with stop=True & success=False.

The standard agno Workflow persists every terminal run to the database via
`save_session` / `asave_session` (called at the end of `_execute`,
`_execute_stream`, `_aexecute`, `_aexecute_stream`). When a step signals early
termination by returning `StepOutput(stop=True)`, the run is still persisted,
regardless of `success`.

`PersistOnSuccessWorkflow` overrides the persistence entry points so that if
any step (recursively, including nested containers) in the just-finished run
reported `stop=True` and `success=False`, the session is NOT persisted.

Pause / error / cancelled saves are preserved because their run status is not
`RunStatus.completed` and their `step_results` do not contain a
stop+failure pair (pauses happen before step output is produced).
"""

from typing import Any, List

from agno.run import RunStatus
from agno.session.workflow import WorkflowSession
from agno.workflow import Workflow
from agno.workflow.types import StepOutput


def _step_has_stop_failure(step_output: Any) -> bool:
    """Recursively check whether a StepOutput (or nested children) has stop=True & success=False.

    `WorkflowRunOutput.step_results` is typed as `List[Union[StepOutput, List[StepOutput]]]`,
    and composite steps (Steps, Loop, Parallel, Router, Condition) expose their
    children via the `.steps` attribute, so we recurse into both shapes.
    """
    if isinstance(step_output, list):
        return any(_step_has_stop_failure(item) for item in step_output)
    if not isinstance(step_output, StepOutput):
        return False
    if step_output.stop and not step_output.success:
        return True
    if step_output.steps:
        return any(_step_has_stop_failure(child) for child in step_output.steps)
    return False


def _last_run_has_stop_failure(session: WorkflowSession) -> bool:
    """Inspect the session's most recent run for the stop+failure suppression condition.

    Only terminal (`RunStatus.completed`) runs are considered for suppression.
    Paused / error / cancelled runs are always persisted by the parent class and
    should continue to be persisted — they represent in-flight HITL state or
    diagnostic data that must not be lost.
    """
    runs: List[Any] = getattr(session, "runs", None) or []
    if not runs:
        return False
    last_run = runs[-1]
    status = getattr(last_run, "status", None)
    if status not in (RunStatus.completed,):
        return False
    step_results = getattr(last_run, "step_results", None) or []
    return any(_step_has_stop_failure(s) for s in step_results)


class PersistOnSuccessWorkflow(Workflow):
    """Workflow subclass that skips DB persistence on stop+failure terminations.

    Behavior:
        - If the just-finished run is `completed` and any step (recursively)
          has `stop=True` and `success=False`, `save_session` / `asave_session`
          become no-ops, so the run is never written to the database.
        - All other cases (successful runs, pauses, errors, cancellations) are
          delegated to the parent `Workflow` and persisted as usual.
    """

    def save_session(self, session: WorkflowSession) -> None:
        if _last_run_has_stop_failure(session):
            return
        super().save_session(session=session)

    async def asave_session(self, session: WorkflowSession) -> None:
        if _last_run_has_stop_failure(session):
            return
        await super().asave_session(session=session)