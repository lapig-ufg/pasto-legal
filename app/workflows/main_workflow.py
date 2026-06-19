"""Composition root for the Pasto Legal workflow.

The workflow used to be a single 450-line monolith. It is now split into
focused modules in this folder, and this file just imports the assembled
pieces and wires them together:

- `app.workflows.satisfaction`   -> `evaluation_branch` (grade + branch + saves)
- `app.workflows.normal_response` -> `normal_response`   (intent/registration routing)
- `app.workflows.feedback`        -> `merge_response`    (persistence + final merge)
- `app.workflows.phone_check`     -> `phone_number_check` (auth helper, not wired yet)

The flow: grade the user's satisfaction and craft a tailored handler message
(`evaluation_branch`) IN PARALLEL with the normal agent response
(`normal_response`), then `merge_response` combines them (apology + better
response when the user was frustrated, otherwise the handler + normal response).
"""
from agno.workflow import Workflow, Step, Parallel

from app.database.agno_db import db
from app.workflows.satisfaction import evaluation_branch
from app.workflows.normal_response import normal_response
from app.workflows.feedback import merge_response


# ---------------------------------------------------------------------------
# Workflow assembly
# ---------------------------------------------------------------------------
pasto_legal_workflow = Workflow(
    name="Pasto Legal Workflow",
    db=db,
    steps=[
        Parallel(
            evaluation_branch,
            normal_response,
            name="grade_and_respond",
        ),
        Step(name="merge_response", executor=merge_response),
    ],
)